# Generate

Generate a single-file environment module at `custom/envs/<module_name>.py`.

Before writing code:

- Run `$PYTHON_PATH .agentsociety/bin/ags.py create-env-module-resolve-sources` if the runtime file locations are not obvious.
- Read `references/runtime-sources.md`.
- Confirm the real contract in `EnvBase`, the bundled local validator, and registry helpers.
- Read at least one reference implementation that matches the desired complexity.
- If the module carries mutable state, replay data, or resume requirements, read `references/persistence-patterns.md`.
- Keep the implementation proportional to the simulation scale budget chosen during intake.

Generation rules:

- Keep the class definition in the target file itself.
- **Inherit ONLY from `EnvBase`.** Never subclass an existing env module, a contrib module (e.g. `SocialMediaEnv`, `MobilitySpaceEnv`, `PublicGoodsEnv`), or any other concrete env class. Read such modules as **references** and re-implement the methods (`@tool`s, `step()`, state setup) yourself in the new file. Reason: `EnvMeta` only collects `@tool` methods from the class's own namespace and overwrites the registry on each subclass, so any tool you inherit is silently dropped — see `references/pitfalls.md` P5.
- Preserve `class_name` as the registry key.
- Include at least one legal `@tool`.
- Provide `step()`.
- Default to no-arg construction.
- If the module needs observation capability, provide it through one or more `@tool(readonly=True, kind="observe")` methods. Observe/statistics 都不是强制项；全空则 router 跳过对应初始化 codegen。
- Keep tool signatures and instruction templates stable. FAISS 模板缓存仅在 agent 侧 `ask(..., template_mode=True)` 时启用，不要假定默认就会命中 cache。
- Provide a short `description()` and useful `init_description()` for init kwargs.
- If per-agent state must be persisted to replay, declare `_agent_state_columns` and write through `_write_agent_state()` or `_write_agent_state_batch()`.
- If global environment state must be persisted to replay, declare `_env_state_columns` and write through `_write_env_state()`.
- Distinguish `tick` from replay `step`: in `EnvBase.step(self, tick, t)`, `tick` is the duration of one simulation step, not the monotonically increasing step index. Do not use `tick` directly as the primary-key step value for replay tables unless the design explicitly defines them to be the same.
- If the environment needs per-step replay snapshots, maintain an internal step counter such as `self._tick` / `self._step_index`, increment it once per `step()` call, and use that counter for `_write_agent_state_batch()` / `_write_env_state()` and other step-keyed state like `created_step`.
- If the module keeps mutable in-memory state, treat it as derived/cached: reconstruct it from the constructor kwargs + replay data on each run.
- If the module should support `--resume`, implement `to_workspace()` / `restore()` writing the dynamic state (counters, queues, maps) to `state/ENV_STATE.json` via `atomic_write_text` (separate from replay; see `references/persistence-patterns.md` → Workspace Persistence). Do NOT serialize `asyncio.Lock`, external subprocesses, or pre-trained model weights — rebuild them in `__init__`/`init()`.
- Persist step counters, IDs, queues, maps, or other reconstruction-critical state by writing them to replay tables (declare the columns, write via `_write_*`), not via a dump channel.
- Do not add placeholder persistence hooks. Either implement the real replay-write path or keep the module intentionally stateless.

## Bundled Agent Skills (recommended for interactive envs)

Agents learn how to operate in a new environment from a bundled skill. `EnvBase`
auto-discovers skills from a directory next to the module file, so for a
single-file module `custom/envs/<module>.py` place skills under
`custom/envs/<module>_agent_skills/`:

```
custom/envs/
├─ social_media.py
└─ social_media_agent_skills/
   └─ social-media/
      └─ SKILL.md
```

Each skill is a subdirectory holding a `SKILL.md`. **Every `SKILL.md` must start
with a YAML frontmatter block** (delimited by `---`) declaring at least `name`
and `description`:

```markdown
---
name: social-media
description: Social-media interaction: post / repost / comment / like / follow, refresh the feed, search posts. Reach env tools via ask_env.
---

# Social Media

Body — injected into the prompt only after the agent activates this skill.
Teach the ask_env(instruction=..., variables=..., ctx={"id": ...}, readonly=...)
contract here; keep instruction templates stable. FAISS 模板缓存仅在
`template_mode=True` 时启用。
```

Why this is mandatory: at selection time the model sees **only** the
`name`/`description` from the frontmatter. A `SKILL.md` without frontmatter is
silently registered with an empty `description`, so agents never discover or
select the skill and the environment is effectively unusable through the
catalog.

Only generate a bundled skill when the environment exposes tools an agent must
invoke (posting, moving, trading, observing). Stateless envs with self-evident
tools may skip it. Reference implementations with bundled skills:
`agentsociety2.contrib.env.mobility_space` and
`agentsociety2.contrib.env.social_media`.

After writing code, keep lightweight notes only if they help later review:

- If traceability matters, write a concise `generation_input.json` or `generation_summary.md` into the current run directory.
- Include `module_path`, `class_name`, and the key generation decisions worth reviewing later.
