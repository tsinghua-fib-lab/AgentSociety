"""Routing requests reuse a local connection and release it on environment close."""

from types import SimpleNamespace

import numpy as np
import pytest
from aiohttp import web
from pycityproto.city.routing.v2.routing_pb2 import (
    ROUTE_TYPE_DRIVING,
    ROUTE_TYPE_WALKING,
)

from agentsociety2.contrib.env.mobility_space.environment import (
    MobilityPerson,
    MobilitySpace,
    Position,
)


async def test_routes_reuse_connection_and_close_session():
    transports = []

    async def route(request):
        transports.append(request.transport)
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
            assert (await env.move_to(1, 2))["status"] == "success"
        assert len(transports) == 2 and transports[0] is transports[1]
        session = env._routing_session
        await env.close()
        assert session.closed and env._routing_session is None
        await env.close()
    finally:
        await env.close()
        await runner.cleanup()


@pytest.mark.parametrize(
    "mode, expected",
    [
        ("driving", ROUTE_TYPE_DRIVING),
        ("walking", ROUTE_TYPE_WALKING),
        ("cycling", None),
    ],
)
async def test_move_to_requests_matching_route_type(mode, expected):
    requested = []

    async def route(request):
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
    env._persons = {
        1: MobilityPerson(
            id=1, position=Position(kind="aoi", aoi_id=1, xy=(0, 0), lnglat=(0, 0))
        )
    }
    env._map = SimpleNamespace(
        get_aoi=lambda aid: {"id": aid},
        estimate_route_time=lambda *args: 10,
        _route_to_xys=lambda *args: np.array([[0, 0], [10, 0]]),
        projector=lambda x, y, inverse: (x, y),
    )
    try:
        if expected is None:
            with pytest.raises(ValueError, match="Unsupported movement mode"):
                await env.move_to(1, 2, mode)
            assert requested == []
            assert env._persons[1].status == "idle"
            assert env._persons[1].target is None
        else:
            result = await env.move_to(1, 2, mode)
            assert result["status"] == "success"
            assert requested == [expected]
            assert env._persons[1].target.mode == mode
    finally:
        await env.close()
        await runner.cleanup()
