"""Shared data loading for Daily Mobility live plots and web dashboard."""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from daily_mobility.env_call_trace import load_env_tool_calls, log_simulation_time

INTENTIONS = [
    "sleep",
    "home activity",
    "work",
    "shopping",
    "eating out",
    "leisure and entertainment",
    "other",
]

# 看板时间轴专用：问卷无此选项，仅用于 moving 路段，避免与就餐/工作意图混淆
TIMELINE_DISPLAY_INTENTIONS = [*INTENTIONS, "commute"]

INTENTION_COLORS = {
    "sleep": "#2c3e50",
    "home activity": "#e67e22",
    "work": "#5dade2",
    "shopping": "#27ae60",
    "eating out": "#e74c3c",
    "leisure and entertainment": "#9b59b6",
    "other": "#7f8c8d",
    "commute": "#2980b9",
    None: "#e8eaed",
}

POSITION_KIND_COLORS = {
    "home": "#2e86c1",
    "work": "#d35400",
    "moving": "#64748b",
    "meal_poi": "#e74c3c",
    "aoi": "#7b8794",
    "unset": "#dce3ed",
    None: "#e8eaed",
}

SCHEDULE_ACTIVITY_COLORS = {
    "sleep": INTENTION_COLORS["sleep"],
    "home_activity": INTENTION_COLORS["home activity"],
    "work": INTENTION_COLORS["work"],
    "meal": INTENTION_COLORS["eating out"],
    "return_home": INTENTION_COLORS["commute"],
}

SCHEDULE_ACTIVITY_LABELS = {
    "sleep": "睡眠",
    "home_activity": "居家",
    "work": "工作/通勤",
    "meal": "用餐",
    "return_home": "回家",
}

SCHEDULE_TO_INTENTION = {
    "sleep": "sleep",
    "home_activity": "home activity",
    "work": "work",
    "meal": "eating out",
    "return_home": "home activity",
}

SLOT_RE = re.compile(r"daily_mobility_intention_slot_(\d+)")


def _hour_label(hour: float) -> str:
    h = int(hour)
    m = round((hour - h) * 60)
    if m >= 60:
        h += 1
        m = 0
    return f"{h:02d}:{m:02d}"


def read_json_object(path: Path) -> dict[str, Any] | None:
    """Read a live run record, tolerating missing or partially written files."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return raw if isinstance(raw, dict) else None


def load_agent_rhythm_state(run_dir: Path, *, agent_id: int) -> dict[str, Any] | None:
    path = run_dir / "agents" / f"agent_{agent_id:04d}" / "state" / "rhythm_state.json"
    return read_json_object(path)


def schedule_block_at_hour(
    schedule: list[dict[str, Any]], hour: float
) -> dict[str, Any] | None:
    for item in schedule:
        if float(item["start"]) <= hour < float(item["end"]):
            return item
    return schedule[-1] if schedule else None


def expand_schedule_to_slots(
    schedule: list[dict[str, Any]], *, total_slots: int = 48
) -> list[dict[str, Any] | None]:
    out: list[dict[str, Any] | None] = []
    for slot in range(total_slots):
        block = schedule_block_at_hour(schedule, slot * 0.5)
        if not block:
            out.append(None)
            continue
        activity = str(block.get("activity") or "home_activity")
        out.append(
            {
                "slot": slot,
                "activity": activity,
                "label": SCHEDULE_ACTIVITY_LABELS.get(activity, activity),
                "intention": SCHEDULE_TO_INTENTION.get(activity, "other"),
                "meal_window": block.get("meal_window"),
                "norm": block.get("norm"),
                "start_hour": float(block["start"]),
                "end_hour": float(block["end"]),
                "time_range": f"{_hour_label(float(block['start']))}–{_hour_label(float(block['end']))}",
            }
        )
    return out


def _parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _hour_fraction(t: datetime | None, slot: int) -> float:
    if t is None:
        return slot * 0.5
    return t.hour + t.minute / 60.0


FOOD_POI_CATEGORIES = frozenset(
    {"restaurant", "fast_food", "cafe", "food", "meal", "bakery", "bar"}
)


def is_food_poi_category(category: str | None) -> bool:
    if not category:
        return False
    cat = str(category).lower()
    if cat in FOOD_POI_CATEGORIES:
        return True
    return any(token in cat for token in ("restaurant", "food", "cafe", "meal"))


def display_intention_for_position(
    intention: str | None,
    *,
    poi_category: str | None,
    poi_name: str | None = None,
    aoi_id: int | None = None,
    home_aoi: int | None = None,
    work_aoi: int | None = None,
    poi_id: int | None = None,
) -> str | None:
    if not intention:
        return intention
    goal_l = intention.lower()
    if goal_l == "eating out":
        return intention
    if goal_l in ("work", "sleep", "shopping", "leisure and entertainment"):
        return intention
    at_named_food = poi_name and any(
        k in str(poi_name).lower()
        for k in ("餐", "饭", "kfc", "麦当劳", "火锅", "肯德基")
    )
    at_meal_poi = (
        poi_id is not None
        and aoi_id is not None
        and home_aoi is not None
        and aoi_id != home_aoi
        and (work_aoi is None or aoi_id != work_aoi)
    )
    if goal_l == "home activity" and (
        is_food_poi_category(poi_category) or at_named_food or at_meal_poi
    ):
        return "eating out"
    return intention


POSITION_FIELD_KEYS = (
    "position_kinds",
    "position_labels",
    "locations",
    "aoi_ids",
    "poi_ids",
    "poi_names",
    "poi_categories",
    "statuses",
    "lngs",
    "lats",
)


def apply_end_of_slot_positions(parsed: dict[str, list[Any]]) -> None:
    """Questionnaire snapshots are taken at slot start; show period-end location from the next slot."""
    for slot in range(47):
        nxt = slot + 1
        if parsed["lngs"][nxt] is None:
            continue
        for key in POSITION_FIELD_KEYS:
            if parsed[key][nxt] is not None:
                parsed[key][slot] = parsed[key][nxt]


def apply_questionnaire_intention_overrides(
    run_dir: Path, agent_id: int, parsed: dict[str, list[Any]]
) -> None:
    path = (
        run_dir
        / "agents"
        / f"agent_{agent_id:04d}"
        / "state"
        / "questionnaire_intention_overrides.json"
    )
    overrides = read_json_object(path)
    if overrides is None:
        return
    slots = overrides.get("slots")
    if not isinstance(slots, dict):
        return
    for key, entry in slots.items():
        try:
            slot = int(key)
        except (TypeError, ValueError):
            continue
        if not (0 <= slot < 48):
            continue
        intention = entry.get("intention") if isinstance(entry, dict) else entry
        if intention in INTENTIONS:
            parsed["intentions"][slot] = intention


def _canonical_meal_slots(run_dir: Path, agent_id: int) -> dict[str, int]:
    canonical: dict[str, int] = {}
    override_path = (
        run_dir
        / "agents"
        / f"agent_{agent_id:04d}"
        / "state"
        / "questionnaire_intention_overrides.json"
    )
    if override_path.is_file():
        try:
            overrides = json.loads(override_path.read_text(encoding="utf-8"))
            for entry in (overrides.get("slots") or {}).values():
                if not isinstance(entry, dict):
                    continue
                meal = entry.get("meal")
                slot_raw = entry.get("slot")
                if meal in {"breakfast", "lunch", "dinner"} and slot_raw is not None:
                    canonical[str(meal)] = int(slot_raw)
                    continue
                when = entry.get("time")
                if meal in {"breakfast", "lunch", "dinner"} and when:
                    canonical[str(meal)] = _slot_index_from_time(when, 0)
        except Exception:
            import logging
            logging.getLogger(__name__).debug("Failed to parse meal schedule from agent state", exc_info=True)
    meal_path = (
        run_dir / "agents" / f"agent_{agent_id:04d}" / "state" / "meal_state.json"
    )
    if meal_path.is_file():
        try:
            meal_state = json.loads(meal_path.read_text(encoding="utf-8"))
            restored = meal_state.get("restored_windows") or {}
            for key, when_raw in restored.items():
                if str(key).endswith(":hunger"):
                    continue
                parts = str(key).split(":")
                if len(parts) < 2:
                    continue
                meal = parts[-1]
                if meal in {"breakfast", "lunch", "dinner"}:
                    canonical[meal] = _slot_index_from_time(when_raw, 0)
        except Exception:
            import logging
            logging.getLogger(__name__).debug("Failed to parse meal schedule from meal state", exc_info=True)
    return canonical


def dedupe_eating_out_intentions(
    run_dir: Path,
    agent_id: int,
    parsed: dict[str, list[Any]],
    *,
    raw_intentions: list[str | None],
) -> None:
    canonical = _canonical_meal_slots(run_dir, agent_id)
    if not canonical:
        return
    keep_slots = set(canonical.values())
    for slot, intent in enumerate(parsed["intentions"]):
        if intent != "eating out" or slot in keep_slots:
            continue
        fallback = raw_intentions[slot] if slot < len(raw_intentions) else None
        if fallback == "eating out":
            meal = _meal_window_for_hour(
                _hour_fraction(_parse_time(parsed["times"][slot]), slot)
            )
            if meal and canonical.get(meal) is not None and canonical[meal] != slot:
                fallback = (
                    "work"
                    if 9
                    <= _hour_fraction(_parse_time(parsed["times"][slot]), slot)
                    < 18
                    else "home activity"
                )
        parsed["intentions"][slot] = (
            fallback if fallback in INTENTIONS else "home activity"
        )


def apply_all_intention_corrections(
    run_dir: Path, agent_id: int, parsed: dict[str, list[Any]]
) -> None:
    raw_intentions = list(parsed["intentions"])
    parsed["base_intentions"] = raw_intentions
    apply_questionnaire_intention_overrides(run_dir, agent_id, parsed)
    apply_recorded_meals_to_intentions(run_dir, agent_id, parsed)
    dedupe_eating_out_intentions(
        run_dir, agent_id, parsed, raw_intentions=raw_intentions
    )


def prepare_timeline_intentions(
    run_dir: Path, agent_id: int, parsed: dict[str, list[Any]]
) -> None:
    apply_all_intention_corrections(run_dir, agent_id, parsed)
    apply_end_of_slot_positions(parsed)
    finalize_timeline_intentions(
        run_dir,
        agent_id,
        parsed,
        base_intentions=parsed.get("base_intentions"),
    )


def apply_recorded_meals_to_intentions(
    run_dir: Path, agent_id: int, parsed: dict[str, list[Any]]
) -> None:
    path = run_dir / "agents" / f"agent_{agent_id:04d}" / "state" / "meal_state.json"
    meal_state = read_json_object(path)
    if meal_state is None:
        return
    restored = meal_state.get("restored_windows")
    if not isinstance(restored, dict):
        return
    for key, when_raw in restored.items():
        if str(key).endswith(":hunger"):
            continue
        parts = str(key).split(":")
        if len(parts) < 2:
            continue
        meal = parts[-1]
        if meal not in {"breakfast", "lunch", "dinner"}:
            continue
        dt = _parse_time(str(when_raw))
        slot = _slot_index_from_time(dt, 0)
        if 0 <= slot < 48:
            parsed["intentions"][slot] = "eating out"


def milestones_from_meal_state(
    run_dir: Path, agent_id: int, existing: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    path = run_dir / "agents" / f"agent_{agent_id:04d}" / "state" / "meal_state.json"
    meal_state = read_json_object(path)
    if meal_state is None:
        return existing
    seen_slots = {m["slot"] for m in existing if m.get("kind") == "meal"}
    restored = meal_state.get("restored_windows")
    if not isinstance(restored, dict):
        return existing
    out = list(existing)
    meals_seen: set[str] = set()
    for key, when_raw in restored.items():
        if str(key).endswith(":hunger"):
            continue
        parts = str(key).split(":")
        if len(parts) < 2:
            continue
        meal = parts[-1]
        if meal not in MEAL_LABELS or meal in meals_seen:
            continue
        dt = _parse_time(str(when_raw))
        slot = _slot_index_from_time(dt, 0)
        if slot in seen_slots:
            continue
        meals_seen.add(meal)
        out.append(
            {
                "slot": slot,
                "kind": "meal",
                "meal": meal,
                "label": MEAL_LABELS[meal],
                "icon": "🍽",
                "color": MILESTONE_COLORS["meal"],
            }
        )
    return sorted(out, key=lambda m: m["slot"])


def align_intentions_with_positions(parsed: dict[str, list[Any]]) -> None:
    for slot in range(48):
        parsed["intentions"][slot] = display_intention_for_position(
            parsed["intentions"][slot],
            poi_category=parsed["poi_categories"][slot],
            poi_name=parsed["poi_names"][slot],
            aoi_id=parsed["aoi_ids"][slot],
            home_aoi=parsed["home_aois"][slot],
            work_aoi=parsed["work_aois"][slot],
            poi_id=parsed["poi_ids"][slot],
        )


def _fallback_intention(
    slot: int,
    parsed: dict[str, list[Any]],
    *,
    base_intentions: list[str | None] | None = None,
) -> str:
    base = (
        base_intentions[slot]
        if base_intentions and slot < len(base_intentions)
        else None
    )
    if base in INTENTIONS and base != "eating out":
        return base
    hour = _hour_fraction(_parse_time(parsed["times"][slot]), slot)
    if 9 <= hour < 18:
        return "work"
    if hour >= 22 or hour < 6.5:
        return "sleep"
    return "home activity"


def finalize_timeline_intentions(
    run_dir: Path,
    agent_id: int,
    parsed: dict[str, list[Any]],
    *,
    base_intentions: list[str | None] | None = None,
) -> None:
    """看板时间轴：moving→通勤；就餐仅保留每餐 canonical 一格，其余回退问卷意图。"""
    canonical = set(_canonical_meal_slots(run_dir, agent_id).values())
    base = base_intentions or parsed.get("base_intentions")
    for slot in range(48):
        status = str(parsed["statuses"][slot] or "").lower()
        pos_kind = parsed["position_kinds"][slot]
        if status == "moving" or pos_kind == "moving":
            parsed["intentions"][slot] = "commute"
            continue
        intent = parsed["intentions"][slot]
        if intent == "eating out" and canonical and slot not in canonical:
            parsed["intentions"][slot] = _fallback_intention(
                slot, parsed, base_intentions=base
            )


def position_kind_from_snapshot(snapshot: dict[str, Any]) -> str:
    status = str(snapshot.get("status") or "").lower()
    aoi = snapshot.get("aoi_id")
    home = snapshot.get("home_aoi")
    work = snapshot.get("work_aoi")
    if status == "moving":
        return "moving"
    if aoi is None and snapshot.get("poi_id") is not None:
        return "aoi"
    if aoi is None:
        return "unset"
    if home is not None and aoi == home:
        return "home"
    if work is not None and aoi == work:
        return "work"
    if snapshot.get("poi_id") is not None and home is not None:
        return "meal_poi"
    return "aoi"


def position_label_from_snapshot(snapshot: dict[str, Any]) -> str:
    status = str(snapshot.get("status") or "").lower()
    aoi = snapshot.get("aoi_id")
    home = snapshot.get("home_aoi")
    work = snapshot.get("work_aoi")
    poi_name = snapshot.get("poi_name")
    poi_id = snapshot.get("poi_id")
    poi_cat = snapshot.get("poi_category")
    target_aoi = snapshot.get("target_aoi_id")

    if status == "moving":
        parts = ["moving"]
        if aoi is not None:
            parts.append(f"aoi={aoi}")
        else:
            parts.append("aoi=—")
        if target_aoi is not None:
            parts.append(f"→{target_aoi}")
        return " · ".join(parts)

    if aoi is None:
        return f"{status or 'idle'} · aoi=—"

    tags: list[str] = [f"aoi={aoi}"]
    if home is not None and aoi == home:
        tags.append("=home")
    elif work is not None and aoi == work:
        tags.append("=work")
    if poi_name:
        tags.append(str(poi_name))
    elif poi_id is not None:
        tags.append(f"poi={poi_id}")
    if poi_cat:
        tags.append(str(poi_cat))
    return " · ".join(tags)


def slot_time_label(parsed: dict[str, list[Any]], slot: int) -> str:
    t = _parse_time(parsed["times"][slot])
    if t is not None:
        return t.strftime("%H:%M")
    return f"{slot // 2:02d}:{'30' if slot % 2 else '00'}"


def detect_wake_slot(
    intentions: list[str | None],
    times: list[Any] | None = None,
) -> int | None:
    prev: str | None = None
    for i, intent in enumerate(intentions):
        if intent is None:
            continue
        if prev == "sleep" and intent != "sleep":
            t = _parse_time(times[i]) if times and i < len(times) else None
            hour = _hour_fraction(t, i)
            if hour < 5:
                prev = intent
                continue
            if intent == "home activity" and hour < 7:
                prev = intent
                continue
            return i
        prev = intent
    return None


MEAL_LABELS = {
    "breakfast": "早餐",
    "lunch": "午餐",
    "dinner": "晚餐",
}

MILESTONE_COLORS = {
    "wake": "#f39c12",
    "bedtime": "#5c6bc0",
    "meal": "#e74c3c",
    "commute": "#2980b9",
    "leave_home": "#16a085",
    "move": "#95a5a6",
}


def _meal_window_for_hour(hour: float) -> str | None:
    if 7 <= hour < 9:
        return "breakfast"
    if 11.5 <= hour < 13.5:
        return "lunch"
    if 17.5 <= hour < 20.5:
        return "dinner"
    return None


def read_step_timing(steps_yaml: Path) -> tuple[int, str | None]:
    import yaml

    if steps_yaml.is_file():
        try:
            raw = yaml.safe_load(steps_yaml.read_text(encoding="utf-8"))
            tick = next(
                (step["tick"] for step in raw["steps"] if step.get("type") == "run" and step.get("tick")),
                900,
            )
            start = raw.get("start_t")
            return int(tick), str(start) if start is not None else None
        except (OSError, AttributeError, TypeError, ValueError, KeyError, yaml.YAMLError):
            pass
    return 900, None


def load_run_timing(
    run_dir: Path, *, tick_sec: int, sim_start: str | None = None
) -> dict[str, Any]:
    ticks_per_slot = (30 * 60) // tick_sec if tick_sec > 0 else 2
    timing: dict[str, Any] = {
        "slot_minutes": 30,
        "tick_seconds": tick_sec,
        "ticks_per_slot": ticks_per_slot,
        "questionnaire_slots": 48,
        "sim_start": sim_start,
        "step_pattern": (
            f"每问卷时段 30 分钟 → 问卷 1 次 + run {ticks_per_slot}×{tick_sec}s "
            f"(共 {ticks_per_slot * tick_sec // 60} 分钟仿真/时段)"
        ),
    }
    pid_path = run_dir / "pid.json"
    if pid_path.is_file():
        try:
            pid = json.loads(pid_path.read_text(encoding="utf-8"))
            timing["run_status"] = pid.get("status")
            timing["simulation_time"] = pid.get("simulation_time")
            timing["step_count"] = pid.get("step_count")
            timing["experiment_id"] = pid.get("experiment_id")
        except Exception:
            import logging
            logging.getLogger(__name__).debug("Failed to read pid file for timing info", exc_info=True)
    sim_raw = timing.get("simulation_time")
    if isinstance(sim_raw, str):
        sim_t = _parse_time(sim_raw)
        if sim_t is not None:
            total_min = sim_t.hour * 60 + sim_t.minute
            timing["current_slot"] = min(47, max(0, total_min // 30))
            timing["sim_time_label"] = sim_t.strftime("%H:%M")
    return timing


def _aoi_milestone_label(
    aoi: Any,
    *,
    home_aoi: int | None,
    work_aoi: int | None,
) -> str:
    if aoi is None:
        return "—"
    if home_aoi is not None and aoi == home_aoi:
        return "家"
    if work_aoi is not None and aoi == work_aoi:
        return "单位"
    tail = str(aoi)[-4:]
    return f"外{tail}"


def detect_milestones(
    parsed: dict[str, list[Any]], intentions: list[str | None]
) -> list[dict[str, Any]]:
    milestones: list[dict[str, Any]] = []
    home_aoi = _first_non_null(parsed["home_aois"])
    work_aoi = _first_non_null(parsed["work_aois"])

    wake = detect_wake_slot(intentions, parsed.get("times"))
    if wake is not None:
        milestones.append(
            {
                "slot": wake,
                "kind": "wake",
                "label": "起床",
                "icon": "☀️",
                "color": MILESTONE_COLORS["wake"],
            }
        )

    bedtime = detect_bedtime_slot(intentions)
    if bedtime is not None:
        milestones.append(
            {
                "slot": bedtime,
                "kind": "bedtime",
                "label": "入睡",
                "icon": "🌙",
                "color": MILESTONE_COLORS["bedtime"],
            }
        )

    meals_seen: set[str] = set()
    for slot, intent in enumerate(intentions):
        if intent != "eating out":
            continue
        hour = _hour_fraction(_parse_time(parsed["times"][slot]), slot)
        meal = _meal_window_for_hour(hour)
        if meal and meal not in meals_seen:
            meals_seen.add(meal)
            milestones.append(
                {
                    "slot": slot,
                    "kind": "meal",
                    "meal": meal,
                    "label": MEAL_LABELS[meal],
                    "icon": "🍽",
                    "color": MILESTONE_COLORS["meal"],
                }
            )

    work_commute_slot: int | None = None
    for slot, intent in enumerate(intentions):
        if slot >= 18 and intent == "work":
            work_commute_slot = slot
            break

    prev_aoi: Any = None
    move_count = 0
    last_leave_slot: int | None = None
    for slot, aoi in enumerate(parsed["aoi_ids"]):
        if aoi is None:
            continue
        if (
            prev_aoi is not None
            and home_aoi is not None
            and prev_aoi == home_aoi
            and aoi != home_aoi
        ):
            milestones.append(
                {
                    "slot": slot,
                    "kind": "leave_home",
                    "label": "出门",
                    "icon": "🚪",
                    "color": MILESTONE_COLORS["leave_home"],
                }
            )
            last_leave_slot = slot
        elif (
            prev_aoi is not None
            and aoi != prev_aoi
            and move_count < 3
            and not (last_leave_slot is not None and slot - last_leave_slot <= 2)
        ):
            milestones.append(
                {
                    "slot": slot,
                    "kind": "move",
                    "label": (
                        f"{_aoi_milestone_label(prev_aoi, home_aoi=home_aoi, work_aoi=work_aoi)}"
                        f"→{_aoi_milestone_label(aoi, home_aoi=home_aoi, work_aoi=work_aoi)}"
                    ),
                    "icon": "📍",
                    "color": MILESTONE_COLORS["move"],
                }
            )
            move_count += 1
        prev_aoi = aoi

    if work_commute_slot is not None:
        near_move = any(
            abs(int(m["slot"]) - work_commute_slot) <= 8
            for m in milestones
            if m.get("kind") in {"move", "leave_home", "meal"}
        )
        if not near_move:
            milestones.append(
                {
                    "slot": work_commute_slot,
                    "kind": "commute",
                    "label": "上班",
                    "icon": "🏢",
                    "color": MILESTONE_COLORS["commute"],
                }
            )

    milestones.sort(key=lambda m: int(m["slot"]))
    return milestones


def detect_bedtime_slot(
    intentions: list[str | None], *, after_slot: int = 36
) -> int | None:
    prev: str | None = None
    for i, intent in enumerate(intentions):
        if intent is None:
            continue
        if (
            i >= after_slot
            and prev is not None
            and prev != "sleep"
            and intent == "sleep"
        ):
            return i
        prev = intent
    return None


def collect_artifacts(run_dir: Path, *, agent_id: int = 1) -> dict[str, list[Any]]:
    artifacts = run_dir / "artifacts"
    data: dict[str, list[Any]] = {
        "times": [None] * 48,
        "intentions": [None] * 48,
        "reasons": [None] * 48,
        "locations": [None] * 48,
        "position_kinds": [None] * 48,
        "position_labels": [None] * 48,
        "aoi_ids": [None] * 48,
        "poi_ids": [None] * 48,
        "poi_names": [None] * 48,
        "poi_categories": [None] * 48,
        "statuses": [None] * 48,
        "lngs": [None] * 48,
        "lats": [None] * 48,
        "home_aois": [None] * 48,
        "work_aois": [None] * 48,
        "target_aoi_ids": [None] * 48,
        "artifact_files": [None] * 48,
    }

    if not artifacts.is_dir():
        return data

    for path in sorted(artifacts.glob("questionnaire*.json")):
        raw = read_json_object(path)
        if raw is None:
            continue
        match = SLOT_RE.search(str(raw.get("questionnaire_id", "")))
        if not match:
            continue
        slot = int(match.group(1))
        if slot < 0 or slot >= 48:
            continue

        data["times"][slot] = raw.get("simulation_time")
        data["artifact_files"][slot] = str(path.relative_to(run_dir))
        for resp in raw.get("responses", []):
            try:
                resp_agent_id = int(resp.get("agent_id", -1))
            except (AttributeError, TypeError, ValueError, OverflowError):
                continue
            if resp_agent_id != agent_id:
                continue
            for ans in resp.get("answers", []):
                if ans.get("question_id") != "primary_intention":
                    continue
                val = ans.get("parsed_value") if ans.get("parse_success") else None
                data["intentions"][slot] = val if val in INTENTIONS else "other"
                data["reasons"][slot] = ans.get("reason")

        snapshot = None
        for snap in raw.get("context_snapshots", raw.get("mobility_snapshots", [])):
            try:
                snap_agent_id = int(snap.get("agent_id", -1))
            except (AttributeError, TypeError, ValueError, OverflowError):
                continue
            if snap_agent_id == agent_id:
                snapshot = snap
                break
        if snapshot:
            kind = position_kind_from_snapshot(snapshot)
            label = position_label_from_snapshot(snapshot)
            data["position_kinds"][slot] = kind
            data["position_labels"][slot] = label
            data["locations"][slot] = kind
            data["aoi_ids"][slot] = snapshot.get("aoi_id")
            data["poi_ids"][slot] = snapshot.get("poi_id")
            data["poi_names"][slot] = snapshot.get("poi_name")
            data["poi_categories"][slot] = snapshot.get("poi_category")
            data["statuses"][slot] = snapshot.get("status")
            data["lngs"][slot] = snapshot.get("lng")
            data["lats"][slot] = snapshot.get("lat")
            data["home_aois"][slot] = snapshot.get("home_aoi")
            data["work_aois"][slot] = snapshot.get("work_aoi")
            data["target_aoi_ids"][slot] = snapshot.get("target_aoi_id")
    return data


def collect_slot_questionnaires(run_dir: Path) -> list[dict[str, Any] | None]:
    slots: list[dict[str, Any] | None] = [None] * 48
    artifacts = run_dir / "artifacts"
    if not artifacts.is_dir():
        return slots
    for path in sorted(artifacts.glob("questionnaire*.json")):
        raw = read_json_object(path)
        if raw is None:
            continue
        match = SLOT_RE.search(str(raw.get("questionnaire_id", "")))
        if not match:
            continue
        slot = int(match.group(1))
        if 0 <= slot < 48:
            raw["_artifact_path"] = str(path.relative_to(run_dir))
            slots[slot] = raw
    return slots


def _apply_meal_drops_to_needs_series(
    run_dir: Path,
    agent_id: int,
    out: dict[str, list[float | None]],
) -> None:
    from daily_mobility.intentions import hunger_after_meal

    slot_to_meal = {v: k for k, v in _canonical_meal_slots(run_dir, agent_id).items()}
    for slot, meal in slot_to_meal.items():
        if not (0 <= slot < 48):
            continue
        h = out["hunger"][slot]
        if h is None:
            continue
        out["hunger"][slot] = round(hunger_after_meal(meal, float(h)), 4)


def reconstruct_needs(
    parsed: dict[str, list[Any]],
    *,
    run_dir: Path | None = None,
    agent_id: int = 1,
) -> dict[str, list[float | None]]:
    from daily_mobility.intentions import (
        HUNGER_MEAL_THRESHOLD,
        hunger_after_meal,
    )

    hunger = 0.32
    energy = 0.60
    stress = 0.06
    out = {"hunger": [], "energy": [], "stress": []}
    last_goal = "sleep"
    position_kinds = parsed.get("position_kinds") or [None] * 48
    slot_to_meal: dict[int, str] = {}
    if run_dir is not None:
        slot_to_meal = {
            v: k for k, v in _canonical_meal_slots(run_dir, agent_id).items()
        }

    for slot in range(48):
        t = _parse_time(parsed["times"][slot])
        hour = _hour_fraction(t, slot)
        hours = 0.5

        if "sleep" in last_goal:
            hunger += (0.018 if 5 <= hour < 8 else 0.012) * hours
            energy = min(0.88, energy + 0.09 * hours)  # hours <= 3 always for 0.5h slots
            stress -= 0.07 * hours
        else:
            if 5 <= hour < 8:
                hunger += 0.045 * hours
            elif 8 <= hour < 14:
                hunger += 0.085 * hours
            elif 14 <= hour < 17:
                hunger += 0.038 * hours
            elif 17 <= hour < 21:
                hunger += 0.075 * hours
            else:
                hunger += 0.028 * hours

            if "work" in last_goal:
                energy -= 0.055 * hours
                stress += 0.038 * hours
            elif "home activity" in last_goal:
                energy += 0.035 * hours
                stress -= 0.045 * hours
            elif "leisure" in last_goal:
                energy += 0.03 * hours
                stress -= 0.05 * hours
            else:
                energy -= 0.028 * hours

        hunger = min(1.0, max(0.0, hunger))
        energy = min(1.0, max(0.08, energy))
        stress = min(1.0, max(0.0, stress + (0.02 * hours if energy < 0.35 else 0.0)))

        current = str(parsed["intentions"][slot] or "").lower()
        at_meal_site = position_kinds[slot] == "meal_poi"
        meal = slot_to_meal.get(slot) or _meal_window_for_hour(hour)
        if (
            meal
            and hunger >= HUNGER_MEAL_THRESHOLD
            and (slot in slot_to_meal or "eating out" in current or at_meal_site)
        ):
            hunger = hunger_after_meal(meal, hunger)

        out["hunger"].append(round(hunger, 4))
        out["energy"].append(round(energy, 4))
        out["stress"].append(round(stress, 4))
        last_goal = current or last_goal
    return out


def _slot_index_from_time(value: str | datetime | None, slot: int) -> int:
    dt = (
        value
        if isinstance(value, datetime)
        else _parse_time(str(value) if value else None)
    )
    if dt is not None:
        return max(0, min(47, (dt.hour * 60 + dt.minute) // 30))
    return slot


def load_current_needs(run_dir: Path, *, agent_id: int = 1) -> dict[str, float] | None:
    path = run_dir / "agents" / f"agent_{agent_id:04d}" / "state" / "needs.json"
    raw = read_json_object(path)
    if raw is None:
        return None
    needs = raw.get("needs")
    if not isinstance(needs, dict):
        return None
    return {
        "hunger": float(needs.get("hunger", 0.0)),
        "energy": float(needs.get("energy", 0.0)),
        "stress": float(needs.get("stress", 0.0)),
    }


def load_agent_live_snapshot(
    run_dir: Path, *, agent_id: int = 1
) -> dict[str, Any] | None:
    path = (
        run_dir / "agents" / f"agent_{agent_id:04d}" / "state" / "observation_ctx.json"
    )
    raw = read_json_object(path)
    if raw is None:
        return None
    obs = raw.get("observations") or {}
    person = obs.get("MobilitySpace.get_person")
    if not isinstance(person, dict):
        return None
    position = person.get("position") or {}
    home_aoi = person.get("home_aoi")
    work_aoi = person.get("work_aoi")
    aoi_id = position.get("aoi_id")
    status = str(person.get("status") or "idle")
    target_aoi_id = None
    target = person.get("target")
    if target is not None:
        if hasattr(target, "model_dump"):
            target = target.model_dump()
        if isinstance(target, dict):
            tpos = target.get("position") or {}
            if hasattr(tpos, "model_dump"):
                tpos = tpos.model_dump()
            if isinstance(tpos, dict):
                target_aoi_id = tpos.get("aoi_id")

    snapshot = {
        "agent_id": agent_id,
        "status": status,
        "aoi_id": aoi_id,
        "poi_id": position.get("poi_id"),
        "poi_name": None,
        "poi_category": None,
        "home_aoi": home_aoi,
        "work_aoi": work_aoi,
        "lng": None,
        "lat": None,
        "target_aoi_id": target_aoi_id,
    }
    lnglat = position.get("lnglat")
    if isinstance(lnglat, (list, tuple)) and len(lnglat) >= 2:
        snapshot["lng"] = float(lnglat[0])
        snapshot["lat"] = float(lnglat[1])
    kind = position_kind_from_snapshot(snapshot)
    label = position_label_from_snapshot(snapshot)
    return {
        **snapshot,
        "position_kind": kind,
        "position_label": label,
        "location_label": human_location_label(kind, snapshot.get("poi_name")),
    }


def human_location_label(
    position_kind: str | None,
    poi_name: str | None = None,
) -> str:
    base = {
        "home": "在家",
        "work": "在单位",
        "moving": "通勤途中",
        "meal_poi": "就餐地点",
        "aoi": "在外部地点",
        "unset": "位置未知",
    }.get(position_kind or "", "—")
    if poi_name:
        return f"{base} · {poi_name}"
    return base


def load_needs_history(
    run_dir: Path, parsed: dict[str, list[Any]], *, agent_id: int = 1
) -> dict[str, list[float | None]]:
    history_path = (
        run_dir / "agents" / f"agent_{agent_id:04d}" / "state" / "needs_history.jsonl"
    )
    if not history_path.is_file():
        out = reconstruct_needs(parsed, run_dir=run_dir, agent_id=agent_id)
        _apply_meal_drops_to_needs_series(run_dir, agent_id, out)
        return out

    by_slot: dict[int, dict[str, float]] = {}
    for line in history_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except ValueError:
            continue
        if not isinstance(raw, dict):
            continue
        needs = raw.get("needs")
        t = raw.get("time")
        if not isinstance(needs, dict):
            continue
        slot = _slot_index_from_time(t, len(by_slot))
        by_slot[slot] = {
            "hunger": float(needs.get("hunger", 0.0)),
            "energy": float(needs.get("energy", 0.0)),
            "stress": float(needs.get("stress", 0.0)),
        }

    fallback = reconstruct_needs(parsed, run_dir=run_dir, agent_id=agent_id)
    out: dict[str, list[float | None]] = {"hunger": [], "energy": [], "stress": []}
    last: dict[str, float] | None = None
    for slot in range(48):
        current = by_slot.get(slot)
        if current is None:
            current = last
        if current is None:
            for key in out:
                out[key].append(fallback[key][slot])
        else:
            for key in out:
                out[key].append(round(current[key], 4))
            last = current

    current = load_current_needs(run_dir, agent_id=agent_id)
    done = sum(v is not None for v in parsed["intentions"])
    if current and done > 0:
        idx = min(done, 47)
        for key in out:
            out[key][idx] = round(current[key], 4)
        if done < 48:
            for key in out:
                out[key][done] = round(current[key], 4)
    _apply_meal_drops_to_needs_series(run_dir, agent_id, out)
    return out


def parse_action_events(
    log_file: Path, *, agent_id: int | None = None
) -> list[dict[str, Any]]:
    if not log_file.is_file():
        return []
    events: list[dict[str, Any]] = []
    patterns = [
        (re.compile(r"mobility meal search ok=(True|False)"), "meal"),
        (
            re.compile(r"mobility enforce target=(\d+) mode=(\w+) ok=(True|False)"),
            "move",
        ),
    ]
    agent_tag = f"Agent {agent_id}:" if agent_id is not None else None
    for line in log_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        if agent_tag is not None:
            other_agent = re.search(r"Agent (\d+):", line)
            if other_agent and other_agent.group(0) != agent_tag:
                continue
        m_time = re.search(r"\d{4}-\d{2}-\d{2}_(\d{2})(\d{2})00", line)
        slot = None
        if m_time:
            hour = int(m_time.group(1))
            minute = int(m_time.group(2))
            slot = max(0, min(47, int((hour + minute / 60) * 2)))
        for regex, kind in patterns:
            match = regex.search(line)
            if match:
                if slot is None:
                    slot = len(events)
                events.append(
                    {
                        "slot": slot,
                        "kind": kind,
                        "label": match.group(0),
                        "line": line.strip()[-240:],
                    }
                )
    return events


def _first_non_null(values: list[Any]) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _agent_ids_from_init_config(path: Path) -> list[int]:
    raw = read_json_object(path)
    if raw is None:
        return []
    ids: set[int] = set()
    for module in raw.get("env_modules", []):
        if not isinstance(module, dict):
            continue
        kwargs = module.get("kwargs")
        if not isinstance(kwargs, dict):
            continue
        for person in kwargs.get("persons", []):
            if isinstance(person, dict) and isinstance(person.get("id"), int):
                ids.add(int(person["id"]))
    for agent in raw.get("agents", []):
        if not isinstance(agent, dict):
            continue
        aid = agent.get("agent_id")
        if isinstance(aid, int):
            ids.add(aid)
            continue
        kwargs = agent.get("kwargs")
        if isinstance(kwargs, dict) and isinstance(kwargs.get("id"), int):
            ids.add(int(kwargs["id"]))
    return sorted(ids)


def discover_agent_ids(run_dir: Path) -> list[int]:
    found: set[int] = set()
    agents_dir = run_dir / "agents"
    if agents_dir.is_dir():
        for path in agents_dir.iterdir():
            if not path.is_dir() or not path.name.startswith("agent_"):
                continue
            try:
                found.add(int(path.name.split("_", 1)[1]))
            except (IndexError, ValueError):
                continue
    artifacts = run_dir / "artifacts"
    if artifacts.is_dir():
        for path in artifacts.glob("questionnaire*.json"):
            raw = read_json_object(path)
            if raw is None:
                continue
            for snap in raw.get("context_snapshots", raw.get("mobility_snapshots", [])):
                aid = snap.get("agent_id")
                if isinstance(aid, int):
                    found.add(aid)
            for resp in raw.get("responses", []):
                aid = resp.get("agent_id")
                if isinstance(aid, int):
                    found.add(aid)
    init_path = run_dir / "init_config.json"
    if not init_path.is_file():
        init_path = run_dir.parent / "init" / "init_config.json"
    if init_path.is_file():
        found.update(_agent_ids_from_init_config(init_path))
    if not found:
        found.add(1)
    return sorted(found)


ACTIVITY_CATEGORY_LABELS = {
    "env": "环境调用",
    "observe": "观察",
    "ask_env": "Codegen",
    "skill": "技能执行",
    "tool": "工作区/工具",
    "plan": "移动计划",
    "harness": "Harness",
    "needs": "需求",
    "step": "仿真步",
    "questionnaire": "问卷",
    "llm": "LLM 决策",
    "behavior": "行为追踪",
    "system": "系统",
}

ACTIVITY_CATEGORY_COLORS = {
    "env": "#2563eb",
    "observe": "#0d9488",
    "ask_env": "#7c3aed",
    "skill": "#059669",
    "tool": "#64748b",
    "plan": "#2471a3",
    "harness": "#dc2626",
    "needs": "#e67e22",
    "step": "#475569",
    "questionnaire": "#9b59b6",
    "llm": "#6366f1",
    "behavior": "#78716c",
    "system": "#94a3b8",
}

_TOOL_ACTION_LABELS = {
    "workspace_read": "读取文件",
    "workspace_write": "写入文件",
    "activate_skill": "激活技能",
    "execute_skill": "执行技能",
    "ask_env": "Codegen",
    "done": "结束步进",
    "finish": "完成",
}


def _activity_record(
    *,
    category: str,
    kind: str,
    label: str,
    summary: str,
    detail: str = "",
    slot: int | None = None,
    simulation_time: str | None = None,
    timestamp: str | None = None,
    ok: bool | None = True,
    source: str = "",
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "category": category,
        "kind": kind,
        "label": label,
        "summary": summary,
        "detail": detail,
        "slot": slot,
        "simulation_time": simulation_time,
        "timestamp": timestamp,
        "ok": ok,
        "source": source,
        "meta": meta or {},
    }


def _tool_log_category(entry: dict[str, Any]) -> str:
    action = str(entry.get("action") or "tool")
    if action == "execute_skill":
        return "skill"
    if action == "ask_env":
        stdout = str(entry.get("stdout") or "")
        if any(
            token in stdout
            for token in (
                "checked their current position",
                "get_person",
                "MobilitySpace.get_person",
            )
        ):
            return "observe"
        return "ask_env"
    if action == "workspace_read":
        path = str(entry.get("path") or "")
        if "observation" in path:
            return "observe"
        return "tool"
    if action in {"activate_skill"}:
        return "skill"
    return "tool"


def _summarize_tool_entry(entry: dict[str, Any]) -> tuple[str, str, str]:
    action = str(entry.get("action") or "tool")
    path = str(entry.get("path") or "")
    if action == "workspace_write" and "mobility_plan.json" in path:
        return "移动计划", path, "mobility_plan"
    if action == "workspace_write" and "meal_state.json" in path:
        return "记餐状态", path, "tool"
    label = _TOOL_ACTION_LABELS.get(action, action)
    if action == "workspace_read":
        summary = path or "—"
        detail = str(entry.get("content") or "")[:400]
        return label, summary if not detail else f"{summary} · {len(detail)} chars", "tool"
    if action == "workspace_write":
        return label, path or "—", "tool"
    if action == "activate_skill":
        return label, str(entry.get("skill_name") or "—"), "skill"
    if action == "execute_skill":
        summary = str(entry.get("skill_name") or "—")
        stderr = str(entry.get("stderr") or entry.get("stdout") or "")
        return label, summary if not stderr else f"{summary} · {stderr[:120]}", "skill"
    if action == "ask_env":
        stdout = str(entry.get("stdout") or entry.get("stderr") or "—")
        return label, stdout[:240], _tool_log_category(entry)
    if entry.get("error"):
        return label, str(entry.get("error"))[:240], "tool"
    return label, str(entry.get("stdout") or path or action)[:240], "tool"


def _load_tool_calls_jsonl(path: Path, *, agent_id: int) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(raw, dict):
            continue
        category = _tool_log_category(raw)
        label, summary, cat_override = _summarize_tool_entry(raw)
        if cat_override == "mobility_plan":
            category = "plan"
        elif cat_override in {"skill", "observe", "ask_env"}:
            category = cat_override
        sim_time = raw.get("time")
        slot = _slot_index_from_time(sim_time, len(out))
        out.append(
            _activity_record(
                category=category,
                kind=str(raw.get("action") or "tool"),
                label=label,
                summary=summary,
                detail=json.dumps(
                    {
                        k: raw[k]
                        for k in raw
                        if k
                        not in {
                            "content",
                            "stdout",
                            "stderr",
                        }
                    },
                    ensure_ascii=False,
                )[:800],
                slot=slot,
                simulation_time=str(sim_time) if sim_time else None,
                ok=bool(raw.get("ok", True)),
                source="tool_calls.jsonl",
                meta={"skill_name": raw.get("skill_name"), "path": raw.get("path")},
            )
        )
    return out


def _load_step_replay_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        tools = raw.get("tool_history") or []
        kinds = Counter(
            str(t.get("action") or "?") for t in tools if isinstance(t, dict)
        )
        summary = ", ".join(f"{k}×{v}" for k, v in kinds.most_common(6)) or "无工具"
        sim_time = raw.get("time")
        slot = _slot_index_from_time(sim_time, len(out))
        out.append(
            _activity_record(
                category="step",
                kind="person_step",
                label="仿真步",
                summary=f"{summary} · {raw.get('step_end_reason') or 'done'}",
                detail=json.dumps(
                    {
                        "selected_skills": raw.get("selected_skills"),
                        "step_end_reason": raw.get("step_end_reason"),
                        "tool_count": len(tools),
                    },
                    ensure_ascii=False,
                ),
                slot=slot,
                simulation_time=str(sim_time) if sim_time else None,
                ok=True,
                source="step_replay.jsonl",
            )
        )
    return out


def _load_needs_activity(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        needs = raw.get("needs")
        if not isinstance(needs, dict):
            continue
        sim_time = raw.get("time")
        slot = _slot_index_from_time(sim_time, len(out))
        summary = (
            f"hunger={float(needs.get('hunger', 0)):.2f} "
            f"energy={float(needs.get('energy', 0)):.2f} "
            f"stress={float(needs.get('stress', 0)):.2f}"
        )
        out.append(
            _activity_record(
                category="needs",
                kind="needs_decay",
                label="需求更新",
                summary=summary,
                slot=slot,
                simulation_time=str(sim_time) if sim_time else None,
                ok=True,
                source="needs_history.jsonl",
            )
        )
    return out


def _load_agent_log_activity(log_file: Path, *, agent_id: int) -> list[dict[str, Any]]:
    if not log_file.is_file():
        return []
    tag = f"Agent {agent_id}:"
    patterns: list[tuple[re.Pattern[str], str, str, str]] = [
        (
            re.compile(
                rf"{re.escape(tag)} harness move target=(\d+) mode=(\w+) ok=(True|False)"
            ),
            "harness",
            "harness_move",
            "Harness 移动",
        ),
        (
            re.compile(rf"{re.escape(tag)} mobility meal search ok=(True|False)"),
            "harness",
            "meal_search",
            "搜索餐厅",
        ),
        (
            re.compile(
                rf"{re.escape(tag)} mobility enforce target=(\d+) mode=(\w+) ok=(True|False)"
            ),
            "harness",
            "enforce_commute",
            "强制通勤",
        ),
        (
            re.compile(rf"{re.escape(tag)} pending .* meal (\w+) ok=(True|False)"),
            "harness",
            "enforce_meal",
            "强制就餐",
        ),
        (
            re.compile(rf"{re.escape(tag)} compact .* focus='([^']*)'"),
            "system",
            "context_compact",
            "上下文压缩",
        ),
        (
            re.compile(rf"{re.escape(tag)} handed off state to memory"),
            "system",
            "memory_handoff",
            "写入记忆",
        ),
        (
            re.compile(rf"{re.escape(tag)} mobility harness observe missing"),
            "harness",
            "harness_warn",
            "Harness 告警",
        ),
    ]
    out: list[dict[str, Any]] = []
    for line in log_file.read_text(encoding="utf-8", errors="ignore").splitlines():
        if tag not in line:
            continue
        sim_time = log_simulation_time(line)
        stamp = _parse_time(sim_time)
        slot = (stamp.hour * 60 + stamp.minute) // 30 if stamp else None
        matched = False
        for regex, category, kind, label in patterns:
            match = regex.search(line)
            if not match:
                continue
            ok = "False" not in match.group(0)
            summary = match.group(0).split(tag, 1)[-1].strip()[:200]
            out.append(
                _activity_record(
                    category=category,
                    kind=kind,
                    label=label,
                    summary=summary,
                    slot=slot,
                    simulation_time=sim_time,
                    ok=ok,
                    source="output.log",
                )
            )
            matched = True
            break
        if not matched and "ERROR" in line and tag in line:
            out.append(
                _activity_record(
                    category="system",
                    kind="error",
                    label="错误",
                    summary=line.strip()[-240:],
                    slot=slot,
                    simulation_time=sim_time,
                    ok=False,
                    source="output.log",
                )
            )
    return out


_BEHAVIOR_STEP_END_REASONS = frozenset(
    {
        "max_tool_rounds",
        "step_timeout",
        "ask_env_loop",
        "env_in_progress",
        "loop_detected",
    }
)


def _load_behavior_trace_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        event_type = str(raw.get("event_type") or "")
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        tick = raw.get("tick")
        sim_time = None
        slot = None
        if isinstance(tick, (int, float)) and tick >= 1800:
            slot = max(0, min(47, int(tick) // 1800))

        if event_type == "skill_activate":
            skill = str(data.get("skill") or raw.get("name") or "skill")
            out.append(
                _activity_record(
                    category="behavior",
                    kind="skill_activate",
                    label="技能激活",
                    summary=skill,
                    slot=slot,
                    simulation_time=sim_time,
                    timestamp=raw.get("timestamp"),
                    ok=True,
                    source="behavior_trace.jsonl",
                )
            )
            continue

        if event_type == "error":
            err = str(raw.get("error") or data.get("error") or "unknown")[:240]
            out.append(
                _activity_record(
                    category="behavior",
                    kind="runtime_error",
                    label="运行错误",
                    summary=err,
                    slot=slot,
                    simulation_time=sim_time,
                    timestamp=raw.get("timestamp"),
                    ok=False,
                    source="behavior_trace.jsonl",
                )
            )
            continue

        if event_type != "step_end":
            continue
        reason = str(data.get("step_end_reason") or "")
        if reason not in _BEHAVIOR_STEP_END_REASONS:
            continue
        summary = (
            f"{reason} · tools={data.get('tool_count', '?')} "
            f"logs={data.get('log_count', '?')}"
        )
        out.append(
            _activity_record(
                category="behavior",
                kind="step_end",
                label="步进异常结束",
                summary=summary,
                slot=slot,
                simulation_time=sim_time,
                timestamp=raw.get("timestamp"),
                ok=False,
                source="behavior_trace.jsonl",
                meta={"step_end_reason": reason},
            )
        )
    return out


def _load_llm_decisions_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError:
            continue
        if raw.get("role") != "assistant":
            continue
        content = raw.get("content")
        if not isinstance(content, str) or not content.strip().startswith("{"):
            continue
        try:
            decision = json.loads(content)
        except json.JSONDecodeError:
            continue
        if not isinstance(decision, dict):
            continue
        tool = decision.get("tool_name")
        if not tool:
            continue
        summary = str(decision.get("summary") or tool)
        done = decision.get("done")
        if done is True:
            summary = f"{summary} · done"
        sim_time = raw.get("time")
        slot = _slot_index_from_time(sim_time, len(out))
        out.append(
            _activity_record(
                category="llm",
                kind=str(tool),
                label="LLM 工具选择",
                summary=summary[:240],
                detail=json.dumps(decision.get("arguments") or {}, ensure_ascii=False)[
                    :400
                ],
                slot=slot,
                simulation_time=str(sim_time) if sim_time else None,
                ok=True,
                source="thread_messages.jsonl",
            )
        )
    return out


def load_agent_activity_log(
    run_dir: Path,
    log_file: Path | None = None,
    *,
    agent_id: int,
    slots: list[dict[str, Any]] | None = None,
    limit: int = 1200,
) -> dict[str, Any]:
    log_path = log_file or (run_dir / "output.log")
    agent_root = run_dir / "agents" / f"agent_{agent_id:04d}"
    runtime_logs = agent_root / ".runtime" / "logs"

    records: list[dict[str, Any]] = []

    env_trace = load_env_tool_calls(
        log_path.parent, log_path, agent_id=agent_id, limit=limit
    )
    for raw in env_trace.get("calls") or []:
        records.append(
            _activity_record(
                category="env",
                kind=str(raw.get("function_name") or "env"),
                label=str(
                    raw.get("function_label") or raw.get("function_name") or "env"
                ),
                summary=str(raw.get("kwargs_summary") or "—"),
                detail=str(raw.get("return_summary") or ""),
                slot=raw.get("slot"),
                simulation_time=raw.get("simulation_time"),
                timestamp=raw.get("timestamp"),
                ok=bool(raw.get("ok", True)),
                source=str(raw.get("source") or "env_tool"),
                meta={
                    "module_name": raw.get("module_name"),
                    "step_type": raw.get("step_type"),
                },
            )
        )

    records.extend(
        _load_tool_calls_jsonl(runtime_logs / "tool_calls.jsonl", agent_id=agent_id)
    )
    records.extend(_load_step_replay_jsonl(runtime_logs / "step_replay.jsonl"))
    records.extend(_load_needs_activity(agent_root / "state" / "needs_history.jsonl"))
    records.extend(_load_agent_log_activity(log_path, agent_id=agent_id))
    records.extend(_load_behavior_trace_jsonl(runtime_logs / "behavior_trace.jsonl"))
    records.extend(_load_llm_decisions_jsonl(runtime_logs / "thread_messages.jsonl"))

    if slots:
        for s in slots:
            if not s.get("filled"):
                continue
            intention = s.get("intention")
            if not intention:
                continue
            records.append(
                _activity_record(
                    category="questionnaire",
                    kind="primary_intention",
                    label="问卷意图",
                    summary=str(intention),
                    detail=str(
                        (s.get("questionnaire") or {}).get("questionnaire_id") or ""
                    ),
                    slot=s.get("slot"),
                    simulation_time=s.get("simulation_time"),
                    ok=True,
                    source="artifacts",
                )
            )

    records.sort(
        key=lambda r: (
            r.get("simulation_time") or "",
            r.get("timestamp") or "",
            r.get("slot") if r.get("slot") is not None else -1,
        )
    )
    if len(records) > limit:
        records = records[-limit:]

    by_category: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    failures = 0
    for r in records:
        cat = str(r.get("category") or "tool")
        kind = str(r.get("kind") or cat)
        by_category[cat] = by_category.get(cat, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if r.get("ok") is False:
            failures += 1

    return {
        "records": records,
        "summary": {
            "total": len(records),
            "failures": failures,
            "by_category": by_category,
            "by_kind": by_kind,
        },
        "category_labels": ACTIVITY_CATEGORY_LABELS,
        "category_colors": ACTIVITY_CATEGORY_COLORS,
    }


def build_dashboard_payload(
    run_dir: Path,
    log_file: Path | None = None,
    *,
    agent_id: int = 1,
    steps_yaml: Path | None = None,
) -> dict[str, Any]:
    if steps_yaml is None:
        steps_yaml = run_dir / "steps.yaml"
        if not steps_yaml.is_file():
            steps_yaml = run_dir.parent / "init" / "steps.yaml"
    tick_sec, sim_start = read_step_timing(steps_yaml)
    timing = load_run_timing(run_dir, tick_sec=tick_sec, sim_start=sim_start)

    available_agents = discover_agent_ids(run_dir)
    if agent_id not in available_agents:
        agent_id = available_agents[0]

    parsed = collect_artifacts(run_dir, agent_id=agent_id)
    prepare_timeline_intentions(run_dir, agent_id, parsed)
    needs = load_needs_history(run_dir, parsed, agent_id=agent_id)
    events = parse_action_events(
        log_file or (run_dir / "output.log"), agent_id=agent_id
    )
    questionnaires = collect_slot_questionnaires(run_dir)
    intentions = parsed["intentions"]
    done = sum(v is not None for v in intentions)
    milestones = milestones_from_meal_state(
        run_dir, agent_id, detect_milestones(parsed, intentions)
    )

    positions: list[dict[str, Any]] = []
    for slot in range(48):
        if parsed["lngs"][slot] is None or parsed["lats"][slot] is None:
            continue
        positions.append(
            {
                "slot": slot,
                "lng": parsed["lngs"][slot],
                "lat": parsed["lats"][slot],
                "intention": parsed["intentions"][slot],
                "position_kind": parsed["position_kinds"][slot],
                "position_label": parsed["position_labels"][slot],
                "aoi_id": parsed["aoi_ids"][slot],
                "status": parsed["statuses"][slot],
            }
        )

    live_snap = load_agent_live_snapshot(run_dir, agent_id=agent_id)
    live_needs = load_current_needs(run_dir, agent_id=agent_id)
    last_filled = max(
        (i for i, v in enumerate(intentions) if v is not None), default=-1
    )
    intent_mismatch = False
    if live_snap and last_filled >= 0:
        last_intent = intentions[last_filled]
        live_kind = live_snap.get("position_kind")
        if last_intent in ("home activity", "sleep") and live_kind == "work":
            intent_mismatch = True
        if last_intent == "eating out" and live_kind == "work":
            intent_mismatch = True

    slots: list[dict[str, Any]] = []
    for slot in range(48):
        filled = parsed["intentions"][slot] is not None
        slots.append(
            {
                "slot": slot,
                "time_label": slot_time_label(parsed, slot),
                "simulation_time": parsed["times"][slot],
                "filled": filled,
                "intention": parsed["intentions"][slot],
                "reason": parsed["reasons"][slot],
                "position_kind": parsed["position_kinds"][slot],
                "position_label": parsed["position_labels"][slot],
                "aoi_id": parsed["aoi_ids"][slot],
                "home_aoi": parsed["home_aois"][slot],
                "work_aoi": parsed["work_aois"][slot],
                "poi_id": parsed["poi_ids"][slot],
                "poi_name": parsed["poi_names"][slot],
                "poi_category": parsed["poi_categories"][slot],
                "status": parsed["statuses"][slot],
                "target_aoi_id": parsed["target_aoi_ids"][slot],
                "lng": parsed["lngs"][slot],
                "lat": parsed["lats"][slot],
                "artifact_file": parsed["artifact_files"][slot],
                "needs": {
                    "hunger": needs["hunger"][slot],
                    "energy": needs["energy"][slot],
                    "stress": needs["stress"][slot],
                },
                "questionnaire": questionnaires[slot],
            }
        )

    env_trace = load_env_tool_calls(
        run_dir, log_file or (run_dir / "output.log"), agent_id=agent_id
    )

    rhythm = load_agent_rhythm_state(run_dir, agent_id=agent_id)
    schedule_blocks = rhythm.get("daily_schedule") if isinstance(rhythm, dict) else None
    schedule_blocks = schedule_blocks if isinstance(schedule_blocks, list) else []
    schedule_slots = expand_schedule_to_slots(schedule_blocks)
    for slot in range(48):
        plan = schedule_slots[slot]
        if plan:
            slots[slot]["plan"] = plan
            slots[slot]["plan_intention"] = plan["intention"]
        else:
            slots[slot]["plan"] = None
            slots[slot]["plan_intention"] = None

    activity_log = load_agent_activity_log(
        run_dir,
        log_file or (run_dir / "output.log"),
        agent_id=agent_id,
        slots=slots,
    )

    return {
        "meta": {
            "slots_done": done,
            "total_slots": 48,
            "agent_id": agent_id,
            "available_agents": available_agents,
            "updated_at": datetime.now(UTC).isoformat(),
            "run_dir": str(run_dir.resolve()),
            "intent_position_mismatch": intent_mismatch,
        },
        "live": {
            "snapshot": live_snap,
            "needs": live_needs,
            "location_label": live_snap.get("location_label") if live_snap else None,
        },
        "env_calls": env_trace,
        "activity_log": activity_log,
        "timing": timing,
        "milestones": milestones,
        "milestone_colors": MILESTONE_COLORS,
        "home_aoi": _first_non_null(parsed["home_aois"]),
        "work_aoi": _first_non_null(parsed["work_aois"]),
        "intention_colors": INTENTION_COLORS,
        "location_colors": POSITION_KIND_COLORS,
        "position_kind_colors": POSITION_KIND_COLORS,
        "wake_slot": detect_wake_slot(intentions, parsed["times"]),
        "bedtime_slot": detect_bedtime_slot(intentions),
        "intent_mix": dict(Counter(v for v in intentions if v)),
        "location_mix": dict(Counter(v for v in parsed["position_kinds"] if v)),
        "times": parsed["times"],
        "intentions": intentions,
        "position_kinds": parsed["position_kinds"],
        "position_labels": parsed["position_labels"],
        "needs": needs,
        "events": events,
        "positions": positions,
        "slots": slots,
        "schedule": {
            "available": bool(schedule_blocks),
            "blocks": schedule_blocks,
            "slots": schedule_slots,
            "scheduled_activity": rhythm.get("scheduled_activity") if rhythm else None,
            "daily_diary": rhythm.get("daily_diary") if rhythm else None,
            "preferences": rhythm.get("preferences") if rhythm else None,
            "norm_strength": rhythm.get("norm_strength") if rhythm else None,
            "activity_colors": SCHEDULE_ACTIVITY_COLORS,
            "activity_labels": SCHEDULE_ACTIVITY_LABELS,
        },
    }


def write_summary(parsed: dict[str, list[Any]], out_path: Path) -> None:
    summary = {
        "slots_done": sum(v is not None for v in parsed["intentions"]),
        "intent_mix": dict(Counter(parsed["intentions"])),
        "location_mix": dict(Counter(parsed["position_kinds"])),
        "aoi_changes": [],
    }
    prev = object()
    for i, aoi in enumerate(parsed["aoi_ids"]):
        if aoi != prev:
            summary["aoi_changes"].append(
                {
                    "slot": i,
                    "time": parsed["times"][i],
                    "intention": parsed["intentions"][i],
                    "position_kind": parsed["position_kinds"][i],
                    "position_label": parsed["position_labels"][i],
                    "aoi_id": aoi,
                    "poi_id": parsed["poi_ids"][i],
                    "poi_name": parsed["poi_names"][i],
                }
            )
            prev = aoi
    out_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
