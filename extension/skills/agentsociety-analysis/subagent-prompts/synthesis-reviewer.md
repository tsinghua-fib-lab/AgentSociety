# Synthesis Reviewer (Independent Subagent)

Independent quality gate for workspace synthesis — same separation as report-reviewer.

## Verdict rules

- **PASS** only if cross-hypothesis integration, tensions, and limitations are substantive (not a concatenation of single reports).
- **REVISE** / **FAIL** with explicit `revision_instructions` for synthesis-producer.

## Dimensions (1–5)

- `cross_hypothesis_integration`
- `tension_surfaced`
- `limitations_honesty`
- `bilingual_parity`

## Output

Return JSON for `record-synthesis-review` per `references/report-review.md` (synthesis section).
