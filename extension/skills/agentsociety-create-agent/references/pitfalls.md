# Common Pitfalls for Agent Authors

These are the bugs that production Codex sessions actually hit when writing custom agents that interact with custom env modules. Read this **before** you generate `ask_env` code, and run the checklist again before declaring the agent ready.

The env side has a companion doc (`agentsociety-create-env-module/references/pitfalls.md`); read it too if you author both sides.

---

## P1 — Don't assume tools always return the same shape

The framework guarantees the second element of `ask_env`'s return (the `response_text`) is a string suitable for prompt display. The first element (`updated_ctx`) is a dict whose schema is determined by the env module's tools — it may contain `results["status"]` (one of `"success"`, `"fail"`, `"in_progress"`, `"error"`), `results["response"]`, and tool-specific payloads.

If you branch on `ctx` keys, treat unknown shapes defensively:

```python
ctx, response = await self.ask_env({}, "Get state", readonly=True)
status = ctx.get("results", {}).get("status", "unknown")
if status != "success":
    self.logger.warning("env query did not succeed: %s", status)
```

Never `bool()` the response or pattern-match on the assumption that the env returns `{"success": True}` — that shape is broken (see env skill P1).

---

## P2 — Phrase your `ask_env` message as a natural-language instruction, not a function call

The router treats your message as the instruction the codegen LLM uses to write the closure that calls the env tool. If your message reads like Python (`"submit(agent_id=1, amount=10)"`), the LLM may emit the literal string verbatim instead of writing properly variable-bound code.

### Anti-pattern

```python
await self.ask_env(
    {"variables": {"amount": 10}},
    "submit(amount={amount})",      # ✗ looks like Python, not an instruction
    readonly=False,
)
```

### Right pattern (matches `contrib/agent/public_goods_agent.py:157`)

```python
await self.ask_env(
    {"variables": {"agent_name": self.name, "contribution": amount}},
    "Please call submit_contribution() using agent_name and contribution "
    "from ctx['variables'] to submit my contribution decision.",
    readonly=False,
    template_mode=True,
)
```

Key elements:

- "Please call `tool_name()`" — instructional verb + bare function name.
- "using `arg1` and `arg2` from `ctx['variables']`" — names match the keys in `ctx["variables"]`.
- One sentence describing intent.

This is the style every built-in agent under `agentsociety2/contrib/agent/` uses.

---

## P3 — `template_mode=True` reuses a cached closure — distinguish writes carefully

The agent-side template cache (`router_codegen.py:534-712`) keys cached closures on:

1. `env_class_type` fingerprint, AND
2. `variable_keys = tuple(sorted(variables.keys()))`, AND
3. cosine similarity of the instruction-string embedding (default threshold 0.85).

It does **NOT** key on tool name. Two different writes that share an argument name and have similar instruction phrasing can silently swap closures — your `share_post` call lands on the cached `read_post` closure, no database write occurs, and only the log shows the intended call.

### Rules of thumb

| Situation | `template_mode` |
|---|---|
| `readonly=True` query (observation, statistics, per-agent state) | `True` is fine and recommended |
| `readonly=False` write, env tool is naturally idempotent (last-write-wins, set-based) | `True` is OK if argument names are distinct from other writes |
| `readonly=False` write, multiple writes share argument names | **`False`** — pay one extra codegen call to avoid silent collision |
| `readonly=False` write, env tool's idempotency is unverified | **`False`** — safer default |

### Anti-pattern

If your env module exposes `read_post(post_id=...)` and `share_post(post_id=...)`, do NOT call both with `template_mode=True` and `{"variables": {"post_id": ...}}`. Either:

- Rename your calling variables (`read_target_id` vs `share_target_id`) so the cache keys differ, OR
- Set `template_mode=False` for at least one of them.

### Right pattern

```python
# Query with template_mode=True — safe
_, state = await self.ask_env(
    {"variables": {"agent_id": self.id}},
    "Please call get_state() using agent_id from ctx['variables'].",
    readonly=True,
    template_mode=True,
)

# Write with template_mode=False — safe by default
_, result = await self.ask_env(
    {"variables": {"target_post": post_id, "comment": text}},
    "Please call share_post() using target_post and comment from ctx['variables'].",
    readonly=False,
    template_mode=False,
)
```

---

## P4 — Don't call the same write twice per step "to be safe"

The env-side may or may not be idempotent against re-invocation. If you call `share_post` twice in one `step()` "in case the first failed", you risk inflating counters by 2× when both succeed.

- Trust the return value of `ask_env`. If the env returns `status="success"`, the write happened.
- If you must retry, check the response and only retry on `status="fail"` / `"error"`.
- Do not loop over `ask_env` write calls without a guard.

If you author the env tool yourself, follow the env skill's pitfall doc P3 (last-write-wins or dedup key).

---

## Quick self-audit (before validate)

1. Grep your agent file for `template_mode=True`. For each hit, check the `readonly=` value:
   - `readonly=True` → fine
   - `readonly=False` → confirm the env tool is idempotent AND no other write tool shares the same argument names.
2. Read your `ask_env` message strings. Do any look like Python expressions (`tool(arg=val)`)? Rewrite as "Please call tool_name() using …".
3. In `step()`, count how many `readonly=False` `ask_env` calls fire per agent per step. More than one of the same tool is a smell.
