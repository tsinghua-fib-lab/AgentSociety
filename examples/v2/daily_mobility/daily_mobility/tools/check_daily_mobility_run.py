#!/usr/bin/env python3
"""Lightweight diagnostics for Daily Mobility experiment artifacts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

EXAMPLE_DIR = Path(__file__).resolve().parents[2]
if str(EXAMPLE_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_DIR))

from daily_mobility.intentions import current_meal_window
from daily_mobility.tools.live_data import read_json_object

INTENTIONS = {
    "sleep",
    "home activity",
    "work",
    "shopping",
    "eating out",
    "leisure and entertainment",
    "other",
}
SLOT_RE = re.compile(r"daily_mobility_intention_slot_(\d+)$")
MAX_WARNINGS_BY_ISSUE = {
    "very_early_work": 1,
    "duplicate_meal_window": 0,
    "meal_outside_window": 0,
    "eating_after_21": 0,
    "work_while_home": 2,
    "sleep_away_from_home": 1,
    "missing_mobility_anchor": 0,
}


def _hour(value: str | None, slot: int) -> float:
    if value:
        try:
            t = datetime.fromisoformat(value)
            return t.hour + t.minute / 60.0
        except (AttributeError, TypeError, ValueError, OverflowError):
            import logging
            logging.getLogger(__name__).debug("Failed to parse time value %r", value, exc_info=True)
    return slot * 0.5


def _meal_window(hour: float) -> str | None:
    return current_meal_window(hour)


def _answer(resp: dict[str, Any]) -> str | None:
    for ans in resp.get("answers", []):
        if ans.get("question_id") == "primary_intention":
            value = ans.get("parsed_value")
            return str(value) if value is not None else None
    return None


def load_artifacts(run_dir: Path) -> dict[int, dict[int, dict[str, Any]]]:
    by_agent: dict[int, dict[int, dict[str, Any]]] = {}
    for path in sorted((run_dir / "artifacts").glob("questionnaire*.json")):
        raw = read_json_object(path)
        if raw is None:
            continue
        match = SLOT_RE.match(str(raw.get("questionnaire_id", "")))
        if not match:
            continue
        slot = int(match.group(1))
        hour = _hour(raw.get("simulation_time"), slot)
        snapshots = {
            int(snap.get("agent_id")): snap
            for snap in raw.get("mobility_snapshots", [])
            if isinstance(snap.get("agent_id"), int)
        }
        for resp in raw.get("responses", []):
            try:
                aid = int(resp.get("agent_id"))
            except (AttributeError, TypeError, ValueError, OverflowError):
                continue
            by_agent.setdefault(aid, {})[slot] = {
                "slot": slot,
                "time": raw.get("simulation_time"),
                "hour": hour,
                "intention": _answer(resp),
                "snapshot": snapshots.get(aid),
            }
    return by_agent


def diagnose_agent(slots: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    seen_meals: set[str] = set()
    for slot in range(48):
        row = slots.get(slot)
        if not row:
            issues.append({"slot": slot, "severity": "error", "issue": "missing_slot"})
            continue
        intent = row.get("intention")
        hour = float(row.get("hour", slot * 0.5))
        meal = _meal_window(hour)
        if intent not in INTENTIONS:
            issues.append(
                {
                    "slot": slot,
                    "time": row.get("time"),
                    "severity": "error",
                    "issue": "invalid_intention",
                    "intention": intent,
                }
            )
            continue
        if intent == "eating out":
            if meal is None:
                issues.append(
                    {
                        "slot": slot,
                        "time": row.get("time"),
                        "severity": "warn",
                        "issue": "meal_outside_window",
                    }
                )
            elif meal in seen_meals:
                issues.append(
                    {
                        "slot": slot,
                        "time": row.get("time"),
                        "severity": "warn",
                        "issue": "duplicate_meal_window",
                        "meal_window": meal,
                    }
                )
            else:
                seen_meals.add(meal)
        if intent == "work" and hour < 8.5:
            issues.append(
                {
                    "slot": slot,
                    "time": row.get("time"),
                    "severity": "warn",
                    "issue": "very_early_work",
                }
            )
        if intent == "eating out" and hour >= 21.0:
            issues.append(
                {
                    "slot": slot,
                    "time": row.get("time"),
                    "severity": "warn",
                    "issue": "eating_after_21",
                }
            )
        snapshot = row.get("snapshot")
        if isinstance(snapshot, dict):
            location = snapshot.get("location_category")
            status = str(snapshot.get("status") or "").lower()
            home_aoi = snapshot.get("home_aoi")
            work_aoi = snapshot.get("work_aoi")
            missing_anchor = home_aoi is None or work_aoi is None
            if missing_anchor:
                issues.append(
                    {
                        "slot": slot,
                        "time": row.get("time"),
                        "severity": "warn",
                        "issue": "missing_mobility_anchor",
                        "home_aoi": home_aoi,
                        "work_aoi": work_aoi,
                    }
                )
            if intent == "work" and location == "home" and status != "moving":
                issues.append(
                    {
                        "slot": slot,
                        "time": row.get("time"),
                        "severity": "warn",
                        "issue": "work_while_home",
                        "aoi_id": snapshot.get("aoi_id"),
                    }
                )
            if (
                intent == "sleep"
                and not missing_anchor
                and location not in {"home", "home_work"}
            ):
                issues.append(
                    {
                        "slot": slot,
                        "time": row.get("time"),
                        "severity": "warn",
                        "issue": "sleep_away_from_home",
                        "location_category": location,
                        "aoi_id": snapshot.get("aoi_id"),
                    }
                )
    return issues


def evaluate_gates(report: dict[str, Any]) -> dict[str, Any]:
    failures: list[dict[str, Any]] = []
    totals = Counter(report.get("totals", {}))
    for issue in ("missing_slot", "invalid_intention"):
        if totals.get(issue, 0) > 0:
            failures.append(
                {
                    "issue": issue,
                    "count": totals[issue],
                    "limit": 0,
                    "severity": "error",
                }
            )
    for issue, limit in MAX_WARNINGS_BY_ISSUE.items():
        count = totals.get(issue, 0)
        if count > limit:
            failures.append(
                {
                    "issue": issue,
                    "count": count,
                    "limit": limit,
                    "severity": "warn",
                }
            )
    return {
        "status": "FAIL" if failures else "PASS",
        "failures": failures,
        "warning_limits": dict(MAX_WARNINGS_BY_ISSUE),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--max-issues", type=int, default=30)
    parser.add_argument(
        "--fail-on-gate",
        action="store_true",
        help="Exit non-zero when hard Daily Mobility gates fail.",
    )
    args = parser.parse_args()

    by_agent = load_artifacts(args.run_dir)
    report: dict[str, Any] = {"agents": {}, "totals": Counter()}
    for aid, slots in sorted(by_agent.items()):
        intentions = [slots.get(i, {}).get("intention") for i in range(48)]
        issues = diagnose_agent(slots)
        counter = Counter(item["issue"] for item in issues)
        report["agents"][str(aid)] = {
            "slots_done": sum(v is not None for v in intentions),
            "intent_mix": dict(Counter(intentions)),
            "issues": issues,
            "issue_counts": dict(counter),
        }
        report["totals"].update(counter)
    report["totals"] = dict(report["totals"])
    report["gate"] = evaluate_gates(report)

    out = args.out or (args.run_dir / "daily_mobility_diagnostics.json")
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"diagnostics written to {out}")
    print(f"agents: {len(by_agent)}")
    print(f"issue totals: {report['totals']}")
    print(f"gate: {report['gate']['status']}")
    shown = 0
    for aid, data in report["agents"].items():
        for issue in data["issues"]:
            print(f"agent {aid}: {issue}")
            shown += 1
            if shown >= args.max_issues:
                return (
                    2 if args.fail_on_gate and report["gate"]["status"] == "FAIL" else 0
                )
    return 2 if args.fail_on_gate and report["gate"]["status"] == "FAIL" else 0


if __name__ == "__main__":
    raise SystemExit(main())
