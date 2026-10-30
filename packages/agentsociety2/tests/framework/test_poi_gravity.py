import random

from agentsociety2.contrib.env.mobility_space.utils.poi_gravity import (
    filter_out_of_anchor_aoi_pois,
    gravity_model,
    gravity_model_candidates,
    normalize_poi_candidates,
    parse_nearby_pois_from_ctx,
    select_poi_by_gravity,
)


def test_gravity_model_candidates_matches_legacy_two_stage():
    random.seed(42)
    pois = [
        {"poi_id": 1, "name": "near", "category": "restaurant", "distance": 300},
        {"poi_id": 2, "name": "mid", "category": "restaurant", "distance": 800},
        {"poi_id": 3, "name": "far", "category": "restaurant", "distance": 1500},
    ]
    candidates = gravity_model_candidates(pois, sample_size=50)
    assert candidates
    assert abs(sum(weight for _, weight in candidates) - 1.0) < 1e-9
    picked = {poi["poi_id"] for poi, _ in candidates}
    assert picked.issubset({1, 2, 3})


def test_normalize_poi_candidates_accepts_legacy_tuple_shape():
    raw = [({"name": "Legacy", "id": 42}, 650.0)]
    out = normalize_poi_candidates(raw)
    assert out == [
        {
            "poi_id": 42,
            "name": "Legacy",
            "category": "",
            "distance": 650.0,
        }
    ]


def test_parse_nearby_pois_from_ctx_response_object():
    class Poi:
        def __init__(self):
            self.id = 700010
            self.name = "Test"
            self.category = "restaurant"
            self.distance = 500.0

    class Resp:
        def __init__(self):
            self.pois = [Poi()]

    ctx = {"status": "success", "response": Resp()}
    pois = parse_nearby_pois_from_ctx(ctx)
    assert len(pois) == 1
    assert pois[0]["poi_id"] == 700010


def test_gravity_model_prefers_closer_when_density_equal():
    random.seed(0)
    pois = [
        {"poi_id": 1, "name": "near", "category": "restaurant", "distance": 300},
        {"poi_id": 2, "name": "far", "category": "restaurant", "distance": 1200},
    ]
    picks = [gravity_model(pois)["poi_id"] for _ in range(30)]
    assert picks.count(1) > picks.count(2)


def test_normalize_poi_candidates_accepts_env_shape():
    raw = [
        {"id": 700000001, "name": "A", "category": "cafe", "distance": 500},
    ]
    out = normalize_poi_candidates(raw)
    assert out == [
        {
            "poi_id": 700000001,
            "name": "A",
            "category": "cafe",
            "distance": 500.0,
        }
    ]


def test_parse_nearby_pois_from_ctx_observations():
    ctx = {
        "status": "success",
        "observations": {
            "MobilitySpace.find_nearby_pois": {
                "pois": [
                    {
                        "id": 700000002,
                        "name": "B",
                        "category": "restaurant",
                        "distance": 700,
                    }
                ]
            }
        },
    }
    pois = parse_nearby_pois_from_ctx(ctx)
    assert len(pois) == 1
    assert pois[0]["poi_id"] == 700000002


def test_select_poi_by_gravity_from_ctx():
    ctx = {
        "pois": [
            {"id": 700000003, "name": "C", "category": "restaurant", "distance": 400},
            {"id": 700000004, "name": "D", "category": "restaurant", "distance": 1400},
        ]
    }
    selected = select_poi_by_gravity(ctx)
    assert selected is not None
    assert selected["poi_id"] in {700000003, 700000004}


def test_filter_out_of_anchor_aoi_pois():
    candidates = [
        {
            "poi_id": 1,
            "name": "home cafe",
            "category": "cafe",
            "distance": 200,
            "aoi_id": 10,
        },
        {
            "poi_id": 2,
            "name": "outside",
            "category": "restaurant",
            "distance": 800,
            "aoi_id": 99,
        },
    ]
    filtered = filter_out_of_anchor_aoi_pois(
        candidates,
        home_aoi=10,
        work_aoi=20,
    )
    assert filtered == [candidates[1]]


def test_select_poi_by_gravity_excludes_home_work_aoi():
    ctx = {
        "pois": [
            {
                "id": 1,
                "name": "home restaurant",
                "category": "restaurant",
                "distance": 300,
                "aoi_id": 10,
            },
            {
                "id": 2,
                "name": "outside restaurant",
                "category": "restaurant",
                "distance": 900,
                "aoi_id": 99,
            },
        ]
    }
    selected = select_poi_by_gravity(
        ctx,
        home_aoi=10,
        work_aoi=20,
        exclude_anchor_aois=True,
    )
    assert selected is not None
    assert selected["poi_id"] == 2


def test_normalize_poi_candidates_includes_aoi_id():
    raw = [
        {
            "id": 700000005,
            "name": "E",
            "category": "restaurant",
            "distance": 600,
            "aoi_id": 55,
        }
    ]
    out = normalize_poi_candidates(raw)
    assert out[0]["aoi_id"] == 55
