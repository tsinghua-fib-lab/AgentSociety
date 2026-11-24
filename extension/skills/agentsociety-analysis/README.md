# agentsociety-analysis skill

Staged skill for AgentSociety experiment analysis: explore → claims → charts → bilingual reports → synthesis → experience memory.

Mechanical ops: `$PYTHON_PATH .agentsociety/bin/ags.py analysis ...`

## Documentation layout

| Path                                             | Role                                                  |
| ------------------------------------------------ | ----------------------------------------------------- |
| `SKILL.md`                                       | Entry contract, CLI quick reference                   |
| `stages/01_frame.md` … `stages/06_synthesis.md`  | **Primary workflow** — includes tool invocation steps |
| `references/integrations.md`                     | **External skills & support bundles by stage**        |
| `references/harness.md`                          | Gates, attestation, paths, QA                         |
| `references/charts.md` / `references/eda.md` / `references/reports.md` | Domain lookup                |
| `references/experience-memory.md`                | Stage 6 Part B governance                             |
| `support/*`                                      | Bundled viz/HTML skills — read during Stages 2, 4, 5  |

Cross-skill: `agentsociety-literature-search`, `agentsociety-use-dataset`, `agentsociety-hypothesis`, Office skills (`pdf`/`docx`/…), `paper-toolkit` after pipeline complete.

## Directory layout

```text
agentsociety-analysis/
├── SKILL.md
├── stages/
├── references/
├── subagent-prompts/
├── assets/
├── support/
└── scripts/
```
