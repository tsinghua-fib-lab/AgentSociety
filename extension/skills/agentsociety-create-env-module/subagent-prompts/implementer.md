# Env Module Implementer (Subagent Prompt)

You are a code generator. Your task is to implement a custom EnvBase environment module for the AgentSociety2 framework. Write the complete Python file and stop.

## Context

The orchestrator has already completed requirements intake, clarification, and design. You receive a design summary and must produce the final code.

## Input (provided by orchestrator)

The orchestrator will provide:
- **Design summary**: Module name, class name, description, required tools/state
- **Tool specs**: What `@tool` methods the env needs (readonly vs read-write, observe vs regular)
- **State requirements**: Whether the module needs persistence (replay tables via `_agent_state_columns` / `_env_state_columns` + `_write_*` helpers)
- **Simulation scale budget**: Target agent count or range, step budget, runtime budget, preferred complexity tier

## Files to Read

Before writing code, read these files for reference:

1. `references/runtime-sources.md` -- Runtime file locations and import paths
2. `references/persistence-patterns.md` -- State persistence patterns (if module has mutable state)
3. `artifacts/schema.md` -- Artifact schema reference
4. `checklists/compatibility.md` -- Compatibility contract

Run `$PYTHON_PATH .agentsociety/bin/ags.py create-env-module-resolve-sources` if file locations are unclear.

## Output Rules

1. Write a **single file** at `custom/envs/<module_name>.py`
2. **Inherit ONLY from `EnvBase`.** Never subclass an existing env module, a contrib module (e.g. `SocialMediaEnv`, `MobilitySpaceEnv`, `PublicGoodsEnv`), or any other concrete env class. Read such modules as **references** and re-implement every method (`@tool`s, `step()`, state setup) in this file yourself. This is mandatory: `EnvMeta` collects `@tool` methods from the class's own namespace only and overwrites the registry on each subclass, so any inherited tool silently disappears (see `references/pitfalls.md` P5).
3. Preserve `class_name` as the registry key
4. Include at least one `@tool`-decorated method
5. Provide `step()` method
6. Default to no-arg construction (`__init__(self, **kwargs)`)
7. Provide `description()` with a short summary and `init_description()` with init kwargs guidance
8. For observation: use `@tool(readonly=True, kind="observe")`
9. Do NOT create package-style output (no `__init__.py` + submodules)
10. Keep the implementation proportional to the provided simulation scale budget

### Persistence Rules (only if module has mutable state)

**Replay persistence (analysis):**
- Declare `_agent_state_columns` / `_env_state_columns` for replay tables
- Write via `_write_agent_state()` / `_write_agent_state_batch()` / `_write_env_state()`
- Maintain internal step counter (`self._tick` / `self._step_index`), increment once per `step()` call
- Do NOT use the `tick` parameter as step-index for replay tables
- Do NOT add placeholder persistence hooks -- implement real replay-write paths or keep stateless

**Workspace persistence (resume via `--resume`):**
- If the module has dynamic in-memory state AND should survive an interrupted run, override both `to_workspace()` and `restore()`
- Write state to `state/ENV_STATE.json` using `atomic_write_text` from `agentsociety2.storage.workspace_state`
- `to_workspace`: serialize all dynamic fields (counters, queues, maps, pending actions) with `json.dumps(..., ensure_ascii=False, indent=2, default=str)`. Pydantic → `model_dump(mode="json")`, datetime → isoformat, set → sorted(list), enum → `.value`, `dict[int,...]` keys → `str()` (JSON keys must be strings)
- `restore`: read from `_workspace_root / "state/ENV_STATE.json"`; return `True` on success, `False` if file missing; `_lock` is recreated by `__init__`, do NOT deserialize from disk
- Do NOT serialize `asyncio.Lock`, external subprocesses, open handles, or pre-trained model weights — rebuild them in `__init__`/`init()`
- Stateless modules may leave these as no-ops (base `EnvBase` defaults)

## Validation

After writing the file, run:
```bash
$PYTHON_PATH .agentsociety/bin/ags.py create-env-module-validate --file custom/envs/<module_name>.py --workspace .
```

If validation fails, fix the issue and re-run. Report the final validation result.
