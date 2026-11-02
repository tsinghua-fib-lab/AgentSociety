"""AgentSociety 无状态 resume 测试（无 Ray / 无 LLM）。

覆盖 ``to_workspace``（写 SOCIETY.json 并委托 env router）、``from_workspace``
（从 run_dir 重建 society），以及经 in-process RouterBase stub 的 env 恢复端到端往返。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agentsociety2.contrib.env.prisoners_dilemma import PrisonersDilemmaEnv
from agentsociety2.env.router_base import RouterBase
from agentsociety2.society.society import AgentSociety


class _StubRouter(RouterBase):
    """用于 society-resume 测试的最小 RouterBase。"""

    async def ask(
        self,
        ctx: dict,
        instruction: str,
        readonly: bool = False,
        template_mode: bool = False,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ):
        return ctx, ""


def _stub_router(env_modules):
    return _StubRouter(
        env_modules=env_modules,
        llm_clients_spec={"coder": object(), "default": object()},
    )


# ---------------------------------------------------------------------------
# to_workspace / from_workspace 机制
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_write_society_json_writes_immutable_full_snapshot(
    tmp_path: Path,
) -> None:
    """``_write_society_json`` 写一次不可变全量（含 agent_specs + steps_hash）。"""
    society = AgentSociety(
        agent_specs=[{"id": 1, "profile": {}, "config": {}}],
        agent_class_name="PersonAgent",
        env_router=AsyncMock(),
        start_t=datetime(2025, 1, 1),
        run_dir=tmp_path,
        env_module_types=["prisoners_dilemma"],
        env_kwargs={"prisoners_dilemma": {"payoff_cc": 3}},
    )
    society._steps_hash = "abc123"
    society._write_society_json()

    data = json.loads((tmp_path / "SOCIETY.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 1
    assert data["agent_class_name"] == "PersonAgent"
    assert data["agent_specs"] == [{"id": 1, "profile": {}, "config": {}}]
    assert data["env_module_types"] == ["prisoners_dilemma"]
    assert data["env_kwargs"] == {"prisoners_dilemma": {"payoff_cc": 3}}
    assert data["steps_hash"] == "abc123"
    # 标量不在此文件（拆到 SOCIETY_STEP.json）。
    assert "current_time" not in data
    assert "step_count" not in data


@pytest.mark.asyncio
async def test_to_workspace_writes_step_scalars_and_delegates(
    tmp_path: Path,
) -> None:
    """``to_workspace`` 每步只写 SOCIETY_STEP.json 标量，并委托 env router。"""
    env_router = AsyncMock()
    env_router.to_workspaces = AsyncMock(return_value=None)

    society = AgentSociety(
        agent_specs=[],
        agent_class_name="PersonAgent",
        env_router=env_router,
        start_t=datetime(2025, 1, 1),
        run_dir=tmp_path,
        env_module_types=["prisoners_dilemma"],
        env_kwargs={"prisoners_dilemma": {"payoff_cc": 3}},
    )
    society._step_count = 3
    society._completed_step_count = 2

    await society.to_workspace(tick=100)  # tick 现在被忽略（兼容旧签名）

    env_router.to_workspaces.assert_awaited_once()
    step = json.loads((tmp_path / "SOCIETY_STEP.json").read_text(encoding="utf-8"))
    assert step["step_count"] == 3
    assert step["completed_step_count"] == 2
    assert step["current_time"] == datetime(2025, 1, 1).isoformat()
    assert step["terminated"] is False
    assert "agent_specs" not in step  # 大字段不每步重写


@pytest.mark.asyncio
async def test_to_workspace_env_failure_blocks_progress_commit(tmp_path: Path) -> None:
    """env 落盘失败必须上报，不能生成虚假的总进度检查点。"""
    env_router = AsyncMock()
    env_router.to_workspaces = AsyncMock(side_effect=RuntimeError("boom"))

    society = AgentSociety(
        agent_specs=[],
        agent_class_name="PersonAgent",
        env_router=env_router,
        start_t=datetime(2025, 1, 1),
        run_dir=tmp_path,
    )
    with pytest.raises(RuntimeError, match="boom"):
        await society.to_workspace(tick=1)
    assert not (tmp_path / "SOCIETY_STEP.json").exists()


@pytest.mark.asyncio
async def test_to_workspace_noop_without_run_dir() -> None:
    env_router = AsyncMock()
    society = AgentSociety(
        agent_specs=[],
        agent_class_name="PersonAgent",
        env_router=env_router,
        start_t=datetime(2025, 1, 1),
        run_dir=None,
    )
    await society.to_workspace(tick=1)
    env_router.to_workspaces.assert_not_awaited()


def _write_checkpoint(
    run_dir: Path,
    *,
    schema_version: int = 1,
    step_count: int = 7,
    completed_step_count: int = 0,
    current_time: str = "2025-01-01T02:00:00",
    steps_hash: str | None = "h",
) -> None:
    """写一份合法的 SOCIETY.json + SOCIETY_STEP.json checkpoint。"""
    (run_dir / "SOCIETY.json").write_text(
        json.dumps(
            {
                "schema_version": schema_version,
                "agent_class_name": "PersonAgent",
                "agent_specs": [{"id": 1, "profile": {"name": "A"}, "config": {}}],
                "env_module_types": ["prisoners_dilemma"],
                "env_kwargs": {"prisoners_dilemma": {"payoff_cc": 3}},
                "batch_size": 128,
                "steps_hash": steps_hash,
            }
        ),
        encoding="utf-8",
    )
    (run_dir / "SOCIETY_STEP.json").write_text(
        json.dumps(
            {
                "current_time": current_time,
                "step_count": step_count,
                "completed_step_count": completed_step_count,
                "terminated": False,
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_from_workspace_restores_state(tmp_path: Path) -> None:
    _write_checkpoint(tmp_path, step_count=7, completed_step_count=3)

    society = await AgentSociety.from_workspace(tmp_path, env_router=AsyncMock())
    assert society.step_count == 7
    assert society._completed_step_count == 3
    assert society.current_time == datetime(2025, 1, 1, 2, 0, 0)
    assert society._env_module_types == ["prisoners_dilemma"]
    assert society._env_kwargs == {"prisoners_dilemma": {"payoff_cc": 3}}
    assert society._steps_hash == "h"
    assert society._agents_created is True
    assert society._agent_profiles_persisted is True
    assert society._society_json_written is True  # init 不会覆盖 SOCIETY.json


@pytest.mark.asyncio
async def test_from_workspace_missing_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        await AgentSociety.from_workspace(tmp_path, env_router=AsyncMock())


@pytest.mark.asyncio
async def test_from_workspace_rejects_bad_schema_version(tmp_path: Path) -> None:
    _write_checkpoint(tmp_path, schema_version=99)
    with pytest.raises(ValueError, match="schema_version"):
        await AgentSociety.from_workspace(tmp_path, env_router=AsyncMock())


@pytest.mark.asyncio
async def test_from_workspace_rejects_corrupt_json(tmp_path: Path) -> None:
    (tmp_path / "SOCIETY.json").write_text("{ truncated", encoding="utf-8")
    with pytest.raises(ValueError, match="corrupt"):
        await AgentSociety.from_workspace(tmp_path, env_router=AsyncMock())


@pytest.mark.asyncio
async def test_from_workspace_falls_back_when_no_step_file(tmp_path: Path) -> None:
    """旧布局：只有 SOCIETY.json（含标量），无 SOCIETY_STEP.json —— 仍能 resume。"""
    (tmp_path / "SOCIETY.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "agent_class_name": "PersonAgent",
                "agent_specs": [],
                "env_module_types": [],
                "env_kwargs": {},
                "batch_size": 64,
                "steps_hash": None,
                "current_time": "2025-01-01T00:00:00",
                "step_count": 5,
            }
        ),
        encoding="utf-8",
    )
    society = await AgentSociety.from_workspace(tmp_path, env_router=AsyncMock())
    assert society.step_count == 5
    assert society._completed_step_count == 0


# ---------------------------------------------------------------------------
# 端到端 env resume（走空 society 的 step 路径，无 Ray / 无 LLM）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_society_env_resume_end_to_end(tmp_path: Path) -> None:
    root = tmp_path / "env"
    module_type = "prisoners_dilemma"
    start = datetime(2025, 1, 1)

    # 阶段 1：跑 2 步并持久化。
    env1 = PrisonersDilemmaEnv()
    router1 = _stub_router([env1])
    router1.run_dir = tmp_path
    router1.bind_env_workspaces(root, [module_type])
    await router1.init(start)

    society1 = AgentSociety(
        agent_specs=[],
        agent_class_name="PersonAgent",
        env_router=router1,
        start_t=start,
        run_dir=tmp_path,
        env_module_types=[module_type],
        env_kwargs={},
    )
    # 模拟 init 写一次不可变 SOCIETY.json（测试绕开 init 以免启动 Ray/LLM）。
    society1._write_society_json()
    society1._society_json_written = True
    # 空 society 的 step 路径：推进 env + 时钟 + 落盘，无 Ray task。
    await env1.submit_action("Agent A", "Yes")
    await society1.step(tick=3600)  # 执行回合
    await society1.step(tick=3600)  # 无 pending -> 不产生新回合

    assert society1.step_count == 2
    assert env1.round_number == 1
    assert len(env1.round_history) == 1
    assert (tmp_path / "SOCIETY.json").is_file()
    assert (tmp_path / "SOCIETY_STEP.json").is_file()
    assert (
        root / module_type / "state" / "ENV_STATE.json"
    ).is_file()

    # 阶段 2：用全新对象 resume。
    env2 = PrisonersDilemmaEnv()
    router2 = _stub_router([env2])
    router2.run_dir = tmp_path
    router2.bind_env_workspaces(root, [module_type])

    society2 = await AgentSociety.from_workspace(tmp_path, env_router=router2)
    assert society2.step_count == 2
    assert society2.current_time == start + timedelta(seconds=7200)
    assert society2._env_module_types == [module_type]

    # society.init() 会调 env_router.init() 恢复 env；这里绕开 society.init
    # 直接调 router.init 以免启动 Ray/LLM。
    await router2.init(society2.current_time)
    assert env2.round_number == 1
    assert len(env2.round_history) == 1
    assert env2._step_counter == 2
