# Common Patterns

These patterns are adapted for AgentSociety analysis reports. Use them for comparison charts,
trend charts, compact multi-panel summaries, and composite evidence figures.

## Pattern 1: Shared Legend Panel

Use when multiple subplots repeat the same method mapping.

```python
fig, axes = plt.subplots(1, n_data_axes + 1, figsize=(16, 5))

for idx, ax in enumerate(axes[:-1]):
    ax.plot(x, ys[idx], color=colors[idx], label=labels[idx])
    if idx == 0:
        handles, legend_labels = ax.get_legend_handles_labels()

axes[-1].legend(handles, legend_labels, loc="center", frameon=False)
axes[-1].set_axis_off()
```

## Pattern 2: Horizontal Multi-Metric Comparison

Use when several metrics share the same method list and each metric needs its own y-axis.

```python
from matplotlib import gridspec

fig = plt.figure(figsize=(18, 5))
gs = gridspec.GridSpec(1, len(metrics) + 1)

for metric_idx, metric in enumerate(metrics):
    ax = fig.add_subplot(gs[metric_idx])
    ax.bar(range(len(methods)), values[metric], color=colors)
    ax.set_xticks([])
    ax.set_ylabel(metric)

ax_leg = fig.add_subplot(gs[-1])
ax_leg.legend(handles, labels, loc="center", frameon=False)
ax_leg.set_axis_off()
```

## Pattern 3: Hide x Labels on Method Bars

If method names already appear in the legend, hide the x-axis labels:

```python
ax.set_xticks([])
```

## Pattern 4: Dynamic y-axis Tightening

When the finding lives in a narrow numeric band, avoid a default range that weakens the signal.

```python
margin = (values.max() - values.min()) * 0.1
ax.set_ylim(values.min() - margin, values.max() + margin)
```

## Pattern 5: Alpha-Graded Ablation Bars

Use when one method gains components progressively.

```python
import numpy as np

blue_rgb = (0.215686, 0.458824, 0.729412)
alphas = np.linspace(0.25, 1.0, len(configs))
colors = [(blue_rgb[0], blue_rgb[1], blue_rgb[2], alpha) for alpha in alphas]
```

## Pattern 6: Grayscale-Safe Hatch Encoding

Use when color alone may be ambiguous in print or projection.

```python
hatches = ["/", "\\\\", ".", "x", "o", "+"]
for bar_container, hatch in zip(grouped_bars, hatches):
    for patch in bar_container:
        patch.set_hatch(hatch)
        patch.set_edgecolor("black")
```

## Pattern 7: Event Markers on Trend Lines

Use when phase switches, interventions, or milestones matter to the interpretation.

```python
for event_x, event_text in event_map.items():
    ax.axvline(event_x, color="#767676", lw=1.0, ls="--")
    ax.text(event_x, y_top, event_text, ha="center", va="bottom", fontsize=8)
```

## Pattern 8: Compact Multi-Panel Grid

Use when one finding truly needs several aligned evidence views.

```python
fig = plt.figure(figsize=(12, 6))
gs = fig.add_gridspec(2, 3, hspace=0.25, wspace=0.28)

ax_a = fig.add_subplot(gs[0, 0])
ax_b = fig.add_subplot(gs[0, 1])
ax_c = fig.add_subplot(gs[0, 2])
ax_d = fig.add_subplot(gs[1, :2])
ax_leg = fig.add_subplot(gs[1, 2])
ax_leg.set_axis_off()
```

## Pattern 9: Atomic Charts Before Composite Assembly

Do not hard-code every report figure into one large matplotlib script. Prefer a two-step flow:

1. generate each evidence panel as `chart_{nn}_{slug}.png` and optional same-stem `.svg`
2. assemble them with `compose-figure` into `figure_{nn}_{slug}.png`

This keeps traceability, reruns, and partial revisions simpler.

## Pattern 10: Direct Labels in Stable Regions

If a detached legend adds eye travel and the chart has stable visual regions, label those regions directly:

```python
ax.text(x_text, y_text, label, color=color, ha="center", va="center", fontweight="bold")
```

## Selection Rule

- large repeated legend: shared legend panel
- multiple metrics over the same methods: horizontal multi-metric comparison
- progressive ablation: alpha-graded bars
- trend affected by phase shifts: event markers
- one finding with multiple evidence views: compact multi-panel layout or composite assembly
- 2–3 series with stable endpoints: direct labels (Pattern 10) instead of legend
- aggregated time series with uncertainty: seaborn CI line (Pattern 11)
- group comparison with visible n: bar + strip/jitter (Pattern 12)
- many subgroups, same axes: seaborn facet grid (Pattern 13)
- redundant series encoding: linestyle + marker cycle (Pattern 14)
- subtle grid for value reading: light y-grid only (Pattern 15)

## Pattern 11: CI Band Trend Line (seaborn)

Use when step-level mean needs uncertainty and n supports it.

```python
import seaborn as sns

sns.lineplot(data=df, x="step", y="metric_value", hue="condition",
             errorbar=("ci", 95), markers=True, linewidth=1.8)
sns.despine()
```

Caption: state CI level and whether points are agents or run aggregates.

## Pattern 12: Bar Summary + Raw Points

Use when n is modest and showing spread strengthens the claim.

```python
sns.barplot(data=df, x="condition", y="metric_value", errorbar="se", palette=OKABE_ITO)
sns.stripplot(data=df, x="condition", y="metric_value", color="#333", alpha=0.3, size=2.5)
```

## Pattern 13: Faceted Small Multiples

Observable Plot–style faceting when one metric repeats across cohorts/regions.

```python
g = sns.relplot(data=df, x="step", y="metric_value", col="cohort", col_wrap=3,
                kind="line", facet_kws={"sharey": True}, height=2.8)
```

## Pattern 14: Linestyle + Marker Redundancy

Grayscale-safe multi-series encoding:

```python
styles = ["-", "--", "-.", ":"]
markers = ["o", "s", "^", "D"]
for i, (label, sub) in enumerate(groups):
    ax.plot(sub.x, sub.y, color=OKABE_ITO[i], ls=styles[i % 4], marker=markers[i % 4], label=label)
```

## Pattern 15: Light Y-Grid Only

Enable only when tick reading is hard; keep alpha low.

```python
ax.yaxis.grid(True, color="#e2e8f0", linewidth=0.8, alpha=0.9)
ax.set_axisbelow(True)
```
