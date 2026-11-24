"""Reference scaffold for agentsociety-analysis chart scripts.

Copy into presentation/hypothesis_{id}/charts/chart_NN_slug.py and adapt.
Do not import this file at runtime — it is documentation-as-code.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

# --- Wong / Okabe-Ito (Nature Methods) + report chrome tokens ---

OKABE_ITO = [
    "#E69F00",
    "#56B4E9",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
    "#000000",
]

REPORT_UI = {
    "text": "#222222",
    "text_muted": "#6B6B6B",
    "neutral_mid": "#999999",
    "bg": "#FFFFFF",
    "accent": "#C41E3A",
    "link": "#0066CC",
}

FIGURE_MM = {"single": 89.0, "wide": 120.0, "double": 183.0}
SEQUENTIAL_CMAPS = ("viridis", "cividis", "plasma")
DIVERGING_CMAPS = ("PuOr", "RdBu", "BrBG")


def mm_to_inches(mm: float) -> float:
    return mm / 25.4


def report_figsize(
    width_mm: float = 120.0, aspect: float = 0.62
) -> tuple[float, float]:
    w = mm_to_inches(width_mm)
    return (w, w * aspect)


def apply_analysis_style(
    *, font_size: float = 7.0, display_scale: float = 1.45
) -> None:
    size = font_size * display_scale
    u = REPORT_UI
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans"],
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": size,
            "axes.labelsize": size,
            "axes.titlesize": size + 1,
            "xtick.labelsize": size - 0.5,
            "ytick.labelsize": size - 0.5,
            "legend.fontsize": size - 0.5,
            "axes.labelcolor": u["text"],
            "axes.edgecolor": u["text"],
            "xtick.color": u["text_muted"],
            "ytick.color": u["text_muted"],
            "text.color": u["text"],
            "axes.spines.right": False,
            "axes.spines.top": False,
            "axes.linewidth": 0.8,
            "axes.grid": False,
            "legend.frameon": False,
            "axes.prop_cycle": plt.cycler(color=OKABE_ITO),
            "lines.linewidth": 1.2,
            "lines.markersize": 4.5,
            "figure.facecolor": u["bg"],
            "axes.facecolor": u["bg"],
            "savefig.facecolor": u["bg"],
        }
    )


def apply_seaborn_layer(*, palette: str = "colorblind", context: str = "paper") -> None:
    import seaborn as sns

    sns.set_theme(style="ticks", context=context, palette=palette, font_scale=1.0)
    apply_analysis_style()


def save_chart_bundle(
    fig, stem: str, output_dir: str | Path, dpi: int = 200
) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / f"{stem}.png"
    svg_path = output_dir / f"{stem}.svg"
    fig.savefig(png_path, dpi=dpi, bbox_inches="tight", facecolor="white")
    fig.savefig(svg_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return png_path, svg_path


def add_panel_label(
    ax, label: str, x: float = -0.08, y: float = 1.04, fontsize: int = 11
) -> None:
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


def tighten_ylim(ax, values, margin_ratio: float = 0.1) -> None:
    vals = list(values)
    lo, hi = min(vals), max(vals)
    margin = (hi - lo) * margin_ratio if hi > lo else max(abs(lo) * margin_ratio, 0.1)
    ax.set_ylim(lo - margin, hi + margin)


def sample_frame(frame, n: int = 5000, random_state: int = 42):
    if len(frame) <= n:
        return frame
    return frame.sample(n=n, random_state=random_state)


def plot_trend_with_ci(df, x: str, y: str, hue: str, ax=None):
    """Seaborn line + 95% CI band — specify CI in caption."""
    import seaborn as sns

    ax = ax or plt.gca()
    sns.lineplot(
        data=df,
        x=x,
        y=y,
        hue=hue,
        errorbar=("ci", 95),
        markers=True,
        marker="o",
        linewidth=1.8,
        ax=ax,
    )
    sns.despine(ax=ax)
    return ax


def plot_grouped_bar_with_points(df, x: str, y: str, hue: str | None, ax=None):
    """Bar summary + jittered raw points when n is small enough."""
    import seaborn as sns

    ax = ax or plt.gca()
    sns.barplot(
        data=df,
        x=x,
        y=y,
        hue=hue,
        errorbar="se",
        capsize=0.08,
        ax=ax,
        palette=OKABE_ITO[:4],
    )
    if len(df) <= 500:
        sns.stripplot(
            data=df,
            x=x,
            y=y,
            hue=hue,
            dodge=True,
            color="#333333",
            alpha=0.35,
            size=2.5,
            ax=ax,
            legend=False,
        )
    sns.despine(ax=ax)
    return ax


def direct_label_last_point(ax, xs, ys, label: str, color: str) -> None:
    ax.annotate(
        label,
        xy=(xs[-1], ys[-1]),
        xytext=(6, 0),
        textcoords="offset points",
        color=color,
        fontsize=9,
        fontweight="bold",
        va="center",
    )


# --- Example entrypoint (replace with SQL-loaded data) ---


def main() -> None:
    apply_analysis_style()
    output_dir = Path("charts")
    stem = "chart_01_example_trend"

    rng = np.random.default_rng(42)
    steps = np.arange(200)
    treatment = 0.5 + 0.002 * steps + rng.normal(0, 0.05, len(steps))
    control = 0.48 + 0.001 * steps + rng.normal(0, 0.05, len(steps))

    fig, ax = plt.subplots(figsize=(7.5, 4.2))
    ax.plot(steps, treatment, color=OKABE_ITO[4], label="Treatment")
    ax.plot(steps, control, color=OKABE_ITO[5], label="Control")
    ax.axvline(150, color=REPORT_UI["neutral_mid"], ls="--", lw=1.0)
    ax.text(
        150,
        ax.get_ylim()[1],
        " phase shift ",
        ha="center",
        va="bottom",
        fontsize=8,
        color="#555",
    )
    ax.set_xlabel("Step")
    ax.set_ylabel("Mean metric (AU)")
    ax.set_title("Treatment vs control over simulation steps")
    direct_label_last_point(ax, steps, treatment, "Treatment", OKABE_ITO[4])
    direct_label_last_point(ax, steps, control, "Control", OKABE_ITO[5])
    fig.tight_layout()
    save_chart_bundle(fig, stem, output_dir)


if __name__ == "__main__":
    main()
