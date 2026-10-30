#!/usr/bin/env python3
"""Daily Mobility evaluation: compute JSD metrics from experiment output.

Matches the official DailyMobility benchmark evaluation
(``agentsociety_benchmark.benchmarks.DailyMobility.evaluation``).

Usage:
    uv run python examples/v2/daily_mobility/tools/eval_metrics.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from scipy.spatial.distance import jensenshannon

# NPY label encoding used by the official benchmark (confirmed via data analysis).
# The groundtruth README has this mapping WRONG (swaps 3↔4 and 7).
# Correct encoding:
#   1 = sleep
#   2 = home activity
#   3 = other
#   4 = work
#   5 = shopping
#   6 = eating out
#   7 = leisure and entertainment
#
# Agent questionnaire responses use string labels. This dict maps them to NPY integers.
QUESTION_LABEL_TO_NPY_IDX = {
    "sleep": 1,
    "home activity": 2,
    "other": 3,
    "work": 4,
    "shopping": 5,
    "eating out": 6,
    "leisure and entertainment": 7,
}

# Label order for proportion vectors (matches NPY integer order 1..7).
NPY_LABEL_ORDER = [
    "sleep",           # 1
    "home activity",   # 2
    "other",           # 3
    "work",            # 4
    "shopping",        # 5
    "eating out",      # 6
    "leisure and entertainment",  # 7
]


def load_gt(gt_dir: Path) -> dict:
    """Load ground truth from .npy files (official benchmark format).

    Returns dict with:
      - gyration_radius: (100,) float array
      - daily_location_numbers: (100,) float array
      - daily_intentions_2d: (100, 48) int array (values 1-7)
      - intention_proportions_2d: (100, 7) float array
    """
    return {
        "gyration_radius": np.load(gt_dir / "gyration_radius.npy"),
        "daily_location_numbers": np.load(gt_dir / "daily_location_numbers.npy"),
        "daily_intentions_2d": np.load(gt_dir / "daily_intentions_2d.npy"),
        "intention_proportions_2d": np.load(gt_dir / "intention_proportions_2d.npy"),
    }


def load_export(run_dir: Path):
    """Load mobility metrics export from simulation run."""
    p = run_dir / "mobility_metrics_export.json"
    if not p.is_file():
        raise FileNotFoundError(f"Missing {p}")
    raw = json.loads(p.read_text())
    trajs = {int(k): v for k, v in raw["trajectories"].items()}
    vis = {int(k): set(v) for k, v in raw["visited_aois"].items()}
    return trajs, vis


def load_intentions(run_dir: Path, agent_ids: list[int]) -> dict[int, list[int]]:
    """Load intention questionnaire results.

    Returns dict: agent_id -> list of 48 int labels (1-7, default 7).
    Labels use the official NPY encoding.
    """
    by_slot: dict[int, dict] = {}
    artifacts_dir = run_dir / "artifacts"
    if artifacts_dir.is_dir():
        for p in sorted(artifacts_dir.glob("questionnaire*.json")):
            try:
                data = json.loads(p.read_text())
            except Exception:
                continue
            qid = str(data.get("questionnaire_id", ""))
            if "daily_mobility_intention_slot_" not in qid:
                continue
            slot = int(qid.rsplit("_", 1)[1])
            by_slot[slot] = data

    out: dict[int, list[int]] = {aid: [7] * 48 for aid in agent_ids}
    for slot in range(48):
        data = by_slot.get(slot)
        if not data:
            continue
        for resp in data.get("responses", []):
            aid = int(resp["agent_id"])
            if aid not in out:
                continue
            answer = ""
            if "answer" in resp and isinstance(resp["answer"], dict):
                answer = resp["answer"].get("primary_intention", "")
            elif (
                "answers" in resp
                and isinstance(resp["answers"], list)
                and resp["answers"]
            ):
                answer = resp["answers"][0].get("raw_text", "")
                if not answer:
                    answer = resp["answers"][0].get("parsed_value", "")
            answer = str(answer).strip().lower()
            idx = QUESTION_LABEL_TO_NPY_IDX.get(answer, 7)
            out[aid][slot] = idx
    return out


def calc_gyration_radius(points: list) -> float:
    if len(points) < 2:
        return 0.0
    arr = np.array(points)
    centroid = arr.mean(axis=0)
    return float(np.mean(np.sqrt(((arr - centroid) ** 2).sum(axis=1))))


def jsd_1d(a: np.ndarray, b: np.ndarray, bins: int = 50) -> float:
    a, b = np.asarray(a).ravel(), np.asarray(b).ravel()
    if not a.size or not b.size or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("JSD requires nonempty, finite samples")
    # Both populations must contribute to the range. Using only ground truth
    # drops valid out-of-range simulation values and produces a zero histogram.
    edges = np.histogram_bin_edges(np.concatenate((a, b)), bins=bins)
    h1, _ = np.histogram(a, bins=edges)
    h2, _ = np.histogram(b, bins=edges)
    h1, h2 = h1 / h1.sum(), h2 / h2.sum()
    return float(jensenshannon(h1, h2))


def jsd_2d(a: np.ndarray, b: np.ndarray, bins: int = 50) -> float:
    return jsd_1d(a.flatten(), b.flatten(), bins=bins)


def compute_metrics(run_dir: Path, gt_dir: Path, agent_ids: list[int]) -> dict:
    gt = load_gt(gt_dir)
    trajs, vis = load_export(run_dir)
    intentions = load_intentions(run_dir, agent_ids)

    n_agents = len(agent_ids)

    # 1. Gyration radius
    gen_gyration = np.array(
        [calc_gyration_radius(trajs.get(aid, [])) for aid in agent_ids]
    )

    # 2. Daily location numbers
    gen_locations = np.array([len(vis.get(aid, set())) for aid in agent_ids])

    # 3. Intention sequences (N x 48 int arrays)
    gen_intentions = np.array(
        [intentions.get(aid, [7] * 48) for aid in agent_ids], dtype=np.int64
    )

    # 4. Intention proportions (N x 7)
    gen_proportions = np.zeros((n_agents, 7), dtype=np.float64)
    for i, aid in enumerate(agent_ids):
        seq = intentions.get(aid, [7] * 48)
        counts = [0] * 7
        for v in seq:
            if 1 <= v <= 7:
                counts[v - 1] += 1
        total = sum(counts) or 1
        gen_proportions[i] = [c / total for c in counts]

    # JSD computation — matches official benchmark.
    jsd_g = jsd_1d(gt["gyration_radius"], gen_gyration)
    jsd_l = jsd_1d(gt["daily_location_numbers"], gen_locations)
    jsd_s = jsd_2d(gt["daily_intentions_2d"], gen_intentions)
    jsd_p = jsd_2d(gt["intention_proportions_2d"], gen_proportions)

    final = ((1 - jsd_g + 1 - jsd_l + 1 - jsd_s + 1 - jsd_p) / 4) * 100

    return {
        "jsd_gyration_radius": round(jsd_g, 4),
        "jsd_daily_location_numbers": round(jsd_l, 4),
        "jsd_intention_sequences": round(jsd_s, 4),
        "jsd_intention_proportions": round(jsd_p, 4),
        "final_score": round(final, 2),
        "num_agents": n_agents,
        "gen_gyration_mean": round(float(gen_gyration.mean()), 2),
        "gt_gyration_mean": round(float(gt["gyration_radius"].mean()), 2),
        "gen_locations_mean": round(float(gen_locations.mean()), 2),
        "gt_locations_mean": round(float(gt["daily_location_numbers"].mean()), 2),
        # Per-label distribution comparison.
        "gt_intentions_dist": {
            NPY_LABEL_ORDER[i]: round(float(np.mean(gt["intention_proportions_2d"][:, i])), 4)
            for i in range(7)
        },
        "gen_intentions_dist": {
            NPY_LABEL_ORDER[i]: round(float(np.mean(gen_proportions[:, i])), 4)
            for i in range(7)
        },
    }


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--gt-dir", type=Path, default=None)
    args = parser.parse_args()

    tools = Path(__file__).resolve().parent
    exp = tools.parent
    run_dir = (args.run_dir or (exp / "tmp" / "run")).resolve()
    gt_dir = (args.gt_dir or (exp / "data" / "groundtruth")).resolve()

    init_cfg = json.loads((exp / "tmp" / "init" / "init_config.json").read_text())
    agent_ids = [a["agent_id"] for a in init_cfg["agents"]]

    results = compute_metrics(run_dir, gt_dir, agent_ids)

    out_path = run_dir / "scores.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(f"Scores written to {out_path}")
    for k, v in results.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
