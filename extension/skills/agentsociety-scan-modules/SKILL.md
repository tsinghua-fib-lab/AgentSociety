---
name: agentsociety-scan-modules
description: Use when agent or environment module names are unknown, need validation, or the user asks which modules are available in the workspace.
---

# Scan Modules

Scan and query available agent classes and environment modules in the AgentSociety2 workspace.

## When to Use
- User asks what agents or environment modules are available
- Need to find a module by name or keyword before configuring an experiment
- Preparing module data for hypothesis generation or experiment-config
- Validating that a custom module is loadable

**Do NOT use when:**
- You already know the exact class name and just need to write code that imports it
- The task is about creating a new module (use create-agent instead)

## Quick Reference

Use the Python interpreter from `.env`. See `CLAUDE.md` for setup.

Run commands from the workspace root through `.agentsociety/bin/ags.py`.

| Action | Command |
|--------|---------|
| List all modules | `$PYTHON_PATH .agentsociety/bin/ags.py scan-modules list` |
| List short names | `$PYTHON_PATH .agentsociety/bin/ags.py scan-modules list --short` |
| Filter by type | `$PYTHON_PATH .agentsociety/bin/ags.py scan-modules list --type agent` (or `env`) |
| Custom modules only | `$PYTHON_PATH .agentsociety/bin/ags.py scan-modules list --custom-only` |
| Full descriptions | `$PYTHON_PATH .agentsociety/bin/ags.py scan-modules list --full` |
| JSON output | `$PYTHON_PATH .agentsociety/bin/ags.py scan-modules list --json` |
| Module info | `$PYTHON_PATH .agentsociety/bin/ags.py scan-modules --workspace PATH info --type TYPE --name NAME` |
| Search by keyword | `$PYTHON_PATH .agentsociety/bin/ags.py scan-modules --workspace PATH search --keyword KEYWORD [--type TYPE]` |
| Export to JSON | `$PYTHON_PATH .agentsociety/bin/ags.py scan-modules --workspace PATH export --output FILE` |
| Validate module | `$PYTHON_PATH .agentsociety/bin/ags.py scan-modules --workspace PATH validate --type TYPE --name NAME` |

Common options: `--workspace PATH` to target a specific workspace directory. `scan_modules.py` now accepts `--workspace` either before or after the subcommand, but prefer the form before the subcommand in examples for consistency.

### info

```bash
$PYTHON_PATH .agentsociety/bin/ags.py scan-modules --workspace PATH info --type TYPE --name NAME [--json]
```

Shows: full description, constructor parameters, file location, import path, prefill parameters.

### search

```bash
$PYTHON_PATH .agentsociety/bin/ags.py scan-modules --workspace PATH search --keyword KEYWORD [--type TYPE] [--json]
```

### export

```bash
$PYTHON_PATH .agentsociety/bin/ags.py scan-modules --workspace PATH export --output FILE
```

### validate

```bash
$PYTHON_PATH .agentsociety/bin/ags.py scan-modules --workspace PATH validate --type TYPE --name NAME
```

Checks that the module can be imported and instantiated.

## Module Locations

- **Built-in Agents**: `packages/agentsociety2/agentsociety2/agent/person.py`
- **Built-in Envs**: `packages/agentsociety2/agentsociety2/contrib/env/`
- **Contrib Agents**: `packages/agentsociety2/agentsociety2/contrib/agent/`
- **Custom Modules**: `<workspace>/custom/agents/` and `<workspace>/custom/envs/`

Note: `packages/agentsociety2/agentsociety2/custom/` contains template files copied to workspace during init — it is not a runtime module location.

## Module Type Identifiers

Use the **class name** as the type identifier:

| Class Name | Type Identifier |
|------------|-----------------|
| PersonAgent | `PersonAgent` |
| SimpleSocialSpace | `SimpleSocialSpace` |
| PrisonersDilemmaEnv | `PrisonersDilemmaEnv` |

## Common Mistakes

| Mistake | Fix |
|---------|-----|
| Using snake_case names as type identifiers (e.g., `person_agent`) | Use the exact class name (e.g., `PersonAgent`) |
| Skipping validate before relying on a module | Always run `validate` after discovering a module you plan to use |
| Searching with wrong `--type` filter | Use `--type agent` for agents, `--type env` for environments; omit `--type` to search both |

## Pipeline Position

**Predecessors:** None
**Successors:** hypothesis, experiment-config
**Required Sub-Skills:** None

Called as an optional discovery and validation helper by hypothesis and experiment-config.
