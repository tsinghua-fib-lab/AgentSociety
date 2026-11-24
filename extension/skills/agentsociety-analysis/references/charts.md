# Charts & Figures

Contract-first plotting for AgentSociety analysis. Copy-paste code: `references/chart-recipes.md`, `references/api.md`, `assets/chart_scaffold.reference.py`. Layout patterns: `references/api.md` § patterns (or legacy `common-patterns.md` snippets in api).

## Figure contract (before any code)

Write before running a chart script or `compose-figure`:

```text
Core finding:
Figure scope:          single chart | composite figure
Chart role:            comparison | trend | distribution | composition | relationship | robustness
Evidence source:       table names, SQL, or aggregation
Analysis scope:        rows / agents / time window
Figure archetype:      e.g. single-panel comparison, 2x2 grid, hero + support row
Visual center:
Axes / grouping:
Legend strategy:
Output files:          chart_{nn}_{slug}.png | figure_{nn}_{slug}.png
Panel map:             (composite only) a/b/c sources
Reviewer check:        easiest way this could mislead
```

Rules: one finding → zero or one primary visual; same condition → same color across report; simulation caveats in caption when relevant.

## Chart selection

| Question                         | Chart form                   |
| -------------------------------- | ---------------------------- |
| Compare methods on one metric    | Grouped bar                  |
| Metric over steps/time           | Line / area trend            |
| Spread, skew, outliers           | Box, violin, histogram, KDE  |
| Two continuous variables         | Scatter (sample if dense)    |
| Metric matrix                    | Heatmap                      |
| Same finding, multiple subgroups | Small multiples              |
| Several approved PNGs, one claim | Composite (`compose-figure`) |

Families (detail): grouped bar, time trend, distribution, scatter, heatmap, small multiples, composite — see routing above.

## Palettes & sizes

**Categorical:** Okabe-Ito via `apply_analysis_style()` in scaffold.

```python
OKABE_ITO = ["#E69F00", "#56B4E9", "#009E73", "#F0E442", "#0072B2", "#D55E00", "#CC79A7", "#000000"]
```

**Semantic lock:** treatment `#0072B2`, baseline `#6B6B6B`, improvement `#009E73`, decline `#D55E00`.

**Sequential:** viridis / cividis / plasma — never jet/rainbow.

**Widths (mm):** single 89, wide 120 (default), double 183.

Categories: ≤8 Wong order; 9–15 top N + other; >15 use table not one rainbow chart.

## Design principles

- **Encoding priority:** position > length > slope > color.
- **EDA vs analysis chart:** exploration stays Stage 2; Stage 4 charts defend approved claims only.
- **Hierarchy:** one visual center per figure; supporting panels stay quieter.
- **Reviewer questions:** what could misread? axis range honest? sample scope stated?

## Visual quality rubric (pre-gate)

Squint test: metric, comparison, highlight identifiable in 3 seconds.

| Check                           | Pass                           |
| ------------------------------- | ------------------------------ |
| Contract recorded               | finding + evidence + archetype |
| Title names metric              | not "Results"                  |
| Axes labeled with units         |                                |
| Legend English-only, ≤6 entries | or direct labels               |
| Okabe-Ito / semantic colors     | locked across report           |
| No jet/rainbow                  |                                |
| Error bars defined in caption   | SE / SD / CI / none            |
| `Agg` backend, PNG exists       | optional SVG for single charts |
| Sample scope in caption         | agents, rows, steps            |

Anti-patterns: 3D bars, pie >5 slices, heavy grid, dual y-axis without reason, decorative charts.

## Composite figures

When one finding needs 2–4 views or merging approved PNGs:

1. Generate atomic charts → `charts/chart_*.png`
2. Write JSON spec (`layout`: grid or manual; `panels` with labels a/b/c)
3. `ags.py analysis compose-figure --workspace . --hypothesis-id ID --spec FILE`
4. Report uses `figure_{nn}_{slug}.png`; keep JSON sidecar in `charts/`

Layout options: `references/composite-figures.md`.

Do **not** composite unrelated findings — split instead.

## Optional interactive export

Default gate requires **PNG**. Optional `presentation_mode`: `plotly`, `altair` — see `references/eda.md`. Register interactive artifacts in phase artifacts; HTML embed via `chart-frame-wrap` in report shell.

## Failure → action

| Symptom                           | Fix                                  |
| --------------------------------- | ------------------------------------ |
| Paragraph needed to explain chart | change type or add direct label      |
| Unreadable categories             | horizontal bar, Top N, or rotate     |
| Decorative / no claim link        | drop chart or return to claims stage |
| Wrong table/column                | fix evidence source, re-run          |

QA layer details: `references/harness.md#qa-contract`.
