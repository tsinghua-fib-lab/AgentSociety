# Reports (MD + HTML)

**No MD→HTML converter.** Bilingual MD and HTML are both **required** gate deliverables — LLM-authored natively.

Primary shell: `assets/report-shell.reference.html`. Independent review: `references/report-review.md`.

## Produce workflow

```text
refine gate_pass
  → prepare-produce (initial context)
  → report-producer subagent
  → prepare-produce (final asset sync + interactive EDA embed)
  → report-reviewer subagent (independent)
  → record-report-review (PASS)
  → validate-release (presentation-read-only; records gate state)
  → record-attestation (produce)
```

Orchestrator only: user alignment, attestation wording, `advance`.

## prepare-produce / build-report-context

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis prepare-produce \
  --workspace . --hypothesis-id $HYP_ID --experiment-id $EXP_ID
```

`prepare-produce` runs the explicit write-side preparation: it builds `data/evidence_index.json` + `data/report_context.md`, syncs report-referenced chart assets, and embeds interactive EDA. The three steps are fingerprinted in `.agentsociety/analysis/hypothesis_{id}/prepare_produce_manifest.json`; unchanged steps are skipped, while missing or changed outputs are rebuilt. The manifest is written atomically only after the whole scheduled run succeeds. Use `prepare-produce ... --dry-run` to inspect the plan without writing, and use `build-report-context` alone only when assets and embeds do not need refresh.

## Section integration

| Section     | Content                                                                |
| ----------- | ---------------------------------------------------------------------- |
| overview    | Research question, experiment design                                   |
| data        | Synthesize EDA (bullets + summary table); iframe hub in HTML §数据 tab |
| findings    | One block per confirmatory claim + `assets/chart_*.png` + caption      |
| conclusions | Answer + simulation limitations                                        |
| appendix    | Artifact table + EDA links                                             |

Simulation template: setup → data → findings (per claim) → conclusions → appendix. See claim subsections with evidence table + figure + caveat.

## Embedding rules

Pipeline: `run-eda` / chart scripts → `sync-report-assets` → `assets/` only in report body.

| Asset type | Markdown                                                | HTML                                                                |
| ---------- | ------------------------------------------------------- | ------------------------------------------------------------------- |
| Chart      | `![caption](assets/chart_01_slug.png)` + one line below | `.figure-block` + img + takeaway                                    |
| Table      | pipe table or small HTML                                | `.table-wrap` + `.data-table`                                       |
| EDA        | bullets + summary table in §数据                        | tab **摘要** + iframe `data/eda_hub.html` (see `references/eda.md`) |

Never reference `charts/` in final report body. Numbers must trace to replay datasets (`run/replay/` + DuckDB/`ReplayReader`) or registered artifacts; legacy `sqlite.db` only for old runs.

## HTML blocks (from shell)

| Block             | Use                                     |
| ----------------- | --------------------------------------- |
| `.metrics`        | 2–4 KPIs with `.metric-source` footnote |
| `.report-toc`     | Sticky nav when ≥4 sections             |
| `.figure-block`   | Chart + caption + takeaway              |
| `.eda-panel`      | Short EDA summary before iframe         |
| `.mermaid-block`  | Claim chain / pipeline (≤12 nodes)      |
| `.limitations`    | Simulation external validity            |
| `.artifact-table` | Appendix inventory                      |

Keep `<!-- EDA_INTERACTIVE_BEGIN -->` … `<!-- EDA_INTERACTIVE_END -->` markers for mechanical re-embed.

## Mermaid (optional)

Templates: data flow, claim→evidence chain, agent loop, EDA→finding. ≤12 nodes; offline `mermaid.min.js` in shell.

## Canvas vs disk

| Layer  | Role                                               |
| ------ | -------------------------------------------------- |
| Canvas | IDE exploration, layout drafts — not gate artifact |
| Disk   | `report_*.md` / `report_*.html` under presentation |

Handoff: finalize narrative on disk; do not treat Canvas as substitute for `validate-release`.

## HTML polish checklist

| Element | Guidance                                                              |
| ------- | --------------------------------------------------------------------- |
| Header  | Brand lockup + `agentsociety_icon.svg`                                |
| Metrics | 3–4 KPIs from EDA/SQL                                                 |
| TOC     | Sticky when long                                                      |
| §数据   | Summary table + interactive EDA tab                                   |
| §发现   | Claim-led sections with figures                                       |
| Style   | Scientific tone; navy/slate shell — no emoji spam, no 5MB inline HTML |

Optional typography: `support/frontend-design/` (polish only, not content).

## Bilingual parity

Same `assets/` filenames, same figures/tables, translated prose only. `report_outline.json` captions match takeaways.

## Pre-review checklist

- [ ] `prepare-produce` run initially and after final report asset references
- [ ] All `assets/` paths resolve
- [ ] §数据 cites EDA from `evidence_index.json`
- [ ] report-reviewer PASS recorded
- [ ] `limitations` in `analysis_summary.json`

Quality bar: `references/analysis-quality.md` (Produce section).

## Synthesis (Stage 6)

Cross-hypothesis reports in `synthesis/` — integrate scoped `report_context.md` / final reports; compare findings, don't re-dump raw EDA. `synthesis_brief.json` lists every `source_artifacts` path used.
