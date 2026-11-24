# Stage 1: Frame (Analysis Plan)

Goal: lock the analysis plan before deep data exploration (PAP-lite).

## Steps

1. Run `$PYTHON_PATH .agentsociety/bin/ags.py analysis intake --workspace $WORKSPACE --hypothesis-id $HYP_ID --experiment-id $EXP_ID`.
2. Confirm analysis direction with the user.
3. Run `$PYTHON_PATH .agentsociety/bin/ags.py analysis write-plan --workspace $WORKSPACE --hypothesis-id $HYP_ID --payload '{...}'` with `research_question`, `primary_metrics`, `target_tables`, `confirmatory_claims`, `eda_profile`, optional `table_checks`, and `synthesis_scope_hypothesis_ids`.
4. Run `$PYTHON_PATH .agentsociety/bin/ags.py analysis validate-plan --workspace $WORKSPACE --hypothesis-id $HYP_ID`.
5. Run `$PYTHON_PATH .agentsociety/bin/ags.py analysis record-attestation --workspace $WORKSPACE --hypothesis-id $HYP_ID --payload '{"phase":"frame",...}'` with the frame rubric.
6. Re-run `validate-plan` so the recorded attestation counts toward the frame gate.
7. Run `$PYTHON_PATH .agentsociety/bin/ags.py analysis advance --workspace $WORKSPACE --hypothesis-id $HYP_ID --experiment-id $EXP_ID --phase explore`.

## Exit Conditions

- `validate-plan` returns `PASS` and the frame attestation is recorded.
- Working paths (`REPLAY_DIR`, `OUTPUT_DIR`, `CHARTS_DIR`) are explicit.
