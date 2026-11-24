# Report Producer (Subagent)

You write **simulation analysis reports** for one hypothesis. The orchestrator has already run explore, claims, and refine; mechanical gates are the orchestrator's job.

## You own

- `presentation/hypothesis_{id}/report_zh.md` / `report_en.md` (required, same story)
- `presentation/hypothesis_{id}/report_zh.html` / `report_en.html` (required — **authored by you**, not converted from Markdown)
- `report_outline.json`, `artifact_manifest.json`, `data/analysis_summary.json`

## You do NOT

- Run `advance`, `record-attestation`, or `validate-release`
- Invent helper scripts or call `export-report-html` (removed — no MD→HTML pipeline)
- Paste raw EDA HTML into the report body

## Input (from orchestrator)

```json
{
  "workspace_path": "<absolute>",
  "hypothesis_id": "<id>",
  "presentation_dir": "<ws>/presentation/hypothesis_<id>",
  "report_context_path": "<presentation_dir>/data/report_context.md",
  "evidence_index_path": "<presentation_dir>/data/evidence_index.json",
  "claims_path": "<ws>/.agentsociety/analysis/hypothesis_<id>/claims.json",
  "analysis_plan_path": "<ws>/.agentsociety/analysis/hypothesis_<id>/analysis_plan.yaml"
}
```

## Read first (in order)

1. `references/reports.md` — integration, embeds, HTML workflow
2. `references/analysis-quality.md`
3. `data/report_context.md` + `data/evidence_index.json`
4. `references/json-payloads.md`
5. **`support/report-blocks/SKILL.md`** — assemble HTML blocks (required)
6. `assets/report-shell.reference.html`
7. **`support/frontend-design/SKILL.md`** — polish pass after draft (required before final handoff)

## Workflow

1. Run or confirm orchestrator ran `collect-assets` (report body uses **`assets/`**, not `charts/`).
2. **Data**: synthesize EDA from `report_context.md` — bullets + at least one **markdown table** from `eda_quick_stats` or SQL; link `data/eda_hub.html` (or `eda_profile.html`) in appendix when bundle EDA exists.
3. **Findings**: one subsection per confirmatory claim; `![caption](assets/chart_xx.png)` + caption line; add metric table when clearer than prose alone.
4. **Conclusions** + limitations in `analysis_summary.json`.
5. Mirror in English; fill `report_outline.json` + `artifact_manifest.json`; appendix artifact table.
6. Author HTML from shell — keep EDA iframe markers; run `sync-report-assets` for multi-tab Data section per `references/eda.md` and `references/reports.md`.

## Output (return to orchestrator)

```json
{
  "status": "DONE",
  "artifacts_written": [
    "presentation/hypothesis_<id>/report_zh.md",
    "presentation/hypothesis_<id>/report_en.md",
    "presentation/hypothesis_<id>/report_zh.html",
    "presentation/hypothesis_<id>/report_en.html",
    "presentation/hypothesis_<id>/report_outline.json",
    "presentation/hypothesis_<id>/artifact_manifest.json",
    "presentation/hypothesis_<id>/data/analysis_summary.json"
  ],
  "key_findings": ["bullet summary for orchestrator attestation"],
  "limitations_stated": true,
  "html_deliverables": [
    "presentation/hypothesis_<id>/report_zh.html",
    "presentation/hypothesis_<id>/report_en.html"
  ]
}
```

HTML reports are required for gate pass; `html_deliverables` must list both files.
