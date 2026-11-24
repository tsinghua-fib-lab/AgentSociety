# Composite Figures

Use this reference when one finding needs several coordinated views, or when
existing raster assets must be combined into one report-ready figure.

## When to Assemble a Composite Figure

- One finding needs `2-4` complementary views such as trend + distribution + subgroup comparison.
- Several approved charts share the same claim and look weaker when separated across the report.
- Existing PNG/JPG assets already exist and the remaining task is panel composition, not data plotting.
- The report needs one figure-level citation target instead of several disconnected screenshots.

## When to Keep Panels Separate

- The candidate panels support different findings.
- A single chart already carries the finding clearly.
- The panel set would exceed `4` views and start reading like an appendix dump.

## Figure-Level Contract

Write this before assembling:

```text
Finding:
Figure archetype:
Visual center:
Panel map:
  a: source + purpose
  b: source + purpose
  c: source + purpose
Shared color rule:
Legend strategy:
Output files:
Reviewer risk:
```

Rules:

- One panel should read as the visual center unless the figure is a symmetric comparison grid.
- Panel order should follow reading order: left-to-right, top-to-bottom.
- Supporting panels should stay quieter than the visual center.
- Preserve the same method or condition colors across all panels.
- If the figure originates from one confirmed finding, record that finding number in `artifact_manifest.json` together with the final `figure_{nn}_{slug}.png`.

## Output Pattern

1. Generate atomic charts first with the plotting backend.
2. Export each source panel as PNG.
3. Write a composition spec:

```json
{
  "output": "figure_01_summary.png",
  "canvas": { "width": 2200, "height": 1400, "background": "#FFFFFF" },
  "layout": { "type": "grid", "rows": 2, "cols": 2, "padding": 72, "gap": 32 },
  "panels": [
    { "source": "chart_01_trend.png", "label": "a" },
    { "source": "chart_02_distribution.png", "label": "b" },
    { "source": "chart_03_subgroup.png", "label": "c" }
  ]
}
```

4. Run:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis compose-figure \
  --workspace . --hypothesis-id ID \
  --spec $CHARTS_DIR/figure_01_summary.json
```

5. Use the generated `figure_01_summary.png` in the report and keep the JSON sidecar in `charts/`.

## Supported Layouts

### Grid

Use when all panels have similar evidence weight.

```json
"layout": { "type": "grid", "rows": 2, "cols": 2, "padding": 72, "gap": 32 }
```

### Manual

Use when one panel should dominate or the figure needs an asymmetric story shape.

```json
{
  "layout": { "type": "manual" },
  "panels": [
    {
      "source": "chart_01_main.png",
      "label": "a",
      "box": { "x": 72, "y": 72, "width": 1100, "height": 760 }
    },
    {
      "source": "chart_02_support.png",
      "label": "b",
      "box": { "x": 1220, "y": 72, "width": 900, "height": 360 }
    }
  ]
}
```

## Layout Catalog

Choose the panel structure from the evidence relationship, then encode it in the
`compose-figure` JSON spec. No bitmap wireframes are needed.

| Layout | Structure | Use when |
| --- | --- | --- |
| `2x2-grid` | Four equal panels | Four comparable conditions or metrics with equal visual weight |
| `hero-plus-row` | One wide hero panel above three supporting panels | One main effect plus robustness or subgroup checks |
| `triptych-with-legend` | Three panels sharing one legend | Method comparison where repeated legends waste space |
| `image-plus-quant` | One qualitative image/panel beside quantitative panels | Qualitative example paired with aggregate metrics |

Keep panel labels (`a`, `b`, `c`) consistent with report prose and preserve axis
text from the atomic charts.

## Failure Checks

- Panels repeat the same point with only cosmetic variation.
- Labels `a`, `b`, `c` do not match report prose.
- A supporting panel visually overwhelms the main evidence.
- White space or gaps imply unrelated groups when the panels are supposed to read as one figure.
- The combined figure hides axis text that was readable in the atomic chart.
