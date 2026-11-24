# Agent Examples

Reference implementations in this repo (paths relative to the **agentsociety repo root**;
Python imports remain `agentsociety2....`). All examples below use the current
`AgentBase` contract: `create` / `from_workspace` classmethods, `restore` as the
init hook, and `to_workspace` for persistence.

## SimpleAgent

`packages/agentsociety2/agentsociety2/custom/agents/examples/simple_agent.py`

- Minimal game-style agent: reimplements `create` / `from_workspace`, calls
  `self._bind_services(service_proxy)` in `restore` (no `super().restore`).
- `ask()` uses `acompletion` for a one-shot LLM call.
- `step()` queries the env via `ask_env` and returns a summary.

**Use as template:** smallest concrete agent (Template 1).

## AdvancedAgent

`packages/agentsociety2/agentsociety2/custom/agents/examples/advanced_agent.py`

- Same construction model as SimpleAgent, plus persistent state
  (`_memories`, `_mood`) round-tripped through a custom `AGENT.json`.
- `to_workspace` writes memories + mood; `restore` reads them back.

**Use as template:** agents with internal state (Template 2).

## VolunteerDilemmaAgent

`packages/agentsociety2/agentsociety2/contrib/agent/volunteer_dilemma_agent.py`

- Full game agent: query history → decide → submit choice each `step()`.
- Canonical `ask_env` usage with `template_mode=True` (readonly query) and
  `template_mode=False` (stateful submit). See `references/pitfalls.md` P3.
- Reimplements `create` / `from_workspace` with a richer `AGENT.json` (history,
  num_rounds, benefit_b, cost_c).

**Use as template:** game / structured-decision agents (Template 3).

## PersonAgent

`packages/agentsociety2/agentsociety2/agent/person.py`

- The reference **full** agent: inherits `create` / `from_workspace` from `AgentBase`,
  overrides `restore` to call `await super().restore(...)` then build the memory runtime.
- Provides `build_react_messages` (person prompt) consumed by the base `run_react_loop`.
- Owns person-specific tools (`memory_*`, `todo_*`) via `dispatch_react_tool`.

**Use as template:** skill-based agents using `run_react_loop` (Template 4).

## AgentBase minimal example

`packages/agentsociety2/agentsociety2/agent/base/README.md` §7

- Authoritative minimal subclass showing the `restore` + `build_react_messages` +
  `to_workspace` + `ask` + `step` contract for the full pattern (uses `super().restore`
  + `run_react_loop`).

## Key Pattern: Memory / state in restore

```python
async def restore(self, workspace_path, service_proxy):
    # Minimal agent (custom AGENT.json, no super):
    meta = json.loads((Path(workspace_path) / "AGENT.json").read_text("utf-8"))
    self._id = int(meta.get("agent_id", meta.get("id", 0)))
    self._profile = meta.get("profile", {})
    self._name = meta.get("name") or f"Agent_{self._id}"
    self._config = {}
    self._bind_services(service_proxy)
    self._step_count = int(meta.get("step_count", 0))
    self._memories = list(meta.get("memories", []))
    self._mood = str(meta.get("mood", "calm"))
```

For full agents, `await super().restore(workspace_path, service_proxy)` handles
everything above; you only add the business fields after it.

## Key Pattern: Environment action

```python
async def step(self, tick, t):
    # Get state (readonly query — template_mode=True is safe)
    _, state = await self.ask_env(
        {"variables": {"agent_name": self.name}},
        "Please call get_state() using agent_name from ctx['variables'].",
        readonly=True,
        template_mode=True,
    )

    # Submit action (stateful write — default template_mode=False unless the
    # env tool is verified idempotent AND no other write tool shares argument
    # names. See references/pitfalls.md P3.)
    _, result = await self.ask_env(
        {"variables": {"agent_name": self.name, "action": decision}},
        "Please call submit_action() using agent_name and action "
        "from ctx['variables'] to submit my decision.",
        readonly=False,
        template_mode=False,
    )
```
