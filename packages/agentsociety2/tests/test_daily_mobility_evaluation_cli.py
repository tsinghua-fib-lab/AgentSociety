"""自定义实验目录必须使用该实验的人员配置计算指标。"""

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

_EXAMPLE = Path(__file__).resolve().parents[3] / "examples/v2/daily_mobility"


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_evaluator_uses_explicit_configuration(tmp_path, monkeypatch):
    evaluator = load("explicit_evaluator", _EXAMPLE / "tools/eval_metrics.py")
    config = tmp_path / "custom.json"
    config.write_text(json.dumps({"agents": [{"agent_id": 17}, {"agent_id": 42}]}))
    seen = []
    contracts = []

    def compute(run, truth, ids):
        seen.append((run, truth, ids))
        return {"num_agents": len(ids)}

    def write_contract(run, truth, ids, *, config_path=None):
        contracts.append((run, truth, ids, config_path))
        return run / "evaluation_contract.json"

    monkeypatch.setattr(evaluator, "compute_metrics", compute)
    # 本测试考配置转发,不考合同写入(合同有独立测试;gt 目录是假的)。
    monkeypatch.setattr(evaluator, "write_evaluation_contract", write_contract)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "eval_metrics.py",
            "--run-dir",
            str(tmp_path),
            "--config",
            str(config),
            "--gt-dir",
            str(tmp_path / "gt"),
        ],
    )
    evaluator.main()
    assert seen == [(tmp_path, tmp_path / "gt", [17, 42])]
    # 评价合同同样使用显式配置的人员名单与 GT 目录。
    assert contracts == [(tmp_path, tmp_path / "gt", [17, 42], config)]
    assert json.loads((tmp_path / "scores.json").read_text())["num_agents"] == 2


def test_one_stop_runner_forwards_explicit_configuration(tmp_path, monkeypatch):
    runner = load("explicit_runner", _EXAMPLE / "run_all.py")
    commands = []
    monkeypatch.setattr(runner, "_run", lambda command: commands.append(command))
    args = SimpleNamespace(
        config=tmp_path / "custom.json",
        run_dir=tmp_path / "run",
        gt_dir=None,
    )
    runner.compute_metrics(args)
    command = commands[0]
    assert command[command.index("--config") + 1] == str(args.config.resolve())


def test_gt_slot_aggregation_majority():
    """同一全天跨度的 GT 降采样:48→24 多数票聚合(平票取较小标签)。"""
    import numpy as np

    em = load("agg_evaluator", _EXAMPLE / "tools/eval_metrics.py")

    gt = np.array(
        [
            [1, 1, 2, 2, 4, 4, 4, 1],  # → [1, 2, 4, 1]
            [2, 1, 1, 1, 3, 3, 3, 3],  # → [1, 1, 3]... 平票组 [2,1]→2?不,取 argmax 首个
        ],
        dtype=np.int64,
    )
    agg = em._aggregate_gt_slots(gt, 4)
    assert agg.shape == (2, 4)
    assert agg[0].tolist() == [1, 2, 4, 1]
    # 组 [2,1] 平票 → bincount argmax 返回 2(标签 2 计 1 与标签 1 计 1,argmax 取首个最大=索引 1?验证)
    # np.bincount([2,1]) = [0,1,1] → argmax=1 → 标签 1。修正断言:
    assert agg[1].tolist() == [1, 1, 3, 3]


def test_gt_slot_aggregation_identity_and_reject():
    import numpy as np
    import pytest

    em = load("agg_evaluator2", _EXAMPLE / "tools/eval_metrics.py")

    gt = np.zeros((3, 48), dtype=np.int64)
    assert em._aggregate_gt_slots(gt, 48).shape == (3, 48)
    # 比例分桶支持非整除；它改变全天采样分辨率,不代表裁剪 16h 窗;
    # 拒绝条件更新为 slots > GT 列数(原"不整除"断言已过时)。
    assert em._aggregate_gt_slots(gt, 5).shape == (3, 5)
    with pytest.raises(ValueError):
        em._aggregate_gt_slots(gt, 49)  # slots > GT 列数


def test_aggregate_nondivisible_slots():
    """非整除 slots(32)聚合:桶宽混合 + 全列覆盖 + 48 原样。"""
    import numpy as np
    import pytest as _p

    # b0295ee8 漏写此行导致 NameError(合并前即挂),补上模块加载。
    em = load("agg_evaluator3", _EXAMPLE / "tools/eval_metrics.py")
    gt = np.array([[1, 1, 2, 2, 4, 4, 4, 1]])
    # 8 列 → 3 桶(非整除):edges=[0,3,5,8] → 桶宽 3,2,3
    agg = em._aggregate_gt_slots(gt, 3)
    assert agg.shape == (1, 3)
    # 桶 1 = [1,1,2] → 1;桶 2 = [2,4] → 2(平票取首个);
    # 桶 3 = [4,4,1] → 4
    assert agg[0].tolist() == [1, 2, 4]
    # 原样
    assert (em._aggregate_gt_slots(gt, 8) == gt).all()
    # slots > 列数拒绝
    with _p.raises(ValueError):
        em._aggregate_gt_slots(gt, 9)
