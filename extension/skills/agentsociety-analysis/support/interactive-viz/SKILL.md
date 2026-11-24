---
name: interactive-viz
description: Multi-modal interactive data presentation for agentsociety-analysis — EDA bundle (PyGWalker, Plotly, sortable tables, eda_hub), plotly/altair claim charts, HTML tab surfaces. Use in explore, refine, and produce stages.
---

# Interactive Viz (bundled support)

## When to use

- User wants interactive / diverse data presentation
- Stage 2 explore: run `run-eda --type bundle`
- Stage 4: `presentation_mode: static_plus_interactive`
- Stage 5: multi-tab §数据 with `eda_hub.html`

## Commands

```bash
# Full interactive EDA pack + hub
ags.py analysis run-eda --db-path DB --output-dir DIR/data --type bundle --workspace WS --hypothesis-id HID

# Single modes
ags.py analysis run-eda ... --type pygwalker
ags.py analysis run-eda ... --type datatable
ags.py analysis run-eda ... --type plotly-profile
ags.py analysis run-eda ... --type eda-hub
```

## Read order

1. `references/eda.md`
2. `references/charts.md` (optional interactive export)
3. `references/reports.md` (HTML embed)

## Python (chart scripts)

```python
from agentsociety2.skills.analysis.chart_export import export_plotly_html, export_pygwalker_html
```

## Report

Embed `data/eda_hub.html` as primary §数据 interactive surface; per-claim plotly iframes under `.figure-block`.
