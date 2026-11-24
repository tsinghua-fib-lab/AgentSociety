# Intake

Collect requirements before generating code. You can finish `design.md` in the same turn; splitting into two passes is optional.

## Required Information

1. **Role and behaviors** - What does this agent do?
2. **Internal states** - What needs tracking? (memory, mood, fatigue...)
3. **Environment interaction** - What queries/actions?
4. **Profile fields** - What defines this agent type?
5. **Simulation scale budget** - How many agents, how many steps, and what runtime budget should the design fit?

## Clarification Points

Ask the user if unclear:

- What decisions does the agent make?
- What triggers each behavior?
- How do internal states affect decisions?
- What environment queries/actions are needed?
- What target agent count or range should the design support?
- Should the design favor lean throughput, balanced fidelity, or richer reasoning?
- What runtime ceiling should the implementation stay within?

If the scale budget is still open, present 2-3 approaches with trade-offs and a recommendation before moving to design.

Do not guess. Keep intake notes for review.
