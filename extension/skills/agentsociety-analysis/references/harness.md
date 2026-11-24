# Analysis Harness

The harness splits work into **structural** (Python) and **attestation** (LLM) layers. Quality bar: `references/analysis-quality.md`.

## Structural gates

| Phase     | Validator checks                                                            |
| --------- | --------------------------------------------------------------------------- |
| frame     | `analysis_plan.yaml` via Pydantic                                           |
| explore   | `run/replay/_schema.json`（或 legacy `sqlite.db`）、目标 datasets/tables、`phase_artifacts.explore` 路径存在 |
| claims    | `claims.json` shape, confirmatory claim present, user-approved confirmatory |
| refine    | contracts + validated chart files on disk; per-chart `validate-chart`       |
| produce   | bilingual MD/HTML, `report_outline.json`, manifests, asset graph            |
| synthesis | `synthesis_brief.json`, scoped hypothesis reports, per-hypothesis summaries |

After each phase: (1) analytical work with user, (2) `validate-<phase>`, (3) `record-attestation`, (4) `gate-status` / `advance`.

Attestation auto-stores `artifact_fingerprint`. If files change later, `attestation_stale` blocks advance — re-read and re-attest.

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis gate-status --workspace . --hypothesis-id ID
```

## Attestation payload

```json
{
  "phase": "explore",
  "status": "DONE",
  "key_findings": ["One sentence per main insight"],
  "artifacts_read": [],
  "artifacts_written": [],
  "blocking_reason": null,
  "recommended_next_step": null,
  "rubric": {}
}
```

`status`: `DONE` | `DONE_WITH_CONCERNS` | `BLOCKED`.

### Rubric keys by phase

| Phase     | Required rubric keys                                                          |
| --------- | ----------------------------------------------------------------------------- |
| frame     | `research_question_confirmed`, `success_criteria`                             |
| explore   | `tables_inspected`, `data_limitations`, `eda_takeaway`                        |
| claims    | `claims_user_approved`, `confirmatory_vs_exploratory_clear`                   |
| refine    | `charts_map_to_claims`, `visual_message_clear`                                |
| produce   | `bilingual_reports_reviewed`, `limitations_stated`, `independent_review_pass` |
| synthesis | `scope_sources_integrated`, `limitations_stated`, `independent_review_pass`   |

Produce/synthesis `independent_review_pass` is true only after reviewer subagent PASS + `record-report-review` / `record-synthesis-review`.

## Output paths

### Single hypothesis (`presentation/hypothesis_{id}/`)

```text
presentation/hypothesis_{id}/
  report_zh.md / report_en.md / report_zh.html / report_en.html   # all required
  report_outline.json, artifact_manifest.json
  data/      # EDA outputs, analysis_summary.json, evidence_index.json, report_context.md
  charts/    # chart_*.png, figure_*.png, scripts
  assets/    # report embeds (from sync-report-assets / collect-assets)
```

**Forbidden under presentation:** `analysis/` (use `.agentsociety/analysis/hypothesis_{id}/`), `figures/` (use `charts/`), `eda/` (use `data/`).

### Harness state

```text
.agentsociety/analysis/hypothesis_{id}/
  state.yaml, analysis_plan.yaml, claims.json
.agentsociety/analysis/synthesis/
  state.yaml
```

### Synthesis (`synthesis/`)

```text
synthesis/
  synthesis_report_zh.md / synthesis_report_en.md / synthesis_report_zh.html / synthesis_report_en.html
  synthesis_brief.json
  charts/, assets/, data/   # optional
```

Naming: `chart_{nn}_{slug}.png`, `figure_{nn}_{slug}.png`, EDA under `data/eda_*`.

## Python plotting backend

- **Python-only** for analysis charts: matplotlib (`Agg`) + optional seaborn/plotly in chart scripts.
- Start from `assets/chart_scaffold.reference.py`; recipes in `references/chart-recipes.md`; API in `references/api.md`.
- English-only legend text; Okabe-Ito or semantic palette from `references/charts.md`.
- Missing optional deps → stop and report; do not invent parallel scripts.

## QA contract (charts + reports)

| Layer     | Pass when                                                                  |
| --------- | -------------------------------------------------------------------------- |
| Chart     | Traces to claim + figure contract; readable at squint distance; PNG exists |
| Script    | Uses scaffold; writes to `charts/`; no hardcoded wrong paths               |
| Composite | Panel map matches `compose-figure` spec; labels a/b/c visible              |
| Report    | Manifest matches body; no `charts/` paths in HTML img src (use `assets/`)  |

Failure triggers: wrong table/column → back to explore; decorative chart → back to claims/refine; manifest mismatch → fix produce.

## JSON payloads

CLI `--payload` accepts JSON object or `.json` file path. Minor syntax repaired via `json-repair` before Pydantic — still fix wrong fields. Templates: `references/json-payloads.md`.

## Anti-patterns

- Do not skip `record-attestation` after validate passes.
- Do not edit phase artifacts after attestation without re-attesting.
- Do not set `approved: true` in claims without user alignment.
- Do not treat structural PASS as sufficient quality.
- Pipeline `analysis completed` only after `validate-synthesis` PASS.
