# Stage 3: Claims

Goal: register confirmatory and exploratory claims with evidence pointers **before** report charts.

## Steps

1. Read `references/analysis-methods.md` — pick appropriate methods language for simulation evidence.
2. **Optional:** `agentsociety-literature-search` — if claims compare to prior work, cite papers in `evidence` or attestation notes (not as substitute for sqlite evidence).
3. Propose 3–5 candidate findings; label each `confirmatory` or `exploratory`.
4. For each: `record-claim` with `claim_id`, `statement`, `mode`, `evidence` (table+column or SQL path), `needs_chart`.
5. **User alignment (required)** — walk through each claim; user confirms or edits.
6. `validate-claims` → `record-attestation` (`claims_user_approved`, `confirmatory_vs_exploratory_clear`) → re-run `validate-claims`.
7. `advance --phase refine` when explore+claims gates pass (`gate-status`).

## Exit conditions

- At least one confirmatory claim approved by user.
- `validate-claims` gate PASS.
