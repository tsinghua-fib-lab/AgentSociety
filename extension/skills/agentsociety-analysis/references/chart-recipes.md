# Chart Recipes (Claim → Code)

Copy-paste starting points for Stage 4 refine. Always write `figure-contract` first. Full scaffold: `assets/chart_scaffold.reference.py`.

## Recipe A: Grouped comparison (bar + SE + points)

**Claim:** method/condition differs on one metric.  
**Contract role:** `comparison` · **Archetype:** `single-panel comparison`

```python
apply_seaborn_layer()
fig, ax = plt.subplots(figsize=(6.5, 4))
plot_grouped_bar_with_points(df, x="condition", y="metric_value", hue=None, ax=ax)
ax.set_xlabel("Condition")
ax.set_ylabel("Metric (AU)")
ax.set_title("Mean metric by condition")
save_chart_bundle(fig, "chart_01_condition_mean", "charts")
```

Caption must state: error bar = SE (or SD/CI) and n per group.

## Recipe B: Time trend + phase marker

**Claim:** metric evolves; intervention/phase matters.  
**Role:** `trend` · **Archetype:** `trend with uncertainty`

```python
apply_analysis_style()
fig, ax = plt.subplots(figsize=(7.5, 4.2))
for cond, sub in df.groupby("condition"):
    sub = sub.sort_values("step")
    ax.plot(sub["step"], sub["metric_value"], label=cond, linewidth=1.8)
ax.axvline(phase_step, color="#767676", ls="--", lw=1.0)
ax.set_xlabel("Step")
ax.set_ylabel("Metric (AU)")
ax.set_title("Metric trajectory by condition")
ax.legend(loc="best")
save_chart_bundle(fig, "chart_02_trajectory", "charts")
```

Prefer Recipe B2 with CI when n per step supports it:

```python
apply_seaborn_layer()
fig, ax = plt.subplots(figsize=(7.5, 4.2))
plot_trend_with_ci(df, x="step", y="metric_value", hue="condition", ax=ax)
```

## Recipe C: Distribution comparison (box + strip)

**Claim:** spread/skew/outliers differ across groups.  
**Role:** `distribution`

```python
import seaborn as sns
apply_seaborn_layer()
fig, ax = plt.subplots(figsize=(6, 4))
order = ["control", "treatment_a", "treatment_b"]
sns.boxplot(data=df, x="condition", y="metric_value", order=order, width=0.55, ax=ax)
sns.stripplot(data=df, x="condition", y="metric_value", order=order, color="#333", alpha=0.25, size=2, ax=ax)
ax.set_xlabel("Condition")
ax.set_ylabel("Metric (AU)")
sns.despine(ax=ax)
save_chart_bundle(fig, "chart_03_distribution", "charts")
```

State in caption: box = IQR, whiskers = 1.5×IQR (seaborn default).

## Recipe D: Relationship (scatter, sampled)

**Claim:** two continuous variables co-vary at agent/episode level.  
**Role:** `relationship`

```python
apply_analysis_style()
sub = sample_frame(df, n=4000)
fig, ax = plt.subplots(figsize=(5.5, 5))
ax.scatter(sub["x_metric"], sub["y_metric"], alpha=0.35, s=12, c=OKABE_ITO[1], edgecolors="none")
ax.set_xlabel("X metric (AU)")
ax.set_ylabel("Y metric (AU)")
save_chart_bundle(fig, "chart_04_scatter", "charts")
```

## Recipe E: Heatmap (matrix metric)

**Role:** `composition` or matrix summary. Use `cividis` or `PuOr` (diverging).

```python
import seaborn as sns
apply_analysis_style()
pivot = df.pivot(index="agent_type", columns="feature", values="score")
fig, ax = plt.subplots(figsize=(8, 5))
sns.heatmap(pivot, cmap="cividis", linewidths=0.5, ax=ax, cbar_kws={"label": "Score (AU)"})
save_chart_bundle(fig, "chart_05_heatmap", "charts")
```

## Recipe F: Small multiples (shared scales)

**Claim:** same metric across subgroups — Tufte/Observable Plot faceting.  
**Archetype:** `small multi-panel grid`

```python
import seaborn as sns
apply_seaborn_layer()
g = sns.relplot(
    data=df, x="step", y="metric_value", col="cohort", col_wrap=3,
    kind="line", height=2.8, aspect=1.2, facet_kws={"sharey": True},
)
g.set_axis_labels("Step", "Metric (AU)")
g.figure.subplots_adjust(top=0.9)
g.figure.suptitle("Metric by cohort (shared y-scale)")
save_chart_bundle(g.figure, "chart_06_facet_cohort", "charts")
```

`sharey=True` when cross-panel comparison is the point.

## Recipe G: Composite (atomic first)

1. Run recipes A–F as separate `chart_NN_*.py`
2. Write JSON spec → `compose-figure` → `figure_01_*.png`

See `references/composite-figures.md`.

## Recipe selection

```text
one metric, few conditions     → A
time / steps                   → B or B2
spread / outliers              → C
two continuous vars            → D
matrix                         → E
same chart, many subgroups     → F
multiple views, one claim      → G
```
