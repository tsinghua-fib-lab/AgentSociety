"""Reported trip time agrees with the unchanged physical advancement speed."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
from aiohttp import web
from shapely.geometry import Point

from agentsociety2.contrib.env.mobility_space.environment import (
    MobilityPerson,
    MobilitySpace,
    Position,
)


@pytest.mark.parametrize("routing_eta", [600, 1800, 7200, 0, -1])
async def test_eta_matches_actual_arrival_and_checkpoint(routing_eta, tmp_path):
    async def route(request):
        await request.json()
        return web.json_response({"journeys": []})

    app = web.Application()
    app.router.add_post("/city.routing.v2.RoutingService/GetRoute", route)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    env = object.__new__(MobilitySpace)
    env._routing_proc = None
    env._routing_session = None
    env._server_addr = f"127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    env._export_trajectory_data = lambda: None
    env._workspace_root = None
    env._replay_writer = None
    env._step_counter = 0
    env._person_trajectories = {1: []}
    env._person_visited_aois = {1: set()}
    env._persons = {
        1: MobilityPerson(
            id=1, position=Position(kind="aoi", aoi_id=1, xy=(0, 0), lnglat=(0, 0))
        )
    }
    env._map = SimpleNamespace(
        get_aoi=lambda aid: {"id": aid, "shapely_xy": Point(2000, 0)},
        estimate_route_time=lambda *args: routing_eta,
        _route_to_xys=lambda *args: np.array([[0, 0], [2000, 0]]),
        projector=lambda x, y, inverse: (x, y),
    )
    try:
        response = await env.move_to(1, 2)
        target = env._persons[1].target
        # Preserve the pre-existing travel speed and half-hour cap exactly.
        expected_speed = max(2000 / routing_eta if routing_eta > 0 else 1, 2000 / 1800)
        assert target.path_v == expected_speed
        expected_seconds = 2000 / expected_speed
        assert response["eta"] == pytest.approx(expected_seconds)
        await env.to_workspace(tmp_path)
        assert env._persons[1].target.path_v == expected_speed
        started = datetime(2018, 6, 13, 8)
        await env.step(
            int(expected_seconds) - 1, started + timedelta(seconds=expected_seconds - 1)
        )
        assert env._persons[1].status == "moving"
        await env.step(1, started + timedelta(seconds=expected_seconds))
        assert env._persons[1].status == "idle"
        assert env._persons[1].position.aoi_id == 2
    finally:
        await env.close()
        await runner.cleanup()


@pytest.mark.parametrize("path_length", [8663.881655592892, 22180.989919881477])
async def test_real_route_lengths_arrive_after_sixty_thirty_second_steps(path_length):
    from shapely.geometry import LineString

    from agentsociety2.contrib.env.mobility_space.environment import Target

    env = object.__new__(MobilitySpace)
    env._workspace_root = None
    env._replay_writer = None
    env._step_counter = 0
    env._person_trajectories = {1: []}
    env._person_visited_aois = {1: set()}
    env._map = SimpleNamespace(
        projector=lambda x, y, inverse: (x, y),
        get_aoi=lambda aid: {"id": aid, "shapely_xy": Point(path_length, 0)},
    )
    goal = Position(kind="aoi", aoi_id=2, xy=(path_length, 0), lnglat=(path_length, 0))
    env._persons = {
        1: MobilityPerson(
            id=1,
            status="moving",
            position=Position(kind="lane", xy=(0, 0), lnglat=(0, 0)),
            target=Target(
                position=goal,
                mode="driving",
                path=LineString([(0, 0), (path_length, 0)]),
                path_s=0,
                path_v=path_length / 1800,
            ),
        )
    }
    started = datetime(2018, 6, 13, 8)
    for elapsed in range(30, 1801, 30):
        await env.step(30, started + timedelta(seconds=elapsed))
        if elapsed < 1800:
            assert env._persons[1].status == "moving"
    assert env._persons[1].status == "idle"
    assert env._persons[1].position.aoi_id == 2
    assert env._persons[1].position.xy == (path_length, 0)
