"""Daily Mobility benchmark intention labels and questionnaire prompts."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Any

INTENTION_CHOICES: tuple[str, ...] = (
    "sleep",
    "home activity",
    "work",
    "shopping",
    "eating out",
    "leisure and entertainment",
    "other",
)

_SLOT_ID_RE = re.compile(r"^daily_mobility_intention_slot_(\d+)$")

HUNGER_MEAL_THRESHOLD = 0.45
HUNGER_BREAKFAST_THRESHOLD = 0.62
HUNGER_DRIVE_THRESHOLD = 0.62
HUNGER_AFTER_BREAKFAST = 0.32
HUNGER_AFTER_LUNCH = 0.18
HUNGER_AFTER_DINNER = 0.16
HUNGER_AFTER_SNACK = 0.48


def _is_food_poi_category(category: str | None) -> bool:
    return bool(
        category
        and category.lower() in {"restaurant", "cafe", "fast_food", "food_court", "bar"}
    )


def hunger_after_meal(meal_window: str | None, hunger_before: float) -> float:
    if meal_window == "breakfast":
        return HUNGER_AFTER_BREAKFAST
    if meal_window == "lunch":
        return HUNGER_AFTER_LUNCH
    if meal_window == "dinner":
        return HUNGER_AFTER_DINNER
    if hunger_before >= 0.55:
        return HUNGER_AFTER_SNACK
    return HUNGER_AFTER_LUNCH


ENERGY_SLEEP_THRESHOLD = 0.34
ENERGY_EXHAUSTED_THRESHOLD = 0.22
STRESS_WIND_DOWN_THRESHOLD = 0.72
BREAKFAST_WINDOW = (7.0, 9.5)
LUNCH_WINDOW = (11.5, 13.5)
DINNER_WINDOW = (17.5, 20.5)
MEAL_WINDOWS = {
    "breakfast": BREAKFAST_WINDOW,
    "lunch": LUNCH_WINDOW,
    "dinner": DINNER_WINDOW,
}


def hour_fraction(sim_time: datetime) -> float:
    return sim_time.hour + sim_time.minute / 60.0


def current_meal_window(hour: float) -> str | None:
    """Named benchmark meal band for a clock hour; None outside standard windows."""
    for name, (start, end) in MEAL_WINDOWS.items():
        if start <= hour < end:
            return name
    return None


def in_standard_meal_window(hour: float) -> bool:
    return current_meal_window(hour) is not None


def daily_mobility_intention_slot_index(questionnaire_id: str) -> int | None:
    match = _SLOT_ID_RE.match(questionnaire_id)
    if match is None:
        return None
    return int(match.group(1))


def is_daily_mobility_intention_questionnaire(questionnaire_id: str) -> bool:
    return daily_mobility_intention_slot_index(questionnaire_id) is not None


def _workspace_text_blob(workspace_context: dict[str, Any]) -> str:
    parts: list[str] = []
    for value in workspace_context.values():
        if isinstance(value, str):
            parts.append(value)
        else:
            parts.append(json.dumps(value, ensure_ascii=False, default=str))
    return " ".join(parts).lower()


def _read_agent_workspace_json(agent: Any, path: str) -> dict[str, Any]:
    """Read a JSON object from an agent workspace.

    Args:
        agent: Person agent-like object.
        path: Workspace-relative path.

    Returns:
        Parsed JSON object, or an empty dict.
    """
    reader = getattr(agent, "_read_workspace_json", None)
    if callable(reader):
        data = reader(path)
        return data if isinstance(data, dict) else {}
    workspace = getattr(agent, "_workspace", None)
    if workspace is not None and hasattr(workspace, "read_text"):
        try:
            data = json.loads(workspace.read_text(path))
            return data if isinstance(data, dict) else {}
        except (OSError, TypeError, ValueError):
            return {}
    return {}


def _write_agent_workspace_text(agent: Any, path: str, content: str) -> None:
    """Write text to an agent workspace.

    Args:
        agent: Person agent-like object.
        path: Workspace-relative path.
        content: Text content to write.

    Returns:
        None.
    """
    workspace = getattr(agent, "_workspace", None)
    if workspace is not None and hasattr(workspace, "write_text"):
        workspace.write_text(path, content)
        return
    runtime = getattr(agent, "_skill_runtime", None)
    writer = getattr(runtime, "workspace_write", None)
    if callable(writer):
        writer(path, content)
        return
    raise RuntimeError("Agent workspace writer is not available")


def _need_scalar(needs: Any, key: str) -> float | None:
    if not isinstance(needs, dict):
        return None
    raw = needs.get(key)
    if isinstance(raw, (int, float)):
        return float(raw)
    nested = needs.get("needs")
    if isinstance(nested, dict) and isinstance(nested.get(key), (int, float)):
        return float(nested[key])
    return None


def _current_aoi_from_observation(workspace_context: dict[str, Any]) -> int | None:
    obs_ctx = workspace_context.get("state/observation_ctx.json")
    if not isinstance(obs_ctx, dict):
        return None
    observations = obs_ctx.get("observations")
    if not isinstance(observations, dict):
        return None
    for observation in observations.values():
        if isinstance(observation, dict):
            position = observation.get("position")
            if isinstance(position, dict) and isinstance(position.get("aoi_id"), int):
                return position["aoi_id"]
    return None


def _profile_aoi(workspace_context: dict[str, Any], label: str) -> int | None:
    blob = _workspace_text_blob(workspace_context)
    m = re.search(rf"{label}\s*AOI\s*(\d+)", blob, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _hour_fraction(sim_time: datetime) -> float:
    return hour_fraction(sim_time)


def _meal_name(hour: float) -> str:
    window = current_meal_window(hour)
    if window == "breakfast":
        return "breakfast"
    if window == "lunch":
        return "lunch"
    if window == "dinner":
        return "dinner"
    return "main meal (typical windows only when hunger is high)"


def _current_meal_window(hour: float) -> str | None:
    return current_meal_window(hour)


def _meal_state_from_context(workspace_context: dict[str, Any]) -> dict[str, Any]:
    raw = workspace_context.get("state/meal_state.json")
    return raw if isinstance(raw, dict) else {}


def meals_completed_today(
    meal_state: dict[str, Any], *, day: date | None = None
) -> set[str]:
    """Meal windows actually consumed today (restore or on-site POI), not questionnaire labels."""
    day_key = (day or datetime.now().astimezone().date()).isoformat()
    done: set[str] = set()
    restored = meal_state.get("restored_windows")
    if isinstance(restored, dict):
        for key in restored:
            if not isinstance(key, str) or not key.startswith(f"{day_key}:"):
                continue
            suffix = key.split(":", 1)[1]
            suffix = suffix.removesuffix(":hunger")
            if suffix in {"breakfast", "lunch", "dinner"}:
                done.add(suffix)
    last_window = meal_state.get("last_meal_window")
    last_time = meal_state.get("last_meal_time")
    last_poi = meal_state.get("last_meal_poi_id")
    if (
        isinstance(last_window, str)
        and isinstance(last_time, str)
        and last_time.startswith(day_key)
        and last_poi is not None
        and last_window not in done
    ):
        done.add(last_window)
    return done


NIGHT_SLEEP_HARD_END_HOUR = 6.5
NIGHT_SLEEP_END_HOUR = 7.0
WORK_BAND_START_HOUR = 9.0
WORK_COMMUTE_END_HOUR = 21.0
WORK_EVENING_LEAVE_HOUR = 17.0
LATE_EVENING_START_HOUR = 22.0
NIGHT_SLEEP_ENERGY_CAP = 0.55
WAKE_ENERGY_THRESHOLD = 0.68


def normalize_questionnaire_intention(
    goal: str,
    *,
    sim_time: datetime,
    hunger: float | None = None,
    energy: float | None = None,
    current_aoi: int | None = None,
    home_aoi: int | None = None,
    work_aoi: int | None = None,
    meal_state: dict[str, Any] | None = None,
    mobility_status: str | None = None,
    rhythm_recommendation: str | None = None,
    scheduled_activity: str | None = None,
    norm_strength: float | None = None,
    poi_id: int | None = None,
    poi_category: str | None = None,
) -> str:
    """Apply benchmark rhythm guards so questionnaire labels match time, needs, and AOI."""
    goal = str(goal).strip()
    goal_l = goal.lower()
    h = hour_fraction(sim_time)
    meal_state = meal_state if isinstance(meal_state, dict) else {}
    moving = str(mobility_status or "").lower() == "moving"
    completed = meals_completed_today(meal_state, day=sim_time.date())
    meal = current_meal_window(h)
    rhythm_work = (
        str(rhythm_recommendation or "").lower() == "work"
        or str(scheduled_activity or "").lower() == "work"
    )
    strong_work_norm = rhythm_work and (norm_strength is None or norm_strength >= 0.62)

    at_home = (
        current_aoi is not None and home_aoi is not None and current_aoi == home_aoi
    )
    at_work = (
        current_aoi is not None and work_aoi is not None and current_aoi == work_aoi
    )

    if (
        meal == "breakfast"
        and "breakfast" not in completed
        and hunger is not None
        and hunger >= HUNGER_BREAKFAST_THRESHOLD
        and goal_l not in ("sleep", "eating out")
    ):
        return "eating out"

    if (
        meal
        and meal not in completed
        and hunger is not None
        and hunger
        >= (
            HUNGER_BREAKFAST_THRESHOLD if meal == "breakfast" else HUNGER_MEAL_THRESHOLD
        )
        and NIGHT_SLEEP_END_HOUR <= h < LATE_EVENING_START_HOUR
        and goal_l != "sleep"
        and goal_l != "eating out"
    ):
        return "eating out"

    if (
        meal == "dinner"
        and "dinner" not in completed
        and hunger is not None
        and hunger >= HUNGER_MEAL_THRESHOLD
        and 17.5 <= h < 20.5
        and goal_l not in ("sleep", "eating out")
        and (
            at_home or (not moving and work_aoi is not None and current_aoi == work_aoi)
        )
    ):
        return "eating out"

    if h < NIGHT_SLEEP_HARD_END_HOUR:
        return "sleep"

    if h < NIGHT_SLEEP_END_HOUR:
        if goal_l in ("work", "shopping", "leisure and entertainment", "eating out"):
            return "sleep"
        if goal_l == "home activity":
            if energy is not None and energy > WAKE_ENERGY_THRESHOLD:
                return "home activity"
            return "sleep"
        return "sleep"

    if h >= LATE_EVENING_START_HOUR:
        if goal_l in ("work", "shopping", "leisure and entertainment"):
            return "home activity"
        if goal_l == "eating out" and (
            hunger is None or hunger < HUNGER_DRIVE_THRESHOLD
        ):
            return "home activity" if energy is None or energy > 0.4 else "sleep"

    if NIGHT_SLEEP_END_HOUR <= h < WORK_BAND_START_HOUR and goal_l == "sleep":
        if energy is not None and energy > 0.52:
            return "home activity"
        return "sleep"

    if (
        WORK_BAND_START_HOUR <= h < WORK_COMMUTE_END_HOUR
        and strong_work_norm
        and work_aoi is not None
        and (energy is None or energy >= 0.38)
        and not (
            meal
            and meal not in completed
            and hunger is not None
            and hunger >= HUNGER_MEAL_THRESHOLD
        )
        and goal_l in {"home activity", "other", "work"}
        and (at_work or moving or not at_home)
    ):
        return "work"

    if (
        goal_l == "work"
        and at_home
        and not moving
        and WORK_BAND_START_HOUR <= h < WORK_COMMUTE_END_HOUR
    ):
        return "home activity"

    if (
        goal_l == "work"
        and not at_work
        and not moving
        and poi_id is not None
        and _is_food_poi_category(poi_category)
    ):
        if (
            meal
            and meal not in completed
            and hunger is not None
            and hunger >= HUNGER_MEAL_THRESHOLD
        ):
            return "eating out"
        return "home activity"

    if goal_l == "work":
        if h < WORK_BAND_START_HOUR:
            return "home activity"
        if (
            h >= WORK_COMMUTE_END_HOUR
            and not moving
            and work_aoi is not None
            and not at_work
        ):
            return "home activity"
        if (
            WORK_BAND_START_HOUR <= h < WORK_COMMUTE_END_HOUR
            and not moving
            and work_aoi is not None
            and at_home
            and not strong_work_norm
        ):
            return "home activity"

    return goal


def postprocess_questionnaire_intention_answers(
    questionnaire_result: Any,
    *,
    sim_time: datetime,
    agents_by_id: dict[int, Any],
) -> None:
    """Record each agent's questionnaire intention as-is, without rule guards.

    The agent's own answer is the final result: no ``normalize_questionnaire_intention``
    or ``coerce_duplicate_meal_intention`` is applied, so the recorded intention
    reflects the agent (LLM) capability rather than benchmark rules. This only
    persists the intention for the mobility harness (``_restore_intention.json``)
    and derives meal-enforcement state from the agent's stated goal.
    """
    import json

    for agent_result in questionnaire_result.responses:
        agent = agents_by_id.get(agent_result.agent_id)
        if agent is None:
            continue
        for answer in agent_result.answers:
            if answer.question_id != "primary_intention" or not answer.parse_success:
                continue
            meal_state = _read_agent_workspace_json(agent, "state/meal_state.json")
            # 以 agent 原始输出为最终结果，不应用任何规则化防护。
            goal = str(answer.parsed_value)
            intent_data = {
                "tick": questionnaire_result.step_count,
                "goal": goal,
                "reason": answer.reason or "",
                "source": "questionnaire",
                "time": sim_time.isoformat(),
            }
            goal_l = goal.lower()
            meal = None
            if "eating out" in goal_l:
                meal = current_meal_window(hour_fraction(sim_time))
                if meal:
                    intent_data["meal_window"] = meal
            _write_agent_workspace_text(
                agent,
                "_restore_intention.json",
                json.dumps(intent_data, ensure_ascii=False, indent=2),
            )
            pending_meal = meal
            if (
                pending_meal is None
                and "eating out" in goal_l
                and 7 <= hour_fraction(sim_time) < 9.5
                and "breakfast"
                not in meals_completed_today(meal_state, day=sim_time.date())
            ):
                pending_meal = "breakfast"
            if pending_meal and pending_meal not in meals_completed_today(
                meal_state, day=sim_time.date()
            ):
                meal_state["pending_meal_enforce"] = pending_meal
                agent._write_meal_state(meal_state)


def coerce_duplicate_meal_intention(
    goal: str,
    sim_time: datetime,
    meal_state: dict[str, Any],
) -> str:
    """If this meal window was already consumed, map eating out to work/home activity."""
    goal_l = str(goal).lower().strip()
    if "eating out" not in goal_l:
        return goal
    meal = current_meal_window(hour_fraction(sim_time))
    completed = meals_completed_today(meal_state, day=sim_time.date())
    if meal is None or meal not in completed:
        if "breakfast" in completed and 7 <= hour_fraction(sim_time) < 10:
            return "work" if hour_fraction(sim_time) >= 9 else "home activity"
        return goal
    h = hour_fraction(sim_time)
    if 9 <= h < 18:
        return "work"
    if h >= 18:
        return "home activity"
    return "home activity"


def slot_index_for_time(when: datetime) -> int:
    return max(0, min(47, (when.hour * 60 + when.minute) // 30))


def mark_meal_recorded(
    meal_state: dict[str, Any],
    *,
    meal_window: str,
    when: datetime,
    poi_id: int | None,
) -> dict[str, Any]:
    day_key = when.date().isoformat()
    restored = meal_state.get("restored_windows")
    if not isinstance(restored, dict):
        restored = {}
    restored[f"{day_key}:{meal_window}"] = when.isoformat()
    meal_state["restored_windows"] = restored
    q_meals = meal_state.get("questionnaire_meals")
    if not isinstance(q_meals, dict):
        q_meals = {}
    q_meals[meal_window] = when.isoformat()
    meal_state["questionnaire_meals"] = q_meals
    return meal_state


def build_questionnaire_runtime_hints(
    *,
    sim_time: datetime,
    workspace_context: dict[str, Any],
) -> list[str]:
    hints: list[str] = []
    h = _hour_fraction(sim_time)
    blob = _workspace_text_blob(workspace_context)
    needs_json = workspace_context.get("state/needs.json")
    hunger = _need_scalar(needs_json, "hunger")
    energy = _need_scalar(needs_json, "energy")
    stress = _need_scalar(needs_json, "stress")

    current_aoi = _current_aoi_from_observation(workspace_context)
    home_aoi = _profile_aoi(workspace_context, "home")
    work_aoi = _profile_aoi(workspace_context, "work")
    at_home = (
        current_aoi is not None and home_aoi is not None and current_aoi == home_aoi
    )
    at_work = (
        current_aoi is not None and work_aoi is not None and current_aoi == work_aoi
    )
    meal_state = _meal_state_from_context(workspace_context)
    completed_meals = meals_completed_today(meal_state, day=sim_time.date())
    rhythm_state = workspace_context.get("state/rhythm_state.json")
    if isinstance(rhythm_state, dict):
        diary = rhythm_state.get("daily_diary")
        scheduled = rhythm_state.get("scheduled_activity")
        norm_strength = rhythm_state.get("norm_strength")
        if isinstance(diary, str) and diary:
            hints.append("Daily diary/social norm: " + diary)
        if isinstance(scheduled, dict):
            activity = scheduled.get("activity")
            start = scheduled.get("start")
            end = scheduled.get("end")
            norm = scheduled.get("norm")
            hints.append(
                f"Scheduled activity now: {activity} ({start}-{end}); norm={norm}; "
                f"norm_strength={norm_strength}. Treat this as a strong prior unless "
                "critical needs or location evidence conflict."
            )
        scores = rhythm_state.get("scores")
        recommendation = rhythm_state.get("recommendation")
        if isinstance(scores, dict) and isinstance(recommendation, str):
            compact_scores = {
                key: round(float(value), 2)
                for key, value in scores.items()
                if isinstance(value, (int, float))
            }
            hints.append(
                f"Rhythm model: recommendation={recommendation}, scores={compact_scores}. "
                "Social norms are a strong prior; needs/location can override only when clear."
            )
        reasons = rhythm_state.get("reasons")
        if isinstance(reasons, list) and reasons:
            hints.append("Rhythm reasons: " + "; ".join(map(str, reasons[:3])))

    mobility_status = ""
    obs_ctx = workspace_context.get("state/observation_ctx.json")
    if isinstance(obs_ctx, dict):
        for val in obs_ctx.get("observations", {}).values():
            if isinstance(val, dict) and val.get("status"):
                mobility_status = str(val["status"]).lower()
                break

    current_meal = _current_meal_window(h)
    already_ate_current_meal = (
        current_meal is not None and current_meal in completed_meals
    )

    if current_meal and already_ate_current_meal:
        hints.append(
            f"Meal log: {current_meal} is already recorded today — do NOT choose "
            "eating out again for this meal; use work or home activity."
        )

    if 0 <= h < NIGHT_SLEEP_HARD_END_HOUR:
        hints.append(
            "Night (00:00-06:30): choose sleep unless the runtime later overrides for safety."
        )
    elif NIGHT_SLEEP_HARD_END_HOUR <= h < NIGHT_SLEEP_END_HOUR:
        hints.append(
            "Early morning (06:30-07:00): sleep if energy is low; home activity only if energy is clearly high."
        )
    elif 7 <= h < 9:
        hints.append(
            "Morning (07:00-09:00): home activity or breakfast are common; commute/work is plausible only if already moving toward work."
        )
        if already_ate_current_meal:
            hints.append(
                "Breakfast is already recorded for this morning - choose home activity until work starts."
            )
        elif hunger is not None and hunger >= HUNGER_BREAKFAST_THRESHOLD:
            hints.append(
                f"hunger={hunger:.2f} - breakfast window and hungry enough (>= {HUNGER_BREAKFAST_THRESHOLD:.2f}); "
                "choose eating out only if going to a restaurant is the main activity this slot, "
                "otherwise home activity until you leave home."
            )
        else:
            hints.append(
                "Not hungry enough for breakfast yet - choose home activity, commute, or work from location and energy."
            )
    elif 9 <= h < 21:
        hints.append(
            "Typical work band (09:00-21:00): choose work only if at workplace AOI or status is moving toward work; "
            "if still idle at home AOI, choose home activity (commute has not started)."
        )
        if at_home and not at_work:
            hints.append(
                f"Mobility check: you are still at HOME (AOI {current_aoi}), not workplace "
                f"({work_aoi}) - choose home activity unless you are starting a commute."
            )
        elif (
            current_aoi is not None
            and work_aoi is not None
            and current_aoi not in ({home_aoi, work_aoi})
        ):
            hints.append(
                f"Mobility check: you are at AOI {current_aoi} (not home/work) - "
                "eating out or other is more accurate than work unless actively commuting."
            )
        elif at_work:
            hints.append(
                f"Mobility check: you are at workplace AOI {current_aoi} - work is appropriate."
            )
        elif (
            "lunch" in completed_meals
            and current_aoi is None
            and mobility_status != "moving"
        ):
            hints.append(
                "Lunch is already recorded but current AOI is missing — prefer work "
                "(return to office / continue workday), not home activity, unless commuting home."
            )
    elif 18 <= h < 21:
        hints.append(
            "Evening (18:00-21:00): return home is common when energy is lower or stress is higher; "
            "dinner is plausible if hunger is high."
        )
    elif h >= 21:
        hints.append(
            "Late evening (21:00+): choose home activity or sleep based on energy; avoid new outings unless clearly motivated."
        )

    if energy is not None and energy <= ENERGY_EXHAUSTED_THRESHOLD:
        hints.append(
            f"energy={energy:.2f} - exhausted: prefer sleep/rest or going home; avoid leisure."
        )
    elif energy is not None and energy <= ENERGY_SLEEP_THRESHOLD and (h >= 21 or h < 6):
        hints.append(f"energy={energy:.2f} - low energy at night: choose sleep/rest.")
    elif energy is not None and energy >= 0.75 and 6 <= h < 22:
        hints.append(
            f"energy={energy:.2f} - well rested: sleep is unlikely; use home activity, "
            "eating out (if hungry), or work per time of day."
        )
    elif energy is not None and energy <= 0.45 and 9 <= h < 18:
        hints.append(
            f"energy={energy:.2f} - low workday energy; stay on work/commute, avoid leisure."
        )

    if stress is not None and stress >= STRESS_WIND_DOWN_THRESHOLD and h >= 18:
        hints.append(
            f"stress={stress:.2f} - high pressure after work: prefer return home, home activity, then sleep/rest."
        )
    elif stress is not None and stress >= 0.60 and 9 <= h < 18:
        hints.append(
            f"stress={stress:.2f} - work pressure is high; continue core routine, no extra leisure."
        )

    to_work = any(
        k in blob
        for k in (
            "commut",
            "to work",
            "toward work",
            "workplace",
            "work aoi",
            "transportation facility",
            "heading to work",
        )
    )
    to_home = any(
        k in blob
        for k in (
            "back to home",
            "return home",
            "going home",
            "driving home",
            "home aoi",
            "commute home",
        )
    )
    breakfast_pending = (
        current_meal == "breakfast"
        and hunger is not None
        and hunger >= HUNGER_BREAKFAST_THRESHOLD
        and "breakfast" not in completed_meals
    )
    lunch_urgent = (
        current_meal == "lunch"
        and hunger is not None
        and hunger >= HUNGER_MEAL_THRESHOLD
        and "lunch" not in completed_meals
    )
    if lunch_urgent and mobility_status == "moving":
        hints.append(
            f"hunger={hunger:.2f} during lunch window while in transit — choose eating out "
            "(stop for lunch). Do NOT label the whole slot as work just because you are driving."
        )
    if to_work and not to_home and not breakfast_pending and not lunch_urgent:
        hints.append(
            "Memory/observation suggests commuting toward work - choose work, not other."
        )
    elif to_work and breakfast_pending:
        hints.append(
            "You may be moving, but hunger is high - breakfast can be the main activity before work."
        )
    elif to_home:
        hints.append(
            "Memory/observation suggests commuting home - choose home activity, not other."
        )

    if h >= 21:
        if hunger is not None:
            hints.append(
                f"hunger={hunger:.2f} - after 21:00 eating out is unusual; choose sleep/home unless hunger is clearly dominant."
            )
        else:
            hints.append(
                "After 21:00 eating out is unusual - choose sleep/home from energy."
            )
    elif (
        hunger is not None
        and hunger >= HUNGER_MEAL_THRESHOLD
        and (current_meal is None or current_meal not in completed_meals)
    ):
        meal = _meal_name(h)
        if current_meal and already_ate_current_meal:
            hints.append(
                f"hunger={hunger:.2f}, but {current_meal} is already recorded today - "
                "do NOT label another eating out slot for the same meal; continue work or home activity."
            )
        elif current_meal:
            hints.append(
                f"hunger={hunger:.2f} - typical {meal} window and hunger is high; prefer eating out if food is the main activity."
            )
        else:
            hints.append(
                f"hunger={hunger:.2f} - hungry outside a typical meal window; keep the main routine unless food is clearly the main activity."
            )
    elif hunger is not None:
        hints.append(
            f"hunger={hunger:.2f} - not hungry enough for a main meal (<{HUNGER_MEAL_THRESHOLD:.2f}): "
            "work or home activity, not eating out."
        )

    hints.append(
        "Population prior: sleep and work dominate the day; leisure and entertainment is rare (~0-1 slots). "
        "Do not use other for routine commute."
    )
    return hints


def build_primary_intention_prompt(
    slot_index: int,
    *,
    total_slots: int = 48,
    slot_minutes: int = 30,
) -> str:
    slot_number = slot_index + 1
    choice_line = ", ".join(INTENTION_CHOICES)
    return f"""Use the **simulation clock** shown in your current system context as the wall time.

You are answering for daily-mobility **time slot {slot_number} of {total_slots}** ({total_slots} consecutive {slot_minutes}-minute periods that cover the simulated run; **{slot_minutes} minutes each**, same resolution as the configured questionnaire slots).

Answer for the **dominant** activity of this whole {slot_minutes}-minute period from your own current situation. Use your current observation, state, memory, and recent actions as evidence. Do not answer from occupation alone or from a plan for later in the day.

Interpret the options in their ordinary daily-mobility sense:
- sleep
- home activity
- work
- shopping
- eating out
- leisure and entertainment
- other

Choose exactly ONE option (copy the phrase exactly): {choice_line}."""
