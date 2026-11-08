"""评价合同:eval_metrics 与官方 DailyMobility evaluator 逐字节口径锁。

2026-10-19 口径核查发现并修复真实差异:官方两直方图用独立 bins,
我们此前用 shared edges(同数据 JSD 0.290 vs 0.169,相对差 72%)。
本测试直接调用官方 calculate_jsd_1d / calculate_jsd_2d 作行为锁——
官方口径一变,此测试红,评价器不会静默漂移。
"""

import sys
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "examples" / "v2" / "daily_mobility" / "tools"))
sys.path.insert(
    0,
    str(
        _REPO
        / "packages"
        / "agentsociety-benchmark"
        / "agentsociety_benchmark"
        / "benchmarks"
        / "DailyMobility"
    ),
)

import eval_metrics as ours
from evaluation import calculate_jsd_1d, calculate_jsd_2d


def test_jsd_1d_matches_official_byte_for_byte():
    rng = np.random.default_rng(42)
    for lo, hi, n in [(0, 1, 500), (900, 2100, 300), (0, 10, 50)]:
        a = rng.uniform(lo, hi, n)
        b = rng.uniform(lo * 0.5, hi * 1.4, n)  # 范围错开,放大口径差
        assert ours.official_jsd_1d(a, b) == pytest.approx(
            calculate_jsd_1d(a, b), abs=1e-12
        ), f"口径漂移: ours vs official @ range [{lo},{hi}]"


def test_jsd_2d_matches_official():
    rng = np.random.default_rng(7)
    a = rng.integers(1, 8, size=(20, 48))
    b = rng.integers(1, 8, size=(20, 48))
    assert ours.official_jsd_1d(a.ravel(), b.ravel()) == pytest.approx(
        calculate_jsd_2d(a, b), abs=1e-12
    )


def test_perfect_fit_yields_zero():
    """评价器灵敏度锚点:GT vs GT 应为 ~0(可评估的'完美'参照)。"""
    rng = np.random.default_rng(0)
    a = rng.uniform(500, 1500, 1000)
    assert ours.official_jsd_1d(a, a.copy()) == pytest.approx(0.0, abs=1e-9)


def test_diagnostic_bins_detect_shift_hidden_by_historical_benchmark():
    a = np.linspace(0.0, 1.0, 500)
    b = a + 100.0
    assert ours.jsd_1d(a, b) > 0.8
    assert ours.official_jsd_1d(a, b) < 0.01


def test_partial_day_cannot_be_scored_against_full_day_groundtruth(tmp_path):
    with pytest.raises(ValueError, match="Full-day"):
        ours.compute_metrics(tmp_path, tmp_path, [1], slots=32)
