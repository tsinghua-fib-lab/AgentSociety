# Intake

Collect the minimum structured inputs before generating code:

- Environment goal and target scenario
- Global state to track
- Per-agent state to track
- Tools the environment should expose
- Initialization config fields
- Success criteria and hard constraints
- Simulation scale budget: target agent count or range, step budget, runtime budget, preferred complexity tier

If one of these is missing, do not guess beyond obvious defaults. Clarify the missing points first, and only keep intake notes under `.agentsociety/custom_env_skill/runs/` if they help review.
