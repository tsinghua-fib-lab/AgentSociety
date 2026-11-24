# Design

Turn the request into a `DesignSpec` that becomes the source of truth for generation.

If the module has mutable runtime state, counters, per-agent snapshots, or replay requirements, also read `references/persistence-patterns.md` before freezing the design.

## Scale Fit

Record the simulation scale budget before freezing the tool and state design:

- target agent count or range
- expected step budget
- runtime or compute budget
- preferred complexity tier, such as lean, balanced, or rich

For larger populations or tighter budgets, prefer batched writes, compact state, and cheaper tool bodies. For smaller simulations, richer state and more detailed tool logic are acceptable.

Minimum design fields:

- `module_name`
- `class_name`
- `global_state`
- `per_agent_state`
- `tools`
- `config_fields`
- `step_semantics`
- `persistence`
- `success_criteria`
- `scale_budget`

The `persistence` section should answer these questions explicitly:

- Which per-agent fields must be queryable from replay tables (declare in `_agent_state_columns`)
- Which environment/global fields must be queryable from replay tables (declare in `_env_state_columns`)
- Which in-memory structures are derived/cached and can be rebuilt from kwargs + replay data on each run (no persistence needed)
- Where replay writes happen, usually `step()` or another canonical mutation boundary
- Which `_write_*` helper (`_write_agent_state` / `_write_agent_state_batch` / `_write_env_state`) each write uses
- Whether the module should support `--resume`: if yes, which dynamic fields are written to `state/ENV_STATE.json` via `to_workspace()`/`restore()` (separate from replay; see `references/persistence-patterns.md` → Workspace Persistence)

Persistence has two independent channels: **replay** (declare columns, auto-register
append-only tables, write via `_write_*`) for analysis; and **workspace**
(`to_workspace`/`restore` → `state/ENV_STATE.json`) for resuming interrupted runs.
A stateful module that needs `--resume` must implement both.

Persist:

- `design_spec.json`
- `design_summary.md`
- Only if you want a reviewable trace under `.agentsociety/custom_env_skill/runs/<run_id>/`.

Do not start code generation until the design spec is internally coherent.
