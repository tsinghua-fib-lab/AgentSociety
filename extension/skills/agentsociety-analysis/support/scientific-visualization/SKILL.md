---
name: scientific-visualization
description: Publication-quality chart patterns for agentsociety-analysis Stage 4 refine — Okabe-Ito palettes, seaborn CI bands, small multiples, error bars, grayscale-safe encoding. Use when writing chart scripts or reviewing chart QA failures.
---

# Scientific Visualization (bundled support)

Active only during **agentsociety-analysis** explore/refine/produce. Does not replace figure contracts or harness gates.

## When to read

- Writing `charts/chart_NN_*.py` via a chart script
- Chart failed squint test or `validate-chart`
- User asks for better-looking or clearer plots

## Read order

1. `references/charts.md`
2. `references/chart-recipes.md`
3. `assets/chart_scaffold.reference.py`
4. `references/api.md`

## Absorbed sources (patterns only — no external deps required)

| Source                           | Absorbed                                                                    |
| -------------------------------- | --------------------------------------------------------------------------- |
| K-Dense scientific-visualization | Okabe-Ito, CI/error bars, multi-panel labels, grayscale test                |
| seaborn                          | `set_theme(ticks, paper, colorblind)`, `lineplot` CI, `boxplot`+`stripplot` |
| Observable Plot                  | Defaults-first workflow, faceting, shared scales                            |
| Tufte                            | Small multiples, chart junk removal                                         |
| Cursor canvas                    | Mandatory metric titles, axis units, source in caption                      |

## AgentSociety overrides

- English-only legend text
- matplotlib `Agg` required
- Simulation caveats — no overstated significance
- Semantic palette locked per condition across report
- PNG in `assets/` required; interactive HTML optional

## Quick invoke

Copy scaffold → pick recipe letter (A–G) → fill SQL/pandas → `save_chart_bundle` → rubric → `compose-figure` if needed.
