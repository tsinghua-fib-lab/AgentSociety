#!/usr/bin/env python3
"""Daily Mobility evaluation: compute JSD metrics from experiment output.

Diagnostic metrics use shared bin edges as on main. ``official_compatibility``
separately reproduces the historical DailyMobility benchmark.

输出两套参照(2026-10-22):
- 顶层平铺键 = **全人群参照**(共享 bins,全部 GT 行)——保持向后兼容,
  另在 official_compatibility 中保留官方 benchmark 数值;
- ``matched_cohort`` 子树 = **匹配人群参照**(GT 裁剪为本 run 实际
  使用的 profile 对应行)。profile id N ↔ GT 行 N-1(映射假设见
  :func:`_matched_gt_rows`)。小规模 run(如 20 人全天)对全人群
  评估存在系统性人群错配:GT 前 20 行 sleep 55.1% vs 全人群 41.1%,
  匹配评估消除该偏差。

每次评估同时写 ``evaluation_contract.json``(评价合同冻结:评价器
SHA-256、GT 文件哈希、人群定义、指标口径),供运行前核验与实验
身份绑定(Roadmap Phase 0 未闭合项)。

Usage:
    uv run python examples/v2/daily_mobility/tools/eval_metrics.py
"""

from __future__ import annotations

import hashlib
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
    "sleep",  # 1
    "home activity",  # 2
    "other",  # 3
    "work",  # 4
    "shopping",  # 5
    "eating out",  # 6
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


def load_intentions(
    run_dir: Path, agent_ids: list[int], slots: int = 48
) -> dict[int, list[int]]:
    """Load intention questionnaire results.

    Returns dict: agent_id -> list of ``slots`` int labels (1-7, default 7).
    Labels use the official NPY encoding. ``slots<48`` 用于降规模协议
    (如 16h 窗 = 32 slot):问卷按 slot 序号读取,超出窗的忽略。
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

    out: dict[int, list[int]] = {aid: [7] * slots for aid in agent_ids}
    for slot in range(slots):
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
    """Compare both populations using shared bin edges, preserving main's metric."""
    a, b = np.asarray(a).ravel(), np.asarray(b).ravel()
    if not a.size or not b.size or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("JSD requires nonempty, finite samples")
    edges = np.histogram_bin_edges(np.concatenate((a, b)), bins=bins)
    h1, _ = np.histogram(a, bins=edges)
    h2, _ = np.histogram(b, bins=edges)
    h1, h2 = h1 / h1.sum(), h2 / h2.sum()
    return float(jensenshannon(h1, h2))


def official_jsd_1d(a: np.ndarray, b: np.ndarray, bins: int = 50) -> float:
    """Historical benchmark compatibility; independent bins can hide shifts.

    Use ``jsd_1d`` for diagnostic comparisons on shared physical coordinates.
    """
    a, b = np.asarray(a).ravel(), np.asarray(b).ravel()
    if not a.size or not b.size or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError("JSD requires nonempty, finite samples")
    h1, _ = np.histogram(a, bins=bins, density=True)
    h2, _ = np.histogram(b, bins=bins, density=True)
    eps = 1e-10
    h1, h2 = h1 + eps, h2 + eps
    h1, h2 = h1 / h1.sum(), h2 / h2.sum()
    return float(jensenshannon(h1, h2))


def jsd_2d(a: np.ndarray, b: np.ndarray, bins: int = 50) -> float:
    return jsd_1d(a.flatten(), b.flatten(), bins=bins)


def jsd_by_timeslot(gen: np.ndarray, gt: np.ndarray, n_labels: int = 7) -> list[float]:
    """时间维扩展(2026-10-19):逐 slot 的标签分布 JSD。

    官方 ``jsd_intention_sequences`` 把 (N,48) flatten 后做直方图,只测
    全局标签频数——对整体平移/打乱完全无感(反例实测:平移 4h JSD=0)。
    本指标逐 30 分钟 slot 比较 gen 与 GT 的标签构成,直接抓"错时":
    ``[jsd(gen[:, s], gt[:, s]) for s in range(48)]``,取均值与最差值。

    :param gen: 生成意图 (N, 48) 整数 1..7。
    :param gt: GT 意图 (M, 48) 整数 1..7。
    :param n_labels: 标签类数。
    :returns: 逐 slot JSD 列表(长度 48)。
    """
    out = []
    for s in range(gen.shape[1]):
        g_counts = np.bincount(gen[:, s], minlength=n_labels + 1)[1:]
        t_counts = np.bincount(gt[:, s], minlength=n_labels + 1)[1:]
        g = g_counts / max(g_counts.sum(), 1)
        t = t_counts / max(t_counts.sum(), 1)
        g, t = g + 1e-10, t + 1e-10
        g, t = g / g.sum(), t / t.sum()
        out.append(float(jensenshannon(g, t)))
    return out


def jsd_transitions(gen: np.ndarray, gt: np.ndarray, n_labels: int = 7) -> float:
    """时间维扩展:逐 agent 相邻 slot 的标签转移结构 JSD。

    抓"节奏感"(何时切换活动)而非标签频数:对每个序列取相邻对
    ``(label[s], label[s+1])`` 计数成 7×7 转移分布,聚齐后与 GT 比
    JSD。通勤/回家等过渡模式的变化在此可见(官方频数维不可见)。

    :param gen: 生成意图 (N, 48)。
    :param gt: GT 意图 (M, 48)。
    :param n_labels: 标签类数。
    :returns: 转移分布 JSD(标量)。
    """

    def _trans(arr: np.ndarray) -> np.ndarray:
        flat = np.zeros(n_labels * n_labels)
        for row in arr:
            for s in range(row.shape[0] - 1):
                a, b = int(row[s]) - 1, int(row[s + 1]) - 1
                if 0 <= a < n_labels and 0 <= b < n_labels:
                    flat[a * n_labels + b] += 1
        return flat

    g, t = _trans(gen) + 1e-10, _trans(gt) + 1e-10
    g, t = g / g.sum(), t / t.sum()
    return float(jensenshannon(g, t))


def _matched_gt_rows(agent_ids: list[int], gt_length: int) -> list[int]:
    """匹配人群的 GT 行选择:profile id N ↔ GT 行 N-1。

    This mapping assumes profile ids follow the ground-truth row order.
    Callers must establish that correspondence for their own input dataset;
    range checks alone cannot prove behavioral or identity alignment.

    :param agent_ids: 本 run 实际使用的 profile/agent id 列表。
    :param gt_length: GT 数组行数(100)。
    :returns: 每个 agent_id 对应的 GT 行下标(0 基)。
    :raises ValueError: id 越界或重复——匹配人群映射必须 fail-loud,
        不做静默回退(错配的人群参照比没有参照更危险)。
    """
    rows: list[int] = []
    for aid in agent_ids:
        row = int(aid) - 1
        if not 0 <= row < gt_length:
            raise ValueError(
                f"agent_id {aid} 无法映射到 GT 行(有效范围 1..{gt_length});"
                "匹配人群评估要求 agent id 与 profile id 一致"
            )
        rows.append(row)
    if len(set(rows)) != len(rows):
        raise ValueError("agent_ids 含重复 id,无法建立匹配人群映射")
    return rows


def _score_against(
    gt: dict,
    gen_gyration: np.ndarray,
    gen_locations: np.ndarray,
    gen_intentions: np.ndarray,
    gen_proportions: np.ndarray,
) -> dict:
    """对单一 GT 参照计算全套指标(官方四维 + 时间维扩展)。"""
    jsd_g = jsd_1d(gt["gyration_radius"], gen_gyration)
    jsd_l = jsd_1d(gt["daily_location_numbers"], gen_locations)
    jsd_s = jsd_2d(gt["daily_intentions_2d"], gen_intentions)
    jsd_p = jsd_2d(gt["intention_proportions_2d"], gen_proportions)

    final = ((1 - jsd_g + 1 - jsd_l + 1 - jsd_s + 1 - jsd_p) / 4) * 100
    timeslot = jsd_by_timeslot(gen_intentions, gt["daily_intentions_2d"])

    official = [official_jsd_1d(a, b) for a, b in (
        (gt["gyration_radius"], gen_gyration),
        (gt["daily_location_numbers"], gen_locations),
        (gt["daily_intentions_2d"], gen_intentions),
        (gt["intention_proportions_2d"], gen_proportions),
    )]
    return {
        "official_compatibility": {
            "jsd_gyration_radius": round(official[0], 4),
            "jsd_daily_location_numbers": round(official[1], 4),
            "jsd_intention_sequences": round(official[2], 4),
            "jsd_intention_proportions": round(official[3], 4),
            "final_score": round((1 - sum(official) / 4) * 100, 2),
        },
        "jsd_gyration_radius": round(jsd_g, 4),
        "jsd_daily_location_numbers": round(jsd_l, 4),
        "jsd_intention_sequences": round(jsd_s, 4),
        "jsd_intention_proportions": round(jsd_p, 4),
        "final_score": round(final, 2),
        "gen_gyration_mean": round(float(gen_gyration.mean()), 2),
        "gt_gyration_mean": round(float(gt["gyration_radius"].mean()), 2),
        "gen_locations_mean": round(float(gen_locations.mean()), 2),
        "gt_locations_mean": round(float(gt["daily_location_numbers"].mean()), 2),
        # Per-label distribution comparison.
        "gt_intentions_dist": {
            NPY_LABEL_ORDER[i]: round(
                float(np.mean(gt["intention_proportions_2d"][:, i])), 4
            )
            for i in range(7)
        },
        "gen_intentions_dist": {
            NPY_LABEL_ORDER[i]: round(float(np.mean(gen_proportions[:, i])), 4)
            for i in range(7)
        },
        # 时间维扩展(官方序列维为全局频数,测不到时序——见
        # test_evaluator_counterexamples 的盲区锁定):
        "jsd_by_timeslot_mean": round(float(np.mean(timeslot)), 4),
        "jsd_by_timeslot_max": round(float(np.max(timeslot)), 4),
        "jsd_transitions": round(
            jsd_transitions(gen_intentions, gt["daily_intentions_2d"]), 4
        ),
    }


def _aggregate_gt_slots(gt_matrix: np.ndarray, slots: int) -> np.ndarray:
    """48-slot GT → 目标 slot 数的多数票聚合。

    This changes resolution over the same full time span; it does not crop
    a shorter time window. Ties select the smallest label value.
    """
    if slots <= 0:
        raise ValueError("slots must be positive")
    total = gt_matrix.shape[1]
    if slots == total:
        return gt_matrix
    if total < slots:
        raise ValueError(f"slots={slots} 超过 GT 列数 {total},无法聚合")
    n = gt_matrix.shape[0]
    out = np.empty((n, slots), dtype=gt_matrix.dtype)
    # 每桶宽度 = total/slots;边界取整,余数摊给前面的桶
    edges = np.round(np.linspace(0, total, slots + 1)).astype(int)
    for j in range(slots):
        lo, hi = edges[j], edges[j + 1]
        if hi <= lo:
            # 退化桶(余数摊派导致):复制前一个 slot 的标签
            out[:, j] = out[:, j - 1] if j > 0 else gt_matrix[:, 0]
            continue
        block = gt_matrix[:, lo:hi]
        # 逐行多数票(平票取首个)
        for i in range(n):
            counts = np.bincount(block[i])
            out[i, j] = int(counts.argmax())
    return out


def compute_metrics(
    run_dir: Path, gt_dir: Path, agent_ids: list[int], slots: int = 48
) -> dict:
    """计算共享分桶诊断、历史 benchmark 兼容分数及匹配人群参照。

    Only full-day runs are comparable to this ground truth. Partial-day
    evaluation needs separate, time-aligned ground truth for every dimension.
    """
    if slots != 48:
        raise ValueError("Full-day ground truth requires slots=48; partial-day evaluation needs matching time-window ground truth")
    gt = load_gt(gt_dir)
    trajs, vis = load_export(run_dir)
    intentions = load_intentions(run_dir, agent_ids, slots=slots)

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

    # 全人群参照(官方语义,全部 GT 行)——平铺键保持向后兼容。
    full = _score_against(
        gt, gen_gyration, gen_locations, gen_intentions, gen_proportions
    )

    # 匹配人群参照:GT 裁剪为本 run 实际 profile 对应行。
    matched_rows = _matched_gt_rows(agent_ids, int(gt["gyration_radius"].shape[0]))
    gt_matched = {key: value[matched_rows] for key, value in gt.items()}
    matched = _score_against(
        gt_matched, gen_gyration, gen_locations, gen_intentions, gen_proportions
    )

    return {
        **full,
        "num_agents": n_agents,
        "matched_cohort": {
            "agent_ids": list(agent_ids),
            "gt_rows": matched_rows,
            "reference_population": len(matched_rows),
            "num_agents": n_agents,
            **matched,
        },
    }


#: 评价合同覆盖的 GT 文件(冻结哈希,防参考数据被静默替换)。
CONTRACT_GT_FILES = (
    "daily_intentions_2d.npy",
    "intention_proportions_2d.npy",
    "daily_location_numbers.npy",
    "gyration_radius.npy",
)
#: 评价合同文件名(写入 run_dir,与该次运行的 scores.json 同级)。
CONTRACT_FILENAME = "evaluation_contract.json"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_evaluation_contract(
    gt_dir: Path,
    agent_ids: list[int],
    *,
    config_path: Path | None = None,
    run_dir: Path | None = None,
) -> dict:
    """构建评价合同:评价器/GT/人群/口径的冻结描述。

    Roadmap Phase 0 未闭合项「评价合同与参考数据版本冻结」的落点:
    合同作为独立产物绑定每次运行,任何维度分数都可追溯到"哪个
    评价器、哪份 GT、哪群人、什么口径"算出来的。
    """
    gt_dir = Path(gt_dir).resolve()
    gt_length = int(np.load(gt_dir / "gyration_radius.npy").shape[0])
    contract = {
        "schema_version": 1,
        "evaluator_sha256": _sha256(Path(__file__).resolve()),
        "gt_dir": str(gt_dir),
        "gt_files_sha256": {name: _sha256(gt_dir / name) for name in CONTRACT_GT_FILES},
        "cohort": {
            "mode": "full+matched",
            "agent_ids": [int(a) for a in agent_ids],
            "gt_rows": _matched_gt_rows(agent_ids, gt_length),
            "reference_population": len(agent_ids),
            "row_alignment_assumption": "profile id N maps to GT row N-1; caller must verify dataset provenance",
        },
        "metrics": {
            "divergence": (
                "scipy.spatial.distance.jensenshannon(JS distance="
                "sqrt(divergence),自然对数底)"
            ),
            "bins": 50,
            "histogram": "shared edges spanning both populations; official_compatibility uses independent density bins",
            "smoothing_eps": 0,
            "official_compatibility_smoothing_eps": 1e-10,
            "dimensions": [
                "jsd_gyration_radius",
                "jsd_daily_location_numbers",
                "jsd_intention_sequences",
                "jsd_intention_proportions",
            ],
            "extensions": ["jsd_by_timeslot", "jsd_transitions"],
            "final_score": "((1-g + 1-l + 1-s + 1-p)/4)*100;顶层=全人群参照,matched_cohort 子树=匹配人群参照",
        },
    }
    if config_path is not None:
        config_path = Path(config_path).resolve()
        contract["config_path"] = str(config_path)
        contract["config_sha256"] = _sha256(config_path)
    if run_dir is not None:
        contract["run_dir"] = str(Path(run_dir).resolve())
    return contract


def write_evaluation_contract(
    run_dir: Path,
    gt_dir: Path,
    agent_ids: list[int],
    *,
    config_path: Path | None = None,
) -> Path:
    """把评价合同写进 run_dir,与 scores.json 同级。"""
    run_dir = Path(run_dir)
    contract = build_evaluation_contract(
        gt_dir, agent_ids, config_path=config_path, run_dir=run_dir
    )
    path = run_dir / CONTRACT_FILENAME
    path.write_text(
        json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return path


def verify_evaluation_contract(run_dir: Path) -> tuple[bool, list[str]]:
    """核验评价合同:重算评价器/GT/配置哈希并与冻结值比对。

    :returns: (是否全部一致, 不一致项列表)。合同缺失视作不一致。
    """
    path = Path(run_dir) / CONTRACT_FILENAME
    if not path.is_file():
        return False, [CONTRACT_FILENAME + " 缺失"]
    try:
        contract = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(contract, dict) or contract.get("schema_version") != 1:
            return False, ["schema_version"]
        mismatches: list[str] = []
        if _sha256(Path(__file__).resolve()) != contract.get("evaluator_sha256"):
            mismatches.append("evaluator_sha256")
        frozen_files = contract.get("gt_files_sha256", {})
        if set(frozen_files) != set(CONTRACT_GT_FILES):
            mismatches.append("gt_files_sha256:required files")
        gt_dir = Path(contract["gt_dir"])
        for name in CONTRACT_GT_FILES:
            current = gt_dir / name
            if not current.is_file() or _sha256(current) != frozen_files.get(name):
                mismatches.append(f"gt_files_sha256:{name}")
        config_path = contract.get("config_path")
        if config_path is not None:
            current = Path(config_path)
            if not current.is_file() or _sha256(current) != contract.get("config_sha256"):
                mismatches.append("config_sha256")
        elif "config_sha256" in contract:
            mismatches.append("config_path")
        expected = build_evaluation_contract(gt_dir, contract["cohort"]["agent_ids"])
        for key in ("cohort", "metrics"):
            if contract.get(key) != expected[key]:
                mismatches.append(key)
        return (not mismatches), mismatches
    except (OSError, ValueError, KeyError, TypeError) as exc:
        return False, [f"invalid contract: {exc}"]


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, default=None)
    parser.add_argument("--gt-dir", type=Path, default=None)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument(
        "--verify-contract",
        action="store_true",
        help="只核验已冻结的评价合同,不重算分数(运行前核验入口)。",
    )
    args = parser.parse_args()

    tools = Path(__file__).resolve().parent
    exp = tools.parent
    run_dir = (args.run_dir or (exp / "tmp" / "run")).resolve()
    gt_dir = (args.gt_dir or (exp / "data" / "groundtruth")).resolve()

    config_path = args.config or (exp / "tmp" / "init" / "init_config.json")

    if args.verify_contract:
        ok, mismatches = verify_evaluation_contract(run_dir)
        if ok:
            print(f"Contract OK: {run_dir / CONTRACT_FILENAME}")
        else:
            print(f"Contract MISMATCH: {mismatches}")
            raise SystemExit(1)
        return

    init_cfg = json.loads(config_path.read_text())
    agent_ids = [a["agent_id"] for a in init_cfg["agents"]]

    results = compute_metrics(run_dir, gt_dir, agent_ids)
    contract_path = write_evaluation_contract(
        run_dir, gt_dir, agent_ids, config_path=config_path
    )

    out_path = run_dir / "scores.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print(f"Scores written to {out_path}")
    print(f"Contract written to {contract_path}")
    for k, v in results.items():
        if k == "matched_cohort":
            print("  matched_cohort (匹配人群参照):")
            for mk, mv in v.items():
                if mk in ("agent_ids", "gt_rows"):
                    continue
                print(f"    {mk}: {mv}")
        else:
            print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
