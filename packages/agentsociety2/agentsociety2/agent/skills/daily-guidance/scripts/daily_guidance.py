from __future__ import annotations

import argparse
import contextvars
import json
import os
import re
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

VALID_REQUIRED = {"required", "soft_required", "optional"}
VALID_TPB_STATUS = {"supported", "weak", "missing", "contradicted"}
VALID_CHOICE = {"commit", "revise", "delay", "skip", "observe"}
TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
COMMAND_NAMES = {
    "init",
    "plan",
    "check",
    "current",
    "show",
    "record",
    "deviate",
    "revise",
}

DEVIATION_ACTIONS = {
    "record_only": "append change_log only; story segments unchanged",
    "local_patch": "edit the current or adjacent segment, then run check",
    "rewrite_remaining_day": "rewrite segments from the current one onward, then run check",
    "carryover": "append change_log; account for this when generating tomorrow's story",
}

FIELD_MEANINGS = {
    "story.yaml": "the daily story YAML file for one date",
    "id": "short unique segment identifier",
    "start": "segment start time in HH:MM",
    "end": "segment end time in HH:MM",
    "activity": "main behavior type, such as sleep, work, meal, commute, leisure",
    "maslow_reason": "why this segment serves a human need",
    "need": "one Maslow-style need label; custom labels are allowed",
    "reason": "short explanation",
    "risk": "what becomes unrealistic if this segment is missing",
    "required": "required, soft_required, or optional",
    "tpb_reason": "why this segment is intended and feasible",
    "want": "why the agent wants or accepts this behavior",
    "norm": "TPB social norm: why this fits role or social expectation",
    "can": "TPB control: why the agent can do this now",
    "proof": "one short sentence with profile, time, location, or observation basis",
    "choice": "commit, revise, delay, skip, or observe",
    "self_check": "post-generation Maslow and TPB review result",
    "change_log": "short event list explaining story creation or later changes",
}

TODO_STORY = """# TODO daily-guidance story.yaml
# Fill this file before daily behavior execution.
# Required top-level fields:
# story_id, date, status, segments, self_check, execution, change_log
# Run:
# python scripts/daily_guidance.py check --date YYYY-MM-DD
"""


def _reason(
    need: str, reason: str, risk: str, required: str = "required"
) -> dict[str, str]:
    """Build one Maslow reason block.

    :param need: Need label served by the segment.
    :param reason: Short explanation for the segment.
    :param risk: What becomes implausible without this segment.
    :param required: Requirement strength.
    :returns: Maslow reason dictionary."""
    return {
        "need": need,
        "reason": reason,
        "risk": risk,
        "required": required,
    }


def _tpb(proof: str, choice: str = "commit") -> dict[str, Any]:
    """Build one TPB reason block.

    :param proof: Short proof string.
    :param choice: Behavioral choice label.
    :returns: TPB reason dictionary."""
    return {
        "want": {"reason": "This keeps the day coherent.", "status": "supported"},
        "norm": {"reason": "This fits ordinary daily routines.", "status": "supported"},
        "can": {
            "reason": "The agent has the time and location context.",
            "status": "supported",
        },
        "proof": proof,
        "choice": choice,
    }


def default_story_for_date(date: str, agent_id: int = 0) -> dict[str, Any]:
    """Create a valid fallback daily story.

    :param date: Story date in YYYY-MM-DD form.
    :param agent_id: Numeric agent id used in the story id.
    :returns: Schema-valid story dictionary."""
    segments = [
        {
            "id": "sleep_night",
            "start": "00:00",
            "end": "07:00",
            "activity": "sleep",
            "location_policy": "home_aoi",
            "maslow_reason": _reason(
                "physiological.rest",
                "Night sleep keeps the agent rested.",
                "The day becomes unrealistic without sleep.",
            ),
            "tpb_reason": _tpb("Night time at home supports sleep."),
        },
        {
            "id": "morning_home",
            "start": "07:00",
            "end": "08:00",
            "activity": "home activity",
            "location_policy": "home_aoi",
            "maslow_reason": _reason(
                "physiological.food",
                "Morning preparation and breakfast support the day.",
                "Skipping preparation makes later activity abrupt.",
                "soft_required",
            ),
            "tpb_reason": _tpb("Morning at home supports preparation."),
        },
        {
            "id": "commute_to_work",
            "start": "08:00",
            "end": "09:00",
            "activity": "commute",
            "location_policy": "transit",
            "maslow_reason": _reason(
                "safety.income_stability",
                "Commuting enables work participation.",
                "Work cannot start plausibly without travel.",
            ),
            "tpb_reason": _tpb("Workday profile supports commuting."),
        },
        {
            "id": "work_morning",
            "start": "09:00",
            "end": "12:00",
            "activity": "work",
            "location_policy": "work_aoi",
            "maslow_reason": _reason(
                "esteem.role_obligation",
                "Work fulfills the agent's role obligation.",
                "A working profile needs a work block.",
            ),
            "tpb_reason": _tpb("The agent has a work AOI and occupation."),
        },
        {
            "id": "lunch",
            "start": "12:00",
            "end": "13:00",
            "activity": "meal",
            "location_policy": "near_work_aoi",
            "maslow_reason": _reason(
                "physiological.food",
                "Lunch maintains energy.",
                "Skipping meals lowers plausibility.",
            ),
            "tpb_reason": _tpb("Lunch time near work supports eating."),
        },
        {
            "id": "work_afternoon",
            "start": "13:00",
            "end": "17:00",
            "activity": "work",
            "location_policy": "work_aoi",
            "maslow_reason": _reason(
                "safety.income_stability",
                "Afternoon work continues the main role.",
                "The workday would be too short without it.",
            ),
            "tpb_reason": _tpb("Afternoon work follows lunch."),
        },
        {
            "id": "commute_home",
            "start": "17:00",
            "end": "18:00",
            "activity": "commute",
            "location_policy": "transit",
            "maslow_reason": _reason(
                "safety.home_shelter",
                "Returning home supports evening shelter.",
                "The agent needs a night location.",
            ),
            "tpb_reason": _tpb("End of workday supports returning home."),
        },
        {
            "id": "evening_home",
            "start": "18:00",
            "end": "22:00",
            "activity": "home activity",
            "location_policy": "home_aoi",
            "maslow_reason": _reason(
                "recovery.leisure",
                "Evening home time supports recovery.",
                "The day lacks recovery without downtime.",
                "soft_required",
            ),
            "tpb_reason": _tpb("Evening at home supports rest and chores."),
        },
        {
            "id": "sleep_late",
            "start": "22:00",
            "end": "24:00",
            "activity": "sleep",
            "location_policy": "home_aoi",
            "maslow_reason": _reason(
                "physiological.rest",
                "Late evening sleep prepares the next day.",
                "The day would not close with rest.",
            ),
            "tpb_reason": _tpb("Night time at home supports sleep."),
        },
    ]
    return build_story_from_plan(
        {
            "story_id": f"agent_{agent_id:04d}:{date}:default",
            "date": date,
            "segments": segments,
            "self_check": {
                "maslow_result": "pass",
                "tpb_result": "pass",
                "issues": [
                    "default story generated by daily_guidance hook; agent may revise it"
                ],
            },
        }
    )


# In-process execution context (set by ``entrypoint``). These are
# ``contextvars`` so 50 agents running their hooks concurrently in one process
# each see their own workspace / emit buffer without racing on globals.
_WORKSPACE_ROOT: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "dg_workspace_root", default=None
)
_EMIT_BUFFER: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "dg_emit_buffer", default=None
)


def agent_work_dir() -> Path:
    """Resolve this agent's workspace root.

    Prefers the in-process context var; falls back to the ``AGENT_WORK_DIR``
    env var (subprocess path) and finally the current directory.
    """
    override = _WORKSPACE_ROOT.get()
    if override is not None:
        return override
    raw = os.environ.get("AGENT_WORK_DIR")
    return Path(raw).resolve() if raw else Path.cwd().resolve()


def parse_hook_time(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    return datetime.fromisoformat(text)


def story_path_for_date(date: str, root: Path | None = None) -> Path:
    base = root or agent_work_dir()
    return base / "state" / "daily_guidance" / date / "story.yaml"


def write_todo_file(path: Path, *, force: bool = False) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return False
    path.write_text(TODO_STORY, encoding="utf-8")
    return True


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def write_yaml(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def emit(payload: dict[str, Any]) -> None:
    """Emit a deterministic YAML result block for the agent to read.

    In-process (entrypoint) mode appends to the per-call emit buffer instead of
    printing, so concurrent agents do not race on the process-global stdout.
    """
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    buffer = _EMIT_BUFFER.get()
    if buffer is not None:
        buffer.append(text)
    else:
        print(text)


def read_sim_time(root: Path | None = None) -> datetime | None:
    """Read the current simulation time written by the agent each step.

    PersonAgent persists ``AGENT.json`` with a ``current_time`` field at the
    start of every step. This is the deterministic clock the CLI uses; no LLM
    and no wall-clock involved.
    """
    base = root or agent_work_dir()
    agent_path = base / "AGENT.json"
    if not agent_path.is_file():
        return None
    try:
        data = json.loads(agent_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    raw = data.get("current_time")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return parse_hook_time(raw)
    except Exception:
        return None


def require_sim_time(root: Path, mode: str) -> datetime | None:
    """Return the deterministic simulation clock or emit an error.

    :param root: Agent workspace root.
    :param mode: CLI mode name used in the emitted error payload.
    :returns: Parsed simulation time, or None when unavailable."""
    sim_time = read_sim_time(root)
    if sim_time is None:
        emit(
            {
                "ok": False,
                "mode": mode,
                "reason": "could not read AGENT.json current_time",
            }
        )
    return sim_time


def validate_command_date(
    args: argparse.Namespace, root: Path, mode: str
) -> datetime | None:
    """Normalize ``--date`` to the deterministic simulation clock date.

    :param args: Parsed command namespace with a ``date`` attribute.
    :param root: Agent workspace root.
    :param mode: CLI mode name used in the emitted error payload.
    :returns: Parsed simulation time when available, otherwise None."""
    sim_time = require_sim_time(root, mode)
    if sim_time is None:
        return None
    sim_date = sim_time.date().isoformat()
    date = getattr(args, "date", "")
    if date and date != sim_date:
        args.corrected_date = {"from": date, "to": sim_date}
    elif not hasattr(args, "corrected_date"):
        args.corrected_date = None
    args.date = sim_date
    return sim_time


def normalize_plan_to_sim_date(plan: dict[str, Any], sim_date: str) -> dict[str, Any]:
    """Return a plan copy whose date-owned fields follow the simulation date.

    :param plan: Validated plan payload.
    :param sim_date: Date derived from the deterministic simulation clock.
    :returns: Plan copy with ``date`` set to sim_date and simple story_id dates updated."""
    normalized = dict(plan)
    original_date = str(normalized.get("date", ""))
    normalized["date"] = sim_date
    story_id = normalized.get("story_id")
    if isinstance(story_id, str) and original_date and original_date != sim_date:
        normalized["story_id"] = story_id.replace(original_date, sim_date)
    return normalized


def hhmm_to_minutes(value: str) -> int | None:
    if value == "24:00":
        return 24 * 60
    match = TIME_RE.match(value or "")
    if match is None:
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def find_active_segment(
    story: dict[str, Any], now_minutes: int
) -> dict[str, Any] | None:
    """Return the segment whose [start, end) window contains now_minutes."""
    segments = story.get("segments")
    if not isinstance(segments, list):
        return None
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        start = hhmm_to_minutes(str(seg.get("start", "")))
        end = hhmm_to_minutes(str(seg.get("end", "")))
        if start is None or end is None:
            continue
        if start <= now_minutes < end:
            return seg
    return None


def infer_from_segment_id(
    existing_segments: list[Any],
    replacement_tail: list[Any],
) -> str | None:
    """Infer a revision start segment from the replacement tail start time.

    :param existing_segments: Current story segments.
    :param replacement_tail: Proposed replacement segment list.
    :returns: Existing segment id that covers the first replacement start time, or None."""
    if not replacement_tail or not isinstance(replacement_tail[0], dict):
        return None
    start = hhmm_to_minutes(str(replacement_tail[0].get("start", "")))
    if start is None:
        return None
    for segment in existing_segments:
        if not isinstance(segment, dict):
            continue
        segment_id = segment.get("id")
        segment_start = hhmm_to_minutes(str(segment.get("start", "")))
        segment_end = hhmm_to_minutes(str(segment.get("end", "")))
        if (
            isinstance(segment_id, str)
            and segment_start is not None
            and segment_end is not None
            and segment_start <= start < segment_end
        ):
            return segment_id
    return None


def as_object(data: Any, label: str, errors: list[str]) -> dict[str, Any]:
    if not isinstance(data, dict):
        errors.append(f"{label} must be a YAML mapping.")
        return {}
    return data


def require_keys(
    data: dict[str, Any], keys: list[str], label: str, errors: list[str]
) -> None:
    for key in keys:
        if key not in data:
            errors.append(f"{label} missing required key: {key}")


def parse_time_minutes(value: Any, label: str, errors: list[str]) -> int | None:
    if not isinstance(value, str):
        errors.append(f"{label} must be HH:MM string.")
        return None
    if value == "24:00":
        return 24 * 60
    match = TIME_RE.match(value)
    if match is None:
        errors.append(f"{label} must use HH:MM 24-hour format.")
        return None
    return int(match.group(1)) * 60 + int(match.group(2))


def minutes_to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def validate_tpb(segment: dict[str, Any], label: str, errors: list[str]) -> None:
    tpb = as_object(segment.get("tpb_reason"), f"{label}.tpb_reason", errors)
    require_keys(
        tpb, ["want", "norm", "can", "proof", "choice"], f"{label}.tpb_reason", errors
    )

    for field in ("want", "norm", "can"):
        reason = as_object(tpb.get(field), f"{label}.tpb_reason.{field}", errors)
        require_keys(
            reason, ["reason", "status"], f"{label}.tpb_reason.{field}", errors
        )
        if reason.get("status") not in VALID_TPB_STATUS:
            errors.append(
                f"{label}.tpb_reason.{field}.status must be one of {sorted(VALID_TPB_STATUS)}."
            )

    proof = tpb.get("proof")
    if not isinstance(proof, str) or not proof.strip():
        errors.append(f"{label}.tpb_reason.proof must be a non-empty string.")

    choice = tpb.get("choice")
    if choice not in VALID_CHOICE:
        errors.append(
            f"{label}.tpb_reason.choice must be one of {sorted(VALID_CHOICE)}."
        )
    can = tpb.get("can")
    if (
        isinstance(can, dict)
        and can.get("status") == "contradicted"
        and choice == "commit"
    ):
        errors.append(f"{label} cannot commit when can.status is contradicted.")


def validate_segment(segment: Any, label: str, errors: list[str]) -> str:
    data = as_object(segment, label, errors)
    require_keys(
        data,
        ["id", "start", "end", "activity", "maslow_reason", "tpb_reason"],
        label,
        errors,
    )

    segment_id = data.get("id")
    if not isinstance(segment_id, str) or not segment_id.strip():
        errors.append(f"{label}.id must be a non-empty string.")
        segment_id = ""

    start = parse_time_minutes(data.get("start"), f"{label}.start", errors)
    end = parse_time_minutes(data.get("end"), f"{label}.end", errors)
    if start is not None and end is not None and end <= start:
        errors.append(f"{label}.end must be later than {label}.start.")

    maslow = as_object(data.get("maslow_reason"), f"{label}.maslow_reason", errors)
    require_keys(
        maslow, ["need", "reason", "risk", "required"], f"{label}.maslow_reason", errors
    )
    need = maslow.get("need")
    if not isinstance(need, str) or not need.strip():
        errors.append(f"{label}.maslow_reason.need must be a non-empty string.")
    if maslow.get("required") not in VALID_REQUIRED:
        errors.append(
            f"{label}.maslow_reason.required must be one of {sorted(VALID_REQUIRED)}."
        )

    validate_tpb(data, label, errors)
    return segment_id


def validate_segments(data: Any, label: str, errors: list[str]) -> None:
    if not isinstance(data, list) or not data:
        errors.append(f"{label} must be a non-empty list.")
        return

    seen: set[str] = set()
    previous_end: int | None = None
    previous_id = ""
    for idx, segment in enumerate(data):
        segment_id = validate_segment(segment, f"{label}[{idx}]", errors)
        if not segment_id:
            continue
        if segment_id in seen:
            errors.append(f"{label} duplicate id: {segment_id}")
        seen.add(segment_id)
        if not isinstance(segment, dict):
            continue
        start = parse_time_minutes(segment.get("start"), f"{label}[{idx}].start", [])
        end = parse_time_minutes(segment.get("end"), f"{label}[{idx}].end", [])
        if (
            idx > 0
            and start is not None
            and previous_end is not None
            and start != previous_end
        ):
            errors.append(
                f"{label}[{idx}].start must equal previous segment end "
                f"({previous_id}.end={minutes_to_hhmm(previous_end)})."
            )
        if end is not None:
            previous_end = end
            previous_id = segment_id


def validate_execution(data: Any, errors: list[str]) -> None:
    execution = as_object(data, "story.yaml.execution", errors)
    require_keys(
        execution,
        ["current_segment_id", "completed_segments", "actual_timeline"],
        "story.yaml.execution",
        errors,
    )
    if not isinstance(execution.get("completed_segments"), list):
        errors.append("story.yaml.execution.completed_segments must be a list.")
    if not isinstance(execution.get("actual_timeline"), list):
        errors.append("story.yaml.execution.actual_timeline must be a list.")


def validate_change_log(data: Any, errors: list[str]) -> None:
    if not isinstance(data, list):
        errors.append("story.yaml.change_log must be a list.")
        return
    for idx, item in enumerate(data):
        event = as_object(item, f"story.yaml.change_log[{idx}]", errors)
        require_keys(
            event, ["event_id", "type", "time"], f"story.yaml.change_log[{idx}]", errors
        )


def validate_ready(data: dict[str, Any], errors: list[str]) -> None:
    if data.get("status") != "ready":
        errors.append("story.yaml.status must be ready.")
    validate_segments(data.get("segments"), "story.yaml.segments", errors)
    validate_execution(data.get("execution"), errors)
    validate_change_log(data.get("change_log"), errors)

    self_check = as_object(data.get("self_check"), "story.yaml.self_check", errors)
    require_keys(
        self_check,
        ["maslow_result", "tpb_result", "issues"],
        "story.yaml.self_check",
        errors,
    )
    if self_check.get("maslow_result") not in {"pass", "revise"}:
        errors.append("story.yaml.self_check.maslow_result must be pass or revise.")
    if self_check.get("tpb_result") not in {"pass", "revise"}:
        errors.append("story.yaml.self_check.tpb_result must be pass or revise.")
    if not isinstance(self_check.get("issues"), list):
        errors.append("story.yaml.self_check.issues must be a list.")


def check_story(path: Path) -> list[str]:
    errors: list[str] = []
    if path.is_dir():
        path = path / "story.yaml"
    if not path.is_file():
        return [f"story file does not exist: {path}"]

    try:
        loaded = load_yaml(path)
    except Exception as exc:
        return [f"story file is not valid YAML: {exc}"]
    if loaded is None:
        return ["story.yaml is empty; fill it with the required daily Story fields."]

    data = as_object(loaded, "story.yaml", errors)
    require_keys(
        data,
        [
            "story_id",
            "date",
            "status",
            "segments",
            "self_check",
            "execution",
            "change_log",
        ],
        "story.yaml",
        errors,
    )
    validate_ready(data, errors)
    return errors


def recommendations(errors: list[str]) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for error in errors:
        if "story.yaml is empty" in error:
            items.append(
                {
                    "field": "story.yaml",
                    "action": "write the complete daily Story YAML for this date",
                    "meaning": FIELD_MEANINGS["story.yaml"],
                }
            )
        elif "missing required key" in error:
            field = error.rsplit(": ", 1)[-1]
            items.append(
                {
                    "field": field,
                    "action": f"add `{field}`",
                    "meaning": FIELD_MEANINGS.get(field, "required story field"),
                }
            )
        elif ".start must equal previous segment end" in error:
            items.append(
                {
                    "field": "segments[].start",
                    "action": "make each segment start equal to the previous segment end",
                    "meaning": "segments form a continuous daily timeline",
                }
            )
        elif ".end must be later" in error:
            items.append(
                {
                    "field": "segments[].end",
                    "action": "set end later than start",
                    "meaning": "each segment needs positive duration",
                }
            )
        elif "HH:MM" in error:
            items.append(
                {
                    "field": "start/end",
                    "action": "write time as HH:MM, for example 09:00; use 24:00 only for day end",
                    "meaning": "24-hour local time",
                }
            )
        elif "proof must be a non-empty string" in error:
            items.append(
                {
                    "field": "tpb_reason.proof",
                    "action": "write one short proof sentence",
                    "meaning": FIELD_MEANINGS["proof"],
                }
            )
    return items


def resolve_check_path(args: argparse.Namespace) -> Path:
    if args.date:
        return story_path_for_date(args.date)
    return Path(args.story_file)


def command_init(args: argparse.Namespace) -> int:
    root = agent_work_dir()
    story_file = args.story_file or f"state/daily_guidance/{args.date}/story.yaml"
    output_path = (root / story_file).resolve()
    if root not in output_path.parents and output_path != root:
        print(
            yaml.safe_dump(
                {"ok": False, "errors": [f"refusing outside workspace: {output_path}"]}
            )
        )
        return 2

    created = write_todo_file(output_path, force=args.force)
    emit(
        {
            "ok": True,
            "mode": "init",
            "story_file": output_path.relative_to(root).as_posix(),
            "created": created,
            "next": f"fill story.yaml, then run check --date {args.date}",
        }
    )
    return 0


def command_check(args: argparse.Namespace) -> int:
    path = resolve_check_path(args)
    errors = check_story(path)
    emit(
        {
            "ok": not errors,
            "mode": "check",
            "story_file": str(path),
            "errors": errors,
            "recommend": recommendations(errors),
        }
    )
    return 0 if not errors else 1


def _load_ready_story(date: str, root: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Load and validate a story; return (story, errors). story is None on hard failure."""
    path = story_path_for_date(date, root)
    errors = check_story(path)
    if errors:
        return None, errors
    story = load_yaml(path)
    if not isinstance(story, dict):
        return None, ["story.yaml is not a mapping"]
    return story, []


def derive_execution(story: dict[str, Any], now_minutes: int | None) -> dict[str, Any]:
    """Compute execution state purely from segments + the clock.

    completed_segments / current_segment_id are NEVER hand-edited by the LLM.
    They are a function of (segments, now). A segment is "completed" once the
    clock has passed its end; the active segment is the one covering now.
    actual_timeline and change_log carry over from stored real-world records.
    """
    segments = story.get("segments", [])
    if not isinstance(segments, list):
        segments = []
    completed: list[str] = []
    current_id: str | None = None
    if now_minutes is not None:
        for seg in segments:
            if not isinstance(seg, dict):
                continue
            sid = seg.get("id")
            end = hhmm_to_minutes(str(seg.get("end", "")))
            start = hhmm_to_minutes(str(seg.get("start", "")))
            if end is not None and now_minutes >= end:
                if isinstance(sid, str):
                    completed.append(sid)
            elif start is not None and start <= now_minutes < (end or start):
                if isinstance(sid, str) and current_id is None:
                    current_id = sid
    stored = story.get("execution", {})
    stored = stored if isinstance(stored, dict) else {}
    return {
        "current_segment_id": current_id,
        "completed_segments": completed,
        "actual_timeline": stored.get("actual_timeline", [])
        if isinstance(stored.get("actual_timeline"), list)
        else [],
        "pending_deviation": stored.get("pending_deviation"),
    }


def validate_plan_input(payload: Any) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate the LLM's plan JSON. Only segments + story_id + date are required.

    execution/change_log/status are synthesized by the CLI — the LLM never
    supplies them. self_check is optional (defaults to pass/pass/[]).
    """
    errors: list[str] = []
    data = as_object(payload, "plan", errors)
    if errors:
        return None, errors
    require_keys(data, ["story_id", "date", "segments"], "plan", errors)
    if (
        not isinstance(data.get("story_id"), str)
        or not str(data.get("story_id")).strip()
    ):
        errors.append("plan.story_id must be a non-empty string.")
    if not isinstance(data.get("date"), str) or not str(data.get("date")).strip():
        errors.append("plan.date must be a non-empty string (YYYY-MM-DD).")
    validate_segments(data.get("segments"), "plan.segments", errors)
    if errors:
        return None, errors
    return data, []


def build_story_from_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Assemble the complete, valid story.yaml from validated plan input.

    The CLI owns serialization and all derived/bookkeeping fields. This is the
    single place YAML is constructed, so the on-disk file is always schema-valid.
    """
    default_self_check = {"maslow_result": "pass", "tpb_result": "pass", "issues": []}
    self_check = plan.get("self_check")
    if not isinstance(self_check, dict):
        self_check = default_self_check
    else:
        self_check = {**default_self_check, **self_check}
        if not isinstance(self_check.get("issues"), list):
            self_check["issues"] = []
    segments = plan["segments"]
    first_id = (
        segments[0].get("id") if segments and isinstance(segments[0], dict) else None
    )
    return {
        "story_id": plan["story_id"],
        "date": plan["date"],
        "status": "ready",
        "segments": segments,
        "self_check": self_check,
        "execution": {
            "current_segment_id": first_id,
            "completed_segments": [],
            "actual_timeline": [],
            "pending_deviation": None,
        },
        "change_log": [
            {
                "event_id": "story_0001",
                "type": "story_created",
                "time": f"{plan['date']}T00:00:00",
                "reason": "plan submitted via daily_guidance.py plan",
            }
        ],
    }


def command_plan(args: argparse.Namespace) -> int:
    """Accept story content as JSON, validate, and write story.yaml atomically.

    The LLM produces JSON (reliable) — never YAML. On any validation error the
    file is left untouched and per-field fix hints are returned.
    """
    root = agent_work_dir()
    if validate_command_date(args, root, "plan") is None:
        return 1
    if not str(args.json or "").strip():
        emit(
            {
                "ok": False,
                "mode": "plan",
                "errors": ["--json is required and must be a JSON object"],
                "recommend": [
                    {
                        "field": "--json",
                        "action": "pass a single valid JSON object",
                        "meaning": "story content as JSON, not YAML",
                    }
                ],
            }
        )
        return 0
    try:
        payload = json.loads(args.json)
    except json.JSONDecodeError as exc:
        emit(
            {
                "ok": False,
                "mode": "plan",
                "errors": [f"--json is not valid JSON: {exc}"],
                "recommend": [
                    {
                        "field": "--json",
                        "action": "pass a single valid JSON object",
                        "meaning": "story content as JSON, not YAML",
                    }
                ],
            }
        )
        return 0

    plan, errors = validate_plan_input(payload)
    if plan is None:
        emit(
            {
                "ok": False,
                "mode": "plan",
                "errors": errors,
                "recommend": recommendations(errors),
            }
        )
        return 0

    plan = normalize_plan_to_sim_date(plan, args.date)
    story = build_story_from_plan(plan)
    # Defense in depth: the synthesized story must pass the full validator.
    tmp_errors: list[str] = []
    validate_ready(story, tmp_errors)
    if tmp_errors:
        emit(
            {
                "ok": False,
                "mode": "plan",
                "errors": tmp_errors,
                "recommend": recommendations(tmp_errors),
            }
        )
        return 0

    path = story_path_for_date(args.date, root)
    write_yaml(path, story)
    result = {
        "ok": True,
        "mode": "plan",
        "story_file": path.relative_to(root).as_posix(),
        "segments": len(story["segments"]),
        "next": "execution state is derived from the clock; use current/show to read it",
    }
    if args.corrected_date:
        result["corrected_date"] = args.corrected_date
    emit(result)
    return 0


def command_current(args: argparse.Namespace) -> int:
    """Report the segment that covers the current simulation time. Deterministic."""
    root = agent_work_dir()
    sim_time = validate_command_date(args, root, "current")
    if sim_time is None:
        return 1
    story, errors = _load_ready_story(args.date, root)
    if story is None:
        emit(
            {
                "ok": False,
                "mode": "current",
                "errors": errors,
                "recommend": recommendations(errors),
            }
        )
        return 1

    now_minutes = sim_time.hour * 60 + sim_time.minute
    now_hhmm = minutes_to_hhmm(now_minutes)
    seg = find_active_segment(story, now_minutes)
    if seg is None:
        emit(
            {
                "ok": False,
                "mode": "current",
                "time": now_hhmm,
                "gap": True,
                "reason": f"no segment covers {now_hhmm}",
                "recommend": "use deviate --type local_patch or rewrite_remaining_day",
            }
        )
        return 1

    maslow = (
        seg.get("maslow_reason", {})
        if isinstance(seg.get("maslow_reason"), dict)
        else {}
    )
    tpb = seg.get("tpb_reason", {}) if isinstance(seg.get("tpb_reason"), dict) else {}
    emit(
        {
            "ok": True,
            "mode": "current",
            "time": now_hhmm,
            "current_segment": {
                "id": seg.get("id"),
                "activity": seg.get("activity"),
                "location_policy": seg.get("location_policy"),
                "start": seg.get("start"),
                "end": seg.get("end"),
                "maslow_need": maslow.get("need"),
                "maslow_required": maslow.get("required"),
                "tpb_choice": tpb.get("choice"),
            },
            "next_transition": seg.get("end"),
        }
    )
    return 0


def command_record(args: argparse.Namespace) -> int:
    """Append what actually happened this step to actual_timeline. Deterministic.

    There is no 'complete' command: completed_segments is derived from the clock
    (see derive_execution). The agent only records the real activity/location it
    performed, which is appended verbatim with the current sim timestamp.
    """
    root = agent_work_dir()
    sim_time = validate_command_date(args, root, "record")
    if sim_time is None:
        return 1
    path = story_path_for_date(args.date, root)
    if not path.is_file():
        emit({"ok": False, "mode": "record", "reason": f"story file not found: {path}"})
        return 1
    story = load_yaml(path)
    if not isinstance(story, dict):
        emit({"ok": False, "mode": "record", "reason": "story.yaml is not a mapping"})
        return 1

    now_hhmm = minutes_to_hhmm(sim_time.hour * 60 + sim_time.minute)

    execution = story.setdefault("execution", {})
    if not isinstance(execution, dict):
        execution = {}
        story["execution"] = execution
    timeline = execution.setdefault("actual_timeline", [])
    if not isinstance(timeline, list):
        timeline = []
        execution["actual_timeline"] = timeline

    entry = {
        "time": now_hhmm,
        "activity": args.activity,
        "location": args.location,
    }
    if args.note:
        entry["note"] = args.note
    for existing in reversed(timeline):
        if not isinstance(existing, dict):
            continue
        if (
            str(existing.get("time") or "") == now_hhmm
            and str(existing.get("activity") or "") == args.activity
            and str(existing.get("location") or "") == args.location
        ):
            emit(
                {
                    "ok": True,
                    "mode": "record",
                    "entry": existing,
                    "timeline_size": len(timeline),
                    "duplicate": True,
                    "next": "activity already recorded for this simulation time",
                }
            )
            return 0
    timeline.append(entry)

    write_yaml(path, story)
    emit(
        {
            "ok": True,
            "mode": "record",
            "entry": entry,
            "timeline_size": len(timeline),
            "duplicate": False,
        }
    )
    return 0


def command_deviate(args: argparse.Namespace) -> int:
    """Append a change_log entry recording a deviation. Deterministic bookkeeping."""
    root = agent_work_dir()
    sim_time = validate_command_date(args, root, "deviate")
    if sim_time is None:
        return 1
    if args.type not in DEVIATION_ACTIONS:
        emit(
            {
                "ok": False,
                "mode": "deviate",
                "reason": f"--type must be one of {sorted(DEVIATION_ACTIONS)}",
            }
        )
        return 1

    path = story_path_for_date(args.date, root)
    if not path.is_file():
        emit(
            {"ok": False, "mode": "deviate", "reason": f"story file not found: {path}"}
        )
        return 1
    story = load_yaml(path)
    if not isinstance(story, dict):
        emit({"ok": False, "mode": "deviate", "reason": "story.yaml is not a mapping"})
        return 1

    stamp = sim_time.isoformat()

    change_log = story.setdefault("change_log", [])
    if not isinstance(change_log, list):
        change_log = []
        story["change_log"] = change_log
    event = {
        "event_id": f"dev_{len(change_log) + 1:04d}",
        "type": args.type,
        "time": stamp,
        "reason": args.reason,
    }
    change_log.append(event)

    # rewrite_remaining_day: drop segments after the current one and flag for refill.
    if args.type == "rewrite_remaining_day":
        execution = (
            story.get("execution", {})
            if isinstance(story.get("execution"), dict)
            else {}
        )
        current_id = execution.get("current_segment_id")
        segments = story.get("segments", [])
        if current_id and isinstance(segments, list):
            kept = []
            for s in segments:
                kept.append(s)
                if isinstance(s, dict) and s.get("id") == current_id:
                    break
            story["segments"] = kept
        story["status"] = "partial"

    write_yaml(path, story)
    emit(
        {
            "ok": True,
            "mode": "deviate",
            "event": event,
            "action_required": DEVIATION_ACTIONS[args.type],
            "status": story.get("status", "ready"),
        }
    )
    return 0


def command_revise(args: argparse.Namespace) -> int:
    """Replace segments from --from onward with new JSON segments. Validates continuity.

    The LLM passes the replacement tail as a JSON list; the CLI keeps the head
    (segments up to and including --from's predecessor), appends the new tail,
    revalidates the whole timeline, and writes only if valid.
    """
    root = agent_work_dir()
    sim_time = validate_command_date(args, root, "revise")
    if sim_time is None:
        return 1
    if not str(args.json or "").strip():
        emit(
            {
                "ok": False,
                "mode": "revise",
                "errors": ["--json is required and must be a segment object or list"],
            }
        )
        return 0
    path = story_path_for_date(args.date, root)
    if not path.is_file():
        emit({"ok": False, "mode": "revise", "reason": f"story file not found: {path}"})
        return 1
    story = load_yaml(path)
    if not isinstance(story, dict):
        emit({"ok": False, "mode": "revise", "reason": "story.yaml is not a mapping"})
        return 1

    try:
        new_tail = json.loads(args.json)
    except json.JSONDecodeError as exc:
        emit(
            {
                "ok": False,
                "mode": "revise",
                "errors": [f"--json is not valid JSON: {exc}"],
            }
        )
        return 0
    if (
        isinstance(new_tail, dict)
        and isinstance(new_tail.get("segments"), list)
        and new_tail["segments"]
    ):
        new_tail = new_tail["segments"]
    single_patch = isinstance(new_tail, dict)
    if single_patch:
        new_tail = [new_tail]
    if not isinstance(new_tail, list) or not new_tail:
        emit(
            {
                "ok": False,
                "mode": "revise",
                "errors": [
                    "--json must be a segment object or a non-empty JSON list of segments"
                ],
            }
        )
        return 0

    segments = story.get("segments", [])
    if not isinstance(segments, list):
        segments = []
    seg_ids = [s.get("id") for s in segments if isinstance(s, dict)]
    inferred_from_missing = False
    if args.from_id not in seg_ids:
        inferred_from = infer_from_segment_id(segments, new_tail)
        if inferred_from is None:
            emit(
                {
                    "ok": False,
                    "mode": "revise",
                    "reason": f"--from segment '{args.from_id}' not found",
                    "known_segments": seg_ids,
                }
            )
            return 0
        args.from_id = inferred_from
        inferred_from_missing = True

    from_index = seg_ids.index(args.from_id)
    original_segment = segments[from_index]

    # A single segment object is treated as a local patch to --from. Preserve the
    # unchanged prefix/suffix of the original segment so a small edit remains a
    # continuous full-day story.
    if (
        single_patch
        and isinstance(original_segment, dict)
        and isinstance(new_tail[0], dict)
    ):
        replacement = new_tail[0]
        patched: list[Any] = []
        orig_start = str(original_segment.get("start", ""))
        orig_end = str(original_segment.get("end", ""))
        repl_start = str(replacement.get("start", ""))
        repl_end = str(replacement.get("end", ""))
        if orig_start and repl_start and orig_start != repl_start:
            prefix = dict(original_segment)
            prefix["id"] = f"{args.from_id}_before_patch"
            prefix["end"] = repl_start
            patched.append(prefix)
        patched.append(replacement)
        if orig_end and repl_end and repl_end != orig_end:
            suffix = dict(original_segment)
            suffix["id"] = f"{args.from_id}_after_patch"
            suffix["start"] = repl_end
            patched.append(suffix)
        new_tail = patched + segments[from_index + 1 :]
    elif inferred_from_missing and isinstance(original_segment, dict):
        replacement_start = hhmm_to_minutes(str(new_tail[0].get("start", "")))
        original_start = hhmm_to_minutes(str(original_segment.get("start", "")))
        if (
            replacement_start is not None
            and original_start is not None
            and original_start < replacement_start
        ):
            prefix = dict(original_segment)
            prefix["id"] = f"{args.from_id}_before_patch"
            prefix["end"] = str(new_tail[0].get("start"))
            new_tail = [prefix, *new_tail]

    # Keep head = everything BEFORE from_id; the new tail replaces from_id onward.
    head: list[Any] = []
    for s in segments:
        if isinstance(s, dict) and s.get("id") == args.from_id:
            break
        head.append(s)
    merged = head + new_tail

    # Revalidate the full timeline before committing.
    errors: list[str] = []
    validate_segments(merged, "story.yaml.segments", errors)
    if errors:
        emit(
            {
                "ok": False,
                "mode": "revise",
                "errors": errors,
                "recommend": recommendations(errors),
            }
        )
        return 0

    story["segments"] = merged

    # Record the revision in change_log.
    stamp = sim_time.isoformat()
    change_log = story.setdefault("change_log", [])
    if not isinstance(change_log, list):
        change_log = []
        story["change_log"] = change_log
    change_log.append(
        {
            "event_id": f"rev_{len(change_log) + 1:04d}",
            "type": "rewrite_remaining_day",
            "time": stamp,
            "reason": f"revised segments from '{args.from_id}' onward",
        }
    )
    story["status"] = "ready"

    write_yaml(path, story)
    emit(
        {
            "ok": True,
            "mode": "revise",
            "from": args.from_id,
            "kept_head": len(head),
            "new_tail": len(new_tail),
            "total_segments": len(merged),
        }
    )
    return 0


def command_show(args: argparse.Namespace) -> int:
    """Compact snapshot of story state with execution DERIVED from the clock."""
    root = agent_work_dir()
    sim_time = validate_command_date(args, root, "show")
    if sim_time is None:
        return 1
    path = story_path_for_date(args.date, root)
    if not path.is_file():
        emit({"ok": False, "mode": "show", "reason": f"story file not found: {path}"})
        return 1
    story = load_yaml(path)
    if not isinstance(story, dict):
        emit({"ok": False, "mode": "show", "reason": "story.yaml is not a mapping"})
        return 1

    now_minutes = sim_time.hour * 60 + sim_time.minute
    now_hhmm = minutes_to_hhmm(now_minutes)

    derived = derive_execution(story, now_minutes)
    segments = story.get("segments", [])
    change_log = story.get("change_log", [])
    snapshot = {
        "ok": True,
        "mode": "show",
        "story_id": story.get("story_id"),
        "status": story.get("status"),
        "current_time": now_hhmm,
        "active_segment": derived["current_segment_id"],
        "completed_count": len(derived["completed_segments"]),
        "total_segments": len(segments) if isinstance(segments, list) else 0,
        "actual_timeline_size": len(derived["actual_timeline"]),
        "change_log_size": len(change_log) if isinstance(change_log, list) else 0,
    }
    if args.format == "full":
        snapshot["segments"] = segments
        snapshot["completed_segments"] = derived["completed_segments"]
        snapshot["actual_timeline"] = derived["actual_timeline"]
        snapshot["change_log"] = change_log
    emit(snapshot)
    return 0


def _build_hook_result(root: Path, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Build the pre_step hook result dict for the current sim time.

    Shared by the CLI ``command_hook_init`` and the native ``pre_step`` function
    hook. Returns None when no simulation time is available.

    :param root: Agent workspace root.
    :param payload: Lifecycle payload (``time``, ``agent_id``, ...).
    :returns: The result dict, or None when sim time is missing."""
    raw_time = payload.get("time")
    if isinstance(raw_time, str) and raw_time.strip():
        current_time = parse_hook_time(raw_time)
    else:
        sim_time = require_sim_time(root, "hook")
        if sim_time is None:
            return None
        current_time = sim_time
    date = current_time.date().isoformat()
    path = story_path_for_date(date, root)
    created = False
    if not path.exists():
        story = default_story_for_date(date, int(payload.get("agent_id") or 0))
        write_yaml(path, story)
        created = True
    errors = check_story(path)
    result: dict[str, Any] = {
        "ok": not errors,
        "skill": "daily-guidance",
        "story_file": path.relative_to(root).as_posix(),
        "date": date,
        "created": created,
    }
    if errors:
        result["errors"] = errors
        result["recommend"] = recommendations(errors)
        result["next"] = (
            f"submit a full-day story: execute daily_guidance.py plan --date {date} "
            "--json '<JSON object with story_id, date, segments>'. "
            "Pass JSON, not YAML. Do NOT include execution/change_log — the CLI derives them."
        )
        return result
    story = load_yaml(path)
    now_minutes = current_time.hour * 60 + current_time.minute
    seg = find_active_segment(story, now_minutes) if isinstance(story, dict) else None
    result["current_time"] = minutes_to_hhmm(now_minutes)
    if seg is None:
        result["active_segment"] = None
        result["note"] = (
            "no segment covers the current time; use deviate --type local_patch "
            "or revise to fill the gap"
        )
    else:
        maslow = (
            seg.get("maslow_reason", {})
            if isinstance(seg.get("maslow_reason"), dict)
            else {}
        )
        tpb = (
            seg.get("tpb_reason", {}) if isinstance(seg.get("tpb_reason"), dict) else {}
        )
        result["active_segment"] = {
            "id": seg.get("id"),
            "activity": seg.get("activity"),
            "location_policy": seg.get("location_policy"),
            "start": seg.get("start"),
            "end": seg.get("end"),
            "maslow_need": maslow.get("need"),
            "tpb_choice": tpb.get("choice"),
        }
        result["guidance"] = (
            f"Your intended activity now is '{seg.get('activity')}' "
            f"at location policy '{seg.get('location_policy')}'. "
            "Act consistently with this when moving and when answering questionnaires."
        )
    return result


def command_hook_init(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {}
    if args.args_json:
        loaded = json.loads(args.args_json)
        if isinstance(loaded, dict):
            payload = loaded
    result = _build_hook_result(agent_work_dir(), payload)
    if result is None:
        return 1
    emit(result)
    return 0


async def pre_step() -> str:
    """Native pre_step lifecycle hook (no-arg, async) — fast path.

    Called directly by the skill runtime (detected by name) instead of running
    the script, so it does not block the agent event loop. Reads its context via
    :func:`get_hook_context` and returns the same YAML the CLI ``hook_init``
    would print.

    :returns: The YAML result string."""
    from agentsociety2.agent.base.skill_hook_context import get_hook_context

    ctx = get_hook_context()
    result = _build_hook_result(ctx.workspace_root, ctx.payload)
    if result is None:
        return yaml.safe_dump(
            {"ok": False, "skill": "daily-guidance", "error": "no simulation time"},
            allow_unicode=True,
            sort_keys=False,
        )
    return yaml.safe_dump(result, allow_unicode=True, sort_keys=False)


def build_parser(*, include_hook_args: bool = False) -> argparse.ArgumentParser:
    """Build the daily-guidance command parser.

    ``--args-json`` is intentionally excluded from the normal command parser:
    it is a lifecycle-hook transport, not a user/model command option.  Legacy
    model calls that use ``--args-json`` as a JSON alias are normalized to
    ``--json`` before parsing.
    """
    parser = argparse.ArgumentParser(
        description="Daily guidance story CLI. The agent passes content as JSON; "
        "the CLI owns YAML serialization and derives execution state from the clock."
    )
    subparsers = parser.add_subparsers(dest="cmd")

    init_parser = subparsers.add_parser("init", help="Create an empty TODO story.yaml.")
    init_parser.add_argument("--agent-id", type=int, default=0)
    init_parser.add_argument("--date", required=True)
    init_parser.add_argument("--story-file", default="")
    init_parser.add_argument("--force", action="store_true")

    plan_parser = subparsers.add_parser(
        "plan",
        help="Submit the full day's story as JSON; CLI validates and writes YAML.",
    )
    plan_parser.add_argument(
        "--date",
        default="",
        help="Compatibility field; simulation clock date is authoritative.",
    )
    plan_parser.add_argument(
        "--json",
        required=True,
        nargs="?",
        help="The story content as a JSON object: {story_id, date, segments, [self_check]}.",
    )

    check_parser = subparsers.add_parser(
        "check", help="Validate an existing story.yaml."
    )
    check_parser.add_argument(
        "story_file", nargs="?", default="state/daily_guidance/story.yaml"
    )
    check_parser.add_argument(
        "--date", default="", help="Check state/daily_guidance/YYYY-MM-DD/story.yaml."
    )

    current_parser = subparsers.add_parser(
        "current", help="Report the segment covering the current simulation time."
    )
    current_parser.add_argument(
        "--date",
        default="",
        help="Compatibility field; simulation clock date is authoritative.",
    )

    show_parser = subparsers.add_parser(
        "show", help="Compact snapshot of story state (execution derived from clock)."
    )
    show_parser.add_argument(
        "--date",
        default="",
        help="Compatibility field; simulation clock date is authoritative.",
    )
    show_parser.add_argument("--format", choices=["summary", "full"], default="summary")

    record_parser = subparsers.add_parser(
        "record",
        help="Append the real activity performed this step to actual_timeline.",
    )
    record_parser.add_argument(
        "--date",
        default="",
        help="Compatibility field; simulation clock date is authoritative.",
    )
    record_parser.add_argument("--activity", required=True)
    record_parser.add_argument("--location", required=True)
    record_parser.add_argument("--note", default="")

    deviate_parser = subparsers.add_parser(
        "deviate", help="Record a deviation in change_log."
    )
    deviate_parser.add_argument(
        "--date",
        default="",
        help="Compatibility field; simulation clock date is authoritative.",
    )
    deviate_parser.add_argument(
        "--type", required=True, choices=sorted(DEVIATION_ACTIONS)
    )
    deviate_parser.add_argument("--reason", required=True)

    revise_parser = subparsers.add_parser(
        "revise", help="Replace segments from a given id onward with new JSON segments."
    )
    revise_parser.add_argument(
        "--date",
        default="",
        help="Compatibility field; simulation clock date is authoritative.",
    )
    revise_parser.add_argument("--from", dest="from_id", required=True)
    revise_parser.add_argument(
        "--json",
        required=True,
        nargs="?",
        help="JSON list of replacement tail segments.",
    )

    if include_hook_args:
        parser.add_argument(
            "--args-json", default="", help="Lifecycle hook payload JSON."
        )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    raw_argv = list(argv if argv is not None else sys.argv[1:])
    if not raw_argv or is_lifecycle_hook_argv(raw_argv):
        return build_parser(include_hook_args=True).parse_args(raw_argv)
    return build_parser().parse_args(normalize_argv(raw_argv))


def is_lifecycle_hook_argv(argv: list[str]) -> bool:
    """Return whether argv is exactly the runtime lifecycle-hook protocol."""
    return len(argv) == 2 and argv[0] == "--args-json"


def normalize_argv(argv: list[str]) -> list[str]:
    """Normalize common abbreviated CLI arguments emitted by agents.

    :param argv: Raw command-line arguments after the script path.
    :returns: Arguments suitable for argparse."""
    if not argv:
        return argv
    if is_lifecycle_hook_argv(argv):
        return argv
    argv = ["--json" if item == "--args-json" else item for item in argv]
    argv = [
        item
        for item in argv
        if item.strip().lower() not in {"daily_guidance", "daily-guidance"}
    ]
    if argv and DATE_RE.match(argv[0]):
        argv = ["--date", argv[0], *argv[1:]]
    argv = coalesce_option_value_argv(argv, "--note")
    argv = drop_redundant_positional_date(argv)
    argv = coalesce_json_argv(argv)
    if not argv:
        return argv
    command = argv[0] if argv[0] in COMMAND_NAMES else ""
    if not command:
        command = next((item for item in argv if item in COMMAND_NAMES), "")
    cleaned = [item for item in argv if item not in COMMAND_NAMES]
    if command:
        return [command, *cleaned]
    if "--from" in cleaned and "--json" in cleaned:
        return ["revise", *cleaned]
    if "--json" in cleaned:
        return ["plan", *cleaned]
    if "--activity" in cleaned and "--location" in cleaned:
        return ["record", *cleaned]
    if "--type" in cleaned and "--reason" in cleaned:
        return ["deviate", *cleaned]
    if "--format" in cleaned:
        return ["show", *cleaned]
    if "--date" in cleaned:
        return ["current", *cleaned]
    if cleaned[0].startswith("-"):
        return argv
    return cleaned


def coalesce_option_value_argv(argv: list[str], option: str) -> list[str]:
    """Merge split free-text values after one option.

    :param argv: Command-line arguments after alias normalization.
    :param option: Option name whose value may contain spaces.
    :returns: Arguments with that option's value coalesced until the next option."""
    if option not in argv:
        return argv
    index = argv.index(option)
    if index >= len(argv) - 2:
        return argv
    result = argv[: index + 1]
    value_parts: list[str] = []
    cursor = index + 1
    while cursor < len(argv) and not argv[cursor].startswith("--"):
        value_parts.append(argv[cursor])
        cursor += 1
    if not value_parts:
        return argv
    result.append(" ".join(value_parts))
    result.extend(argv[cursor:])
    return result


def coalesce_json_argv(argv: list[str]) -> list[str]:
    """Merge a JSON value split across multiple argv tokens.

    :param argv: Command-line arguments after alias normalization.
    :returns: Arguments with the value after ``--json`` merged when needed."""
    if "--json" not in argv:
        return argv
    json_index = argv.index("--json")
    if json_index >= len(argv) - 2:
        return argv
    prefix = argv[: json_index + 1]
    fragments = argv[json_index + 1 :]
    for end in range(1, len(fragments) + 1):
        candidate = " ".join(fragments[:end])
        try:
            json.loads(candidate)
        except Exception:
            continue
        return [*prefix, candidate, *fragments[end:]]
    return [*prefix, " ".join(fragments)]


def drop_redundant_positional_date(argv: list[str]) -> list[str]:
    """Drop a trailing date when ``--date`` is already present.

    :param argv: Command-line arguments after alias normalization.
    :returns: Arguments without a redundant trailing date."""
    date_index = argv.index("--date") if "--date" in argv else -1
    if (
        date_index >= 0
        and len(argv) > date_index + 2
        and DATE_RE.match(argv[-1])
        and argv[-1] == argv[date_index + 1]
    ):
        return argv[:-1]
    return argv


def dispatch(args: argparse.Namespace) -> int:
    """Run the command selected by argparse.

    :param args: Parsed CLI namespace.
    :returns: Process exit code."""
    if args.cmd == "init":
        return command_init(args)
    if args.cmd == "plan":
        return command_plan(args)
    if args.cmd == "check":
        return command_check(args)
    if args.cmd == "current":
        return command_current(args)
    if args.cmd == "show":
        return command_show(args)
    if args.cmd == "record":
        return command_record(args)
    if args.cmd == "deviate":
        return command_deviate(args)
    if args.cmd == "revise":
        return command_revise(args)
    return command_hook_init(args)


def entrypoint(argv: list[str], ctx: Any) -> str:
    """In-process entry for the skill runtime (replaces the subprocess).

    The runtime calls this directly instead of spawning ``python
    daily_guidance.py``. ``ctx`` carries this agent's workspace root (replacing
    the ``AGENT_WORK_DIR`` env var) and is stored in a contextvar so every
    ``agent_work_dir()`` / ``emit()`` call inside dispatch resolves correctly
    and concurrently-safely.

    :param argv: Command-line arguments after the script path.
    :param ctx: Skill runtime context exposing ``workspace_root``.
    :returns: The YAML text the subprocess would have printed to stdout."""
    workspace_root = Path(str(ctx.workspace_root)).resolve()
    ws_token = _WORKSPACE_ROOT.set(workspace_root)
    buf_token = _EMIT_BUFFER.set([])
    try:
        args = parse_args(list(argv))
        dispatch(args)
        return "".join(_EMIT_BUFFER.get() or [])
    except SystemExit:
        return "".join(_EMIT_BUFFER.get() or [])
    except Exception:
        return yaml.safe_dump(
            {"ok": False, "error": traceback.format_exc()}, allow_unicode=True
        )
    finally:
        _EMIT_BUFFER.reset(buf_token)
        _WORKSPACE_ROOT.reset(ws_token)


def main() -> int:
    return dispatch(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
