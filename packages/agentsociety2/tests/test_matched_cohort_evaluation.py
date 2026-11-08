"""匹配人群评估与评价合同冻结的测试(2026-10-22)。

背景:二十人全天实验的评估是「20 生成分布 vs 全部 100 GT」的人群
错配——GT 前 20 行 sleep 55.1% vs 全人群 41.1%,偏差被系统性低估。
本套件锁定:
- 匹配人群裁剪语义(profile id N ↔ GT 行 N-1)与全人群键的向后兼容;
- 行映射越界/重复必须 fail-loud,不做静默回退;
- 评价合同(评价器/GT/配置哈希 + 人群 + 口径)写入并可核验,
  任何一项被篡改必须核验失败。
"""

import importlib.util
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest

_REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_REPO / "examples" / "v2" / "daily_mobility" / "tools"))

import eval_metrics as em

_PROFILES = Path(
    os.environ.get("DAILY_MOBILITY_PROFILES_PATH") or _REPO / "profiles.json"
)

_GT = _REPO / "examples" / "v2" / "daily_mobility" / "data" / "groundtruth"


def _load_evaluator():
    """按独立模块名重新加载,保证合同哈希针对当前文件内容。"""
    spec = importlib.util.spec_from_file_location(
        f"eval_metrics_contract_{id(em)}",
        _REPO / "examples/v2/daily_mobility/tools/eval_metrics.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _synthetic_gt(tmp_path: Path, n: int = 10) -> Path:
    """合成 n 行 GT,行 i 的值带行号印记(用于断言裁剪正确)。"""
    rng = np.random.default_rng(7)
    gt_dir = tmp_path / "gt"
    gt_dir.mkdir(parents=True, exist_ok=True)
    intentions = rng.integers(1, 8, size=(n, 48))
    # 行印记:每行前 3 个 slot 固定为行号 mod 7 + 1,验证匹配裁剪取对行。
    for i in range(n):
        intentions[i, :3] = (i % 7) + 1
    proportions = np.zeros((n, 7))
    for i in range(n):
        counts = np.bincount(intentions[i], minlength=8)[1:8]
        proportions[i] = counts / counts.sum()
    # 回旋值取非等距(素数间隔):等距值会恰好落在官方独立 bins 的
    # bin 边界上,圆环合成的 ~1e-8 浮点噪声即跨 bin,微小样本下
    # JSD 被浮点噪声支配(官方口径固有行为,非本实现缺陷)。
    gyration = np.cumsum(
        np.array([105.0, 83.0, 79.0, 89.0, 71.0, 97.0, 67.0, 73.0, 91.0, 61.0][:n])
    )
    np.save(gt_dir / "daily_intentions_2d.npy", intentions)
    np.save(gt_dir / "intention_proportions_2d.npy", proportions)
    np.save(gt_dir / "gyration_radius.npy", gyration)
    np.save(
        gt_dir / "daily_location_numbers.npy", np.arange(1, n + 1, dtype=float) / 2.0
    )
    return gt_dir


def _write_run(run_dir: Path, agent_ids: list[int], gt_dir: Path) -> Path:
    """按 evaluator 读取格式合成 run 产物(轨迹/访问/问卷)。"""
    run_dir.mkdir(parents=True, exist_ok=True)
    gt_gyration = np.load(gt_dir / "gyration_radius.npy")
    trajs, visited = {}, {}
    for aid in agent_ids:
        # 圆环半径取 GT 行 aid-1 的回旋值:calc_gyration_radius(圆环)
        # = 半径,与匹配 GT 行同值(同一数值单位)。
        r = float(gt_gyration[aid - 1])
        angles = np.linspace(0, 2 * np.pi, 24, endpoint=False)
        trajs[str(aid)] = [
            [round(116.4 + r * np.cos(a), 6), round(39.9 + r * np.sin(a), 6)]
            for a in angles
        ]
        visited[str(aid)] = [500000000 + aid * 977]
    (run_dir / "mobility_metrics_export.json").write_text(
        json.dumps({"trajectories": trajs, "visited_aois": visited}),
        encoding="utf-8",
    )
    art = run_dir / "artifacts"
    art.mkdir(exist_ok=True)
    gt_int = np.load(gt_dir / "daily_intentions_2d.npy")
    for slot in range(48):
        responses = []
        for aid in agent_ids:
            row = aid - 1
            label_idx = int(gt_int[row, slot])
            label = em.NPY_LABEL_ORDER[label_idx - 1]
            responses.append(
                {
                    "agent_id": aid,
                    "answers": [
                        {"question_id": "primary_intention", "parsed_value": label}
                    ],
                }
            )
        (art / f"questionnaire_step_{slot * 2}_t.json").write_text(
            json.dumps(
                {
                    "questionnaire_id": f"daily_mobility_intention_slot_{slot}",
                    "responses": responses,
                }
            ),
            encoding="utf-8",
        )
    return run_dir


_GT_CACHE: dict[str, Path] = {}


def _cached_gt(tmp_path: Path) -> Path:
    """同一测试模块内复用一份合成 GT(免重复落盘)。"""
    key = str(tmp_path)
    if key not in _GT_CACHE:
        _GT_CACHE[key] = _synthetic_gt(tmp_path / "shared_gt", n=10)
    return _GT_CACHE[key]


class TestMatchedCohort:
    def test_matched_rows_are_id_minus_one(self):
        assert em._matched_gt_rows([1, 2, 3], 10) == [0, 1, 2]
        assert em._matched_gt_rows([17, 42], 100) == [16, 41]
        # 非前缀、乱序的 id 集合同样有定义(映射按 id,与顺序无关)。
        assert em._matched_gt_rows([5, 3, 9], 10) == [4, 2, 8]

    def test_out_of_range_id_fails_loud(self):
        with pytest.raises(ValueError, match="无法映射到 GT 行"):
            em._matched_gt_rows([0, 1], 10)
        with pytest.raises(ValueError, match="无法映射到 GT 行"):
            em._matched_gt_rows([11], 10)

    def test_duplicate_id_fails_loud(self):
        with pytest.raises(ValueError, match="重复"):
            em._matched_gt_rows([3, 3], 10)

    def test_matched_perfect_fit_is_zero_and_full_is_not(self, tmp_path):
        """合成 run 精确复现 GT 前 3 行 → 匹配人群各维 ≈0。

        同时全人群参照(10 行)不应为 0——锁定「两个参照真的不同」。
        """
        gt_dir = _cached_gt(tmp_path)
        run = _write_run(tmp_path / "run", [1, 2, 3], gt_dir)
        m = em.compute_metrics(run, gt_dir, [1, 2, 3])
        matched = m["matched_cohort"]
        for key in (
            "jsd_gyration_radius",
            "jsd_intention_sequences",
            "jsd_intention_proportions",
        ):
            assert matched[key] < 0.02, f"匹配人群 {key} 应≈0,实为 {matched[key]}"
        # gyration:run 合成的正是 GT 行 0-2 的半径;全人群参照包含
        # 行 3-9 的其他半径值 → 该维在全人群参照下必然偏离。
        assert m["jsd_gyration_radius"] > matched["jsd_gyration_radius"]
        # 意图序列维:全人群 flatten 后 48*10 个标签 vs 匹配 48*3。
        assert m["jsd_intention_sequences"] > matched["jsd_intention_sequences"]
        # 匹配参照统计量来自裁剪后的行:gt_gyration_mean = 前 3 行均值。
        assert matched["gt_gyration_mean"] == pytest.approx(186.67, abs=1.0)
        assert m["gt_gyration_mean"] == pytest.approx(
            float(np.load(gt_dir / "gyration_radius.npy").mean()), abs=1.0
        )
        # 人群元数据。
        assert matched["agent_ids"] == [1, 2, 3]
        assert matched["gt_rows"] == [0, 1, 2]
        assert matched["reference_population"] == 3

    def test_full_population_keys_backward_compatible(self, tmp_path):
        """顶层平铺键保持官方全人群语义(向后兼容旧消费者)。"""
        gt_dir = _cached_gt(tmp_path)
        run = _write_run(tmp_path / "run", [1, 2, 3], gt_dir)
        m = em.compute_metrics(run, gt_dir, [1, 2, 3])
        for key in (
            "jsd_gyration_radius",
            "jsd_daily_location_numbers",
            "jsd_intention_sequences",
            "jsd_intention_proportions",
            "final_score",
            "num_agents",
            "jsd_by_timeslot_mean",
            "jsd_by_timeslot_max",
            "jsd_transitions",
            "gt_intentions_dist",
            "gen_intentions_dist",
        ):
            assert key in m, f"平铺键 {key} 缺失(向后兼容被破坏)"
        assert m["num_agents"] == 3

    def test_real_gt_first20_sleep_share_differs_from_full(self):
        """真实 GT 上锁定人群偏差事实(评价合同判读的依据)。

        GT 前 20 行与全人群的 sleep 占比差异显著(>10 个百分点):
        小规模 run 若不做匹配评估,行为质量判读会被系统性带偏。
        """
        gt_int = np.load(_GT / "daily_intentions_2d.npy")
        full = float(np.mean(gt_int == 1))
        first20 = float(np.mean(gt_int[:20] == 1))
        assert abs(first20 - full) > 0.10

    @pytest.mark.skipif(
        not _PROFILES.is_file(),
        reason="optional population dataset is not tracked; set DAILY_MOBILITY_PROFILES_PATH",
    )
    def test_optional_profile_ids_match_groundtruth_shape(self):
        """Check structural alignment; this does not establish behavioral correlation."""
        profiles = json.loads(_PROFILES.read_text())
        gyration = np.load(_GT / "gyration_radius.npy")
        assert [p["id"] for p in profiles] == list(range(1, len(profiles) + 1))
        assert len(profiles) == gyration.shape[0]


class TestEvaluationContract:
    def test_contract_written_and_verifies(self, tmp_path):
        gt_dir = _cached_gt(tmp_path)
        run = _write_run(tmp_path / "run", [1, 2, 3], gt_dir)
        config = tmp_path / "init_config.json"
        config.write_text(json.dumps({"agents": [{"agent_id": i} for i in (1, 2, 3)]}))
        path = em.write_evaluation_contract(run, gt_dir, [1, 2, 3], config_path=config)
        assert path.name == "evaluation_contract.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        assert contract["cohort"]["agent_ids"] == [1, 2, 3]
        assert contract["cohort"]["gt_rows"] == [0, 1, 2]
        assert set(contract["gt_files_sha256"]) == set(em.CONTRACT_GT_FILES)
        assert contract["config_sha256"]
        assert contract["metrics"]["bins"] == 50
        ok, mismatches = em.verify_evaluation_contract(run)
        assert ok, mismatches

    def test_contract_detects_gt_tampering(self, tmp_path):
        gt_dir = _synthetic_gt(tmp_path / "gt2", n=10)
        run = _write_run(tmp_path / "run", [1, 2], gt_dir)
        em.write_evaluation_contract(run, gt_dir, [1, 2])
        # 篡改 GT:重写一个文件。
        values = np.load(gt_dir / "gyration_radius.npy")
        np.save(gt_dir / "gyration_radius.npy", values * 2.0)
        ok, mismatches = em.verify_evaluation_contract(run)
        assert not ok
        assert any("gyration_radius" in item for item in mismatches)

    def test_contract_detects_config_tampering(self, tmp_path):
        gt_dir = _cached_gt(tmp_path)
        run = _write_run(tmp_path / "run", [1, 2], gt_dir)
        config = tmp_path / "init_config.json"
        config.write_text(json.dumps({"agents": [{"agent_id": 1}, {"agent_id": 2}]}))
        em.write_evaluation_contract(run, gt_dir, [1, 2], config_path=config)
        config.write_text(json.dumps({"agents": [{"agent_id": 1}]}))
        ok, mismatches = em.verify_evaluation_contract(run)
        assert not ok
        assert "config_sha256" in mismatches

    def test_contract_missing_fails_verification(self, tmp_path):
        ok, mismatches = em.verify_evaluation_contract(tmp_path)
        assert not ok
        assert mismatches == ["evaluation_contract.json 缺失"]

    def test_main_writes_contract_and_scores(self, tmp_path, monkeypatch):
        evaluator = _load_evaluator()
        gt_dir = _synthetic_gt(tmp_path / "gt3", n=10)
        run = _write_run(tmp_path / "run", [1, 2, 3], gt_dir)
        config = tmp_path / "init_config.json"
        config.write_text(json.dumps({"agents": [{"agent_id": i} for i in (1, 2, 3)]}))
        monkeypatch.setattr(
            sys,
            "argv",
            [
                "eval_metrics.py",
                "--run-dir",
                str(run),
                "--gt-dir",
                str(gt_dir),
                "--config",
                str(config),
            ],
        )
        evaluator.main()
        scores = json.loads((run / "scores.json").read_text())
        assert "matched_cohort" in scores
        assert scores["matched_cohort"]["gt_rows"] == [0, 1, 2]
        contract = json.loads((run / "evaluation_contract.json").read_text())
        assert contract["cohort"]["agent_ids"] == [1, 2, 3]
        # CLI 写出的合同当场核验通过。
        ok, _ = evaluator.verify_evaluation_contract(run)
        assert ok

    def test_verify_contract_cli_exit_code(self, tmp_path, monkeypatch, capsys):
        evaluator = _load_evaluator()
        monkeypatch.setattr(
            sys,
            "argv",
            ["eval_metrics.py", "--run-dir", str(tmp_path), "--verify-contract"],
        )
        with pytest.raises(SystemExit) as exc:
            evaluator.main()
        assert exc.value.code == 1
        assert "MISMATCH" in capsys.readouterr().out


def test_contract_cannot_omit_groundtruth_hashes(tmp_path):
    gt_dir = _cached_gt(tmp_path)
    run = tmp_path / "run"
    run.mkdir()
    path = em.write_evaluation_contract(run, gt_dir, [1, 2])
    contract = json.loads(path.read_text())
    contract["gt_files_sha256"] = {}
    path.write_text(json.dumps(contract))
    ok, mismatches = em.verify_evaluation_contract(run)
    assert not ok
    assert any("required files" in mismatch for mismatch in mismatches)


def test_contract_malformed_json_is_reported_as_invalid(tmp_path):
    (tmp_path / em.CONTRACT_FILENAME).write_text("{broken")
    ok, mismatches = em.verify_evaluation_contract(tmp_path)
    assert not ok
    assert "invalid contract" in mismatches[0]
