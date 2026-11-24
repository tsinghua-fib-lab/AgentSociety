# EDA & Interactive Presentation

Stage 2 exploration only — do not promote generic EDA into final claims without explicit claim registration.

## Default command (bundle)

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis run-eda \
  --db-path $DB_PATH \
  --output-dir $OUTPUT_DIR/data \
  --type bundle \
  --workspace $WORKSPACE \
  --hypothesis-id $HYP_ID
```

Produces `eda_hub.html` plus tool-specific files. Custom profiles:

```bash
--type bundle --profiles quick-stats,ydata,pygwalker,datatable,plotly-profile
```

Plan fields (`write-plan` / `analysis_plan.yaml`):

```json
{ "eda_profile": "bundle", "eda_profiles": ["quick-stats", "ydata", "pygwalker"] }
```

`eda_profiles` overrides single `eda_profile` when non-empty.

## Mode catalog

| `--type`         | Output                   | Use                        |
| ---------------- | ------------------------ | -------------------------- |
| `quick-stats`    | `eda_quick_stats.md`     | Static summary             |
| `ydata`          | `eda_profile.html`       | Profiling sections         |
| `sweetviz`       | `eda_sweetviz.html`      | Target associations        |
| `missingno`      | `eda_missingno.html`     | Missing structure          |
| `correlation`    | `correlation_index.html` | Correlation gallery        |
| `pygwalker`      | `eda_pygwalker.html`     | Drag-drop explorer         |
| `datatable`      | `eda_datatable.html`     | Sort/filter table          |
| `plotly-profile` | `eda_plotly.html`        | Zoom/hover matrix          |
| `eda-hub`        | `eda_hub.html`           | Tab launcher over existing |
| `bundle`         | multiple + hub           | Recommended default        |

Run EDA **only** for tables selected in Stage 2 plan. Register paths via auto-register on `run-eda` or `record-phase-artifacts`.

## Dependencies

```bash
uv sync --extra analysis
UV_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple uv pip install plotly pygwalker
```

`intake`, `status`, and `run-loop` expose capability state as `available`, `missing_dependency`, `unhealthy`, or `disabled`. A direct unavailable profile fails explicitly; `bundle` reports and skips unavailable optional profiles while continuing with its available core.

## Embed in HTML reports (Stage 5)

Do **not** inline megabyte HTML. Use tabs + iframe relative to report file:

```html
<!-- EDA_INTERACTIVE_BEGIN -->
<div class="tab-root">
  <div class="tab-bar">…</div>
  <div class="tab-panel active"><iframe class="eda-frame" src="data/eda_hub.html"></iframe></div>
</div>
<!-- EDA_INTERACTIVE_END -->
```

Rules:

- §数据 tab **摘要**: bullets + one summary table from `eda_quick_stats.md`
- Tab **交互式 EDA**: iframe to hub or single tool (`data/eda_pygwalker.html`, etc.)
- Only render tabs for files listed in `evidence_index.json`
- After produce: `sync-report-assets` or `embed-interactive-eda` re-injects blocks

Mechanical injection: `ags.py analysis embed-interactive-eda --workspace . --hypothesis-id ID`

## Presentation modes (figure contract)

| Mode                      | Stage           | Gate                        |
| ------------------------- | --------------- | --------------------------- |
| `static_png`              | refine          | PNG required                |
| `static_plus_interactive` | refine          | PNG + optional HTML sidecar |
| `plotly` / `altair`       | refine          | PNG still required for gate |
| EDA hub iframe            | produce         | `run-eda` artifacts exist   |
| Canvas (IDE)              | explore/produce | not a disk gate substitute  |

Philosophy: **explore wide → refine narrow → produce layered**. Interactive surfaces support doubt in explore; claims charts defend findings in refine.

## Stage routing

| Stage   | EDA role                                     |
| ------- | -------------------------------------------- |
| explore | `run-eda`, register artifacts, user takeaway |
| claims  | cite tables/columns — not EDA screenshots    |
| refine  | claim-driven charts only                     |
| produce | summarize EDA in prose + iframe hub in HTML  |

Full report embedding rules: `references/reports.md`.
