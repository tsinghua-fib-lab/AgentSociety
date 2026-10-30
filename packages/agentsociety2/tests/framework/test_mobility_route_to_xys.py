"""Tests for MobilityMap._route_to_xys driving vs walking segment handling."""


import numpy as np
import pytest
from google.protobuf.json_format import ParseDict
from pycityproto.city.routing.v2 import routing_pb2  # type: ignore[import-untyped]
from pycityproto.city.routing.v2 import routing_service_pb2 as routing_service  # type: ignore[import-untyped]
from shapely.geometry import LineString  # type: ignore[import-untyped]

from agentsociety2.contrib.env.mobility_space.map import Map


@pytest.fixture
def map_with_geometry():
    m = Map.__new__(Map)
    m.aois = {
        1: {"shapely_xy": LineString([(0, 0), (10, 0)]).buffer(5)},
        2: {"shapely_xy": LineString([(100, 0), (110, 0)]).buffer(5)},
    }
    road_line = LineString([(0, 0), (50, 0), (100, 0)])
    m.roads = {10: {"shapely_xy": road_line}}
    m.lanes = {
        100: {
            "id": 100,
            "type": 1,
            "shapely_xy": road_line,
            "length": road_line.length,
        }
    }

    def walking_geo(segment):
        return 100, road_line

    def driving_geo(road_id):
        return 100, road_line

    def lane_s(position, lane_id):
        return 0.0

    m._get_walking_geo = walking_geo
    m._get_driving_geo = driving_geo
    m._get_lane_s = lane_s
    return m


def test_route_to_xys_driving_uses_road_ids_not_walking_route(map_with_geometry):
    route_req = ParseDict(
        {
            "type": routing_pb2.ROUTE_TYPE_DRIVING,
            "start": {"aoi_position": {"aoi_id": 1}},
            "end": {"aoi_position": {"aoi_id": 2}},
        },
        routing_service.GetRouteRequest(),
    )
    route_res = ParseDict(
        {
            "journeys": [
                {
                    "type": routing_pb2.JOURNEY_TYPE_DRIVING,
                    "driving": {"road_ids": [10, 10], "eta": 600},
                    "walking": {"route": [], "eta": 0},
                }
            ]
        },
        routing_service.GetRouteResponse(),
    )
    xys = map_with_geometry._route_to_xys(route_req, route_res)
    assert xys.shape[0] >= 2
    assert np.isfinite(xys).all()


def test_route_to_xys_walking_empty_route_skipped(map_with_geometry):
    route_req = ParseDict(
        {
            "type": routing_pb2.ROUTE_TYPE_WALKING,
            "start": {"aoi_position": {"aoi_id": 1}},
            "end": {"aoi_position": {"aoi_id": 2}},
        },
        routing_service.GetRouteRequest(),
    )
    route_res = ParseDict(
        {
            "journeys": [
                {
                    "type": routing_pb2.JOURNEY_TYPE_WALKING,
                    "walking": {"route": [], "eta": 0},
                }
            ]
        },
        routing_service.GetRouteResponse(),
    )
    xys = map_with_geometry._route_to_xys(route_req, route_res)
    assert xys.shape[0] >= 2
