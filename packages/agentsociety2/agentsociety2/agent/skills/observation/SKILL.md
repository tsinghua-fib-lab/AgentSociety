---
name: observation
description: Fetch the current world observation for this tick.
---

# Observation

You are a situated agent in a simulated world. This skill fetches the latest sensory observation for the current tick—what you can see, hear, and perceive around you.

## When to Use

Activate this skill when you need fresh perception for the current tick. Other skills **may** read `state/observation.txt` / `state/observation_ctx.json` if those files exist—there is no hard activation order.

## Workflow

1. Call `codegen` with `instruction: "<observe>"` and `ctx: {"id": <your_agent_id>}` (replace <your_agent_id> with your actual agent ID from the Agent Identity section).
2. Parse the response:
   - `stdout` contains the observation text (natural language description of what you perceive).
   - `ctx` contains structured environment data (positions, nearby agents, objects, time, weather, etc.).
3. **If the response contains `status: "in_progress"`**: the environment is still processing. Call `done` and resume next tick.
4. Write the observation to workspace for downstream skills:

```
workspace_write("state/observation.txt", <stdout text>)
```

5. If `ctx` contains useful structured data, also write it:

```
workspace_write("state/observation_ctx.json", <ctx as JSON string>)
```

## Persisting perception

After a successful observe, if you want a durable trace, append one line to `memory.jsonl` with `type: "observation"` (or `event`) and a short factual `summary`. Skip if this tick’s perception duplicates the latest entry.

## What Observation Contains

The observation text typically includes:

### Location Information
- Where you are (building, street, park, etc.)
- Your current coordinates or position
- Available exits or directions

### Nearby Entities
- Other agents in the vicinity
- Objects and items you can interact with
- Points of interest (shops, landmarks, etc.)

### Environmental Context
- Current time of day
- Weather conditions
- Any ongoing events or activities

### Available Actions
- What actions are possible in the current location
- What interactions are available with nearby entities

## Re-observation After Actions

Do not re-observe repeatedly in the same step. After a meaningful environment action, end the step and observe on the next tick unless the tool result is ambiguous and immediate clarification is necessary.

1. Execute action via `codegen`.
2. Check the response status.
3. If status is `success` or `in_progress`, call `done`.
4. Observe again on the next tick and update `state/observation.txt` / `state/observation_ctx.json`.

This keeps the agent's internal state aligned with the environment without turning one step into an observation loop.

## Observation Context Structure

The `state/observation_ctx.json` typically contains:

```json
{
  "agent_id": 1,
  "position": {"x": 100, "y": 200},
  "location": "park_entrance",
  "nearby_agents": [
    {"id": 2, "name": "Alice", "distance": 5.2}
  ],
  "nearby_objects": [
    {"id": "bench_01", "type": "bench", "distance": 2.0}
  ],
  "time": {"hour": 10, "minute": 30},
  "weather": "sunny",
  "available_actions": ["move", "interact", "wait"]
}
```

## Important Notes

- Prefer writing `state/observation.txt` every time you observe so the workspace stays self-consistent.
- If you skip observation, other skills have less grounding—work from profile + whatever files already exist.
- The `ctx` JSON may be large; you don't need to memorize it all—write it to `state/observation_ctx.json` and let readers pull fields as needed.
- If `codegen` returns an error, write a short note into `state/observation.txt` so later reads see what failed.

## Notes on State

This skill only produces **observation artifacts** (`state/observation.txt`, optional `state/observation_ctx.json`).
Higher-level “agent state snapshot / replay logging” is considered **system functionality** rather than a human-like capability skill, and should be handled by the runtime/framework if needed.
