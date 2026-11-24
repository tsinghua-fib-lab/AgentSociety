# Clarify

Only ask for missing critical fields.

- Ask one round at a time.
- If you are keeping a run trace, persist each question/answer pair into `clarifications.jsonl`.
- Prefer concrete questions about state, tools, step semantics, and acceptance criteria.
- If the simulation scale budget is missing, ask for agent count, step budget, runtime budget, and preferred complexity tier before design.
- When the budget is open, propose 2-3 approaches with trade-offs and a recommendation, then narrow to one option.
- Once critical gaps are closed, move to design instead of asking open-ended follow-ups.
