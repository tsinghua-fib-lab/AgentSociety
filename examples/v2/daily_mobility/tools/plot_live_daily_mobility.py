#!/usr/bin/env python3
"""Live plots for the Daily Mobility 48-slot experiment.

The script watches questionnaire artifacts and writes:
- live_timeline.png: intention + real AOI/POI timeline
- live_state_curves.png: reconstructed hunger/energy/stress curves + action events
- live_timeline_data.json: parsed data for quick inspection

For an interactive web dashboard, run serve_live_dashboard.py instead.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

_TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TOOLS_DIR.parent))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from daily_mobility.tools.live_data import (
    INTENTION_COLORS,
    POSITION_KIND_COLORS,
    TIMELINE_DISPLAY_INTENTIONS,
    build_dashboard_payload,
    collect_artifacts,
    detect_bedtime_slot,
    detect_wake_slot,
    load_needs_history,
    parse_action_events,
    prepare_timeline_intentions,
    slot_time_label,
    write_summary,
)
from matplotlib.patches import Patch


def _annotate_transition(
    ax,
    slot: int,
    *,
    label: str,
    color: str = "#555",
    y: float = 0.77,
    linestyle: str = "-",
) -> None:
    ax.axvline(slot + 0.5, color=color, linewidth=1.1, alpha=0.75, linestyle=linestyle)
    ax.text(slot + 0.65, y, label, color=color, fontsize=10)


def draw_timeline(parsed: dict, out_png: Path) -> None:
    done = sum(v is not None for v in parsed["intentions"])
    fig, axes = plt.subplots(2, 1, figsize=(16, 6.4), sharex=True)
    rows = [
        (axes[0], parsed["intentions"], INTENTION_COLORS, "Intention"),
        (axes[1], parsed["position_kinds"], POSITION_KIND_COLORS, "AOI / status"),
    ]
    for ax, arr, colors, title in rows:
        ax.set_xlim(0, 48)
        ax.set_ylim(0, 1)
        ax.set_yticks([])
        ax.set_title(title, fontsize=14, weight="bold")
        ax.grid(axis="x", color="#e5e5e5", linewidth=0.8)
        for i, val in enumerate(arr):
            ax.barh(
                0.5,
                1,
                left=i,
                height=0.42,
                color=colors.get(val, colors[None]),
                edgecolor="white",
                linewidth=0.6,
            )
            if ax is axes[1] and parsed["aoi_ids"][i] is not None:
                ax.text(
                    i + 0.5,
                    0.5,
                    str(parsed["aoi_ids"][i])[-3:],
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="white",
                    weight="bold",
                )
        ax.axvline(done, color="#555", linestyle=":", linewidth=1.5)

    axes[1].set_xticks(range(0, 49, 2))
    axes[1].set_xticklabels([f"{h:02d}:00" for h in range(25)], rotation=45, ha="right")
    axes[1].set_xlabel("Simulation time")
    axes[0].legend(
        handles=[
            Patch(facecolor=INTENTION_COLORS[k], label=k)
            for k in TIMELINE_DISPLAY_INTENTIONS
            if k in INTENTION_COLORS
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.10),
        ncol=7,
        frameon=False,
        fontsize=9,
    )
    axes[1].legend(
        handles=[
            Patch(facecolor=POSITION_KIND_COLORS[k], label=k)
            for k in POSITION_KIND_COLORS
            if k
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.25),
        ncol=6,
        frameon=False,
        fontsize=9,
    )
    fig.suptitle(f"Daily mobility live timeline - Agent 1 - {done}/48", fontsize=16)
    fig.tight_layout(rect=[0, 0.05, 1, 0.94])
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def draw_reference_needs_intention(
    parsed: dict,
    needs: dict,
    events: list,
    out_png: Path,
) -> None:
    from collections import Counter

    done = sum(v is not None for v in parsed["intentions"])
    x = list(range(48))
    fig, (ax, ax2) = plt.subplots(
        2,
        1,
        figsize=(16, 10),
        sharex=True,
        gridspec_kw={"height_ratios": [3.2, 1.05]},
    )

    ax.plot(
        x, needs["hunger"], color="#e74c3c", marker="o", linewidth=2.4, label="Hunger"
    )
    ax.plot(
        x, needs["energy"], color="#3498db", marker="s", linewidth=2.4, label="Energy"
    )
    ax.plot(
        x, needs["stress"], color="#9b59b6", marker="^", linewidth=2.4, label="Stress"
    )

    for i, intent in enumerate(parsed["intentions"]):
        if intent == "eating out":
            ax.axvspan(i, i + 1, color="#e74c3c", alpha=0.18)
            ax.text(
                i + 0.5,
                0.99,
                "Eating out",
                ha="center",
                va="bottom",
                fontsize=10,
                color="#9f1d17",
            )

    for event in events:
        slot = event["slot"] if isinstance(event, dict) else event[0]
        kind = event["kind"] if isinstance(event, dict) else event[1]
        color = "#b03a2e" if kind == "meal" else "#555"
        ax.axvline(slot + 0.5, color=color, linestyle=":", linewidth=1.25, alpha=0.75)

    intentions = parsed["intentions"]
    wake_slot = detect_wake_slot(intentions)
    if wake_slot is not None:
        wake_time = slot_time_label(parsed, wake_slot)
        _annotate_transition(
            ax,
            wake_slot,
            label=f"Wake up ({wake_time})",
            color="#777",
            y=0.77,
        )
    bed_slot = detect_bedtime_slot(intentions)
    if bed_slot is not None:
        bed_time = slot_time_label(parsed, bed_slot)
        _annotate_transition(
            ax,
            bed_slot,
            label=f"Bedtime ({bed_time})",
            color="#555",
            y=0.72,
            linestyle=":",
        )
    ax.axhline(0.45, color="#999", linestyle="--", linewidth=1.1)
    ax.text(48.08, 0.45, "hunger meal", va="center", color="#777", fontsize=9)
    ax.axhline(0.34, color="#999", linestyle=":", linewidth=1.1)
    ax.text(48.08, 0.34, "low energy", va="center", color="#777", fontsize=9)
    ax.axhline(0.72, color="#999", linestyle="-.", linewidth=1.1)
    ax.text(48.08, 0.72, "high stress", va="center", color="#777", fontsize=9)

    ax.set_ylim(0, 1.05)
    ax.set_xlim(0, 48)
    ax.set_ylabel("Need Value", fontsize=12)
    ax.grid(True, color="#dfdfdf", linewidth=0.85, alpha=0.8)
    ax.legend(loc="upper right", frameon=True)
    ax.set_title(
        f"Needs Decay + Restoration ({done}/48 slots, 30min each) - Agent 1",
        fontsize=17,
        weight="bold",
        pad=18,
    )

    ax2.set_title("Intention Timeline", fontsize=15, weight="bold", pad=6)
    ax2.set_ylim(0, 1)
    ax2.set_yticks([])
    ax2.grid(axis="x", color="#ededed", linewidth=0.85)
    for i, intent in enumerate(parsed["intentions"]):
        ax2.barh(
            0.5,
            1,
            left=i,
            height=0.33,
            color=INTENTION_COLORS.get(intent, INTENTION_COLORS[None]),
            edgecolor="white",
            linewidth=0.6,
        )

    ax2.set_xticks(range(0, 49, 1))
    ax2.set_xticklabels(
        [f"{h // 2:02d}:{'30' if h % 2 else '00'}" for h in range(49)],
        rotation=50,
        ha="right",
        fontsize=8,
    )
    ax2.set_xlabel("Simulation Time", fontsize=12)
    ax2.legend(
        handles=[
            Patch(facecolor=INTENTION_COLORS[k], label=k)
            for k in TIMELINE_DISPLAY_INTENTIONS
            if k in INTENTION_COLORS
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.52),
        ncol=7,
        frameon=False,
        fontsize=10,
    )

    mix = Counter(v for v in parsed["intentions"] if v)
    mix_text = ", ".join(
        f"{k} {mix[k]}" for k in TIMELINE_DISPLAY_INTENTIONS if mix.get(k)
    )
    fig.text(
        0.5,
        0.02,
        f"{done}/48 slot mix: {mix_text}",
        ha="center",
        fontsize=11,
        color="#555",
    )
    fig.tight_layout(rect=[0, 0.06, 1, 0.96])
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def draw_reference_aoi(parsed: dict, out_png: Path) -> None:
    done = sum(v is not None for v in parsed["intentions"])
    fig, axes = plt.subplots(
        2,
        1,
        figsize=(16, 8.2),
        sharex=True,
        gridspec_kw={"height_ratios": [1, 1]},
    )
    title_bits = []
    home = next(
        (
            a
            for a, kind in zip(parsed["aoi_ids"], parsed["position_kinds"])
            if kind == "home"
        ),
        None,
    )
    work = next(
        (
            a
            for a, kind in zip(parsed["aoi_ids"], parsed["position_kinds"])
            if kind == "work"
        ),
        None,
    )
    if home:
        title_bits.append(f"home {home}")
    if work:
        title_bits.append(f"work {work}")
    fig.suptitle(
        f"Agent 1 intention + AOI/status ({done}/48)\n" + " | ".join(title_bits),
        fontsize=17,
        weight="bold",
    )

    rows = [
        (axes[0], parsed["intentions"], INTENTION_COLORS, "Intention (30 min slots)"),
        (axes[1], parsed["position_kinds"], POSITION_KIND_COLORS, "AOI / status"),
    ]
    for ax, arr, colors, title in rows:
        ax.set_ylim(0, 1)
        ax.set_yticks([])
        ax.set_title(title, fontsize=14, weight="bold")
        ax.grid(axis="x", color="#ededed", linewidth=0.85)
        for i, val in enumerate(arr):
            ax.barh(
                0.5,
                1,
                left=i,
                height=0.38,
                color=colors.get(val, colors[None]),
                edgecolor="white",
                linewidth=0.6,
            )
            if ax is axes[1] and parsed["aoi_ids"][i] is not None:
                label = str(parsed["aoi_ids"][i])[-3:]
                if parsed["poi_ids"][i] is not None:
                    label = "POI"
                ax.text(
                    i + 0.5,
                    0.5,
                    label,
                    ha="center",
                    va="center",
                    fontsize=7,
                    color="white",
                    weight="bold",
                )
    axes[1].set_xlim(0, 48)
    axes[1].set_xticks(range(0, 49, 1))
    axes[1].set_xticklabels(
        [f"{h // 2:02d}:{'30' if h % 2 else '00'}" for h in range(49)],
        rotation=50,
        ha="right",
        fontsize=8,
    )
    axes[1].set_xlabel("Simulation time", fontsize=12)
    axes[0].legend(
        handles=[
            Patch(facecolor=INTENTION_COLORS[k], label=k)
            for k in TIMELINE_DISPLAY_INTENTIONS
            if k in INTENTION_COLORS
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.20),
        ncol=7,
        frameon=False,
        fontsize=9,
    )
    axes[1].legend(
        handles=[
            Patch(facecolor=POSITION_KIND_COLORS[k], label=k)
            for k in POSITION_KIND_COLORS
            if k
        ],
        loc="upper center",
        bbox_to_anchor=(0.5, -0.38),
        ncol=6,
        frameon=False,
        fontsize=9,
    )
    fig.tight_layout(rect=[0, 0.07, 1, 0.91])
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def draw_curves(
    parsed: dict,
    needs: dict,
    events: list,
    out_png: Path,
) -> None:
    x = list(range(48))
    fig, ax = plt.subplots(figsize=(16, 6.2))
    ax.plot(x, needs["hunger"], color="#e74c3c", marker="o", label="Hunger")
    ax.plot(x, needs["energy"], color="#3498db", marker="s", label="Energy")
    ax.plot(x, needs["stress"], color="#9b59b6", marker="^", label="Stress")
    ax.axhline(0.45, color="#999", linestyle="--", linewidth=1, label="meal threshold")
    ax.axhline(0.34, color="#999", linestyle=":", linewidth=1, label="low energy")

    for i, intent in enumerate(parsed["intentions"]):
        if intent == "eating out":
            ax.axvspan(i, i + 1, color="#e74c3c", alpha=0.12)
        elif intent == "work":
            ax.axvspan(i, i + 1, color="#5dade2", alpha=0.06)
        elif intent == "sleep":
            ax.axvspan(i, i + 1, color="#2c3e50", alpha=0.07)

    for event in events:
        slot = event["slot"] if isinstance(event, dict) else event[0]
        kind = event["kind"] if isinstance(event, dict) else event[1]
        color = "#c0392b" if kind == "meal" else "#34495e"
        ax.axvline(slot + 0.5, color=color, linestyle="-.", linewidth=1.2, alpha=0.65)
        ax.text(slot + 0.55, 0.98, kind, rotation=90, va="top", fontsize=8, color=color)

    ax.set_xlim(0, 48)
    ax.set_ylim(0, 1.02)
    ax.set_xticks(range(0, 49, 2))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(25)], rotation=45, ha="right")
    ax.set_ylabel("Need value")
    ax.set_xlabel("Simulation time")
    ax.set_title(
        "Needs curves + behavior events (reconstructed from artifacts)", weight="bold"
    )
    ax.grid(True, color="#e8e8e8", linewidth=0.8)
    ax.legend(loc="upper right")
    fig.tight_layout()
    fig.savefig(out_png, dpi=150)
    plt.close(fig)


def render_once(
    run_dir: Path, out_dir: Path, log_file: Path | None = None, *, agent_id: int = 1
) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    parsed = collect_artifacts(run_dir, agent_id=agent_id)
    prepare_timeline_intentions(run_dir, agent_id, parsed)
    needs = load_needs_history(run_dir, parsed, agent_id=agent_id)
    log_path = log_file or (run_dir / "output.log")
    events = parse_action_events(log_path, agent_id=agent_id)
    draw_timeline(parsed, out_dir / "live_timeline.png")
    draw_curves(parsed, needs, events, out_dir / "live_state_curves.png")
    draw_reference_needs_intention(
        parsed, needs, events, out_dir / "needs_intention_timeline.png"
    )
    draw_reference_aoi(parsed, out_dir / "intention_real_aoi.png")
    payload = build_dashboard_payload(run_dir, log_file)
    (out_dir / "live_timeline_data.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_summary(parsed, out_dir / "summary.json")
    return sum(v is not None for v in parsed["intentions"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--watch", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()

    while True:
        done = render_once(args.run_dir, args.out_dir, args.log_file)
        print(f"updated live plots: {done}/48", flush=True)
        if not args.watch or done >= 48:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
