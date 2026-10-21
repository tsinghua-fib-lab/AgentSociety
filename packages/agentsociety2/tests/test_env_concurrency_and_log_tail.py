"""Correctness + same-condition A/B timing for concurrency / log tail."""

from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

import pytest

from agentsociety2.agent.person import PersonAgent
from agentsociety2.backend.routers.experiments import read_log_tail
from agentsociety2.contrib.env.economy_space import EconomySpace
from agentsociety2.contrib.env.global_information import GlobalInformationEnv
from agentsociety2.contrib.env.mobility_space.environment import MobilitySpace
from agentsociety2.contrib.env.simple_social_space import SimpleSocialSpace


def test_locked_contrib_modules_declare_concurrency_safe() -> None:
    assert SimpleSocialSpace.is_concurrency_safe() is True
    assert EconomySpace.is_concurrency_safe() is True
    assert GlobalInformationEnv.is_concurrency_safe() is True
    assert MobilitySpace.is_concurrency_safe() is True


def test_typical_stack_enables_env_actor_parallelism() -> None:
    types = [SimpleSocialSpace, GlobalInformationEnv, MobilitySpace]
    assert all(cls.is_concurrency_safe() for cls in types)


def test_env_actor_max_concurrency_default_is_64() -> None:
    """默认并发上限 64：300-agent 实测在飞 env ask 的 p50 ≈ 59，旧默认 8 会
    饿死 actor（env ask 均值 38.2s@8 vs 2.5s@64）。conftest 已清理环境变量，
    此处断言的是代码默认值。"""
    from agentsociety2.config import Config

    assert Config.ENV_ACTOR_MAX_CONCURRENCY == 64


@pytest.mark.asyncio
async def test_template_lookup_runs_embeddings_outside_cache_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """embedding（含 HTTP）不得在 ``_template_cache_lock`` 内计算。

    回归：``_lookup``（每次 ask 都走）曾在锁内 await embedding，把并行 ask
    串行化到 embedding 端点延迟上（实测并行度 5.6×，配置 64×）。修复后
    embedding 在锁外并发、锁内只剩纯 CPU 检索。断言不依赖时间阈值：锁外
    化的直接可观测特征是 N 个 embedding 调用全部重叠。
    """
    from types import SimpleNamespace

    import numpy as np

    from agentsociety2.env.router_codegen import CacheCodeProvider

    n = 8
    delay = 0.05
    inflight = 0
    max_inflight = 0

    async def fake_embedding(router, text):
        nonlocal inflight, max_inflight
        inflight += 1
        max_inflight = max(max_inflight, inflight)
        await asyncio.sleep(delay)
        inflight -= 1
        return np.zeros(8, dtype=np.float32)

    monkeypatch.setattr(CacheCodeProvider, "_compute_embedding", fake_embedding)

    router = SimpleNamespace(
        _template_cache_enabled=True,
        _template_cache_lock=asyncio.Lock(),
        _cache_entries=[],
        _cache_faiss_index=None,
        _cache_faiss_entry_indices=[],
        _env_class_type_key="stub_env",
        _template_cache_similarity_threshold=0.9,
    )

    t0 = time.perf_counter()
    results = await asyncio.gather(
        *(
            CacheCodeProvider._lookup(router, f"instruction {i}", {"x": i})
            for i in range(n)
        )
    )
    elapsed = time.perf_counter() - t0

    # 语义不变：空缓存下全部 miss，miss 原因一致。
    assert all(r == (None, "no_similar_entry") for r in results)
    # 锁外化的判据：N 个 embedding 全部重叠（修复前 max_inflight 恒为 1）。
    assert max_inflight == n
    # 时间维度兜底：串行（锁内）需要 ≥ n*delay，并发只需 ~1*delay。
    assert elapsed < delay * n * 0.8


@pytest.mark.asyncio
async def test_exec_print_capture_isolated_between_concurrent_asks() -> None:
    """并发 ask 的 exec print 输出不得串台（回归：sys.stdout 全局替换）。

    旧实现在 exec 前全局替换 sys.stdout；async 生成代码在 await 环境工具期间
    让出事件循环，另一个 ask 会换走全局 stdout，本执行恢复后的 print 写进
    别人的 buffer。现改为向 exec globals 注入每执行独立的 print。
    """
    from types import SimpleNamespace

    from agentsociety2.env.router_codegen import CodeGenRouter, CodeStage

    class _Snoozer:
        async def snooze(self):
            await asyncio.sleep(0.02)

    router = SimpleNamespace(
        ALLOWED_MODULES=CodeGenRouter.ALLOWED_MODULES,
        ALLOWED_BUILTINS=CodeGenRouter.ALLOWED_BUILTINS,
        _modules={"env": _Snoozer()},
    )

    async def run(tag: str) -> dict:
        code = (
            f"print('{tag}-start')\n"
            "r = await modules['env'].snooze()\n"
            f"print('{tag}-end')\n"
            "results['status'] = 'success'\n"
        )
        return await CodeStage._execute_code(router, code, {}, readonly=True)

    res_a, res_b = await asyncio.gather(run("A"), run("B"))
    assert res_a["success"] is True and res_b["success"] is True
    # 各自的输出完整、且不含对方的任何内容（串台判据）。
    assert "A-start" in res_a["output"] and "A-end" in res_a["output"]
    assert "B-start" in res_b["output"] and "B-end" in res_b["output"]
    assert "B-" not in res_a["output"]
    assert "A-" not in res_b["output"]


def test_codegen_validation_requires_final_status_assignment() -> None:
    from agentsociety2.env.router_codegen import CodeGenRouter, CodeStage

    valid = "print('done')\nresults['status'] = 'success'"
    assert CodeStage._validate_code_safety(CodeGenRouter, valid) == (True, "")

    ok, reason = CodeStage._validate_code_safety(CodeGenRouter, "print('done')")
    assert not ok
    assert "Final statement must assign results['status']" in reason

    unknown = "result = 'unknown'\nresults['status'] = result"
    ok, reason = CodeStage._validate_code_safety(CodeGenRouter, unknown)
    assert not ok
    assert "instead of unknown" in reason


@pytest.mark.asyncio
async def test_module_local_locks_faster_than_global_lock() -> None:
    """A/B: global serialize lock (before) vs module-local locks (after)."""
    delay = 0.04
    n_per_module = 4
    lock_a = asyncio.Lock()
    lock_b = asyncio.Lock()
    global_lock = asyncio.Lock()

    async def ask(module_lock: asyncio.Lock, *, use_global: bool) -> None:
        if use_global:
            async with global_lock, module_lock:
                await asyncio.sleep(delay)
        else:
            async with module_lock:
                await asyncio.sleep(delay)

    async def run_batch(*, use_global: bool) -> float:
        t0 = time.perf_counter()
        await asyncio.gather(
            *(ask(lock_a, use_global=use_global) for _ in range(n_per_module)),
            *(ask(lock_b, use_global=use_global) for _ in range(n_per_module)),
        )
        return time.perf_counter() - t0

    before_s = await run_batch(use_global=True)
    after_s = await run_batch(use_global=False)
    assert before_s >= delay * (n_per_module * 2) * 0.85
    assert after_s <= before_s * 0.75
    assert after_s < delay * (n_per_module + 1.5)


def test_read_log_tail_ab_bytes_and_time(tmp_path: Path) -> None:
    """A/B: full read vs tail — bytes transferred and wall time."""
    log_path = tmp_path / "output.log"
    line = ("x" * 200) + "\n"
    with log_path.open("w", encoding="utf-8") as fh:
        for i in range(12_000):
            fh.write(f"{i:06d}:{line}")

    full_bytes = log_path.stat().st_size
    t0 = time.perf_counter()
    full_text = log_path.read_text(encoding="utf-8")
    before_ms = (time.perf_counter() - t0) * 1000
    before_bytes = len(full_text.encode("utf-8"))

    t0 = time.perf_counter()
    tail = read_log_tail(log_path, tail=500)
    after_ms = (time.perf_counter() - t0) * 1000
    after_bytes = len(tail.encode("utf-8"))

    assert after_bytes < before_bytes * 0.08
    assert after_ms < before_ms * 2.0 or after_ms < 50.0
    assert tail.splitlines()[-1].startswith("011999:")
    assert before_bytes == full_bytes or abs(before_bytes - full_bytes) < 8


def test_world_description_persists_in_agent_json(tmp_path: Path) -> None:
    agent = PersonAgent()
    agent._id = 1
    agent._name = "alice"
    agent._profile = {"name": "alice"}
    agent._config = {}
    agent._world_description = "A quiet riverside town."
    agent._bind_workspace(tmp_path)
    agent._setup_skill_runtime(agent_id=1)

    data = agent.build_agent_json(tick=3, t=datetime(2026, 1, 1, 12, 0, 0))
    assert data["world_description"] == "A quiet riverside town."
    assert "world_description" not in agent.build_prompt_agent_view(
        tick=3, t=datetime(2026, 1, 1, 12, 0, 0)
    )

    (tmp_path / "AGENT.json").write_text(json.dumps(data), encoding="utf-8")
    meta = json.loads((tmp_path / "AGENT.json").read_text(encoding="utf-8"))
    assert str(meta.get("world_description") or "") == "A quiet riverside town."


def test_rate_limit_retry_seconds_parses_provider_hint() -> None:
    from agentsociety2.config.llm_dispatcher import rate_limit_retry_seconds

    assert (
        rate_limit_retry_seconds(
            Exception("Try again in 60 seconds. Passed model=x"),
            1.0,
        )
        == 60.0
    )
    assert rate_limit_retry_seconds(Exception("no hint"), 1.5) == 1.5
