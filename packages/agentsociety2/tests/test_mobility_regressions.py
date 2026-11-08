"""Mobility optimization preserves observations, routing and resumed trips."""

import json
from datetime import datetime, timedelta
from types import SimpleNamespace

import numpy as np
import pytest
import shapely
from aiohttp import web
from pycityproto.city.routing.v2.routing_pb2 import (
    ROUTE_TYPE_DRIVING,
    ROUTE_TYPE_WALKING,
)
from shapely.geometry import LineString, Point

from agentsociety2.contrib.env.mobility_space.environment import (
    MobilityPerson,
    MobilitySpace,
    Position,
    Target,
)
from agentsociety2.contrib.env.mobility_space.map import Map
from agentsociety2.contrib.env.mobility_space.utils import const


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


async def test_summary_preserves_overlap_cap_tie_order_and_missing_names(monkeypatch):
    monkeypatch.setattr(
        const,
        "POI_CATG_DICT",
        {
            "food": ["cafe", "restaurant"],
            "leisure": ["cafe"],
            "missing": ["unused"],
            "unexpanded": [],
        },
    )
    candidates = [
        ({"category": ["cafe", "cafe", "restaurant"], "name": "first"}, 1.04),
        ({"category": ["restaurant"], "name": "tie"}, 1.04),
    ]
    candidates += [({"category": ["restaurant"]}, float(i)) for i in range(2, 70)]
    candidates += [({"category": ["unexpanded"]}, 100.0)]
    calls = []

    def query(**kwargs):
        calls.append(kwargs)
        return candidates

    env = object.__new__(MobilitySpace)
    env._map = SimpleNamespace(
        poi_cate={
            "food": ["cafe", "restaurant"],
            "leisure": ["cafe"],
            "missing": ["unused"],
        },
        query_pois=query,
    )
    env._persons = {
        1: MobilityPerson(
            id=1, position=Position(kind="aoi", aoi_id=1, xy=(1, 2), lnglat=(1, 2))
        )
    }
    result = await env.get_person(1)
    assert [r.model_dump() for r in result.nearby_pois] == [
        {
            "category": "food",
            "count": 50,
            "nearest_name": "first",
            "nearest_distance": 1.0,
        },
        {
            "category": "leisure",
            "count": 1,
            "nearest_name": "first",
            "nearest_distance": 1.0,
        },
        {
            "category": "unexpanded",
            "count": 1,
            "nearest_name": "unknown",
            "nearest_distance": 100.0,
        },
    ]
    assert calls == [{"center": (1.0, 2.0), "radius": 3000}]
    # Moving people continue to omit nearby summaries and do no spatial query.
    env._persons[1].status = "moving"
    result = await env.get_person(1)
    assert result.nearby_pois is None and len(calls) == 1


@pytest.mark.parametrize(
    "radius,category,limit",
    [(None, None, None), (2, "cafe", 1), (0, None, 0), (5, "missing", -1)],
)
def test_vectorized_query_preserves_candidates_distances_ties_and_slices(
    radius, category, limit
):
    instance = object.__new__(Map)
    instance._poi_list = [
        {
            "id": i,
            "category": ["cafe"] if i % 2 else ["park"],
            "shapely_xy": Point(x, y),
        }
        for i, (x, y) in enumerate([(1, 0), (-1, 0), (2, 0), (0, 2), (4, 4), (8, 0)])
    ]
    instance._poi_tree = shapely.STRtree([p["shapely_xy"] for p in instance._poi_list])
    center = Point(0, 0)
    candidates = (
        instance._poi_list
        if radius is None
        else [
            instance._poi_list[i]
            for i in instance._poi_tree.query(center.buffer(radius))
        ]
    )
    expected = sorted(
        [
            (poi, center.distance(poi["shapely_xy"]))
            for poi in candidates
            if category is None or category in poi["category"]
        ],
        key=lambda row: row[1],
    )
    if limit is not None:
        expected = expected[:limit]
    assert instance.query_pois((0, 0), radius, category, limit) == expected


@pytest.mark.parametrize("routing_eta", [600, 7200])
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


@pytest.mark.parametrize(
    "mode,route_type",
    [("walking", ROUTE_TYPE_WALKING), ("driving", ROUTE_TYPE_DRIVING)],
)
async def test_routes_reuse_connection_and_close_session(mode, route_type):
    transports = []
    requested = []

    async def route(request):
        transports.append(request.transport)
        requested.append((await request.json())["type"])
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
    origin = Position(kind="aoi", aoi_id=1, xy=(0, 0), lnglat=(0, 0))
    env._persons = {1: MobilityPerson(id=1, position=origin)}
    env._map = SimpleNamespace(
        get_aoi=lambda aid: {"id": aid},
        estimate_route_time=lambda *args: 10,
        _route_to_xys=lambda *args: np.array([[0, 0], [10, 0]]),
        projector=lambda x, y, inverse: (x, y),
    )
    try:
        for _ in range(2):
            env._persons[1].status = "idle"
            env._persons[1].position = origin
            assert (await env.move_to(1, 2, mode))["status"] == "success"
        assert len(transports) == 2 and transports[0] is transports[1]
        assert requested == [route_type, route_type]
        session = env._routing_session
        await env.close()
        assert session.closed and env._routing_session is None
        await env.close()
    finally:
        await env.close()
        await runner.cleanup()
