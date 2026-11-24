"""Persist and load env-module @tool call history for experiment debugging."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

CURSOR_NAME = "env_tool_calls.cursor"
LOG_NAME = "env_tool_calls.jsonl"

_MOBILITY_FN_LABELS = {
    "get_person": "查询位置",
    "move_to": "移动",
    "stop_trip": "停止行程",
    "finish_trip": "完成行程",
    "find_nearby_pois": "搜索 POI",
    "get_poi": "查询 POI",
    "get_aoi": "查询 AOI",
}


def _cursor_path(run_dir: Path) -> Path:
    return run_dir / CURSOR_NAME


def _log_path(run_dir: Path) -> Path:
    return run_dir / LOG_NAME


def read_cursor(run_dir: Path) -> int:
    path = _cursor_path(run_dir)
    if not path.is_file():
        return 0
    try:
        return max(0, int(path.read_text(encoding="utf-8").strip()))
    except ValueError:
        return 0


def write_cursor(run_dir: Path, index: int) -> None:
    _cursor_path(run_dir).write_text(str(index), encoding="utf-8")


def _person_id_from_kwargs(kwargs: Any) -> int | None:
    if not isinstance(kwargs, dict):
        return None
    pid = kwargs.get("person_id")
    if isinstance(pid, int):
        return pid
    return None


def _summarize_kwargs(kwargs: Any, *, max_len: int = 120) -> str:
    if not isinstance(kwargs, dict):
        return str(kwargs)[:max_len]
    parts: list[str] = []
    for key in (
        "person_id",
        "aoi_id_or_poi_id",
        "target_aoi_id",
        "mode",
        "category",
        "radius",
    ):
        if key not in kwargs:
            continue
        parts.append(f"{key}={kwargs[key]}")
    if not parts:
        text = json.dumps(kwargs, ensure_ascii=False)
    else:
        text = ", ".join(parts)
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _tool_call_ok(call: dict[str, Any]) -> bool:
    if call.get("exception_occurred"):
        return False
    ret = call.get("return_value")
    if isinstance(ret, dict):
        status = str(ret.get("status", "")).lower()
        if status in {"fail", "failed", "error"}:
            return False
    return True


def _summarize_return(ret: Any, *, max_len: int = 100) -> str:
    if ret is None:
        return "—"
    if isinstance(ret, dict):
        status = ret.get("status")
        reason = ret.get("reason")
        poi = ret.get("poi_name") or ret.get("poi_id")
        bits: list[str] = []
        if status is not None:
            bits.append(f"status={status}")
        if poi is not None:
            bits.append(f"poi={poi}")
        if reason:
            bits.append(str(reason)[:40])
        text = " · ".join(bits) if bits else json.dumps(ret, ensure_ascii=False)
    else:
        text = str(ret)
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def append_env_tool_calls(
    run_dir: Path,
    env_router: Any,
    *,
    step_idx: int,
    step_type: str,
    simulation_time: str | None = None,
    step_count: int | None = None,
) -> int:
    if env_router is None or not hasattr(env_router, "get_tool_call_history"):
        return 0
    history = env_router.get_tool_call_history()
    cursor = read_cursor(run_dir)
    if cursor >= len(history):
        return 0
    path = _log_path(run_dir)
    written = 0
    with path.open("a", encoding="utf-8") as f:
        for call in history[cursor:]:
            kwargs = call.get("kwargs")
            record = {
                "step_idx": step_idx,
                "step_type": step_type,
                "simulation_time": simulation_time,
                "step_count": step_count,
                "module_name": call.get("module_name", "MobilitySpace"),
                "function_name": call.get("function_name"),
                "function_label": _MOBILITY_FN_LABELS.get(
                    str(call.get("function_name") or ""), call.get("function_name")
                ),
                "person_id": _person_id_from_kwargs(kwargs),
                "kwargs_summary": _summarize_kwargs(kwargs),
                "return_summary": _summarize_return(call.get("return_value")),
                "ok": _tool_call_ok(call),
                "exception_info": call.get("exception_info"),
                "timestamp": call.get("timestamp"),
                "source": "env_tool",
            }
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1
    write_cursor(run_dir, len(history))
    return written


def _slot_from_sim_time(sim_time: str | None, fallback: int = 0) -> int:
    if not sim_time:
        return fallback
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(sim_time)
        return max(0, min(47, (dt.hour * 60 + dt.minute) // 30))
    except (TypeError, ValueError):
        return fallback


def log_simulation_time(line: str) -> str | None:
    match = re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", line)
    return match.group() if match else None


def load_env_tool_calls(
    run_dir: Path,
    log_file: Path | None = None,
    *,
    agent_id: int | None = None,
    limit: int = 400,
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    path = _log_path(run_dir)
    if path.is_file():
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if agent_id is not None:
                pid = raw.get("person_id")
                if pid is not None and int(pid) != int(agent_id):
                    continue
            raw["slot"] = _slot_from_sim_time(
                raw.get("simulation_time"), raw.get("step_idx", 0)
            )
            records.append(raw)

    if log_file and log_file.is_file():
        log_patterns = [
            (
                re.compile(
                    r"Agent (\d+): pending (?:questionnaire )?meal (\w+) ok=(True|False)"
                ),
                "enforce_meal",
            ),
            (
                re.compile(r"Agent (\d+): mobility meal search ok=(True|False)"),
                "meal_search",
            ),
            (
                re.compile(
                    r"Agent (\d+): mobility enforce target=(\d+) mode=(\w+) ok=(True|False)"
                ),
                "enforce_commute",
            ),
        ]
        for line in log_file.read_text(encoding="utf-8", errors="ignore").splitlines():
            if agent_id is not None and f"Agent {agent_id}:" not in line:
                continue
            sim_time = log_simulation_time(line)
            slot = _slot_from_sim_time(sim_time)
            for regex, kind in log_patterns:
                match = regex.search(line)
                if not match:
                    continue
                aid = int(match.group(1))
                if agent_id is not None and aid != agent_id:
                    continue
                ok = "False" not in match.group(0)
                records.append(
                    {
                        "step_idx": None,
                        "step_type": "runtime_log",
                        "simulation_time": sim_time,
                        "slot": slot,
                        "module_name": "MobilitySpace",
                        "function_name": kind,
                        "function_label": {
                            "enforce_meal": "强制就餐",
                            "meal_search": "搜索餐厅",
                            "enforce_commute": "强制通勤",
                        }.get(kind, kind),
                        "person_id": aid,
                        "kwargs_summary": match.group(0)[-120:],
                        "return_summary": "ok" if ok else "fail",
                        "ok": ok,
                        "timestamp": None,
                        "source": "output_log",
                    }
                )
                break

    records.sort(
        key=lambda r: (
            r.get("simulation_time") or "",
            r.get("timestamp") or "",
            r.get("step_idx") if r.get("step_idx") is not None else -1,
        )
    )
    if len(records) > limit:
        records = records[-limit:]

    by_fn: dict[str, int] = {}
    failures = 0
    for r in records:
        fn = str(r.get("function_name") or "unknown")
        by_fn[fn] = by_fn.get(fn, 0) + 1
        if not r.get("ok", True):
            failures += 1

    return {
        "calls": records,
        "summary": {
            "total": len(records),
            "failures": failures,
            "by_function": by_fn,
        },
    }
