# API Reference

`agentsociety-analysis` uses a fixed Python plotting backend. This file collects the
minimum plotting scaffold, palette constants, export helpers, and a few reusable utilities
that match the analysis plotting contract.

## Required Scaffold

The following block should appear near the top of every matplotlib script:

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Arial", "DejaVu Sans", "Liberation Sans"]
plt.rcParams["svg.fonttype"] = "none"
```

Why this matters:

- `Agg` keeps rendering stable in headless environments
- the sans-serif stack gives cross-platform fallback consistency
- `svg.fonttype = "none"` keeps SVG text editable

## Recommended Style Helper

```python
def apply_analysis_style(font_size=10, axes_linewidth=1.2):
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "DejaVu Sans", "Liberation Sans"],
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": font_size,
            "axes.spines.right": False,
            "axes.spines.top": False,
            "axes.linewidth": axes_linewidth,
            "legend.frameon": False,
        }
    )
```

Suggested presets:

- ordinary report chart: `font_size=10`, `axes_linewidth=1.2`
- compact multi-panel chart: `font_size=8`, `axes_linewidth=1.0`
- wide chart that may later move into a manuscript draft: `font_size=12`, `axes_linewidth=1.5`

## Export Helper

```python
from pathlib import Path


def save_chart_bundle(fig, stem: str, output_dir: str | Path, dpi: int = 200):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / f"{stem}.png"
    svg_path = output_dir / f"{stem}.svg"
    fig.savefig(png_path, dpi=dpi, bbox_inches="tight")
    fig.savefig(svg_path, bbox_inches="tight")
    return png_path, svg_path
```

The default bundle keeps both PNG and same-stem SVG for report embedding and later label adjustments.

## Panel Label Helper

For matplotlib multi-panel figures, place panel labels in axes coordinates:

```python
def add_panel_label(ax, label, x=-0.06, y=1.02, fontsize=11):
    ax.text(
        x,
        y,
        label,
        transform=ax.transAxes,
        fontsize=fontsize,
        fontweight="bold",
        ha="left",
        va="bottom",
        color="#111111",
    )
```

For composite figures produced by `compose-figure`, panel labels are drawn by the CLI tool layer.

## Suggested Palettes

### Semantic Palette

```python
PALETTE = {
    "blue_main": "#0F4D92",
    "blue_secondary": "#3775BA",
    "green_soft": "#AADCA9",
    "green_main": "#8BCF8B",
    "red_soft": "#E9A6A1",
    "red_main": "#B64342",
    "neutral_light": "#CFCECE",
    "neutral_mid": "#767676",
    "neutral_dark": "#4D4D4D",
    "teal": "#42949E",
    "violet": "#9A4D8E",
}
```

Suggested use:

- primary method or condition: `blue_main`
- control or attenuation: `neutral_mid` / `neutral_dark`
- improvement: `green_main`
- decline, anomaly, or warning: `red_main`

### Method-Family Palette

```python
PALETTE_METHOD_FAMILY = {
    "baseline_dark": "#484878",
    "baseline_mid": "#7884B4",
    "baseline_soft": "#B4C0E4",
    "ours_tiny": "#E4E4F0",
    "ours_base": "#E4CCD8",
    "ours_large": "#F0C0CC",
    "delta_up": "#2E9E44",
    "delta_down": "#E53935",
}
```

Use this when several related methods or conditions should read as a coherent family.

## Common Utilities

### Dynamic y-axis tightening

```python
def tighten_ylim(ax, values, margin_ratio=0.1):
    values = list(values)
    lo = min(values)
    hi = max(values)
    margin = (hi - lo) * margin_ratio if hi > lo else max(abs(lo) * margin_ratio, 0.1)
    ax.set_ylim(lo - margin, hi + margin)
```

### Large-data sampling

```python
def sample_frame(frame, n=5000, random_state=42):
    if len(frame) <= n:
        return frame
    return frame.sample(n=n, random_state=random_state)
```

Useful for scatter or dense distribution charts when full rendering adds clutter without improving the finding.

## Naming Conventions

- atomic chart: `chart_{nn}_{description}`
- composite figure: `figure_{nn}_{description}`
- chart script: `chart_{nn}_{description}.py`
- composite spec: `figure_{nn}_{description}.json`

Keep these aligned with `references/harness-contract.md`.

## Experience Memory Commands

- `draft-reflection --hypothesis-id ID --experiment-id ID`: create a reviewable
  learning draft from harness state.
- `record-reflection --hypothesis-id ID --payload reflection.json`: store an
  edited reflection payload.
- `record-feedback --hypothesis-id ID --payload feedback.json`: store user
  satisfaction, requested changes, and confirmed preference candidates.
- `review-reflection --hypothesis-id ID`: run the pre-promotion safety/quality
  review used by `promote-reflection`.
- `promote-reflection --hypothesis-id ID`: write project lessons and method
  recipes under `.agentsociety/memory/`.
- `promote-reflection --hypothesis-id ID --include-preferences`: also promote
  preference candidates after explicit user confirmation.
- `memory-context --hypothesis-id ID`: inspect the memory automatically injected
  into `intake`, `status`, and `run-loop`.

See `references/experience-memory.md` for governance and payload details.
