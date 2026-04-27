---
name: plan
description: Execute intentions through the environment.
---

# Plan

Execute intentions by generating environment actions via `codegen`.

## Activation

Activate this skill when you have an intention to execute.

## Dual-Process Decision Making

Human decisions arise from two systems:

### System 1: Fast, Habitual

- Triggered by: routine situations, familiar contexts
- Characteristics: quick, automatic, low cognitive load
- Output: single-step action, no plan_state needed
- Use when:
  - Routine activity (eating, sleeping, commuting)
  - Time pressure
  - Low stakes
  - Strong habit exists

### System 2: Deliberate, Planned

- Triggered by: novel situations, complex goals, conflicts
- Characteristics: slow, analytical, requires attention
- Output: multi-step plan_state.json
- Use when:
  - New or unfamiliar goal
  - Multiple steps required
  - High stakes or uncertainty
  - Conflicting options

### System Selection

| Condition | System |
|-----------|--------|
| Routine time + routine action | System 1 |
| Familiar location + known action | System 1 |
| New intention + complex goal | System 2 |
| Multiple options + uncertainty | System 2 |
| Urgent need + known solution | System 1 |
| Conflict detected | System 2 |

## Input Files

| File | Use |
|------|-----|
| `state/intention.json` | Current goal |
| `state/observation.txt` | Environment context |
| `state/plan_state.json` | Ongoing multi-step plan |

## Output Files

### state/plan_state.json

```json
{
  "goal": "Buy groceries at the supermarket",
  "steps": ["walk to supermarket", "enter store", "pick items", "pay"],
  "current_step": 1,
  "started_tick": 42,
  "status": "in_progress",
  "decision_mode": "system2",
  "estimated_ticks": 4
}
```

## Single-Step Actions (System 1)

Most routine intentions execute in one `codegen` call:

```json
{
  "tool_name": "codegen",
  "arguments": {
    "instruction": "Move to the café on Main Street.",
    "ctx": {}
  }
}
```

No `plan_state.json` needed for single-step actions.

## Multi-Step Plans (System 2)

For complex goals, maintain `state/plan_state.json`:

1. Check if `plan_state.json` exists
2. If new intention, generate steps (max 6)
3. Execute current step via `codegen`
4. Update `plan_state.json` with progress
5. Clear when all steps complete

### Step Status

| Status | Meaning |
|--------|---------|
| `pending` | Not started |
| `in_progress` | Currently executing |
| `completed` | Successfully finished |
| `failed` | Cannot complete |

### Step Complexity

| Steps | Use Case |
|-------|----------|
| 1-2 | Simple location change, simple interaction |
| 3-4 | Multi-location trip, task with preparation |
| 5-6 | Complex project, event with multiple phases |

## Need-Driven Plan Adjustment

Plans adapt to changing physiological states.

### Adjustment Triggers

| Trigger | Action |
|---------|--------|
| `satiety < 0.2` | Pause plan, find food |
| `energy < 0.2` | Pause plan, rest |
| `safety < 0.2` | Pause plan, seek safety |
| Need satisfied mid-plan | Resume original plan |

### Plan State for Interruption

```json
{
  "goal": "Work on project",
  "status": "interrupted",
  "interrupted_at_step": 2,
  "interrupt_reason": "satiety_critical",
  "resumable": true,
  "resume_conditions": ["satiety > 0.5"]
}
```

### Resume Logic

1. Check `resumable` flag
2. Verify all `resume_conditions` met
3. Continue from `interrupted_at_step`
4. Update status to `in_progress`

## Plan Interruption

Interrupt ongoing plan when:
- New urgent need emerges (satiety/energy < 0.2)
- Current intention differs significantly
- Environment makes plan impossible
- External event requires attention

### Forced vs Voluntary

| Type | Condition | Recovery |
|------|-----------|----------|
| `forced` | Critical need | Resume when satisfied |
| `voluntary` | Better option | May abandon plan |

## Habit Integration

When a plan becomes routine, convert to habit.

### Habit Formation

| Repetitions | Status |
|-------------|--------|
| 1-2 | Novel (System 2) |
| 3-5 | Learning (mix) |
| 6+ | Habit (System 1) |

### Habit Output

For habitual actions, add to `intention.json`:

```json
{
  "intention": "Morning commute to work",
  "is_habit": true,
  "habit_strength": 0.8,
  "automatic": true
}
```

## Workflow

1. Read `state/intention.json` and `state/plan_state.json`
2. Determine decision mode (System 1 or 2)
3. Check for need-based interrupts
4. Generate or continue plan execution
5. Call `codegen` with action instruction
6. Update `plan_state.json`
7. Re-observe after action if needed

## Guidelines

- One meaningful action per tick
- Actions must match AVAILABLE ACTIONS from observation
- Handle idle gracefully with `done`
- Mark plan as `failed` after 3 consecutive failures
- Prefer System 1 for routines, System 2 for novel goals
- Always check needs before executing plan step

## Re-observation

After each `codegen` action:

1. Check the result
2. Call `codegen` with `<observe>` to get updated state
3. Update `state/observation.txt`
4. Continue reasoning
