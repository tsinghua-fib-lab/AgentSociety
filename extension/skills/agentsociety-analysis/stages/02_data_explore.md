# Stage 2: Data Exploration

Goal: identify the 1-3 tables that matter most for the hypothesis and understand their limits.

## Steps

1. Inspect `run/replay/_schema.json` or use `ReplayReader` for a cheap dataset overview.
2. Use `ReplayReader` to inspect schema, row counts, and quality signals.
3. Identify the core tables and explain why they are relevant to the analysis direction.
4. If needed, use DuckDB through `ReplayReader` for targeted checks.
5. Generate EDA artifacts under `$OUTPUT_DIR/data` where `TYPE` matches `analysis_plan.eda_profile`.
6. After `run-eda`, pass `--workspace $WORKSPACE --hypothesis-id $HYP_ID` to auto-register explore artifacts (so they flow into `build-report-context` at produce time), or run `record-phase-artifacts` manually.
7. Explain data shape, limitations, and EDA takeaways to the user (LLM judgment — not keyword checks).
8. Run `$PYTHON_PATH .agentsociety/bin/ags.py analysis validate-explore --workspace $WORKSPACE --hypothesis-id $HYP_ID --experiment-id $EXP_ID`.
9. Run `$PYTHON_PATH .agentsociety/bin/ags.py analysis record-attestation` for phase `explore` per `references/phase-attestation.md`.
10. Re-run `validate-explore` so the attestation counts toward the explore gate.
11. Run `$PYTHON_PATH .agentsociety/bin/ags.py analysis advance --workspace $WORKSPACE --hypothesis-id $HYP_ID --experiment-id $EXP_ID --phase claims`.

## Exit Conditions

- `validate-explore` returns `PASS`.
- The relevant tables and data limits are understood.
