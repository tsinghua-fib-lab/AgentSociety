# Report Quality Checklist

Use this **before** `record-attestation` and **even if** `validate-release` / `validate-synthesis` would pass structurally.

After reports are drafted, run the **independent reviewer** (`report-reviewer` / `synthesis-reviewer`) per `references/report-review.md` — do not self-approve produce/synthesis.

See `references/analysis-quality.md` for phase-by-phase bars.

- Every finding cites real tables, columns, or verified query outputs.
- Every chart can be traced back to a written figure contract and one confirmed finding.
- Every chart has a one-line description below it.
- Every chart in the report maps to a claim or figure contract; omit charts when they add no argument.
- Color mapping, emphasis, and scale choices stay consistent for comparable series.
- Legend text is English-only, labels are readable, and repeated legends are trimmed or consolidated.
- `artifact_manifest.json` matches the report contents and referenced assets.
- No hallucinated tables, columns, statistics, or unsupported causal claims.
- The report structure covers overview, data, findings, conclusions, and appendix unless the user requested a different structure.
