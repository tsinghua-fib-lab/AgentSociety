# Figure Contract

Use this before writing any chart code or assembling a multi-panel figure. The
purpose is to keep experiment analysis visuals tied to an analytical claim instead
of drifting into generic EDA or disconnected screenshots.

## Required Contract

Write a short contract in notes or in the conversation before generating chart code:

```text
Core finding:
Figure scope:
Chart role:
Evidence source:
Analysis scope:
Figure archetype:
Visual center:
Audience:
Highlight:
Axes / grouping:
Legend strategy:
Output files:
Panel map:
Reviewer check:
```

## Field Guidance

- `Core finding`: one sentence that the chart must support. Use a verb and keep it falsifiable.
- `Figure scope`: choose `single chart` or `composite figure`. Use `composite figure` when one finding needs multiple coordinated views or when several existing PNG/JPG assets must be shown together.
- `Chart role`: choose one of `comparison`, `trend`, `distribution`, `composition`, `relationship`, or `robustness`.
- `Evidence source`: list the table names, query, or derived aggregation that will feed the chart.
- `Analysis scope`: state the sample or slice used in the chart, such as run-level aggregate, per-agent rows, time-window subset, or cross-experiment summary.
- `Figure archetype`: choose a compact layout such as `single-panel comparison`, `trend with uncertainty`, `distribution focus`, `small multi-panel grid`, `hero + support row`, or `comparison triptych`.
- `Visual center`: identify which panel, series, or subgroup should draw attention first.
- `Audience`: default is experiment report reader. If the chart is likely to flow into paper or slides, keep the styling more restrained and retain vector export.
- `Highlight`: state which series, threshold, or subgroup should draw visual attention.
- `Axes / grouping`: name the x-axis, y-axis, grouping, and whether scales must be comparable across panels.
- `Legend strategy`: prefer direct labels first; if repeated legend blocks waste space, use one shared legend.
- `Output files`: atomic charts default to `chart_{nn}_{description}.png`; composite figures default to `figure_{nn}_{description}.png`. Add same-stem `.svg` only for single charts that may need later text edits. Composite figures also write a same-stem `.json` sidecar when assembled through `compose-figure`.
- `Panel map`: required for composite figures. Record `a`, `b`, `c`... with each panel's source chart or image plus its reason for inclusion.
- `Reviewer check`: identify the easiest way the chart could mislead, such as category crowding, truncated axes, unstable sample counts, or hidden null handling.

## Contract Rules

- One finding can have zero or one primary visual artifact. That artifact may be a single chart or a composite figure.
- When several findings compete for one figure, rank them and choose one visual center. Supporting evidence should stay visually quieter.
- If categories exceed what can be read in one scan, collapse to Top N plus `other`, facet into small multiples, or switch to a table.
- When comparing methods or conditions across several charts, preserve the same color mapping throughout the report.
- If a composite figure would mix unrelated findings, split it. A panel group exists to strengthen one message, not to compress file count.
- If the chart is derived from simulation output that has known caveats, surface that caveat in `Reviewer check` instead of leaving it implicit.
