# Design

Make key architectural decisions.

## Scale Fit

Record the simulation scale budget before choosing the final shape of the agent:

- target agent count or range
- expected step budget
- runtime or compute budget
- preferred complexity tier, such as lean, balanced, or rich

If the scale budget is wide or the runtime ceiling is tight, keep per-step reasoning, environment queries, and mutable state as small as possible. If the simulation is intentionally small, richer behavior and heavier state are acceptable.

## Decision Checklist

### 1. Base Class

- [ ] `AgentBase` — 简单行为、自管状态；无 PersonAgent 那套 skill 工具循环
- [ ] `PersonAgent` — skills / tool loop / workspace 与持久化；内置 skill 仅 `daily-guidance`

Choose the lightest base class that satisfies the hypothesis and the scale budget.

### 2. Workspace

- [ ] None - Game/benchmark agents
- [ ] Simple (`state.json`) - Basic state persistence
- [ ] Full (`state/`, `memory/`, `logs/`) - Complex agents

### 3. Profile Fields

List required fields:
- [ ] Standard: name, age, gender...
- [ ] Custom: ________________

### 4. State Variables

List internal states:
- [ ] ________________
- [ ] ________________

### 5. Environment Interactions

List queries/actions:
- [ ] Query: ________________
- [ ] Action: ________________
