# AgentBase Interface

> Authoritative source: `packages/agentsociety2/agentsociety2/agent/base/README.md`
> and `packages/agentsociety2/agentsociety2/agent/base/agent.py`.
>
> This is the current AgentBase API.

## Construction model

`AgentBase.__init__(self)` is arg-less and only sets empty slots. The real lifecycle is:

| Entry point | Description |
|-------------|-------------|
| `await AgentBase.create(workspace_path, profile, config)` | classmethod; writes `config.json` + initial `AGENT.json` + standard empty dirs. **Does not return** an instance. |
| `await AgentBase.from_workspace(workspace_path, service_proxy)` | classmethod; does `agent = cls()` (arg-less) → `await agent.restore(ws, proxy)` → returns the ready agent. Concrete in the base; subclasses normally inherit it. |
| `AgentBase.__init__(self)` | arg-less. Only empty slots; no profile parsing, no id required. |
| `await agent.restore(workspace_path, service_proxy)` | **the real init hook.** Reads `config.json` + `AGENT.json`; sets `_id`/`_profile`/`_name`/`_config`; calls `_bind_services` + `_bind_workspace`; restores visible/activated skills + counters. Subclasses override and call `await super().restore(...)` first, then add state. |

The extension point most subclasses need is `restore`.

## Required abstract methods (subclasses MUST implement)

```python
async def to_workspace(self, workspace_path: Path) -> None
async def ask(self, message: str, readonly: bool = True, *, t: datetime | None = None) -> str
async def step(self, tick: int, t: datetime) -> str
```

`create` and `from_workspace` have concrete base implementations; override them only
when you need a custom `AGENT.json` layout (see the minimal/game templates).

## Override hooks (public, no `_`)

| Hook | When to override |
|------|------------------|
| `restore(self, workspace_path, service_proxy)` | Always call `await super().restore(...)` first, then add business state. The most common override. |
| `build_react_messages(self, *, tick, t, observations, question=None, readonly=False, skill_hooks=None) -> list[dict]` | **Required** if you reuse the base `run_react_loop`. The base raises `NotImplementedError`. Build OpenAI-style chat messages here. |
| `build_agent_json(self, *, tick, t) -> dict` | Extend `AGENT.json` fields. Call `data = super().build_agent_json(...)` first, then add keys. |
| `dispatch_react_tool(self, action, args, *, readonly=False) -> ReactToolResult` | Add custom tool-name prefixes (e.g. `memory_*`). Forward unknown actions to `await super().dispatch_react_tool(...)`. |
| `description()` / `init_description()` (classmethods) | Registry / AI-readable descriptions. Recommended for real modules. |
| `close()` | Release resources (base is a no-op). |

## Public utilities (callable from subclasses, no `_`)

| Method / property | Purpose |
|-------------------|---------|
| `await self.run_react_loop(*, tick, t, observations=None, question=None, readonly=False, skill_hooks=None) -> str` | Generic ReAct loop until `finish` or turn limit. |
| `await self.acompletion(messages, stream=False, **kwargs) -> ModelResponse` | One-shot LLM completion via the bound default-role dispatcher. |
| `await self.run_lifecycle_hooks(hook_type, *, tick, t) -> list[dict]` | Run `pre_step` / `post_step` skill hooks. |
| `self.discover_skill_sources(env, *, extra_skill_paths=None) -> dict[str, list[str]]` | Scan custom + env-provided skills; refresh visible set; apply default-activated. Sources: `<env.run_dir>/custom/skills`, this workspace's `custom/skills`, any `config["extra_skill_paths"]`, the optional `extra_skill_paths` arg, and env-module skill dirs. Extra entries are skill-subdir roots; relative paths resolve against the workspace root — so an agent can load custom skills from anywhere. |
| `self.persist_agent_json(*, tick=None, t=None) -> dict` | Write `AGENT.json` (calls `build_agent_json`). |
| `self.trace_span(name, *, trace_id=None, parent_span_id=None, attributes=None, end_attributes=None)` | Agent-scoped trace span context manager. |
| `self.workspace_root_path() -> Path` | Workspace root (raises `RuntimeError` if unbound). |
| `self.dispatch_todo_tool(action, args) -> ReactToolResult` | Built-in TODO tools (`todo_list`/`todo_add`/`todo_update`/`todo_start`/`todo_complete`/`todo_defer`/`todo_clear_completed`). |
| `await self.ask_env(ctx, message, readonly, template_mode=False, trace_id=None, parent_span_id=None)` | Request to the env router. Returns `(ctx, answer)`. |
| `self.get_profile() -> dict` | Profile dict (handles dict / pydantic / other). |
| `self.env_ask_env_ctx_overlay() -> dict` | Stable identity overlay (`id` / `agent_id` / `person_id`) merged into `ask_env` context automatically. |
| `self.skill_runtime` (attribute) | The `AgentSkillRuntime` (None until `restore`). |
| `self.id` / `self.name` / `self.logger` (properties) | Identity + agent-scoped logger. |

## LLM interaction

The base binds the default LLM role in `restore` via `_bind_services`, exposing
`self._dispatcher` / `self._model_name`.

```python
# One-shot completion (returns litellm ModelResponse)
response = await self.acompletion([
    {"role": "user", "content": "What should I do?"}
])
content = response.choices[0].message.content
```

For structured output, call `acompletion` and parse the response yourself. For a
multi-turn tool loop, use `run_react_loop` instead.

## Environment interaction

Minimal examples below; templates, context overlay, and error handling live in
**`environment-interaction.md`**.

```python
# Query (readonly) — template_mode=True is safe.
ctx, response = await self.ask_env(
    {"variables": {"location": "Beijing"}},
    "Please call get_weather() using location from ctx['variables'].",
    readonly=True,
    template_mode=True,
)

# Execute action — stateful write, default template_mode=False unless the
# env tool is verified idempotent. See references/pitfalls.md P3.
ctx, response = await self.ask_env(
    {"variables": {"agent_id": self.id, "destination": "Beijing"}},
    "Please call travel_to() using agent_id and destination "
    "from ctx['variables'].",
    readonly=False,
    template_mode=False,
)
```

The framework automatically merges `id` / `agent_id` / `person_id` into the
`ask_env` context (via `env_ask_env_ctx_overlay`) — you don't need to pass them.

## Configuration

Config is a plain dict written to `config.json` by `create`. The base `restore`
reads these generic keys (all optional):

| Key | Default | Effect |
|-----|---------|--------|
| `max_react_turns` | `10` | Max ReAct turns per `run_react_loop`. |
| `force_template_mode` | `False` | Force template mode for `ask_env` tool calls. |
| `allow_template_mode` | `True` | Whether template mode is permitted at all. |
| `enable_todo_list` | `True` | Enable the built-in TODO tools. |
| `disabled_skill_ids` | `[]` | Skill ids to hide from the visible set. |
| `default_activated_skill_ids` | `[]` | Skills to activate on first restore. |
| `extra_skill_paths` | `[]` | Extra skill directories scanned by `discover_skill_sources` **in addition to** the default `<root>/custom/skills` locations. Each entry is a root of skill subdirectories (same layout as `custom/skills`); relative paths resolve against the workspace root. Lets an agent load custom skills stored anywhere on disk — see [Skill sources](#skill-sources). |

Subclasses add their own keys (e.g. `PersonAgent` reads `enable_memory`,
`memory_context_max_chars`, etc.). When using the CLI / `init_config.json`, the
config keys listed above are split out of the agent's `kwargs` into the `config`
record (see `society/cli.py:_build_agent_specs`); the remaining `kwargs` become the
`profile` (with `id` + name + persona fields).

## Skill sources

An agent loads its skills from several directories, scanned in order by
`discover_skill_sources` (called automatically on first use):

1. `<env.run_dir>/custom/skills` — experiment-run-local skills (if `run_dir` is set).
2. `<workspace>/custom/skills` — the agent workspace's own custom skills.
3. **`config["extra_skill_paths"]`** — any extra directories you list (each a root of
   skill subdirectories, same layout as `custom/skills`). Relative paths resolve
   against the workspace root.
4. Each registered environment module's `skill_dirs()`.
5. Built-in skills (`agentsociety2/agent/skills/`) are scanned once globally.

So an agent can use custom skills stored **anywhere** on disk — just point at them
via `extra_skill_paths`. Two equivalent entry points:

```python
# Declarative (recommended): in the agent's init_config.json → written verbatim to
# config.json by create(), read back by restore().
{
  "extra_skill_paths": ["/shared/skills", "research/skills"]
}

# Programmatic: pass when driving discovery directly.
discovered = agent.discover_skill_sources(env, extra_skill_paths=["/shared/skills"])
```

The default `<root>/custom/skills` scan is unchanged when no extra paths are given.

## State management

State lives in two places:

- **`AGENT.json`** — dynamic self-description, persisted via `to_workspace` /
  `persist_agent_json`. Extend it by overriding `build_agent_json`.
- **Skill runtime state** — handled by the `AgentSkillRuntime` for activated skills;
  use `activate_skill` / `read_skill_file` / `execute_skill_script` (ReAct tools).

For workspace-backed agents (Template 4), the workspace FS (`read` / `write` /
`append` / `list` / `grep`) is exposed through ReAct tools dispatched by the base
`dispatch_react_tool`. Minimal/game agents (Templates 1–3) read/write their own
`AGENT.json` directly.

## Persistence

Persistence is workspace-based:

- `to_workspace(workspace_path)` writes dynamic state back to the workspace.
- The framework reconstructs agents via `from_workspace` → `restore` on restart.
- For replay, env modules write to replay tables via `set_replay_writer`; agent
  state is restored from the workspace.

## Properties

- `id: int` — unique identifier (set in `restore`).
- `name: str` — display name (set in `restore`).
- `logger: logging.Logger` — agent-scoped logger.
- `skill_runtime` — `AgentSkillRuntime` instance (None until `restore`).

`self._env` (the env router) and `self._dispatcher` (the LLM dispatcher) are
underscore-prefixed service slots injected by `_bind_services`; prefer the public
`ask_env` / `acompletion` over touching them directly.

## What NOT to call (internal, `_`-prefixed, may change)

`_bind_services`, `_bind_workspace`, `_setup_skill_runtime`,
`_refresh_visible_skills`, `_call_react_llm`, `_execute_react_tool`,
`_complete_react_once`, `_parse_react_responses`, `_workspace` (property),
`_trace` (property), `_todo_store`, `_normalize_todo_tool_args`, etc. The only
internal minimal/game agents call directly is `self._bind_services(service_proxy)`
inside their custom `restore` (because they skip `super().restore()`).
