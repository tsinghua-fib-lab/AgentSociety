# Generate

Write the Agent code.

## Output Location

`custom/agents/<agent_name>.py` (or a nested path such as `custom/agents/<package>/<agent_name>.py`). Avoid `examples/` if the file should be picked up by **Scan Custom Modules**.

## Generation Steps

1. Select appropriate template from `artifacts/templates.md`
2. Replace placeholders with actual values
3. Implement custom logic in `ask()` and `step()`
4. Add `description()` and `init_description()` with profile fields
5. Keep the implementation proportional to the simulation scale budget chosen during intake

## Template Placeholders

| Placeholder | Replace With |
|-------------|--------------|
| `{AgentName}` | Class name (PascalCase) |
| `{Description}` | Brief description |
| `{Short Description}` | One-line summary |
| `{field_list}` | Profile field names |

## Code Quality

- **Inherit ONLY from `AgentBase` or `PersonAgent`.** Never subclass an existing agent (contrib agent or another custom agent) to reuse behaviour. Read similar agents as **references** and re-implement the methods (`ask`, `step`, `restore`, `to_workspace`, `build_react_messages`, …) yourself in the new file. The validator enforces a direct `AgentBase`/`PersonAgent` base, and subclassing drops inherited contracts (notably env `@tool` interaction setup). Rewrite from scratch.
- Use async for all required methods (`to_workspace`, `ask`, `step`)
- State setup goes in `restore`
- Use current framework skill runtime and LLM role APIs
- If reusing `run_react_loop`, override `build_react_messages`
- Env or LLM failures should be handled predictably (do not blanket-swallow exceptions)
- Use `.get(key, default)` for profile access
- Keep `to_workspace` / `restore` symmetric
