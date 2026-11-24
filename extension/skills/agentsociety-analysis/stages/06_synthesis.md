# Stage 6: Synthesis (Required)

Goal: workspace-level bilingual synthesis after every scoped hypothesis passes `validate-release`.

## Steps

1. Confirm scoped hypotheses have `validate-release` PASS.
2. Orchestrator may run `build-report-context` per hypothesis if reports need refresh.
3. Dispatch **synthesis-producer** (`subagent-prompts/synthesis-producer.md`).
4. Dispatch **synthesis-reviewer** → `record-synthesis-review` (PASS required).
5. Deliverables: `synthesis_brief.json`, bilingual synthesis MD + HTML (`synthesis_report_zh/en.md` and `.html`, all four required).
6. Orchestrator: `record-attestation` (`phase: synthesis`, `independent_review_pass: true`) → `validate-synthesis` (final gate; fix structural issues and refresh attestation if needed).
7. Optional experience loop: `draft-reflection` or `record-reflection`, then `promote-reflection` after user review.
8. Then: `research-pipeline update-stage analysis completed`.

## Exit Conditions

- `validate-synthesis` PASS (`workspace_release=ready`).
- Optional memory artifacts under `.agentsociety/memory/` are reviewable and promoted only after confirmation.
