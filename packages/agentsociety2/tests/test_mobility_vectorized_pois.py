"""Vectorized POI distances preserve the original spatial query contract."""

import pytest
import shapely
from shapely.geometry import Point

from agentsociety2.contrib.env.mobility_space.map import Map


@pytest.mark.parametrize("radius", [None, 0, 2, 5])
@pytest.mark.parametrize("category", [None, "cafe", "missing"])
@pytest.mark.parametrize("limit", [None, 0, 1, -1])
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
