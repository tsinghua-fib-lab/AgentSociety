# Embedding Images, Tables, and EDA in Reports

Applies to **Markdown** and **HTML** (both required). All paths are relative to `presentation/hypothesis_{id}/` unless noted.

## Pipeline (always)

```text
run-eda  →  data/eda_* , charts/chart_*.png
prepare-produce     → data/report_context.md + evidence_index.json
report-producer     → narrative + embeds (assets/ only)
prepare-produce     → explicit charts→assets sync + interactive EDA embed
validate-release    → presentation-read-only checks; records gate state and blocks unresolved assets
```

Never embed from `charts/` in the final report body — use **`assets/`** after `sync-report-assets` or `collect-assets`.

---

## Images (charts & composite figures)

| Step        | Rule                                                                                                              |
| ----------- | ----------------------------------------------------------------------------------------------------------------- |
| Source      | `charts/chart_NN_slug.png` or `figure_NN_slug.png`                                                                |
| Report path | `assets/chart_NN_slug.png` (same filename after collect)                                                          |
| Markdown    | `![简短说明](assets/chart_01_treatment_mean.png)` then **one line** caption below                                 |
| HTML        | `<figure class="figure-block">` + `img src="assets/..."` + caption + takeaway (see `report-shell.reference.html`) |
| Alt text    | Describe the metric/condition, not "chart1"                                                                       |

Every image in `report_outline.json` / `artifact_manifest.json` must exist on disk under `assets/`.

---

## Tables (SQL, EDA quick-stats, metrics)

**Do not** screenshot tables as PNG unless readability fails (wide grids). Prefer real tables:

| Source               | Markdown                                            | HTML                                                    |
| -------------------- | --------------------------------------------------- | ------------------------------------------------------- |
| SQL / aggregation    | GitHub-style pipe table or small HTML in MD         | `<table class="data-table">` with `<thead>` / `<tbody>` |
| `eda_quick_stats.md` | Extract 1–2 key tables into §数据; rest in appendix | Same data in `.table-wrap`                              |
| Claim evidence       | One compact comparison table per claim              | Place under claim `<h3>` in findings                    |

Table rules:

- Header row required; align numbers right (`class="num"` in HTML).
- Caption above table: `表 1：…` / `Table 1: …`
- Numbers must match replay dataset queries or EDA files (traceable in prose).

---

## EDA and other tool outputs

| Artifact                        | In §数据 (body)                                                   | Appendix                                                                                   |
| ------------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `data/eda_quick_stats.md`       | 3–5 bullets + **one** summary table (rows, missing %, key ranges) | —                                                                                          |
| `data/eda_profile.html` (ydata) | Summary table + bullets in tab **摘要**                           | Tab **交互式 EDA**: `<iframe src="data/eda_profile.html">` (see `references/eda.md`) |
| `data/eda_sweetviz.html`        | Same                                                              | iframe `eda_sweetviz.html` when plan used Sweetviz                                         |
| `data/*.csv` / query exports    | Summarize; small preview table (≤8 rows)                          | Full file link in appendix                                                                 |

Synthesis: **integrate** EDA into narrative (report_context.md § data). Raw tool output stays in `data/`; the report **interprets** it.

---

## HTML layout blocks (copy from reference shell)

| Block                         | Use for                                  |
| ----------------------------- | ---------------------------------------- |
| `.metrics`                    | 2–4 headline KPIs from EDA/SQL           |
| `.table-wrap` + `.data-table` | EDA / metric tables                      |
| `.eda-panel`                  | Short EDA summary + link to full profile |
| `.figure-block`               | Each chart with caption + takeaway       |
| `.artifact-table`             | Appendix inventory                       |
| `.limitations`                | Simulation caveats                       |

Read `assets/report-shell.reference.html` — it contains working examples for every block.

---

## Bilingual parity

- Same figures in zh/en (same `assets/` filenames).
- Same tables (translated headers only).
- Same appendix links to `data/eda_*.html`.

---

## Quality checks (before review)

- [ ] `collect-assets` run after chart list is final
- [ ] Every `![](assets/...)` / `<img src="assets/...">` resolves to a file
- [ ] §数据 cites at least one EDA source from `evidence_index.json`
- [ ] No orphan `charts/` paths in report body
- [ ] HTML opened locally: images and appendix links load (relative paths)
