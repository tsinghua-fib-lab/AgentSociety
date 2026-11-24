import re

import pytest
from daily_mobility.mobility_snapshot import (
    clamp_poi_search_radius,
    env_ask_move_to_nearby_poi,
    env_ask_sync_trip,
    parse_person_from_observe,
    should_commute_home_after_meal,
)


def _find_ask(asks: list[tuple[str, dict, bool]], substring: str) -> str:
    for instruction, _, _ in asks:
        if substring in instruction:
            return instruction
    raise AssertionError(f"no ask containing {substring!r}")


class _AskRouter:
    def __init__(self, mobility):
        self._mobility = mobility
        self.asks: list[tuple[str, dict, bool]] = []

    async def ask(self, ctx, instruction, readonly=False, template_mode=False):
        self.asks.append((instruction, dict(ctx), readonly))
        await self._mobility.run_ask(instruction, ctx)
        lower = instruction.lower()
        if readonly and "<observe>" in lower:
            person = await self._mobility.get_person(ctx["id"])
            return {
                "status": "success",
                "observations": {"MobilitySpace.get_person": person},
            }, "ok"
        if "find_nearby_pois" in lower or (
            readonly and "results['response']" in instruction
        ):
            return {
                "status": "success",
                "observations": {
                    "MobilitySpace.find_nearby_pois": {
                        "pois": self._mobility.nearby_pois,
                    }
                },
            }, "ok"
        if "move person" in lower and "poi" in lower:
            m = re.search(r"poi\s+(\d+)", lower)
            if m:
                poi_id = int(m.group(1))
                await self._mobility.move_to(ctx["id"], poi_id, "walking")
            return {"status": "success"}, "ok"
        return {"status": "success"}, "ok"


class MobilitySpace:
    def __init__(self):
        self.nearby_pois = [
            {
                "id": 700000001,
                "name": "near cafe",
                "category": "cafe",
                "distance": 400,
                "aoi_id": 99,
            },
            {
                "id": 700000002,
                "name": "mid restaurant",
                "category": "restaurant",
                "distance": 900,
                "aoi_id": 99,
            },
        ]

        self.moves = []
        self.finished = False
        self.status = "idle"
        self.current_poi_id = 700000001

    async def run_ask(self, instruction: str, ctx: dict):
        person_id = ctx["id"]
        lower = instruction.lower()
        if "finish_trip" in lower:
            await self.finish_trip(person_id)

    async def get_person(self, person_id):
        return {
            "id": person_id,
            "status": self.status,
            "position": {
                "aoi_id": 1,
                "poi_id": self.current_poi_id,
                "lnglat": [116.0, 39.9],
            },
            "target": None,
            "home_aoi": 1,
            "work_aoi": 2,
        }

    async def move_to(self, person_id, target_id, mode):
        self.moves.append((person_id, target_id, mode))
        if target_id >= 700000000:
            self.current_poi_id = target_id
        self.status = "moving"
        return {"status": "success"}

    async def finish_trip(self, person_id):
        self.finished = True
        self.status = "idle"
        return {"status": "ok", "finished": True}


@pytest.mark.asyncio
async def test_env_ask_sync_trip_uses_router_ask():
    mobility = MobilitySpace()
    mobility.status = "moving"
    router = _AskRouter(mobility)

    result = await env_ask_sync_trip(router, 1, tick_sec=1800)

    assert any("finish_trip" in a[0].lower() for a in router.asks)
    assert mobility.finished is True
    assert result["status"] == "success"


@pytest.mark.parametrize(
    ("radius", "meal_window", "expected"),
    [
        (5000, None, 1500),
        (5000, "breakfast", 900),
        (5000, "lunch", 1200),
        (5000, "dinner", 1500),
        (300, None, 300),
        (50, "lunch", 200),
    ],
)
def test_clamp_poi_search_radius(radius, meal_window, expected):
    assert clamp_poi_search_radius(radius, meal_window=meal_window) == expected


def test_should_commute_home_after_meal():
    assert should_commute_home_after_meal(
        home_aoi=1,
        work_aoi=2,
        current_aoi=99,
        poi_id=700000001,
        status="idle",
    )
    assert not should_commute_home_after_meal(
        home_aoi=1,
        work_aoi=2,
        current_aoi=1,
        poi_id=700000001,
        status="idle",
    )
    assert not should_commute_home_after_meal(
        home_aoi=1,
        work_aoi=1,
        current_aoi=1,
        poi_id=700000001,
        status="idle",
    )


@pytest.mark.asyncio
async def test_env_ask_move_to_nearby_poi_uses_gravity_then_move():
    mobility = MobilitySpace()
    router = _AskRouter(mobility)

    result = await env_ask_move_to_nearby_poi(router, 1, "restaurant", radius=5000)

    search_instr = _find_ask(router.asks, "find_nearby_pois")
    assert "1500" in search_instr
    move_instr = _find_ask(router.asks, "Move person 1 to POI")
    assert "walking" in move_instr
    assert result["status"] == "success"
    assert result["selection"] == "gravity_model"
    assert isinstance(result["poi_id"], int)
    assert mobility.moves[-1][1] == result["poi_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("meal_window", "expected_radius"),
    [
        ("breakfast", 900),
        ("lunch", 1200),
        ("dinner", 1500),
    ],
)
async def test_env_ask_move_to_nearby_poi_meal_window_radius(
    meal_window, expected_radius
):
    mobility = MobilitySpace()
    router = _AskRouter(mobility)

    await env_ask_move_to_nearby_poi(
        router,
        1,
        "restaurant",
        radius=5000,
        meal_window=meal_window,
    )

    search_instr = _find_ask(router.asks, "find_nearby_pois")
    assert f"radius={expected_radius}" in search_instr


def test_parse_person_from_observe():
    ctx = {
        "observations": {
            "MobilitySpace.get_person": {
                "id": 1,
                "status": "idle",
                "position": {
                    "aoi_id": 10,
                    "poi_id": 700000001,
                    "poi_category": "restaurant",
                    "poi_name": "mid restaurant",
                    "lnglat": [116.1, 39.8],
                },
                "home_aoi": 10,
                "work_aoi": 20,
            }
        }
    }
    state = parse_person_from_observe(ctx, 1)
    assert state is not None
    assert state["aoi_id"] == 10
    assert state["poi_category"] == "restaurant"
    assert state["home_aoi"] == 10
    assert state["poi_category"] == "restaurant"
    assert state["poi_name"] == "mid restaurant"
    assert state["lng"] == 116.1
