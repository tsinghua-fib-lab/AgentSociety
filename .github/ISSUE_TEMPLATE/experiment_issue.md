---
name: Experiment / Runtime Issue
about: Report a problem when running an experiment or simulation
title: "[EXPERIMENT] "
labels:
  - bug
  - experiment
  - triage
assignees: ""
---

## Problem Description

<!-- What happened during the experiment run? -->

## CLI Command

<!-- The exact command you used to run the experiment. -->

```bash
python -m agentsociety2.society.cli --config ... --steps ... --run-dir ...
```

## Configuration Files

<!-- Attach the relevant config files. REDACT ALL API KEYS before posting. -->

<details>
<summary>init_config.json</summary>

```json
// Paste contents here (remove API keys!)
```

</details>

<details>
<summary>steps.yaml</summary>

```yaml
# Paste contents here
```

</details>

## Logs

<details>
<summary>Relevant log output</summary>

```
Paste relevant log output or the contents of --log-file here.
For long logs, only include the portion around the error.
```

</details>

## Environment

| Item                  | Value |
| --------------------- | ----- |
| Python version        |       |
| AgentSociety version  |       |
| OS                    |       |
| LLM Provider          |       |
| LLM Model             |       |
| Number of agents      |       |
| Experiment steps      |       |

## Agent / Module Involves

<!-- If the issue is specific to certain modules, check them here. -->

- [ ] Agent (PersonAgent / custom agent)
- [ ] Agent Skill (daily-guidance / custom)
- [ ] Environment Router (ReAct / PlanExecute / CodeGen / TwoTier)
- [ ] Environment Module
- [ ] Research Skill (literature / experiment / hypothesis / analysis)
- [ ] External paper-toolkit integration
- [ ] Storage / replay
- [ ] LLM / Embedding call failure
- [ ] Not sure

## Additional Context

<!-- Any other information that might help diagnose the issue. -->
