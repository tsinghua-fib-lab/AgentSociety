# Common Pitfalls for Env Module Authors

These are the bugs that production Codex sessions actually hit when writing custom env modules. Read this **before** you generate code, and run through the checklist again before declaring the module ready.

---

## P1 — Return shape: `status` must be a STRING

The router's prompt-summarisation stage calls `status.upper()` on the value extracted from your tool's return. If your `@tool` returns a `bool`, or a dict whose `status` key is a `bool`, the chain breaks with:

```
WARNING env call failed: 'bool' object has no attribute 'upper'
```

Worse: the warning is **swallowed** by some agent wrappers, so writes silently no-op and your replay tables stay empty.

### Anti-pattern

```python
@tool(readonly=False)
async def submit(self, agent_id: str, amount: int) -> dict:
    self._buf[agent_id] = amount
    return {"success": True}            # ✗ bool, not status string
```

```python
return True                              # ✗ plain bool
return {"success": True, "data": ...}    # ✗ wrong field name
```

### Right pattern

```python
return {"status": "success", "response": f"Recorded {amount}"}
```

Valid `status` values: `"success" | "fail" | "in_progress" | "error"`.
On `fail` / `error`, include a `reason` field so the LLM can recover or report it cleanly.

For typed returns, use a Pydantic model whose `status` field is annotated `str`. See `contrib/env/public_goods.py:17-22` (`SubmitContributionResponse.status: str`).

### How the framework consumes this

- `agentsociety2/env/router_codegen.py` ≈ line 801: the generated closure extracts `results["status"]` with a soft fallback.
- `agentsociety2/env/router_codegen.py` ≈ line 1211: `status = results.get("status", "unknown")`.
- `agentsociety2/env/router_base.py` ≈ line 1183: the prompt builds with `status.upper()`.

There is **no runtime schema validator** between your tool and these call sites. You must produce the right shape yourself.

---

## P2 — Instruction style: describe operations in prose, not as function-call literals

The module `description()` / `init_description()` text and your `@tool` docstrings may be shown to an LLM. From that, the LLM **generates** Python that calls your tool. If your docs phrase the operation as a literal Python call, the LLM tends to echo the literal back instead of writing properly variable-bound code.

### Anti-pattern

```text
Available operations:
- submit_contribution(agent_name="Agent-1", contribution=10): submit a contribution
```

### Right pattern (from `contrib/env/public_goods.py:118-128`)

```text
**Available Operations (you MUST use these within your plan):**
1. **submit_contribution(agent_name, contribution)**: Submit your contribution
   - agent_name: Your full name (e.g., "Agent-1")
   - contribution: 0 to {self.initial_endowment} coins
   - You MUST submit exactly once per round before round executes
```

Bold the function name + parameter names, then describe semantics in prose. The agent side should then invoke it with natural language: `"Please call submit_contribution() using agent_name and contribution from ctx['variables'] ..."` (see `contrib/agent/public_goods_agent.py:157`).

---

## P3 — Same-step idempotency: writes MUST be safe under repeated invocation

The `CodeGenRouter` re-executes the entire generated code block on retryable failures, and the agent-side template cache can replay a previously-recorded closure. Both can cause a single user-intent to fire your `@tool` **more than once per step**.

If your write does any of these unconditionally:

```python
self._counter += 1
self._events.append(event)
self._seen.add(thing)        # OK actually — set is idempotent
self._rows.append(row)       # ✗ list append is NOT idempotent
```

you will see inflated counts (`counter_attitudinal_share > 1.0`, duplicate endline rows, etc.).

### Two safe patterns

**Pattern A — last-write-wins** (preferred for "submit X" style):

```python
self._pending[agent_id] = value           # overwrite is idempotent
self._submitted_this_step.add(agent_id)   # set, not list
```

This is what `contrib/env/public_goods.py:166-168` does. A second call from the same agent in the same step is a no-op semantically.

**Pattern B — explicit per-step dedup key**:

```python
key = (agent_id, target_id)
if key in self._seen_this_step:
    return {"status": "success", "response": "noop (already done this step)"}
self._seen_this_step.add(key)
# … do the write …
```

Clear `self._seen_this_step` at the start of `step()`. If your env exposes multiple write tools that should each fire at most once per step, give each its own `_seen_*_this_step` set.

### What the framework does NOT provide

There is no `@idempotent_per_step` decorator and no built-in `_seen_keys` mechanism. `EnvBase._tool_call_history` is a **passive log only** — it does not guard against re-execution. Idempotency is the module author's responsibility.

---

## P4 — Variable-name collisions with the agent-side template cache

The agent-side template cache (`router_codegen.py:534-712`) keys cached closures on:

1. `env_class_type` fingerprint, AND
2. `variable_keys = tuple(sorted(variables.keys()))`, AND
3. cosine similarity of the instruction-string embedding (default threshold 0.85).

It does **NOT** include the tool name in the key. Two different write tools whose **agent-side instruction strings are phrased similarly** and which take **arguments with the same names** can silently swap closures.

The Levy reproduction hit this exact bug: `read_post(post_id=...)` and `share_post(post_id=...)` shared `variable_keys=("post_id",)`. With similar instruction phrasing on the agent side, `share_post` calls reused `read_post`'s cached closure, and share events never reached the database.

### Mitigations on the env side

- **Distinguish argument names** across write tools. Prefer `read_target_post_id` / `share_target_post_id` over generic `post_id` if both `read_post` and `share_post` exist.
- Make argument types semantically richer when natural: a `post: PostDict` parameter is less likely to collide than a bare `post_id: str`.
- Keep tool docstrings distinctive — opening sentences that share many tokens push the embedding similarity over 0.85.

The agent side has the complementary fix: either rename variables when calling, or pass `template_mode=False` for writes when the env has not been audited for collisions. See the create-agent skill's pitfalls doc for that side.

---

## P5 — Inheritance drops inherited `@tool` methods: inherit ONLY from `EnvBase`

`EnvBase` uses the `EnvMeta` metaclass. At class-creation time it discovers `@tool`-decorated methods by iterating **only the class's own `namespace`** (the methods literally written in that `class` body) — and it **overwrites** `_registered_tools` / `_readonly_tools` / `_tool_kinds` on every subclass rather than merging with the base.

```python
# agentsociety2/env/base.py
class EnvMeta(type):
    def __new__(cls, name, bases, namespace, **kwargs):
        new_class = super().__new__(cls, name, bases, namespace, **kwargs)
        registered_tools = {}
        ...
        for attr_name, attr_value in namespace.items():          # own namespace ONLY
            if callable(attr_value) and hasattr(attr_value, "_tool_info"):
                ...
        new_class._registered_tools = registered_tools           # OVERWRITES, never merges
```

### Anti-pattern — subclass an existing module to "reuse" its tools

```python
from agentsociety2.contrib.env.social_media import SocialMediaEnv

class MySocialMedia(SocialMediaEnv):      # ✗ inherited @tool methods vanish
    @tool(readonly=False)
    async def boost(self, agent_id: str, post_id: str) -> dict:
        ...
        return {"status": "success"}
```

`MySocialMedia` will expose **only** `boost`. Every `@tool` inherited from `SocialMediaEnv` (`post`, `repost`, `comment`, `like`, `follow`, `refresh_feed`, …) is **silently dropped** from the registry because none of them are in `MySocialMedia`'s own `namespace`. The class imports cleanly, validation may pass, and agents simply cannot call the inherited tools — the env looks alive but is effectively non-functional.

Re-declaring a tool with the same name in the subclass to "shadow" it does not bring back the others either.

### Right pattern — rewrite from scratch, use the existing module only as a reference

```python
from agentsociety2.env import EnvBase, tool

# Read agentsociety2.contrib.env.social_media as a REFERENCE, then re-implement
# every tool the new module needs in THIS class body.

class MySocialMedia(EnvBase):             # ✓ direct EnvBase only
    def __init__(self, ...):
        ...

    @tool(readonly=False)
    async def post(self, agent_id: str, content: str) -> dict:   # re-implemented here
        ...
        return {"status": "success"}

    @tool(readonly=False)
    async def repost(self, agent_id: str, post_id: str) -> dict: # re-implemented here
        ...
        return {"status": "success"}

    # ...copy/rewrite every tool you need into this file's class body...
```

### How to check

1. Confirm the `class` line names `EnvBase` and **no** other env class: `grep -n "^class " custom/envs/<module>.py`.
2. Confirm every tool the module promises to expose is defined **inside the class body of that file**, not inherited.

---

## Quick self-audit (before validate)

1. Grep your file for `return True`, `return False`, `return {"success":`. Any hit in a `@tool`-decorated method is a P1 bug.
2. Read your `description()` / `init_description()` and tool docstrings. Are operations in prose with bold names, or as Python literals?
3. For every `@tool(readonly=False)` method, identify the write line. Is it idempotent under same-step repeat? If not, add a dedup key or last-write-wins buffer.
4. If you have two or more write tools, do they share argument names? If yes, rename or document the collision risk.
5. `grep -n "^class " custom/envs/<module>.py` — the only base class on that line must be `EnvBase`. If it names any other env/contrib class, rewrite the inherited tools into the file yourself (P5).
