"""在移动途中保存、恢复并继续行走，验证路径与动态状态没有丢失。"""

import json
from datetime import datetime
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Point

from agentsociety2.contrib.env.mobility_space.environment import (
    MobilityPerson,
    MobilitySpace,
    Position,
    Target,
)


def space():
    env = object.__new__(MobilitySpace)
    env._workspace_root = None
    env._persons = {}
    env._person_trajectories = {}
    env._person_visited_aois = {}
    env._step_counter = 3
    env._replay_writer = None
    env._map = SimpleNamespace(
        projector=lambda x, y, inverse: (x, y),
        get_aoi=lambda aid: {"shapely_xy": Point(100, 0)},
    )
    return env


def moving_person():
    destination = Position(kind="aoi", aoi_id=5, xy=(100, 0), lnglat=(100, 0))
    return MobilityPerson(
        id=1,
        status="moving",
        position=Position(kind="lane", xy=(10, 0), lnglat=(10, 0)),
        target=Target(
            position=destination,
            mode="walking",
            path=LineString([(0, 0), (100, 0)]),
            path_s=10,
            path_v=2,
        ),
    )


def test_target_roundtrip_preserves_geometry_and_python_representation():
    person = moving_person()
    restored = MobilityPerson.model_validate_json(person.model_dump_json())
    assert restored.target.path.equals_exact(person.target.path, 0)
    assert restored.target.path_s == 10
    assert restored.target.path_v == 2
    assert isinstance(person.model_dump()["target"]["path"], LineString)


@pytest.mark.asyncio
async def test_resume_mid_trip_matches_uninterrupted_movement(tmp_path):
    original = space()
    original._persons = {1: moving_person()}
    original._person_trajectories = {1: [(0, 0), (10, 0)]}
    original._person_visited_aois = {1: {4}}
    await original.to_workspace(tmp_path)
    state = json.loads((tmp_path / "state/ENV_STATE.json").read_text())
    assert state["persons"]["1"]["target"]["path"] == [[0.0, 0.0], [100.0, 0.0]]
    resumed = space()
    assert await resumed.restore(tmp_path)
    assert resumed._step_counter == 3
    assert resumed._person_trajectories == original._person_trajectories
    assert resumed._person_visited_aois == original._person_visited_aois
    for tick in [2, 45]:
        now = datetime(2018, 6, 13, 8)
        await original.step(tick, now)
        await resumed.step(tick, now)
        assert resumed._persons[1].model_dump(mode="json") == original._persons[
            1
        ].model_dump(mode="json")
        assert resumed._person_trajectories == original._person_trajectories
        assert resumed._person_visited_aois == original._person_visited_aois
    assert resumed._persons[1].status == "idle"
    assert resumed._persons[1].target is None
    assert resumed._persons[1].position.aoi_id == 5
    assert resumed._step_counter == 5


@pytest.mark.asyncio
@pytest.mark.parametrize("restart_after", [1, 47, 48, 95])
async def test_full_day_restart_matches_every_remaining_tick(tmp_path, restart_after):
    """跨午夜的 96 个真实 step；分别在移动中、到达前后及最后一步前恢复。"""
    from datetime import timedelta

    from agentsociety2.society.society import AgentSociety

    def society(env, directory, now, count=0):
        soc = object.__new__(AgentSociety)
        soc._run_dir = directory
        soc._agent_ids = []
        soc._replay_writer = None
        soc._t = now
        soc._step_count = count
        soc._completed_step_count = 0
        soc._should_terminate = False
        soc._env_router = SimpleNamespace(
            set_current_time=lambda t: setattr(env, "t", t),
            step=env.step,
            to_workspaces=lambda: env.to_workspace(directory / "env"),
        )
        return soc

    def state(env):
        return {
            "persons": {
                pid: p.model_dump(mode="json") for pid, p in env._persons.items()
            },
            "trajectory": env._person_trajectories,
            "visited": env._person_visited_aois,
            "steps": env._step_counter,
        }

    started = datetime(2018, 6, 13, 12)
    original = space()
    original._step_counter = 0
    person = moving_person()
    person.target.path_v = 90 / (48 * 900)
    original._persons = {1: person}
    original._person_trajectories = {1: [(10, 0)]}
    original._person_visited_aois = {1: {4}}
    control = society(original, tmp_path / "control", started)
    resumed_env = None
    for index in range(1, 97):
        await control.step(900)
        if index == restart_after:
            resumed_env = space()
            assert await resumed_env.restore(tmp_path / "control/env")
            checkpoint = json.loads(
                (tmp_path / "control/SOCIETY_STEP.json").read_text()
            )
            resumed = society(
                resumed_env,
                tmp_path / "resumed",
                datetime.fromisoformat(checkpoint["current_time"]),
                checkpoint["step_count"],
            )
        elif index > restart_after:
            await resumed.step(900)
            assert state(resumed_env) == state(original)
            assert resumed._t == control._t
            assert resumed._step_count == control._step_count
    assert resumed._t == started + timedelta(days=1)
    assert resumed._step_count == resumed_env._step_counter == 96
    assert resumed_env._persons[1].status == "idle"
    assert resumed_env._persons[1].position.aoi_id == 5


@pytest.mark.asyncio
async def test_failed_serialization_keeps_previous_checkpoint(tmp_path, monkeypatch):
    """后续保存失败时，前一次已落盘的检查点仍可读取。"""
    env = space()
    env._persons = {1: moving_person()}
    await env.to_workspace(tmp_path)
    checkpoint = tmp_path / "state/ENV_STATE.json"
    before = checkpoint.read_bytes()

    def fail(*args, **kwargs):
        raise ValueError("injected serialization failure")

    monkeypatch.setattr(MobilityPerson, "model_dump", fail)
    with pytest.raises(ValueError, match="injected serialization failure"):
        await env.to_workspace(tmp_path)
    assert checkpoint.read_bytes() == before
    restored = space()
    assert await restored.restore(tmp_path)
    assert restored._persons[1].target.path_s == 10
