---
name: agentsociety-create-agent
description: Use when creating or revising a custom agent type, when an experiment needs an agent class that does not yet exist in the workspace, or when the agent design must be sized against a simulation budget.
---

# Create Agent

Add Python modules under **`custom/agents/`** relative to the **workspace root** (the directory that contains `custom/`). The backend scanner loads every `*.py` under that tree **except** paths under an **`examples/`** segment.

- Nested folders are allowed (e.g. `custom/agents/research/lab_agent.py`).
- Prefer **one primary agent class per file** for clarity; the scanner can surface multiple `AgentBase` subclasses in the same file if you define them.

## When to Use
- User asks to create a new agent type (e.g., "student agent", "donor agent")
- Designing agent behaviors or implementing AgentBase/PersonAgent subclasses
- experiment-config needs an agent class that does not yet exist in the workspace
- Extending an existing agent with custom logic
- The simulation size, step budget, or runtime budget needs to shape the agent design

**Do NOT use when:**
- You only need to discover existing agents (use scan-modules)
- The task is about environment modules, not agents

## Quick Reference

Use the Python interpreter from `.env`. See `CLAUDE.md` for setup.

## Scale Budget

Collect the simulation scale budget before locking the agent design:

- target agent count or range
- expected step budget
- runtime or compute budget
- preferred complexity tier, such as lean, balanced, or rich

If the budget is still open, ask a single round of clarifying questions. Present 2-3 approaches with trade-offs and a recommendation, then choose the option that keeps per-agent logic proportional to the simulation size.

| Action | Command |
|--------|---------|
| Validate agent file | `$PYTHON_PATH .agentsociety/bin/ags.py create-agent --file /path/to/workspace/custom/agents/my_agent.py` |
| Validate (JSON output) | `$PYTHON_PATH .agentsociety/bin/ags.py create-agent --file ... --json` |
| Register | VS Code: **Scan Custom Modules** (and **Test Custom Modules** if needed) |

## Workflow

```dot
digraph create_agent_flow {
    rankdir=LR;
    node [shape=box, style=filled, fillcolor="#E8F4FD"];
    intake [label="gather requirements"];
    design [label="choose base class\nand state model"];
    generate [label="implement code\nfrom templates"];
    validate [label="run validator\nand self-check"];
    register [label="scan custom modules"];

    intake -> design -> generate -> validate -> register;
}
```

## Stage Notes

- `stages/intake.md`: gather requirements and clarify open questions
- `stages/design.md`: choose base class, workspace, profile, and state shape
- `stages/generate.md`: implement code with `artifacts/templates.md`
- `stages/validate.md` and `checklists/compatibility.md`: final validation

## Base Class

| Class | When to use |
|-------|-------------|
| `AgentBase` | 简单行为、游戏/基准；自行管理状态 |
| `PersonAgent` | Skills、工具循环、workspace、checkpoint；内置 skill 仅 **`daily-guidance`** |

**Inherit ONLY from `AgentBase` or `PersonAgent`.** Never subclass an existing agent — neither a contrib agent (e.g. `PublicGoodsAgent`) nor another custom agent in `custom/agents/`. If a similar agent already exists, read it as a **reference** and re-implement the methods (`ask`, `step`, `restore`, `to_workspace`, `build_react_messages`, …) yourself in the new file. The validator rejects anything that is not a **direct** `AgentBase`/`PersonAgent` subclass, but more importantly: env `@tool` discovery and the agent's own registration treat each class by its own namespace, so an agent that "inherits to reuse" behaviour silently loses the inherited contract. Rewrite from scratch.

Required and optional methods, LLM/env APIs, config: use **`references/agent-base-interface.md`** as the single detailed source (avoids duplicating it here).

## Environment and Profile

- Env call patterns: `references/environment-interaction.md`
- **Common pitfalls (read before writing `ask_env` code): `references/pitfalls.md`**
- Profile fields: `references/profile-design.md`
- In-repo examples: `references/examples.md`

## Custom Skills

By default an agent loads skills from `<workspace>/custom/skills/` plus any
environment-module skill dirs. You can also point an agent at skills stored
**anywhere** on disk — useful for sharing a skill library across agents or
mounting skills from outside the workspace:

- **Declarative** (recommended): add `extra_skill_paths` to the agent's
  `init_config.json` (written verbatim to `config.json`, read back on restore):
  ```json
  { "extra_skill_paths": ["/shared/skills", "research/skills"] }
  ```
- **Programmatic**: `agent.discover_skill_sources(env, extra_skill_paths=[...])`

Each entry is a root of skill subdirectories (same layout as `custom/skills`);
relative paths resolve against the workspace root. The default scan is unchanged
when omitted. Full details: `references/agent-base-interface.md` → *Skill sources*.

### Skill directory layout and required frontmatter

Each skill is a subdirectory containing a `SKILL.md` file. **`SKILL.md` must
start with a YAML frontmatter block** delimited by `---` and declare at least
`name` and `description`:

```
custom/skills/
└─ my-skill/
   └─ SKILL.md
```

```markdown
---
name: my-skill
description: One-line summary the agent sees in the skill catalog before activation. Keep it specific.
---

# My Skill

Body — only injected into the prompt AFTER the agent activates this skill.
```

The `name`/`description` are the **only** catalog fields the model sees at
selection time. A `SKILL.md` without frontmatter is silently registered with an
empty `description`, so the agent effectively never discovers or selects it.
Rules:

- `name`: stable skill id; lowercase kebab-case is conventional.
- `description`: concise, action-oriented; mention what it does and that env
  tools are reached via `ask_env` when the skill drives an environment.
- `script` / `hooks` are optional frontmatter keys.
- Keep the body's `ask_env` instructions stable (template + `variables`) so env
  router cache hits across agents.

## Validation

```bash
$PYTHON_PATH .agentsociety/bin/ags.py create-agent --file /path/to/workspace/custom/agents/my_agent.py
$PYTHON_PATH .agentsociety/bin/ags.py create-agent --file ... --json
```

The script checks: AST shows a **direct** base named **`AgentBase`** or **`PersonAgent`**,
the three required abstracts (`to_workspace`, `ask`, `step`) are **`async def`**,
the module imports, and the class is not abstract. That is **stricter**
than **Scan Custom Modules**: the scanner now verifies real overrides of
`to_workspace`/`ask`/`step`, arg-less construction, and non-empty
`description()`/`init_description()` (via `build_agent_scan_diagnostic`), but it
does **not** enforce `async def` or a direct base class — this validator does.

`AgentBase` already defines default `description()` and `init_description()` methods;
overriding both is still recommended for real modules.

For the full human checklist see `stages/validate.md` and `checklists/compatibility.md`.

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Subclassing an existing agent (contrib or another custom agent) to reuse behaviour | Don't. The validator requires a **direct** `AgentBase`/`PersonAgent` base, and inherited contracts (e.g. env `@tool` interaction setup) are not carried over reliably through subclassing. Rewrite the methods yourself in the new file, inheriting ONLY from `AgentBase` or `PersonAgent` |
| Putting runtime state in construction code | Put state setup in `restore(self, workspace_path, service_proxy)` and persist state through `to_workspace` |
| Reusing `run_react_loop` without overriding `build_react_messages` | The base raises `NotImplementedError`. Always override `build_react_messages` when you call `run_react_loop` |
| Using intermediate base classes that fail the AST validation rule | Ensure direct inheritance from `AgentBase` or `PersonAgent`, or follow the MRO note in `stages/validate.md` |
| Forgetting to make required methods async | `to_workspace` / `ask` / `step` must all be `async def` |
| Not running the validator after creating the agent | Always run `.agentsociety/bin/ags.py create-agent --file ...` as the final step |
| Adding files under an `examples/` path | The scanner skips any path containing an `examples/` segment; place files directly under `custom/agents/` |
| Phrasing `ask_env` message as a Python call literal (`"tool(arg=val)"`) | Use natural language `"Please call tool_name() using <args> from ctx['variables'] ..."` — see `references/pitfalls.md` P2 |
| Using `template_mode=True` for `readonly=False` writes without checking idempotency / argument-name collisions | Default to `template_mode=False` for writes; only enable when the env tool is verified idempotent AND argument names don't collide with other writes — see `references/pitfalls.md` P3 |
| Calling the same write tool more than once per `step()` "to be safe" | Trust the `status` return; retry only on `fail`/`error` — see `references/pitfalls.md` P4 |
| Shipping a `SKILL.md` without YAML frontmatter (or with empty `description`) | Always start `SKILL.md` with `---` frontmatter declaring `name` + `description`; without it the skill registers with an empty description and is never selected — see *Custom Skills* above |

## Subagent Delegation

Stages 2-3 (design + code generation) can consume significant context. Delegate to subagents when:

- The agent design involves complex logic (multi-step reasoning, state machines, nested tool calls)
- The profile has many custom fields that need careful mapping
- The hypothesis requires non-trivial agent behaviors tied to experiment variables
- The target simulation size is high enough that the design needs a leaner reasoning or state strategy
- You are in a long research pipeline session and context is at a premium

**How to delegate (planner → generator → reviewer):**

1. Complete Stage 1 yourself (intake). Collect user requirements.
2. **Planner**: Dispatch a subagent with the user requirements + hypothesis context, instructing it to read `subagent-prompts/planner.md` and follow it. The planner produces a structured DesignSpec JSON — what methods to implement, what state to track, what persistence is needed, all tied to the hypothesis.
3. **Generator**: Dispatch a subagent with the DesignSpec, instructing it to read `subagent-prompts/implementer.md` and follow it. The generator writes code from the spec.
4. **Reviewer**: Dispatch a subagent with the file path + DesignSpec, instructing it to read `subagent-prompts/reviewer.md` and follow it. The reviewer checks the code against the spec with fresh context.
5. After all subagents return, run `$PYTHON_PATH .agentsociety/bin/ags.py create-agent --file ...` yourself and fix any remaining issues from the reviewer report.

**Do NOT delegate:** simple agents that inherit from `AgentBase` with trivial `ask`/`step` overrides. For those, do Stages 1-4 yourself.

## Pipeline Position

**Optional helpers:** scan-modules (to check existing agents before creating a new one)
**Successors:** experiment-config (when custom agents are needed)
**Required Sub-Skills:** None

Called by experiment-config as an optional branch when the required agent class does not already exist.
