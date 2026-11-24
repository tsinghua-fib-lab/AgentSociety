# Stage 5: Produce (Bilingual Report)

Goal: trustworthy bilingual reports — not just structural gate PASS.

Full workflow: `references/reports.md`. Tool map: `references/integrations.md`.

## Steps

1. `prepare-produce` after refine gate passes (combines `build-report-context` + `sync-report-assets` including `embed-interactive-eda`).
2. Dispatch **report-producer** with explicit reads:
   - `references/reports.md`, `data/report_context.md`, `assets/report-shell.reference.html`
   - **`support/report-blocks/SKILL.md`** — block assembly (KPI, TOC, Mermaid, EDA tabs, figure blocks)
   - **`support/frontend-design/SKILL.md`** — typography polish only, after content is correct
3. Re-run `prepare-produce` after report references are final, then verify assets and iframes load locally.
4. Dispatch **report-reviewer** (independent run) → `record-report-review` on PASS.
5. On REVISE/FAIL: loop producer → `prepare-produce` → reviewer with `revision_instructions` until PASS.
6. Deliverables under `presentation/hypothesis_{id}/`:
   - `report_zh.md`, `report_en.md`, `report_zh.html`, `report_en.html`
   - `report_outline.json`, `artifact_manifest.json`, `data/analysis_summary.json`
7. HTML: keep `<!-- EDA_INTERACTIVE_BEGIN -->` … `<!-- EDA_INTERACTIVE_END -->` markers.
8. `validate-report-quality` (optional) → `record-attestation` (`bilingual_reports_reviewed`, `limitations_stated`, `independent_review_pass: true`) → `validate-release`.
9. **On user request** — export copies via Office skills (not gate artifacts):
   - `pdf` — static PDF for sharing
   - `docx` — Word for collaborators
   - `pptx` — slides from findings
   - `xlsx` — large appendix tables

Review rubric: `references/report-review.md`.

## Pre-attestation checklist

- Every figure in `assets/`; no `charts/` paths in body.
- §数据 synthesizes EDA; findings map to claims.
- Bilingual parity; limitations explicit.

## Exit conditions

- `validate-release` PASS + report-reviewer PASS recorded.
- Proceed to Stage 6 synthesis (required).
