"""Persisted activation survives every step's warm or cold workspace restore."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agentsociety2.agent import PersonAgent
from agentsociety2.agent.base import skill_registry
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


def test_initial_manifest_uses_the_persisted_skill_schema(tmp_path):
    ws = create(tmp_path)
    meta = json.loads((ws / "AGENT.json").read_text())
    assert meta["skills"]["activated"] == []
    assert meta["skills"]["default_activated"] == [GUIDANCE]


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
