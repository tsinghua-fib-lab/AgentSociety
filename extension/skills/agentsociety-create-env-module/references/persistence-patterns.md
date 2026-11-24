# Persistence Patterns

Use this reference when the custom environment is stateful. There are **two
independent** persistence channels — do not confuse them:

- **Replay persistence** (analysis): declare snapshot columns, let the framework
  auto-register append-only replay tables, write rows via the `_write_*` helpers.
  Consumed by replay/analysis tooling. The rest of this file (below) covers replay.
- **Workspace persistence** (resume): override `to_workspace()` / `restore()` to write
  the module's dynamic state to `state/ENV_STATE.json` so a crashed/interrupted run can
  continue via CLI `--resume`. Covered in the **Workspace Persistence** section below.

Replay is append-only and queryable; workspace is the latest-state overwrite used only
to restart. A module that carries in-memory state and wants `--resume` support MUST do
both: replay snapshots (for analysis) **and** workspace `to_workspace`/`restore` (for
resume).

## Workspace Persistence (for `--resume`)

`EnvBase` provides a free-form persistence contract — the module chooses its own state
format, filename, and directory layout (the convention is `<workspace_root>/state/ENV_STATE.json`).

| Member | Purpose |
|--------|---------|
| `_bind_workspace(workspace_path)` | Bind the module to a workspace dir (idempotent); called automatically by `to_workspace`/`restore`. |
| `async to_workspace(workspace_path=None)` | **Override**: write dynamic state (atomic write recommended). Called every step by the framework. |
| `async restore(workspace_path) -> bool` | **Override**: read state back; return `True` if loaded, `False` if no checkpoint. Called during `--resume`, AFTER `__init__`/`init()` (so it overrides any reset). |
| `classmethod async from_workspace(workspace_path, **init_kwargs)` | Convenience: `cls(**init_kwargs)` then `restore`. Used by the actor on resume. |

Convention + example (mirror `simple_social_space` / `economy_space` / `prisoners_dilemma`):

```python
import json
from agentsociety2.storage.workspace_state import atomic_write_text

_STATE_REL = "state/ENV_STATE.json"

async def to_workspace(self, workspace_path=None) -> None:
    if workspace_path is not None:
        self._bind_workspace(workspace_path)
    if self._workspace_root is None:
        raise RuntimeError("Env module workspace is not bound")
    atomic_write_text(
        self._workspace_root / _STATE_REL,
        json.dumps(
            {"mailboxes": {...}, "next_id": self._next_id, "step_counter": self._step_counter},
            ensure_ascii=False, indent=2, default=str,
        ),
    )

async def restore(self, workspace_path) -> bool:
    self._bind_workspace(workspace_path)
    state_path = self._workspace_root / _STATE_REL
    if not state_path.is_file():
        return False
    d = json.loads(state_path.read_text(encoding="utf-8"))
    self._mailboxes = {...}              # rebuild from d
    self._step_counter = int(d.get("step_counter", 0))
    return True
```

Workspace persistence rules:

- **JSON keys are strings**: `dict[int, ...]` → store `str(k)`, restore `int(k)` (or use
  `agentsociety2.env.base.dump_int_map` / `load_int_map`).
- **pydantic** → `model_dump(mode="json")` / `model_validate`. **datetime** →
  `isoformat` / `fromisoformat`. **set** → `sorted(list)`. **enum** → `.value` and
  reconstruct. **defaultdict/deque** → store as plain list/dict, restore the wrapper type.
- **Do NOT persist** `asyncio.Lock`, external subprocesses, open handles, or pre-trained
  model weights — rebuild them in `__init__`/`init()` (e.g. `MobilitySpace`'s routing
  server, `SocialMediaSpace`'s recommender loaded from `recommendation_model_path`).
- Constructor kwargs (config) live in `SOCIETY.json`'s `env_kwargs` and are re-supplied
  to `__init__` on resume — do not duplicate them in `ENV_STATE.json`.
- A module without dynamic state may leave `to_workspace`/`restore` as the no-op defaults
  (it then does not survive `--resume`, but will not crash).

## Replay Persistence (analysis snapshots)

The Persistence API on `EnvBase`

`agentsociety2.env.base.EnvBase` owns:

| Member | Purpose |
|--------|---------|
| `_agent_state_columns: ClassVar[list[ColumnDef]]` | Per-agent snapshot columns (keyed by `agent_id + step`). Declare on the class. |
| `_env_state_columns: ClassVar[list[ColumnDef]]` | Per-step env snapshot columns (keyed by `step`). Declare on the class. |
| `set_replay_writer(writer)` | Called by the framework; triggers lazy table registration when columns are declared. |
| `_register_state_tables()` | Auto-builds `{prefix}_agent_state` / `{prefix}_env_state` tables from the column declarations (called lazily on first write). |
| `await _write_agent_state(agent_id, step, t, **data)` | Write one per-agent snapshot row. |
| `await _write_agent_state_batch(step, t, records)` | Write many per-agent rows in one call. |
| `await _write_env_state(step, t, **data)` | Write one env-level snapshot row. |

`ColumnDef` / `TableSchema` / `ReplayDatasetSpec` come from `agentsociety2.storage`.
The framework auto-adds `agent_id` / `step` / `t` columns; you only declare your
module-specific fields. Table-name prefix is derived from the class name
(PascalCase → snake_case).

## Read These Runtime Examples

- `agentsociety2.env.base`
  Source of truth for `_agent_state_columns`, `_env_state_columns`,
  `set_replay_writer`, `_register_state_tables`, `_write_agent_state`,
  `_write_agent_state_batch`, `_write_env_state`.
- `agentsociety2.contrib.env.economy_space`
  Reference for combined per-agent + env-level replay (declares both column lists,
  writes snapshots in `step()`).
- `agentsociety2.contrib.env.simple_social_space`
  Reference for env-level replay only (`_env_state_columns` + `_write_env_state`).
- `agentsociety2.contrib.env.mobility_space.environment`
  Reference for per-agent replay of richer person state (position, etc.).

## Make The Design Decision Explicit

For every meaningful piece of mutable state, classify it before generating code:

- **Replay (per-agent)**: queryable per-agent snapshots keyed by `agent_id + step`
  → declare in `_agent_state_columns`, write via `_write_agent_state` /
  `_write_agent_state_batch`.
- **Replay (env-level)**: queryable env-wide snapshots keyed by `step`
  → declare in `_env_state_columns`, write via `_write_env_state`.
- **In-memory only**: derived / cached values that you can recompute from kwargs +
  replay data → keep as instance attributes, do NOT persist. They are rebuilt on
  each run by the constructor + replay.

Do not leave this undecided in prose. Put the result into the design spec's
`persistence` section.

## Map Design To Code

Declare columns as class-level `ClassVar[list[ColumnDef]]`:

```python
from typing import ClassVar
from agentsociety2.storage import ColumnDef

class MyEnv(EnvBase):
    _agent_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("balance", "REAL", description="Agent's current balance."),
        ColumnDef("status", "TEXT", description="Agent status string."),
    ]
    _env_state_columns: ClassVar[list[ColumnDef]] = [
        ColumnDef("total_messages", "INTEGER", description="Cumulative message count."),
        ColumnDef("market_rate", "REAL", description="Current market rate."),
    ]
```

Typical per-agent (`_agent_state_columns`) fields:

- balances, income, consumption
- lng/lat or other per-agent position snapshots (the framework auto-detects
  `lng` + `lat` and tags the dataset with `geo_point` / `trajectory` capabilities)
- per-agent scores or status values

Typical env-level (`_env_state_columns`) fields:

- aggregate counters
- market rates
- total message counts
- group counts

## Write At Canonical Boundaries

Prefer replay writes at deterministic boundaries:

- `step()` for periodic snapshots
- a single canonical mutation path if state changes outside `step()`

If multiple agents are written every step, use `_write_agent_state_batch(step, t, records)`
instead of many single-row `_write_agent_state` calls.

```python
async def step(self, tick: int, t: datetime) -> None:
    self._step_index += 1
    # Env-level snapshot
    await self._write_env_state(
        self._step_index, t,
        total_messages=self._msg_count,
        market_rate=self._rate,
    )
    # Per-agent batch snapshot
    records = [
        {"agent_id": aid, "balance": bal, "status": st}
        for aid, (bal, st) in self._agent_state.items()
    ]
    await self._write_agent_state_batch(self._step_index, t, records)
```

## Step Semantics: Do Not Confuse `tick` With Replay Step

In AgentSociety, `step(self, tick, t)` receives:

- `tick`: the duration of one simulation step, for example `1`, `60`, or `3600`
- `t`: the wall-clock simulation time after advancing by that duration

For replay tables keyed by `step`, you need a monotonic step index like `1, 2, 3, ...`,
not the duration value in `tick`.

Correct pattern:

- keep an internal counter such as `self._step_index`
- increment it once per `step()` call
- pass that internal counter as the `step` argument to `_write_agent_state_batch` /
  `_write_env_state`
- use the same counter for step-keyed decay windows or queued event timestamps

Typical bug to avoid:

- writing replay rows with `step=tick`
- with `tick=1`, tests may appear to pass by accident
- with `tick=60` or repeated same-duration runs, every replay write lands on the same
  primary key and later rows overwrite earlier ones

Minimum persistence review for step-keyed modules:

- after a 3-step smoke run, do step-keyed replay tables contain rows for steps
  `1, 2, 3` instead of only one surviving step?
- do decay windows compare against the internal step counter rather than the duration
  argument?

## Common Failure Modes

- Declaring replay columns but never writing them
- Writing replay rows whose keys do not match declared columns
- Reusing `tick` as the replay step primary key, causing multi-step runs to overwrite
  earlier rows
- Writing `**data` keys that don't match the declared `ColumnDef` names

## Minimum Review Questions

- Can replay consumers query the intended per-agent and env snapshots without reading
  opaque blobs?
- Are all declared replay columns actually written?
- Are all write points stable and deterministic?
- Is the internal step counter passed as `step` (not `tick`)?
