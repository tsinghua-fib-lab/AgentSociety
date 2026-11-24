# External Tools & Skills by Stage

Invoke these **during** the matching stage — do not only cite them in references.

Skill paths assume workspace sync to `.claude/skills/` (VS Code extension sync). Bundled support lives under `.claude/skills/agentsociety-analysis/support/`.

## Stage map

| Stage           | Invoke                                                             | When                                                                                               |
| --------------- | ------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------- |
| **1 Frame**     | `analysis memory-context`                                          | After `intake`, before `write-plan` — apply promoted lessons/recipes                               |
|                 | `agentsociety-literature-search`                                   | Need prior work to frame the research question or success criteria                                 |
|                 | `agentsociety-use-dataset`                                         | Plan includes external baseline / validation dataset — search, `readme`, `download`                |
|                 | `agentsociety-hypothesis`                                          | Analysis should revise hypothesis — pause pipeline, update HYPOTHESIS.md, restart frame            |
| **2 Explore**   | `analysis run-eda --type bundle`                                   | **Default** — runs capability-checked EDA and auto `record-phase-artifacts` with hypothesis id     |
|                 | `analysis run-eda --type quick-stats`                              | Targeted fallback when only a compact static profile is needed                                     |
|                 | `support/interactive-viz/SKILL.md`                                 | User wants PyGWalker / hub / multi-tab EDA — read before choosing `--type`                         |
|                 | `agentsociety-use-dataset`                                         | Compare simulation tables to downloaded external data — register paths in `record-phase-artifacts` |
|                 | `query-data` / chart scripts                                          | Targeted checks only; not bulk charting                                                            |
| **3 Claims**    | `references/analysis-methods.md`                                   | Choose stats language (correlation vs comparison vs time series)                                   |
|                 | `agentsociety-literature-search`                                   | Ground claims against published findings — cite in `evidence` or attestation                       |
|                 | User dialogue                                                      | **Required** — `claims_user_approved` before refine                                                |
| **4 Refine**    | `assets/chart_scaffold.reference.py` + `chart-recipes.md`          | Every chart script                                                                             |
|                 | `support/scientific-visualization/SKILL.md`                        | Squint test fail, CI/error bars, multi-panel layout                                                |
|                 | `analysis compose-figure`                                          | One finding, multiple panels — see `references/composite-figures.md`                                          |
|                 | `chart_export` (package)                                           | Optional Plotly/Altair sidecar per `references/eda.md`                                             |
| **5 Produce**   | `analysis prepare-produce`                                         | **Default** — `build-report-context` + `sync-report-assets` before drafting                        |
|                 | `analysis build-report-context`                                    | Use alone only if assets already synced                                                            |
|                 | `subagent-prompts/report-producer.md` + `subagent-prompts/report-reviewer.md` | **Required** independent review loop                                                    |
|                 | `support/report-blocks/SKILL.md`                                   | Assembling HTML sections (KPI, TOC, Mermaid, EDA tabs)                                             |
|                 | `support/frontend-design/SKILL.md`                                 | Typography/layout polish only — after content is correct                                           |
|                 | `assets/report-shell.reference.html`                               | HTML skeleton                                                                                      |
|                 | `analysis sync-report-assets` / `embed-interactive-eda`            | **Required** before `validate-release`                                                             |
|                 | `pdf` / `docx` / `pptx` / `xlsx` skills                            | **On user request** — export/share deliverables (not gate artifacts)                               |
| **6 Synthesis** | `subagent-prompts/synthesis-producer.md` + `subagent-prompts/synthesis-reviewer.md` | **Required**                                                                          |
|                 | Experience epilogue (below)                                        | **After** pipeline complete — user debrief; **non-blocking**                                       |
|                 | `paper-toolkit` plugin                                             | After analysis completed — compile manuscript from reports + literature                            |

## Experience epilogue (Stage 6 Part C — non-blocking)

Run after `validate-synthesis` PASS **and** `research-pipeline update-stage analysis completed`. Details: `references/experience-memory.md`. `gate-status` / `run-loop` return `epilogue` when workspace + hypothesis releases are ready.

```text
1. Chat with user (conversation prompts in epilogue)
2. record-feedback          (if user answered)
3. draft-reflection
4. Walk user through draft — edit if needed
5. record-reflection        (reviewed payload)
6. review-reflection        (harness safety check)
7. promote-reflection       (lessons + method_recipes)
8. promote-reflection --include-preferences   ONLY after explicit user OK
9. memory-context           (verify what next intake will see)
```

Do not skip the user conversation silently. Preferences without user confirmation must not be promoted. Skipping promotion does not block pipeline completion.

## Next pipeline stage

After step 9, `research-pipeline where-am-i` should show analysis completed. User intent for paper → invoke **paper-toolkit** plugin (external); requires `presentation/` reports + `papers/literature_index.json`.

## Lightweight paths

| User intent                               | Minimum path                                                                                        |
| ----------------------------------------- | --------------------------------------------------------------------------------------------------- |
| Quick data check only                     | Stage 1 frame + Stage 2 explore → stop (no attestation for later phases if user declines)           |
| Report without cross-hypothesis synthesis | Not supported — Stage 6 still required; single-hypothesis scope in `synthesis_scope_hypothesis_ids` |
| Failed / empty run                        | Stage 2 attestation `DONE_WITH_CONCERNS` + document `blocking_reason`; do not fabricate claims      |

## Office export (Stage 5+, on request)

| Skill  | Use                                         |
| ------ | ------------------------------------------- |
| `pdf`  | Share static PDF of report or merge figures |
| `docx` | Word version for collaborators              |
| `pptx` | Slide deck from findings section            |
| `xlsx` | Large appendix tables                       |

Gate deliverables remain MD + HTML under `presentation/` — exports are copies.
