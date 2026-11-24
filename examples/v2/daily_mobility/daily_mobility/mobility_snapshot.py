"""Mobility snapshots and env-router-only interaction helpers."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agentsociety2.contrib.env.mobility_space.utils.poi_gravity import (
    poi_travel_mode,
    select_poi_by_gravity,
)
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from agentsociety2.env.router_base import RouterBase

TRIP_FINISH_RATIO = 0.85
DEFAULT_BENCHMARK_TICK_SEC = 1800
POI_START_ID = 700000000

DEFAULT_NEARBY_POI_SEARCH_RADIUS_M = 1200
MAX_NEARBY_POI_SEARCH_RADIUS_M = 1500
MEAL_SEARCH_RADIUS_M = {
    "breakfast": 900,
    "lunch": 1200,
    "dinner": 1500,
}


def clamp_poi_search_radius(
    radius: float,
    *,
    meal_window: str | None = None,
) -> float:
    cap = MEAL_SEARCH_RADIUS_M.get(meal_window, MAX_NEARBY_POI_SEARCH_RADIUS_M)
    return min(max(float(radius), 200.0), float(cap))


class AgentMobilitySnapshot(BaseModel):
    agent_id: int
    status: str
    aoi_id: int | None = None
    poi_id: int | None = None
    poi_name: str | None = None
    poi_category: str | None = None
    home_aoi: int | None = None
    work_aoi: int | None = None
    lng: float | None = None
    lat: float | None = None
    target_aoi_id: int | None = None
    location_category: str = Field(
        ...,
        description="home | work | home_work | other | in_transit",
    )


def classify_location(
    *,
    aoi_id: int | None,
    home_aoi: int | None,
    work_aoi: int | None,
    status: str,
) -> str:
    if status == "moving":
        return "in_transit"
    if home_aoi is not None and home_aoi == work_aoi:
        return "home_work"
    if aoi_id is None:
        return "other"
    if aoi_id == home_aoi:
        return "home"
    if aoi_id == work_aoi:
        return "work"
    return "other"


def _agent_ctx(person_id: int) -> dict[str, int]:
    return {"id": person_id, "agent_id": person_id, "person_id": person_id}


def _env_ask_status_ok(ctx: Any) -> bool:
    if not isinstance(ctx, dict):
        return False
    status = str(ctx.get("status", "")).lower()
    if status in {"success", "in_progress", "ok", "partial"}:
        return True
    observations = ctx.get("observations")
    if isinstance(observations, dict):
        obs_status = str(observations.get("status", "")).lower()
        if obs_status in {"success", "in_progress", "ok", "partial"}:
            return True
    return False


def verify_move_effect(
    *,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    target_id: int | None,
) -> dict[str, Any]:
    """Verify that a requested move produced a live environment state change."""
    if after is None:
        return {"ok": False, "reason": "post-move observe did not return person state"}

    status = str(after.get("status") or "idle").lower()
    after_aoi = after.get("aoi_id")
    after_poi = after.get("poi_id")
    target_aoi = after.get("target_aoi_id")

    if target_id is None:
        before_aoi = before.get("aoi_id") if isinstance(before, dict) else None
        before_status = (
            str(before.get("status") or "idle").lower()
            if isinstance(before, dict)
            else "idle"
        )
        changed = (
            status == "moving" or status != before_status or after_aoi != before_aoi
        )
        return {
            "ok": changed,
            "reason": (
                "move changed live state" if changed else "move left person unchanged"
            ),
            "after_status": status,
            "after_aoi": after_aoi,
            "target_aoi": target_aoi,
        }

    is_poi_target = target_id >= POI_START_ID
    reached = after_poi == target_id if is_poi_target else after_aoi == target_id
    en_route = status == "moving" and (
        target_aoi == target_id or (is_poi_target and target_aoi is not None)
    )
    if is_poi_target and status == "moving":
        before_status = (
            str(before.get("status") or "idle").lower()
            if isinstance(before, dict)
            else "idle"
        )
        before_poi = before.get("poi_id") if isinstance(before, dict) else None
        if before_status != "moving" or after_poi != before_poi:
            en_route = True
    ok = bool(reached or en_route)
    return {
        "ok": ok,
        "reason": (
            "move verified by live state"
            if ok
            else f"post-move state does not match target {target_id}"
        ),
        "after_status": status,
        "after_aoi": after_aoi,
        "after_poi": after_poi,
        "target_aoi": target_aoi,
        "requested_target": target_id,
    }


async def _env_ask(
    env_router: RouterBase,
    person_id: int,
    instruction: str,
    *,
    readonly: bool = False,
) -> tuple[dict, str]:
    ctx = _agent_ctx(person_id)
    updated, answer = await env_router.ask(
        ctx=ctx,
        instruction=instruction.strip(),
        readonly=readonly,
        template_mode=True,
    )
    if isinstance(updated, dict):
        return updated, answer
    return ctx, answer


async def env_ask_observe(env_router: RouterBase, person_id: int) -> dict:
    ctx, _answer = await _env_ask(env_router, person_id, "<observe>", readonly=True)
    return ctx


def parse_person_from_observe(ctx: dict, person_id: int) -> dict[str, Any] | None:
    observations = ctx.get("observations")
    if not isinstance(observations, dict):
        return None
    raw = observations.get("MobilitySpace.get_person")
    if raw is None:
        for key, val in observations.items():
            if key.endswith(".get_person"):
                raw = val
                break
    if raw is None:
        return None
    if hasattr(raw, "model_dump"):
        data = raw.model_dump()
    elif isinstance(raw, dict):
        data = raw
    elif hasattr(raw, "id"):
        pos = getattr(raw, "position", None)
        data = {
            "id": getattr(raw, "id", person_id),
            "status": getattr(raw, "status", "idle"),
            "position": pos,
            "home_aoi": getattr(raw, "home_aoi", None),
            "work_aoi": getattr(raw, "work_aoi", None),
            "target": getattr(raw, "target", None),
        }
    else:
        return None
    if int(data.get("id", person_id)) != int(person_id):
        return None
    pos = data.get("position") or {}
    if hasattr(pos, "model_dump"):
        pos = pos.model_dump()
    poi_id = pos.get("poi_id") if isinstance(pos, dict) else None
    poi_category = None
    poi_name = None
    if isinstance(pos, dict):
        poi_category = pos.get("poi_category") or pos.get("category")
        poi_name = pos.get("poi_name") or pos.get("name")
    poi_category = poi_category or data.get("poi_category")
    poi_name = poi_name or data.get("poi_name")
    target = data.get("target")
    target_aoi_id = None
    if target is not None:
        if hasattr(target, "model_dump"):
            target = target.model_dump()
        if isinstance(target, dict):
            tpos = target.get("position") or {}
            if hasattr(tpos, "model_dump"):
                tpos = tpos.model_dump()
            if isinstance(tpos, dict):
                target_aoi_id = tpos.get("aoi_id")
    lnglat = pos.get("lnglat") if isinstance(pos, dict) else None
    lng = lat = None
    if isinstance(lnglat, (list, tuple)) and len(lnglat) >= 2:
        lng, lat = float(lnglat[0]), float(lnglat[1])
    return {
        "id": person_id,
        "status": str(data.get("status") or "idle").lower(),
        "aoi_id": pos.get("aoi_id") if isinstance(pos, dict) else None,
        "poi_id": poi_id,
        "poi_name": poi_name,
        "poi_category": poi_category,
        "home_aoi": data.get("home_aoi"),
        "work_aoi": data.get("work_aoi"),
        "target_aoi_id": target_aoi_id,
        "lng": lng,
        "lat": lat,
    }


def commute_target_aoi(
    *,
    hour: float,
    home_aoi: int | None,
    work_aoi: int | None,
    current_aoi: int | None,
    status: str,
) -> int | None:
    if status == "moving" or home_aoi is None or work_aoi is None:
        return None
    if home_aoi == work_aoi:
        return None
    from daily_mobility.intentions import (
        WORK_BAND_START_HOUR,
        WORK_COMMUTE_END_HOUR,
    )

    if WORK_BAND_START_HOUR <= hour < WORK_COMMUTE_END_HOUR and current_aoi != work_aoi:
        return work_aoi
    if (
        hour >= WORK_COMMUTE_END_HOUR
        and current_aoi is not None
        and current_aoi != home_aoi
    ):
        return home_aoi
    return None


def should_commute_home_after_meal(
    *,
    home_aoi: int | None,
    work_aoi: int | None,
    current_aoi: int | None,
    poi_id: int | None,
    status: str,
) -> bool:
    if (
        status == "moving"
        or home_aoi is None
        or work_aoi is None
        or home_aoi == work_aoi
    ):
        return False
    if current_aoi is None or current_aoi == home_aoi:
        return False
    if poi_id is None and current_aoi == work_aoi:
        return False
    return poi_id is not None or current_aoi not in {home_aoi, work_aoi}


async def env_commute_home_after_meal(
    env_router: RouterBase,
    person_id: int,
    *,
    home_aoi: int | None,
    work_aoi: int | None,
    current_aoi: int | None,
    poi_id: int | None,
    status: str,
) -> dict | None:
    if not should_commute_home_after_meal(
        home_aoi=home_aoi,
        work_aoi=work_aoi,
        current_aoi=current_aoi,
        poi_id=poi_id,
        status=status,
    ):
        return None
    return await env_ask_move_person(
        env_router,
        person_id,
        int(home_aoi),
        mode="driving",
    )


async def ensure_questionnaire_work_commute(
    env_router: RouterBase,
    agent_ids: list[int],
    *,
    sim_time: datetime,
    tick_sec: int = DEFAULT_BENCHMARK_TICK_SEC,
) -> None:
    from daily_mobility.intentions import (
        WORK_BAND_START_HOUR,
        WORK_COMMUTE_END_HOUR,
    )

    hour = sim_time.hour + sim_time.minute / 60.0
    if not (WORK_BAND_START_HOUR <= hour < WORK_COMMUTE_END_HOUR):
        return

    for person_id in agent_ids:
        observe_ctx = await env_ask_observe(env_router, person_id)
        state = parse_person_from_observe(observe_ctx, person_id)
        if state is None:
            continue
        status = str(state.get("status") or "idle").lower()
        home_aoi = state.get("home_aoi")
        work_aoi = state.get("work_aoi")
        current_aoi = state.get("aoi_id")
        if (
            status != "idle"
            or not isinstance(home_aoi, int)
            or not isinstance(work_aoi, int)
            or home_aoi == work_aoi
            or current_aoi != home_aoi
        ):
            continue
        await env_ask_move_person(env_router, person_id, work_aoi, mode="driving")
        observe_ctx = await env_ask_observe(env_router, person_id)
        state = parse_person_from_observe(observe_ctx, person_id)
        if state is not None and str(state.get("status")).lower() == "moving":
            await env_ask_sync_trip(env_router, person_id, tick_sec=tick_sec)


async def env_ask_move_person(
    env_router: RouterBase,
    person_id: int,
    target_aoi_id: int,
    *,
    mode: str = "driving",
) -> dict:
    before_ctx = await env_ask_observe(env_router, person_id)
    before = parse_person_from_observe(before_ctx, person_id)
    ctx, answer = await _env_ask(
        env_router,
        person_id,
        f"Move person {person_id} to AOI {target_aoi_id} using {mode}",
    )
    ok = _env_ask_status_ok(ctx)
    observe_ctx = await env_ask_observe(env_router, person_id)
    after = parse_person_from_observe(observe_ctx, person_id)
    verification = verify_move_effect(
        before=before,
        after=after,
        target_id=target_aoi_id,
    )
    ok = ok and bool(verification.get("ok"))
    return {
        "status": "success" if ok else "fail",
        "person_id": person_id,
        "destination_id": target_aoi_id,
        "mode": mode,
        "answer": answer,
        "verification": verification,
    }


async def env_ask_stop_trip(env_router: RouterBase, person_id: int) -> dict:
    ctx, answer = await _env_ask(
        env_router,
        person_id,
        f"Stop the current trip for person {person_id}",
    )
    ok = _env_ask_status_ok(ctx)
    return {"status": "success" if ok else "fail", "answer": answer}


async def env_ask_finish_trip(env_router: RouterBase, person_id: int) -> dict:
    ctx, answer = await _env_ask(
        env_router,
        person_id,
        f"Finish the current trip for person {person_id}",
    )
    ok = _env_ask_status_ok(ctx)
    return {"status": "success" if ok else "fail", "answer": answer}


async def env_ask_sync_trip(
    env_router: RouterBase,
    person_id: int,
    *,
    tick_sec: int = DEFAULT_BENCHMARK_TICK_SEC,
) -> dict:
    ratio_pct = int(TRIP_FINISH_RATIO * 100)
    ctx, answer = await _env_ask(
        env_router,
        person_id,
        (
            f"For person {person_id}: if status is moving and trip progress is at least "
            f"{ratio_pct}% complete, or the trip should complete within {tick_sec}s of "
            f"simulation time at current speed, call finish_trip; otherwise do nothing."
        ),
        readonly=False,
    )
    ok = _env_ask_status_ok(ctx)
    return {"status": "success" if ok else "fail", "answer": answer}


async def env_ask_find_nearby_pois(
    env_router: RouterBase,
    person_id: int,
    category: str,
    *,
    radius: float,
    home_aoi: int | None = None,
    work_aoi: int | None = None,
    exclude_anchor_aois: bool = False,
) -> dict:
    ctx, answer = await _env_ask(
        env_router,
        person_id,
        (
            f"For person {person_id}: call get_person({person_id}), then "
            f"find_nearby_pois at that person's current xy with category='{category}' "
            f"and radius={int(radius)}. "
            "Store the FindNearbyPoisResponse in results['response'] and set "
            "results['status']='success'. Do not call move_to."
        ),
        readonly=True,
    )
    selected = select_poi_by_gravity(
        ctx,
        home_aoi=home_aoi,
        work_aoi=work_aoi,
        exclude_anchor_aois=exclude_anchor_aois,
    )
    ok = selected is not None
    return {
        "status": "success" if ok else "fail",
        "person_id": person_id,
        "answer": answer,
        "selected_poi": selected,
        "search_ctx": ctx,
    }


async def env_ask_move_to_poi(
    env_router: RouterBase,
    person_id: int,
    poi_id: int,
    *,
    mode: str,
    before: dict[str, Any] | None = None,
) -> dict:
    ctx, answer = await _env_ask(
        env_router,
        person_id,
        f"Move person {person_id} to POI {poi_id} using {mode}",
    )
    ok = _env_ask_status_ok(ctx)
    observe_ctx = await env_ask_observe(env_router, person_id)
    after = parse_person_from_observe(observe_ctx, person_id)
    verification = verify_move_effect(
        before=before,
        after=after,
        target_id=poi_id,
    )
    ok = ok and bool(verification.get("ok"))
    return {
        "status": "success" if ok else "fail",
        "person_id": person_id,
        "poi_id": poi_id,
        "mode": mode,
        "answer": answer,
        "verification": verification,
    }


def _extract_poi_details(ctx: dict, poi_id: int) -> dict[str, Any]:
    observations = ctx.get("observations")
    if not isinstance(observations, dict):
        return {}

    candidates: list[Any] = list(observations.values())
    for value in observations.values():
        if isinstance(value, dict):
            for key in ("poi", "result", "response"):
                if key in value:
                    candidates.append(value[key])
            for key in ("pois", "items", "results"):
                nested = value.get(key)
                if isinstance(nested, list):
                    candidates.extend(nested)

    for raw in candidates:
        if hasattr(raw, "model_dump"):
            raw = raw.model_dump()
        if not isinstance(raw, dict):
            continue
        raw_id = raw.get("poi_id", raw.get("id"))
        if raw_id is not None:
            try:
                if int(raw_id) != int(poi_id):
                    continue
            except (TypeError, ValueError):
                continue
        category = raw.get("category") or raw.get("poi_category")
        name = raw.get("name") or raw.get("poi_name")
        if category or name:
            return {"poi_category": category, "poi_name": name}
    return {}


async def env_ask_get_poi_details(
    env_router: RouterBase,
    person_id: int,
    poi_id: int,
) -> dict[str, Any]:
    ctx, _answer = await _env_ask(
        env_router,
        person_id,
        (
            f"For person {person_id}: call get_poi({poi_id}) and return its "
            "category and name. Do not move the person."
        ),
        readonly=True,
    )
    return _extract_poi_details(ctx, poi_id)


async def _env_ask_move_to_nearby_poi_combined(
    env_router: RouterBase,
    person_id: int,
    category: str,
    *,
    radius: float,
    mode: str,
    before: dict[str, Any] | None,
) -> dict:
    ctx, answer = await _env_ask(
        env_router,
        person_id,
        (
            f"Find a nearby {category} within {int(radius)}m of person {person_id} "
            f"and move there using {mode}"
        ),
    )
    if not _env_ask_status_ok(ctx):
        return {
            "status": "fail",
            "reason": answer or "env ask_env move failed",
            "person_id": person_id,
            "selection": "ask_env_combined",
        }

    observe_ctx = await env_ask_observe(env_router, person_id)
    state = parse_person_from_observe(observe_ctx, person_id)
    if state is None:
        return {
            "status": "fail",
            "person_id": person_id,
            "answer": answer,
            "selection": "ask_env_combined",
            "verification": verify_move_effect(
                before=before, after=None, target_id=None
            ),
        }

    poi_id = state.get("poi_id")
    target_id = poi_id if isinstance(poi_id, int) else state.get("target_aoi_id")
    verification = verify_move_effect(
        before=before,
        after=state,
        target_id=target_id if isinstance(target_id, int) else None,
    )
    ok = bool(verification.get("ok"))
    return {
        "status": "success" if ok else "fail",
        "person_id": person_id,
        "poi_id": poi_id,
        "poi_category": state.get("poi_category"),
        "poi_name": state.get("poi_name"),
        "answer": answer,
        "selection": "ask_env_combined",
        "verification": verification,
    }


async def env_ask_move_to_nearby_poi(
    env_router: RouterBase,
    person_id: int,
    category: str,
    *,
    radius: float = DEFAULT_NEARBY_POI_SEARCH_RADIUS_M,
    mode: str | None = None,
    meal_window: str | None = None,
) -> dict:
    radius = clamp_poi_search_radius(radius, meal_window=meal_window)
    before_ctx = await env_ask_observe(env_router, person_id)
    before = parse_person_from_observe(before_ctx, person_id)
    if before is not None and str(before.get("status")).lower() == "moving":
        await env_ask_sync_trip(env_router, person_id)
        before_ctx = await env_ask_observe(env_router, person_id)
        before = parse_person_from_observe(before_ctx, person_id)

    search = await env_ask_find_nearby_pois(
        env_router,
        person_id,
        category,
        radius=radius,
        home_aoi=before.get("home_aoi") if isinstance(before, dict) else None,
        work_aoi=before.get("work_aoi") if isinstance(before, dict) else None,
        exclude_anchor_aois=True,
    )
    selected = search.get("selected_poi")
    if not isinstance(selected, dict):
        combined_mode = mode or poi_travel_mode(radius)
        combined = await _env_ask_move_to_nearby_poi_combined(
            env_router,
            person_id,
            category,
            radius=radius,
            mode=combined_mode,
            before=before,
        )
        if combined.get("status") != "success" and combined_mode != "walking":
            combined = await _env_ask_move_to_nearby_poi_combined(
                env_router,
                person_id,
                category,
                radius=radius,
                mode="walking",
                before=before,
            )
        return combined

    poi_id = selected.get("poi_id")
    if not isinstance(poi_id, int):
        return {
            "status": "fail",
            "reason": "gravity model selected POI without id",
            "person_id": person_id,
            "search": search,
        }

    distance = float(selected.get("distance", radius))
    chosen_mode = mode or poi_travel_mode(distance)
    move = await env_ask_move_to_poi(
        env_router,
        person_id,
        poi_id,
        mode=chosen_mode,
        before=before,
    )
    if move.get("status") != "success" and chosen_mode != "walking":
        move = await env_ask_move_to_poi(
            env_router,
            person_id,
            poi_id,
            mode="walking",
            before=before,
        )

    move_status = move.get("status")
    return {
        "status": move_status if move_status in {"success", "fail"} else "fail",
        "person_id": person_id,
        "poi_id": poi_id,
        "poi_name": selected.get("name"),
        "poi_category": selected.get("category"),
        "distance": distance,
        "mode": move.get("mode", chosen_mode),
        "selection": "gravity_model",
        "search": search,
        "move": move,
        "verification": move.get("verification"),
    }


async def resolve_moving_trips_for_agents(
    env_router: RouterBase,
    agent_ids: list[int],
    *,
    tick_sec: int = DEFAULT_BENCHMARK_TICK_SEC,
) -> None:
    for agent_id in agent_ids:
        observe_ctx = await env_ask_observe(env_router, agent_id)
        state = parse_person_from_observe(observe_ctx, agent_id)
        if state is None or str(state.get("status")).lower() != "moving":
            continue
        await env_ask_sync_trip(env_router, agent_id, tick_sec=tick_sec)


async def capture_mobility_snapshots(
    env_router: RouterBase,
    agent_ids: list[int],
    *,
    tick_sec: int = DEFAULT_BENCHMARK_TICK_SEC,
) -> list[AgentMobilitySnapshot]:
    await resolve_moving_trips_for_agents(env_router, agent_ids, tick_sec=tick_sec)

    out: list[AgentMobilitySnapshot] = []
    for agent_id in agent_ids:
        try:
            observe_ctx = await env_ask_observe(env_router, agent_id)
            state = parse_person_from_observe(observe_ctx, agent_id)
        except Exception:
            logging.getLogger(__name__).debug("Observation failed for agent %s", agent_id, exc_info=True)
            continue
        if state is None:
            continue
        aoi_id = state.get("aoi_id")
        poi_id = state.get("poi_id")
        poi_name = state.get("poi_name")
        poi_category = state.get("poi_category")
        if isinstance(poi_id, int) and not poi_category:
            try:
                details = await env_ask_get_poi_details(env_router, agent_id, poi_id)
            except Exception:
                logging.getLogger(__name__).debug("POI lookup failed for %s", poi_id, exc_info=True)
                details = {}
            poi_category = details.get("poi_category") or poi_category
            poi_name = details.get("poi_name") or poi_name
        category = classify_location(
            aoi_id=aoi_id,
            home_aoi=state.get("home_aoi"),
            work_aoi=state.get("work_aoi"),
            status=str(state.get("status") or "idle"),
        )
        out.append(
            AgentMobilitySnapshot(
                agent_id=agent_id,
                status=str(state.get("status") or "idle"),
                aoi_id=aoi_id,
                poi_id=poi_id,
                poi_name=poi_name,
                poi_category=poi_category,
                home_aoi=state.get("home_aoi"),
                work_aoi=state.get("work_aoi"),
                lng=state.get("lng"),
                lat=state.get("lat"),
                target_aoi_id=state.get("target_aoi_id"),
                location_category=category,
            )
        )
    return out
