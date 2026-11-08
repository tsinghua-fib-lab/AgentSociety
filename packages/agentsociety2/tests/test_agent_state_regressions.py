"""Skill restore and semaphore resizing preserve active state."""

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentsociety2.agent import PersonAgent
from agentsociety2.agent.base import skill_registry
from agentsociety2.config.llm_dispatcher import _AdjustableSemaphore
from agentsociety2.contrib.env.mobility_space.environment import MobilitySpace

MOBILITY = "env:MobilitySpace@mobility"
GUIDANCE = "built-in@daily-guidance"


def services(tmp_path):
    import inspect

    skill_root = Path(inspect.getfile(MobilitySpace)).parent / "agent_skills"
    env = SimpleNamespace(
        run_dir=tmp_path,
        env_modules=[],
        env_skill_dirs=[("MobilitySpace", str(skill_root))],
    )
    return SimpleNamespace(
        env=env,
        llm=SimpleNamespace(default=SimpleNamespace(model_name="owned-test")),
        trace=None,
        replay=None,
    )


def create(tmp_path):
    ws = tmp_path / "agents/agent_0001"
    PersonAgent.create(
        ws,
        {"id": 1, "name": "Ari"},
        {
            "enable_memory": False,
            "enable_todo_list": False,
            "default_activated_skill_ids": [GUIDANCE],
        },
    )
    return ws


@pytest.mark.parametrize("cold_worker", [False, True])
async def test_activated_env_skill_survives_repeated_real_workspace_restore(
    tmp_path, monkeypatch, cold_worker
):
    monkeypatch.setattr(skill_registry, "_registry", None)
    ws = create(tmp_path)
    proxy = services(tmp_path)
    agent = await PersonAgent.from_workspace(ws, proxy)
    assert agent.skill_runtime.activate_skill("mobility")[0]
    expected = {GUIDANCE, MOBILITY}
    assert agent.skill_runtime.activated_skill_ids() == expected
    for _ in range(3):
        await agent.to_workspace(ws)
        if cold_worker:
            monkeypatch.setattr(skill_registry, "_registry", None)
        agent = await PersonAgent.from_workspace(ws, proxy)
        assert agent.skill_runtime.activated_skill_ids() == expected


async def test_restore_respects_newly_disabled_and_explicitly_deactivated_skills(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(skill_registry, "_registry", None)
    ws = create(tmp_path)
    proxy = services(tmp_path)
    agent = await PersonAgent.from_workspace(ws, proxy)
    agent.skill_runtime.activate_skill("mobility")
    await agent.to_workspace(ws)
    config = json.loads((ws / "config.json").read_text())
    config["disabled_skill_ids"] = [MOBILITY]
    (ws / "config.json").write_text(json.dumps(config))
    monkeypatch.setattr(skill_registry, "_registry", None)
    restored = await PersonAgent.from_workspace(ws, proxy)
    assert MOBILITY not in restored.skill_runtime.visible_skill_ids()
    assert restored.skill_runtime.activated_skill_ids() == {GUIDANCE}
    # Re-enable visibility; a saved non-active skill remains non-active.
    config["disabled_skill_ids"] = []
    (ws / "config.json").write_text(json.dumps(config))
    await restored.to_workspace(ws)
    monkeypatch.setattr(skill_registry, "_registry", None)
    restored = await PersonAgent.from_workspace(ws, proxy)
    assert MOBILITY in restored.skill_runtime.visible_skill_ids()
    assert restored.skill_runtime.activated_skill_ids() == {GUIDANCE}


async def test_shrink_below_inflight_debt_is_repaid():
    """缩容低于在途数:先偿还债务,最终仅留下新容量的可用许可。"""
    sem = _AdjustableSemaphore(8)
    holders = [asyncio.create_task(sem.acquire()) for _ in range(8)]
    await asyncio.gather(*holders)
    await sem.set_capacity(2)
    # 8 个旧许可归还,只有 2 个计入
    for _ in range(8):
        await sem.release()
    assert sem._available == 2
    # 再 release 也不超(钳上界)
    await sem.release()
    assert sem._available == 2


async def test_shrink_retains_inflight_debt_under_waiting_demand():
    sem = _AdjustableSemaphore(4)
    for _ in range(4):
        await sem.acquire()
    await sem.set_capacity(1)
    waiter = asyncio.create_task(sem.acquire())
    try:
        for _ in range(3):
            await sem.release()
            await asyncio.sleep(0)
            assert not waiter.done(), (
                "new request started while capacity still occupied"
            )
        await sem.release()
        await asyncio.wait_for(waiter, timeout=1)
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)
