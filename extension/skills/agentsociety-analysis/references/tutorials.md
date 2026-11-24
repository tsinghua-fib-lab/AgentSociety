# Tutorials

These walkthroughs focus on the most common `agentsociety-analysis` situations. The emphasis is
finding-driven analysis rather than showcasing complicated plotting tricks.

## Tutorial 1: Single-Experiment Trend Chart

Scenario: a system metric changes over steps, and the report needs to show behavior before and after an intervention.

Workflow:

1. `load-context`
2. `list-tables`
3. `query-data` to retrieve `step`, `metric`, and `condition`
4. write the figure contract
5. generate chart script `chart_01_trend.py` and execute it
6. reference `assets/chart_01_trend.png` in the report

Minimal script scaffold:

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from agentsociety2.storage import ReplayReader

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Arial", "DejaVu Sans", "Liberation Sans"]
plt.rcParams["svg.fonttype"] = "none"

reader = ReplayReader("run/replay")
dataset = reader.get_dataset_by_id("metric.series")
rows = reader.fetch_dataset_rows(
    dataset,
    columns=["step", "metric_value", "condition"],
    order_by="step",
    limit=100000,
)["rows"]
reader.close()
df = pd.DataFrame(rows)

fig, ax = plt.subplots(figsize=(9, 5))
for condition, frame in df.groupby("condition"):
    ax.plot(frame["step"], frame["metric_value"], label=condition)

ax.set_title("Metric trend across steps")
ax.set_xlabel("Step")
ax.set_ylabel("Metric value")
ax.legend()
fig.savefig("chart_01_trend.png", dpi=200, bbox_inches="tight")
fig.savefig("chart_01_trend.svg", bbox_inches="tight")
plt.close(fig)
```

## Tutorial 2: Multi-Metric Comparison

Scenario: several methods in the same experiment need to be compared across multiple metrics.

Route:

1. aggregate into a tidy table with SQL first
2. use a shared legend plus a horizontal multi-metric layout
3. if differences are narrow, tighten the y-axis and explain the choice in nearby prose

Open first:

- `references/api.md`
- `references/common-patterns.md`
- `references/harness.md#qa-contract`

## Tutorial 3: Composite Figure Assembly

Scenario: one finding needs a main trend chart, a distribution chart, and a subgroup chart together.

Steps:

1. generate `chart_01_main.png`, `chart_02_dist.png`, and `chart_03_group.png`
2. write a JSON spec:

```json
{
  "output": "figure_01_summary.png",
  "canvas": { "width": 2200, "height": 1400, "background": "#FFFFFF" },
  "layout": { "type": "grid", "rows": 2, "cols": 2, "padding": 72, "gap": 32 },
  "panels": [
    { "source": "chart_01_main.png", "label": "a" },
    { "source": "chart_02_dist.png", "label": "b" },
    { "source": "chart_03_group.png", "label": "c" }
  ]
}
```

3. run:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis compose-figure \
  --workspace . --hypothesis-id ID \
  --spec $CHARTS_DIR/figure_01_summary.json
```

4. reference `assets/figure_01_summary.png` in the report

## Tutorial 4: Data Exploration Without Final Report Figures

If the task is only to understand data shape quickly, use:

```bash
python - <<'PY'
from agentsociety2.storage import ReplayReader
reader = ReplayReader("hypothesis_1/experiment_1/run/replay")
for dataset in reader.load_dataset_catalog():
    print(dataset["dataset_id"], dataset["table_name"])
reader.close()
PY
```

Such EDA outputs usually remain Stage 2 support material unless a later finding promotes them into Stage 3.
