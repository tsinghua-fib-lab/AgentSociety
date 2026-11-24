# Stage 4: Refine (Charts & Figure Contracts)

Goal: turn approved claims into a small set of **argument-driven** visuals. Exploration stays in Stage 2; this stage only confirms charts that defend claims.

Read `references/analysis-quality.md` (Refine section) before generating code.

## Steps

1. For each claim with `needs_chart: true`, draft a figure contract (`references/figure-contract.md`).
2. Run `$PYTHON_PATH .agentsociety/bin/ags.py analysis record-contract --workspace $WORKSPACE --hypothesis-id $HYP_ID --payload '{...}'` per chart.
3. Generate charts by writing Python scripts and executing them directly (max 5 unless user approves more). Use `references/api.md` and `references/charts.md`.
4. Optional: `$PYTHON_PATH .agentsociety/bin/ags.py analysis compose-figure --workspace . --hypothesis-id ID --spec FILE` for multi-panel figures.
5. Run `validate-chart` per new chart (code path or `--chart-path`).
6. Run `$PYTHON_PATH .agentsociety/bin/ags.py analysis validate-refine --workspace $WORKSPACE --hypothesis-id $HYP_ID` (holistic refine gate).
7. Run `record-attestation` with `phase: refine` only after step 6 structural PASS.
8. Re-run `validate-refine` so the attestation counts toward the refine gate.
9. `advance --phase produce` only when `gate-status` shows `refine` gate_pass.

## Exit Conditions

- Every chart traces to a claim + contract.
- `validate-refine` + refine attestation → `refine` gate_pass.
- Do **not** run `record-attestation --phase produce` or `validate-release` until refine gate_pass (harness enforces).

## Quality (not optional)

- One chart = one takeaway; reject decorative plots.
- Same condition → same color across charts.
- English-only legend text; simulation limitations visible in captions where relevant.
