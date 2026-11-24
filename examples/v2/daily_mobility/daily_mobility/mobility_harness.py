"""Post-step mobility harness: all env mutations via env_router.ask (ask_env)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

from agentsociety2.logger import get_logger

from daily_mobility.mobility_snapshot import (
    clamp_poi_search_radius,
    commute_target_aoi,
    env_ask_move_person,
    env_ask_move_to_nearby_poi,
    env_ask_observe,
    env_ask_sync_trip,
    env_commute_home_after_meal,
    parse_person_from_observe,
    should_commute_home_after_meal,
)

logger = get_logger()


async def run_mobility_harness(
    agent: Any,
    t: datetime,
    *,
    tick: int,
    run_mobility_skill: Callable[[], Awaitable[None]],
) -> None:
    if agent._env is None:
        return

    observe_ctx = await env_ask_observe(agent._env, agent.id)
    state = parse_person_from_observe(observe_ctx, agent.id)
    if state is None:
        logger.warning(
            "Agent %s: mobility harness observe missing person state", agent.id
        )
        return

    hour = t.hour + t.minute / 60.0
    current_meal_window = agent._meal_window_for_hour(hour)

    if await agent._enforce_pending_questionnaire_meal(
        t, current_meal_window=current_meal_window
    ):
        return

    status = str(state.get("status") or "idle").lower()
    from daily_mobility.intentions import (
        HUNGER_BREAKFAST_THRESHOLD,
        HUNGER_DRIVE_THRESHOLD,
        HUNGER_MEAL_THRESHOLD,
        WORK_EVENING_LEAVE_HOUR,
        meals_completed_today,
    )

    meal_state_pre = agent._read_workspace_json("state/meal_state.json") or {}
    needs_raw_pre = agent._read_workspace_json("state/needs.json") or {}
    needs_pre = needs_raw_pre.get("needs", needs_raw_pre)
    hunger_pre = float(needs_pre.get("hunger", 0.0))
    home_aoi_bf = state.get("home_aoi")
    current_aoi_bf = state.get("aoi_id")
    if (
        7 <= hour < 9.5
        and status != "moving"
        and home_aoi_bf is not None
        and current_aoi_bf == home_aoi_bf
        and "breakfast" not in meals_completed_today(meal_state_pre, day=t.date())
        and hunger_pre >= HUNGER_DRIVE_THRESHOLD
    ):
        meal_state_pre["pending_meal_enforce"] = "breakfast"
        agent._write_meal_state(meal_state_pre)
        if await agent._enforce_pending_questionnaire_meal(
            t, current_meal_window="breakfast"
        ):
            return

    status = str(state.get("status") or "idle").lower()
    current_aoi_pre = state.get("aoi_id")
    work_aoi_pre = state.get("work_aoi")
    if (
        current_meal_window == "dinner"
        and work_aoi_pre is not None
        and current_aoi_pre == work_aoi_pre
        and status != "moving"
    ):
        from daily_mobility.intentions import (
            HUNGER_MEAL_THRESHOLD,
            meals_completed_today,
        )

        meal_state = agent._read_workspace_json("state/meal_state.json") or {}
        needs_raw = agent._read_workspace_json("state/needs.json") or {}
        needs_map = needs_raw.get("needs", needs_raw)
        hunger = float(needs_map.get("hunger", 0.0))
        if hunger >= HUNGER_MEAL_THRESHOLD and "dinner" not in meals_completed_today(
            meal_state, day=t.date()
        ):
            meal_state["pending_meal_enforce"] = "dinner"
            agent._write_meal_state(meal_state)

    current_aoi = state.get("aoi_id")
    home_aoi = state.get("home_aoi")
    work_aoi = state.get("work_aoi")
    poi_id = state.get("poi_id")
    poi_category = state.get("poi_category")

    if status == "moving":
        from daily_mobility.intentions import (
            HUNGER_MEAL_THRESHOLD,
            meals_completed_today,
        )

        meal_state = agent._read_workspace_json("state/meal_state.json") or {}
        needs_raw = agent._read_workspace_json("state/needs.json") or {}
        needs_map = needs_raw.get("needs", needs_raw)
        hunger = float(needs_map.get("hunger", 0.0))
        if (
            current_meal_window in {"breakfast", "lunch", "dinner"}
            and current_meal_window
            not in meals_completed_today(meal_state, day=t.date())
            and hunger
            >= (
                HUNGER_BREAKFAST_THRESHOLD
                if current_meal_window == "breakfast"
                else HUNGER_MEAL_THRESHOLD
            )
        ):
            meal_state["pending_meal_enforce"] = current_meal_window
            agent._write_meal_state(meal_state)
            if await agent._enforce_pending_questionnaire_meal(
                t, current_meal_window=current_meal_window
            ):
                return
        await env_ask_sync_trip(agent._env, agent.id, tick_sec=tick)
        return

    meal_state = agent._read_workspace_json("state/meal_state.json") or {}
    if meal_state.get("post_meal_return_pending"):
        target_kind = str(meal_state.get("post_meal_return_target") or "home").lower()
        return_target = (
            work_aoi if target_kind == "work" and work_aoi is not None else home_aoi
        )
        if (
            return_target is not None
            and current_aoi is not None
            and current_aoi != return_target
            and not (
                target_kind == "work"
                and home_aoi is not None
                and work_aoi is not None
                and home_aoi == work_aoi
            )
        ):
            move_result = await env_ask_move_person(
                agent._env,
                agent.id,
                int(return_target),
                mode="driving",
            )
            if isinstance(move_result, dict) and move_result.get("status") == "success":
                meal_state["post_meal_return_pending"] = False
                meal_state["post_meal_return_done_time"] = t.isoformat()
                agent._write_meal_state(meal_state)
            agent._invalidate_all_workspace_cache()
            agent._bump_workspace_state_version()
            logger.info(
                "Agent %s: post-meal return target=%s ok=%s",
                agent.id,
                return_target,
                move_result,
            )
            return
        meal_state["post_meal_return_pending"] = False
        meal_state["post_meal_return_done_time"] = t.isoformat()
        agent._write_meal_state(meal_state)

    await run_mobility_skill()

    plan = agent._read_workspace_json("state/mobility_plan.json")
    target: int | None = None
    plan_target: int | None = None
    if plan and plan.get("should_move"):
        raw_target = plan.get("target_aoi_id") or plan.get("target_id")
        if isinstance(raw_target, int):
            plan_target = raw_target
            target = raw_target
    elif plan is None:
        target = commute_target_aoi(
            hour=hour,
            home_aoi=home_aoi,
            work_aoi=work_aoi,
            current_aoi=current_aoi,
            status=status,
        )

    restore = agent._read_workspace_json("_restore_intention.json") or {}
    restore_goal = str(restore.get("goal", "")).lower()
    meal_state = agent._read_workspace_json("state/meal_state.json") or {}
    pending_meal = meal_state.get("pending_meal_enforce")

    if (
        home_aoi is not None
        and work_aoi is not None
        and current_aoi == work_aoi
        and hour >= WORK_EVENING_LEAVE_HOUR
        and status != "moving"
        and restore_goal in ("home activity", "sleep")
        and not pending_meal
    ):
        target = home_aoi

    meal_categories = (
        plan.get("recommended_categories") if isinstance(plan, dict) else None
    )
    if (
        plan
        and plan.get("should_move")
        and isinstance(meal_categories, list)
        and "restaurant" in meal_categories
        and not isinstance(plan_target, int)
        and (pending_meal or "eating out" in restore_goal)
    ):
        meal_window = (
            pending_meal
            if pending_meal in {"breakfast", "lunch", "dinner"}
            else (
                restore.get("meal_window")
                if restore.get("meal_window") in {"breakfast", "lunch", "dinner"}
                else current_meal_window
            )
        )
        radius = clamp_poi_search_radius(
            int(plan.get("radius", 1200) or 1200),
            meal_window=(
                meal_window if meal_window in {"breakfast", "lunch", "dinner"} else None
            ),
        )
        meal_mode = "driving" if radius >= 1000 else "walking"
        meal_result = await env_ask_move_to_nearby_poi(
            agent._env,
            agent.id,
            "restaurant",
            radius=radius,
            mode=meal_mode,
            meal_window=(
                meal_window if meal_window in {"breakfast", "lunch", "dinner"} else None
            ),
        )
        meal_ok = isinstance(meal_result, dict) and meal_result.get("status") not in {
            "fail",
            "failed",
            "error",
        }
        if meal_ok and isinstance(meal_result, dict) and meal_window:
            agent._record_meal_state(
                t=t,
                meal_result=meal_result,
                meal_window=meal_window,
            )
            meal_state = agent._read_workspace_json("state/meal_state.json") or {}
            meal_state["pending_meal_enforce"] = None
            agent._write_meal_state(meal_state)
            observe_ctx = await env_ask_observe(agent._env, agent.id)
            after_meal = parse_person_from_observe(observe_ctx, agent.id) or {}
            commute = await env_commute_home_after_meal(
                agent._env,
                agent.id,
                home_aoi=home_aoi,
                work_aoi=work_aoi,
                current_aoi=after_meal.get("aoi_id"),
                poi_id=after_meal.get("poi_id"),
                status=str(after_meal.get("status") or status),
            )
            if commute is not None:
                logger.info(
                    "Agent %s: post-meal commute home ok=%s",
                    agent.id,
                    commute.get("status"),
                )
        agent._invalidate_all_workspace_cache()
        agent._bump_workspace_state_version()
        logger.info(
            "Agent %s: harness meal move ok=%s result=%s",
            agent.id,
            meal_ok,
            meal_result,
        )
        return

    completed_meals = meals_completed_today(meal_state, day=t.date())
    if (
        target is None
        and should_commute_home_after_meal(
            home_aoi=home_aoi,
            work_aoi=work_aoi,
            current_aoi=current_aoi,
            poi_id=poi_id if isinstance(poi_id, int) else None,
            status=status,
        )
        and (
            (current_meal_window and current_meal_window in completed_meals)
            or hour >= WORK_EVENING_LEAVE_HOUR
            or restore_goal in ("home activity", "sleep")
        )
    ):
        target = home_aoi

    if (
        target is None
        and agent._is_food_poi_category(poi_category)
        and current_aoi in {home_aoi, work_aoi}
        and current_meal_window is None
    ):
        target = current_aoi

    if target is None:
        return
    if current_aoi == target and not agent._is_food_poi_category(poi_category):
        return

    mode = "driving"
    if plan and isinstance(plan.get("mode"), str) and plan["mode"].strip():
        mode = plan["mode"].strip()
    elif isinstance(plan, dict) and isinstance(plan.get("radius"), (int, float)) and plan["radius"] < 1000:
        mode = "walking"

    move_result = await env_ask_move_person(agent._env, agent.id, target, mode=mode)
    move_ok = isinstance(move_result, dict) and move_result.get("status") not in {
        "fail",
        "failed",
        "error",
    }
    agent._invalidate_all_workspace_cache()
    agent._bump_workspace_state_version()
    logger.info(
        "Agent %s: harness move target=%s mode=%s ok=%s plan_should_move=%s",
        agent.id,
        target,
        mode,
        move_ok,
        bool(plan and plan.get("should_move")),
    )
