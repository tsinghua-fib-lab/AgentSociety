# Environment Interaction Patterns

> **Read `references/pitfalls.md` before writing `ask_env` calls.** It covers the four production bugs (return-shape misuse, function-literal messages, template-cache collision, retry inflation) that this guide's patterns are designed to avoid.

## ask_env Method

```python
async def ask_env(
    self,
    ctx: dict,
    message: str,
    readonly: bool,
    template_mode: bool = False
) -> tuple[dict, str]
```

Returns `(updated_context, response_string)`. The `message` is an **instruction to the codegen LLM** — phrase it as natural language ("Please call …"), not as a Python call literal.

## Common Patterns

### Query State (read-only)

```python
_, observation = await self.ask_env(
    {},
    "Please describe the current environment state.",
    readonly=True,
)
```

### Get Agent-Specific Data (read-only, with variables)

`template_mode=True` is safe and recommended for read-only queries — it caches the codegen and saves an LLM call.

```python
ctx, response = await self.ask_env(
    {"variables": {"agent_id": self.id}},
    "Please call get_state() using agent_id from ctx['variables'].",
    readonly=True,
    template_mode=True,
)
```

### Execute Action (stateful write)

For writes, the safest default is **`template_mode=False`** unless you have verified the env tool is idempotent per step AND no other write tool shares the same argument names. See `references/pitfalls.md` P3.

```python
ctx, response = await self.ask_env(
    {"variables": {
        "agent_id": self.id,
        "action": "move",
        "target": "home",
    }},
    "Please call execute_action() using agent_id, action, and target "
    "from ctx['variables'] to perform the move.",
    readonly=False,
    template_mode=False,
)
```

Notes:

- The message uses `"Please call <tool>() using <args> from ctx['variables'] ..."` — natural language, function name in bare form, parameter names matching the keys you passed.
- Do NOT write `"execute_action(agent_id={agent_id}, target={target})"` as the message — the LLM will sometimes echo that literal back, and the generated closure mis-parses.
- See `contrib/agent/public_goods_agent.py:157` for the canonical built-in pattern.

## Context Overlay

Agent identity is automatically merged from `self.env_ask_env_ctx_overlay()`:
- `id`, `agent_id`, `person_id`

You don't need to pass these explicitly:

```python
# These are equivalent:
ctx, response = await self.ask_env({}, "My state", readonly=True)
ctx, response = await self.ask_env({"id": self.id}, "My state", readonly=True)
```

## Template Variables

You can pass `{"variables": {...}}` and reference them in the instruction. The codegen LLM reads `ctx['variables']` and binds the call accordingly. Prefer phrasing that names the variables in prose:

```python
# Multiple variables — readonly query, template_mode=True is safe.
ctx, response = await self.ask_env(
    {"variables": {
        "donor": self.id,
        "recipient": neighbor_id,
    }},
    "Please call get_relationship() using donor and recipient "
    "from ctx['variables'].",
    readonly=True,
    template_mode=True,
)
```

If you have two or more write tools that take **the same argument names** (e.g. both `read_post` and `share_post` take `post_id`), the template cache key collides on those variable names + similar instruction wording. Either:

- give the variables distinct names per call (`read_post_id` vs `share_post_id`), or
- set `template_mode=False` for the writes.

See `references/pitfalls.md` P3 for the full mechanism.

## Error Handling

When `ask_env` fails, behavior should be **predictable**: log, degrade to a default, or **re-raise** for upper layers—avoid bare `except` that hides everything. If you catch exceptions, keep the scope narrow (e.g. timeout or specific types only).

```python
try:
    _, result = await self.ask_env({}, "Query", readonly=True)
except TimeoutError:
    self.logger.warning("env query timed out")
    result = ""
```

## Readonly vs Read-Write

| Mode | `readonly` | Use Case |
|------|------------|----------|
| Query | `True` | Get information without side effects |
| Action | `False` | Execute actions that change state |

## Response Structure

The response string format depends on the environment module. Common patterns:

```python
# Observation response
updated_ctx, observation_text = await self.ask_env(
    {"id": self.id},
    "Please describe what is observable to me right now.",
    readonly=True,
)

# Action response — stateful write defaults to template_mode=False
updated_ctx, result_text = await self.ask_env(
    {"variables": {"agent_id": self.id, "target": "cafe"}},
    "Please call move_to() using agent_id and target from ctx['variables'].",
    readonly=False,
    template_mode=False,
)
```

The `updated_ctx` may contain structured data from the environment:

```python
ctx, response = await self.ask_env(
    {"variables": {"agent_id": self.id}},
    "Please call observe() using agent_id from ctx['variables'].",
    readonly=True,
    template_mode=True,
)
if "observations" in ctx:
    # Parse structured observation data
    neighbors = ctx["observations"].get("get_neighbors", {})
```

For the env tool's return-shape contract (`status: str` etc.), see `references/pitfalls.md` P1 and the env-module skill's pitfalls doc.
