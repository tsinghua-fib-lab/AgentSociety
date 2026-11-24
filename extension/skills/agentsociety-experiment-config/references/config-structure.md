# Configuration Structure Reference

## init_config.json

```json
{
  "env_modules": [
    {"module_type": "SimpleSocialSpace", "kwargs": {...}}
  ],
  "agents": [
    {"agent_id": 1, "agent_type": "PersonAgent", "kwargs": {...}}
  ]
}
```

### Key Rules

- Use class names as type identifiers (e.g., `PersonAgent`, not `person_agent`).
- All parameters go in the `kwargs` dictionary.
- `agent_id` must equal `kwargs.id`.

### Agent `kwargs` split (profile + config)

The CLI's `_build_agent_specs` (`agentsociety2/society/cli.py`) splits each agent's
`kwargs` into two records before the agent is created via
`AgentBase.create(workspace_path, profile, config)`:

- **`profile`** — `id` plus all persona fields (`name`, `age`, `gender`, `occupation`,
  `persona`, …). Everything in `kwargs` that is NOT a recognized config key lands here.
- **`config`** — recognized runtime-config keys, lifted out of `kwargs`. The current
  set is:

  | config key | effect |
  |------------|--------|
  | `max_react_turns` | max ReAct turns per step |
  | `enable_memory` | enable PersonAgent memory runtime |
  | `enable_todo_list` | enable built-in TODO tools |
  | `force_template_mode` | force template mode for `ask_env` |
  | `allow_template_mode` | whether template mode is permitted |
  | `disabled_skill_ids` | skill ids hidden from the visible set |
  | `default_activated_skill_ids` | skills activated on first restore |
  | `extra_skill_paths` | extra skill directories (roots of skill subdirs, like `custom/skills`) scanned by `discover_skill_sources` on top of the default `<root>/custom/skills`; relative paths resolve against the workspace root. Use it to load custom skills stored anywhere on disk. |

So a typical agent `kwargs` block mixes persona fields and (optionally) the config keys
above. The split is automatic; you do not nest `profile` / `config` in `init_config.json`.

```json
{
  "agent_id": 1,
  "agent_type": "PersonAgent",
  "kwargs": {
    "id": 1,
    "name": "Alice",
    "age": 30,
    "occupation": "Engineer",
    "enable_memory": true,
    "max_react_turns": 6
  }
}
```

For custom `AgentBase` subclasses that declare their own config keys in `config.json`,
add those keys to `kwargs` too — but note the CLI only auto-splits the keys in the table
above; any other key stays in `profile` and is written verbatim to `config.json` by
`AgentBase.create`. Custom agents that need extra config keys outside `profile` should
read them from `self._config` in `restore` (and document them in `init_description`).

## steps.yaml

```yaml
start_t: "2024-01-01T00:00:00"
steps:
  - type: run
    num_steps: 100
    tick: 1
  - type: ask
    question: "Summarize current state"
  - type: intervene
    instruction: "Modify something..."
  - type: questionnaire
    questionnaire_id: "post_run_survey"
    title: "Post-run survey"
    description: "Collect structured responses from agents after the run"
    target_agent_ids: [1, 2, 3]
    questions:
      - id: "mood"
        prompt: "How do you feel about the outcome?"
        response_type: "choice"
        choices: ["positive", "neutral", "negative"]
      - id: "reason"
        prompt: "Briefly explain your answer."
        response_type: "text"
```

### Step Types

| Type | Purpose | Key Fields |
|------|---------|------------|
| `run` | Simulate N ticks | `num_steps`, `tick` |
| `ask` | Query agents | `question` |
| `intervene` | Modify simulation state | `instruction` |
| `questionnaire` | Structured agent survey | `questionnaire_id`, `questions` |

### questionnaire Step

Use a `questionnaire` step when the experiment needs structured answers from agents during or after the simulation.

**Required fields:**
- `type: questionnaire`
- `questionnaire_id`: unique identifier for this questionnaire run
- `questions`: non-empty list of question objects

**Optional fields:**
- `title`: questionnaire title shown in the prompt context
- `description`: questionnaire-level instructions
- `target_agent_ids`: list of agent IDs; omit to survey all agents

**Question object fields:**
- `id`: unique question identifier
- `prompt`: question text
- `response_type`: one of `text`, `integer`, `float`, `choice`, `json`
- `choices`: required when `response_type` is `choice`
