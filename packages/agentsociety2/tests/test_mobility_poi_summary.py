"""Observe queries the spatial index once while preserving category semantics."""

from types import SimpleNamespace

from agentsociety2.contrib.env.mobility_space.environment import (
    MobilityPerson,
    MobilitySpace,
    Position,
)
from agentsociety2.contrib.env.mobility_space.utils import const


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
