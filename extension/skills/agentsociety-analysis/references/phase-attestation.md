# Phase Attestation (LLM Layer)

Use `record-attestation` after you and the user are satisfied with the phase outcome. The harness only checks that required rubric keys are present and non-empty — it does not grade prose quality.

## Payload shape

```json
{
  "phase": "explore",
  "status": "DONE",
  "key_findings": ["One sentence per main insight from this phase"],
  "artifacts_read": ["paths you relied on"],
  "artifacts_written": ["paths you created"],
  "blocking_reason": null,
  "recommended_next_step": null,
  "artifact_fingerprint": "",
  "rubric": { }
}
```

`status`: `DONE` | `DONE_WITH_CONCERNS` | `BLOCKED` (use `BLOCKED` only when you cannot proceed without user input).

`artifact_fingerprint` is filled automatically by the CLI when omitted. Leave it blank in
hand-written payloads. If a later `validate-*` reports `attestation_stale`, inspect the
changed files and run `record-attestation` again for that phase.

## Rubric keys by phase

### frame

| Key                           | LLM fills                                                |
| ----------------------------- | -------------------------------------------------------- |
| `research_question_confirmed` | Boolean true after user alignment; put the question in the analysis plan |
| `success_criteria`            | How you will decide confirmatory success                 |

### explore

| Key                | LLM fills                            |
| ------------------ | ------------------------------------ |
| `tables_inspected` | List of table names actually used    |
| `data_limitations` | Missing data, sparsity, run failures |
| `eda_takeaway`     | What EDA suggests — not final claims |

### claims

| Key                                 | LLM fills                            |
| ----------------------------------- | ------------------------------------ |
| `claims_user_approved`              | true after user confirms claim set   |
| `confirmatory_vs_exploratory_clear` | Short note on which claims are which |

### refine

| Key                    | LLM fills                                   |
| ---------------------- | ------------------------------------------- |
| `charts_map_to_claims` | Mapping claim_id → chart/figure files       |
| `visual_message_clear` | Whether each chart stands alone at a glance |

### produce

| Key                          | LLM fills                                                     |
| ---------------------------- | ------------------------------------------------------------- |
| `bilingual_reports_reviewed` | true when zh/en narratives are aligned                        |
| `limitations_stated`         | Simulation-to-real-world caveat summary                       |
| `independent_review_pass`    | true only after report-reviewer PASS + `record-report-review` |

### synthesis

| Key                        | LLM fills                                                           |
| -------------------------- | ------------------------------------------------------------------- |
| `scope_sources_integrated` | Which hypothesis reports were integrated                            |
| `limitations_stated`       | Workspace-level caveats and conflicts                               |
| `independent_review_pass`  | true only after synthesis-reviewer PASS + `record-synthesis-review` |

## Pairing with structured files

| Phase     | LLM also writes                                                                   |
| --------- | --------------------------------------------------------------------------------- |
| produce   | `report_outline.json`, `artifact_manifest.json`, `analysis_summary.json`, reports |
| synthesis | `synthesis_brief.json`, bilingual synthesis reports                               |

Structural validators read those files; attestation captures interpretation the schema cannot encode.
