# Independent Report Review

Produce and synthesis require **two roles**: author subagent + **independent reviewer**. The harness blocks `validate-release` / `validate-synthesis` without a fresh PASS review.

## Workflow (produce)

```text
build-report-context
  → report-producer (writes reports)
  → report-reviewer (reads only — does not edit files)
  → record-report-review (verdict PASS, score ≥ 4)
  → validate-report-quality (optional early mechanical check)
  → validate-release (structure + mechanical quality + review file + fingerprint)
  → record-attestation (orchestrator; rubric includes independent_review_pass)
```

If review is **REVISE** or **FAIL**: orchestrator re-dispatches report-producer with `revision_instructions`, then runs report-reviewer again. Do not attest until review PASS.

## Stored files

| Scope      | Path                                                        |
| ---------- | ----------------------------------------------------------- |
| Hypothesis | `.agentsociety/analysis/hypothesis_{id}/report_review.json` |
| Synthesis  | `.agentsociety/analysis/synthesis/synthesis_review.json`    |

`report_fingerprint` is set automatically by `record-report-review` from current `report_zh.md` + `report_en.md`. If reports change, review becomes **stale** until re-recorded.

## Payload (`record-report-review`)

```json
{
  "hypothesis_id": "1",
  "reviewer_role": "independent",
  "verdict": "PASS",
  "overall_score": 5,
  "dimensions": {
    "evidence_traceability": 5,
    "narrative_clarity": 4,
    "limitations_honesty": 5,
    "bilingual_parity": 4,
    "chart_integration": 5
  },
  "blocking_issues": [],
  "revision_instructions": [],
  "reviewed_artifact_paths": [
    "presentation/hypothesis_1/report_zh.md",
    "presentation/hypothesis_1/report_en.md"
  ]
}
```

`verdict`: `PASS` | `REVISE` | `FAIL`

Gate requirements for PASS:

- `overall_score` ≥ 4
- Each dimension ≥ 3
- `blocking_issues` empty

## Synthesis (`record-synthesis-review`)

Same shape minus `hypothesis_id`; include `scope_hypothesis_ids`. Dimensions:

- `cross_hypothesis_integration`
- `tension_surfaced`
- `limitations_honesty`
- `bilingual_parity`

## Mechanical checks (`validate-report-quality`)

Runs inside `validate-release` (and standalone). Catches:

- Reports too short or missing `##` sections
- Generic fluff phrases
- Missing Markdown figure captions
- HTML figures without `alt`, outside a figure block, or without a `figcaption`
- Weak `analysis_summary.json` limitations / key_findings
- Confirmatory claims absent from `report_zh.md` or `report_en.md`
- Bilingual figure set mismatch, or Markdown/HTML figure mismatch within one language

Mechanical PASS does **not** replace independent review.

## Attestation rubric

Produce / synthesis attestation must set `independent_review_pass: true` only after `record-*-review` with PASS and successful `validate-release` / `validate-synthesis`.
