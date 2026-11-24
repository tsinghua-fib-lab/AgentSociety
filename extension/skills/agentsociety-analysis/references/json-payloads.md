# JSON Payloads (LLM-authored)

CLI accepts `--payload` as a **JSON object** or path to a `.json` file. Malformed JSON is repaired via `json-repair` before validation — fix semantics, not escaping.

## analysis_plan (`write-plan`)

```json
{
  "research_question": "Does treatment X increase metric Y by step 10?",
  "primary_metrics": ["Y", "treatment_flag"],
  "target_tables": ["agent_metrics", "run_summary"],
  "confirmatory_claims": [
    "Mean Y is higher under treatment than control after step 10"
  ],
  "exploratory_notes": "Optional side comparisons on subgroups",
  "simulation_limitations": "Single seed; not calibrated to real city",
  "eda_profile": "bundle",
  "eda_profiles": ["quick-stats", "ydata", "pygwalker", "datatable", "plotly-profile"],
  "table_checks": [
    {"table": "agent_metrics", "min_rows": 10, "columns": ["step", "Y"]}
  ],
  "synthesis_scope_hypothesis_ids": ["1"]
}
```

## claim (`record-claim`)

```json
{
  "claim_id": "c1",
  "statement": "Treatment arm shows higher mean Y after step 10",
  "mode": "confirmatory",
  "evidence": "agent_metrics: filter step>=10; compare mean(Y) by treatment_flag",
  "needs_chart": true,
  "approved": true
}
```

## phase attestation (`record-attestation`)

See `references/harness.md#attestation` for rubric keys. Minimal example:

```json
{
  "phase": "explore",
  "status": "DONE",
  "key_findings": [
    "agent_metrics has 1200 rows; treatment_flag balanced"
  ],
  "artifacts_written": [
    "presentation/hypothesis_1/data/eda_quick_stats.md"
  ],
  "artifact_fingerprint": "",
  "rubric": {
    "tables_inspected": ["agent_metrics"],
    "data_limitations": "No demographic table; 12% missing Y in early steps",
    "eda_takeaway": "Distributions overlap but treatment tail is heavier"
  }
}
```

Leave `artifact_fingerprint` empty unless you are replaying an existing record; the CLI
fills it and uses it to detect stale attestations after artifact edits.

## report_outline.json (written to presentation dir)

```json
{
  "hypothesis_id": "1",
  "sections": [
    {"id": "overview", "title": "Experiment overview"},
    {"id": "data", "title": "Data and measures"},
    {"id": "findings", "title": "Findings"},
    {"id": "conclusions", "title": "Conclusions"},
    {"id": "appendix", "title": "Artifacts"}
  ],
  "figures": [
    {
      "asset": "chart_01_treatment_compare.png",
      "caption": "Mean Y by treatment after step 10",
      "finding_number": 1
    }
  ]
}
```

## evidence_index.json (`build-report-context`)

Auto-generated. Each source maps to a report section (`data`, `findings`, …).

```json
{
  "hypothesis_id": "1",
  "sources": [
    {
      "path": "presentation/hypothesis_1/data/eda_quick_stats.md",
      "kind": "eda",
      "phase": "explore",
      "report_section": "data",
      "label": "eda_quick_stats.md",
      "excerpt": "..."
    }
  ],
  "section_map": {
    "data": ["presentation/hypothesis_1/data/eda_quick_stats.md"],
    "findings": ["presentation/hypothesis_1/charts/chart_01_compare.png"]
  }
}
```

Also writes `data/report_context.md` (grouped digest for LLM).

## analysis_summary.json

```json
{
  "summary": "Treatment raises mean Y post step 10; effect modest.",
  "key_findings": ["Confirmatory claim c1 supported with caveats"],
  "limitations": "Single simulation run; not external validation",
  "evidence_index_path": "data/evidence_index.json"
}
```

## reflection report (`record-reflection`)

Use this after reviewing a `draft-reflection` result or after synthesis.

```json
{
  "hypothesis_id": "1",
  "experiment_id": "1",
  "source": "hypothesis",
  "what_worked": [
    {
      "title": "Claim-first charting worked",
      "content": "Charts were easier to justify after claims were approved.",
      "evidence": ["presentation/hypothesis_1/data/evidence_index.json"],
      "confidence": "high"
    }
  ],
  "what_failed": [
    {
      "title": "EDA scope was too broad",
      "content": "Unselected tables made the first pass noisy.",
      "evidence": [".agentsociety/analysis/hypothesis_1/state.yaml"],
      "confidence": "medium"
    }
  ],
  "reusable_methods": [
    {
      "recipe_id": "claim_first_charting",
      "title": "Claim-first charting",
      "content": "Approve confirmatory claims before producing final charts.",
      "applies_when": ["simulation analysis", "bilingual report"],
      "recommended_steps": [
        "Record claims with approved=true",
        "Write figure contracts",
        "Validate each chart before report assembly"
      ],
      "pitfalls": ["Do not promote exploratory EDA to a claim without review"],
      "confidence": "high"
    }
  ],
  "user_preferences_observed": [
    {
      "item_id": "claim_tone",
      "title": "Claim tone",
      "category": "writing",
      "value": "conservative, caveated claims",
      "content": "User explicitly preferred cautious interpretation.",
      "evidence": ["user-confirmed"],
      "confidence": "high"
    }
  ]
}
```

`promote-reflection` writes lessons and recipes by default. Add
`--include-preferences` only after explicit user confirmation.

## user feedback (`record-feedback`)

Use this after showing the analysis or reflection draft to the user.

```json
{
  "hypothesis_id": "1",
  "experiment_id": "1",
  "rating": 5,
  "satisfied": true,
  "comments": "以后保持结论克制，先中文解释再英文报告。",
  "requested_changes": ["Add a robustness caveat before paper drafting"],
  "preference_candidates": [
    {
      "item_id": "writing_order",
      "title": "Writing order",
      "category": "workflow",
      "value": "Chinese explanation before English report",
      "content": "User explicitly requested this order.",
      "evidence": ["feedback:user-confirmed"],
      "confidence": "high"
    }
  ],
  "lesson_candidates": [
    {
      "title": "Robustness caveat needed",
      "content": "The user wanted a stronger caveat before publication-oriented writing.",
      "evidence": ["feedback:user-comment"],
      "confidence": "medium"
    }
  ]
}
```

## synthesis_brief.json

```json
{
  "synthesis_question": "What is consistent across hypotheses 1 and 2?",
  "scope_hypothesis_ids": ["1", "2"],
  "source_artifacts": [
    "presentation/hypothesis_1/report_zh.md",
    "presentation/hypothesis_2/data/analysis_summary.json"
  ],
  "comparison_mode": "cross_hypothesis"
}
```

## figure contract (`record-contract`)

```json
{
  "contract_id": "fc1",
  "claim_id": "c1",
  "core_finding": "Treatment mean Y higher after step 10",
  "output_files": ["charts/chart_01_treatment_compare.png"]
}
```
