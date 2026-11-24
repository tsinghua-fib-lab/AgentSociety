#!/usr/bin/env python3
"""Experiment progress tracker for AgentSociety research workflows.

Manages a single workspace governance file: `.agentsociety/progress.json`.

Usage:
    python progress.py <command> [options]

Commands:
    status              Show current progress summary
    init                Initialize progress.json for a workspace
    update-stage        Update a pipeline stage's status
    reroute             Reopen an earlier stage and invalidate downstream work
    set-verification    Set a stage verification status
    next-action         Suggest the next recommended action
    where-am-i          Determine current pipeline position (with legacy fallback)
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STAGE_ORDER = [
    "literature_search",
    "hypothesis",
    "experiment_config",
    "run_experiment",
    "analysis",
    "generate_paper",
]

VALID_STATUSES = {
    "not_started",
    "needs_revision",
    "in_progress",
    "completed",
    "failed",
    "skipped",
}
UPDATE_STATUSES = VALID_STATUSES - {"needs_revision"}
VERIFICATION_STATUSES = {"not_started", "partial", "complete"}

PROGRESS_VERSION = "1.3"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(data, temporary_file, indent=2, ensure_ascii=False)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        assert temporary_path is not None
        temporary_path.replace(path)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()


def _progress_path(workspace: Path) -> Path:
    return workspace / ".agentsociety" / "progress.json"


def _make_empty_stage_state() -> dict[str, Any]:
    return {
        "status": "not_started",
        "started_at": None,
        "completed_at": None,
        "attempts": 0,
        "error": None,
        "metadata": {},
        "verification_status": "not_started",
        "revision_round": 0,
    }


def _make_empty_stages() -> dict[str, dict[str, Any]]:
    return {stage: _make_empty_stage_state() for stage in STAGE_ORDER}


def _default_progress(topic: str = "") -> dict[str, Any]:
    return {
        "version": PROGRESS_VERSION,
        "workspace": {
            "topic": topic,
            "created_at": _now_iso(),
            "current_stage": "literature_search",
            "current_hypothesis_id": None,
            "current_experiment_id": None,
            "revision_round": 0,
            "active_reroute": None,
        },
        "stages": _make_empty_stages(),
        "hypotheses": {},
        "transitions": [],
    }


def _normalize_progress_data(data: dict[str, Any] | None) -> dict[str, Any]:
    normalized = _default_progress()
    if isinstance(data, dict):
        normalized.update(
            {k: v for k, v in data.items() if k not in {"workspace", "stages"}}
        )

        workspace = normalized["workspace"]
        existing_workspace = (
            data.get("workspace", {}) if isinstance(data.get("workspace"), dict) else {}
        )
        workspace.update(existing_workspace)
        if workspace.get("current_stage") not in STAGE_ORDER:
            workspace["current_stage"] = "literature_search"
        if (
            not isinstance(workspace.get("revision_round"), int)
            or workspace["revision_round"] < 0
        ):
            workspace["revision_round"] = 0
        active_reroute = workspace.get("active_reroute")
        if isinstance(active_reroute, dict):
            pending_stages = active_reroute.get("pending_stages")
            active_reroute["pending_stages"] = (
                [stage for stage in pending_stages if stage in STAGE_ORDER]
                if isinstance(pending_stages, list)
                else []
            )
            if (
                active_reroute.get("from_stage") not in STAGE_ORDER
                or active_reroute.get("target_stage") not in STAGE_ORDER
                or not isinstance(active_reroute.get("reason"), str)
                or not active_reroute["reason"].strip()
            ):
                workspace["active_reroute"] = None
        else:
            workspace["active_reroute"] = None

        normalized_stages = normalized["stages"]
        existing_stages = (
            data.get("stages", {}) if isinstance(data.get("stages"), dict) else {}
        )
        for stage in STAGE_ORDER:
            state = _make_empty_stage_state()
            state.update(existing_stages.get(stage, {}))
            if state.get("status") not in VALID_STATUSES:
                state["status"] = "not_started"
            if state.get("verification_status") not in VERIFICATION_STATUSES:
                state["verification_status"] = "not_started"
            if not isinstance(state.get("metadata"), dict):
                state["metadata"] = {}
            if not isinstance(state.get("revision_round"), int):
                state["revision_round"] = 0
            # Drop legacy fields that older progress.json files may carry.
            state.pop("gate_status", None)
            normalized_stages[stage] = state

    normalized["version"] = PROGRESS_VERSION
    if not isinstance(normalized.get("hypotheses"), dict):
        normalized["hypotheses"] = {}
    if not isinstance(normalized.get("transitions"), list):
        normalized["transitions"] = []
    else:
        normalized["transitions"] = [
            item for item in normalized["transitions"] if isinstance(item, dict)
        ]
    return normalized


def _read_progress(workspace: Path) -> dict[str, Any] | None:
    data = _read_json(_progress_path(workspace))
    if data is None:
        return None
    return _normalize_progress_data(data)


def _write_progress(workspace: Path, data: dict[str, Any]) -> None:
    _write_json(_progress_path(workspace), _normalize_progress_data(data))


def _append_transition(
    progress: dict[str, Any], kind: str, **details: Any
) -> dict[str, Any]:
    transitions = progress.setdefault("transitions", [])
    event = {
        "sequence": len(transitions) + 1,
        "timestamp": _now_iso(),
        "kind": kind,
        "revision_round": progress["workspace"].get("revision_round", 0),
        **details,
    }
    transitions.append(event)
    return event


def _finish_active_reroute_stage(
    progress: dict[str, Any], stage: str, status: str
) -> None:
    if status not in {"completed", "skipped"}:
        return

    active_reroute = progress["workspace"].get("active_reroute")
    if not isinstance(active_reroute, dict):
        return

    pending_stages = active_reroute.get("pending_stages", [])
    if stage in pending_stages:
        active_reroute["pending_stages"] = [
            item for item in pending_stages if item != stage
        ]
    if not active_reroute.get("pending_stages"):
        progress["workspace"]["active_reroute"] = None


def _compute_next_actions(progress: dict[str, Any]) -> list[dict[str, Any]]:
    workspace = progress["workspace"]
    stage = workspace["current_stage"]
    stage_state = progress["stages"][stage]
    status = stage_state["status"]

    if status == "failed":
        return [
            {
                "kind": "repair",
                "title": f"Repair {stage}",
                "reason": stage_state.get("error") or "the stage failed",
                "stage": stage,
                "priority": "high",
            }
        ]

    if status == "needs_revision":
        active_reroute = workspace.get("active_reroute") or {}
        return [
            {
                "kind": "revise",
                "title": f"Revise {stage}",
                "reason": active_reroute.get("reason", "upstream work was rerouted"),
                "stage": stage,
                "priority": "high",
                "revision_round": workspace.get("revision_round", 0),
            }
        ]

    if status == "not_started":
        return [
            {
                "kind": "start",
                "title": f"Start {stage}",
                "reason": "stage has not started",
                "stage": stage,
                "priority": "medium",
            }
        ]

    if status in {"completed", "skipped"} and stage == STAGE_ORDER[-1]:
        return [
            {
                "kind": "review_or_finish",
                "title": "Review the paper or finish the workflow",
                "reason": f"{stage} is {status}",
                "stage": stage,
                "priority": "low",
            }
        ]

    return [
        {
            "kind": "continue",
            "title": f"Continue {stage}",
            "reason": f"stage status is {status}",
            "stage": stage,
            "priority": "medium",
        }
    ]


# ── Commands ──────────────────────────────────────────────────────────


def cmd_init(args: argparse.Namespace) -> int:
    progress_path = _progress_path(args.workspace)
    if progress_path.exists() and not args.force:
        print(f"progress.json already exists: {progress_path}")
        return 1

    _write_progress(args.workspace, _default_progress(args.topic or ""))
    print(f"Initialized progress tracking in {args.workspace / '.agentsociety/'}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    progress = _read_progress(args.workspace)
    if progress is None:
        print("No progress.json found. Run 'init' first.")
        return 1

    if args.json:
        payload = dict(progress)
        payload["next_recommended_actions"] = _compute_next_actions(progress)
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    workspace = progress["workspace"]
    current_stage = workspace["current_stage"]
    current_stage_state = progress["stages"][current_stage]
    print(f"Topic: {workspace['topic'] or '(not set)'}")
    print(f"Current stage: {current_stage}")
    print(f"Revision round: {workspace.get('revision_round', 0)}")
    print(f"Verification: {current_stage_state['verification_status']}")
    active_reroute = workspace.get("active_reroute")
    if active_reroute:
        print(
            "Active reroute: "
            f"{active_reroute['from_stage']} → {active_reroute['target_stage']}"
        )
        print(f"Reroute reason: {active_reroute['reason']}")
    if workspace.get("current_hypothesis_id"):
        print(f"Current hypothesis: {workspace['current_hypothesis_id']}")
    if workspace.get("current_experiment_id"):
        print(f"Current experiment: {workspace['current_experiment_id']}")

    print()
    marker_map = {
        "completed": "+",
        "in_progress": ">",
        "failed": "!",
        "skipped": "-",
        "needs_revision": "~",
        "not_started": " ",
    }
    for stage_name in STAGE_ORDER:
        stage = progress["stages"].get(stage_name, {})
        status = stage.get("status", "unknown")
        marker = marker_map.get(status, "?")
        line = f"  [{marker}] {stage_name}: {status}"
        if stage.get("attempts", 0) > 1:
            line += f" ({stage['attempts']} attempts)"
        if stage.get("error"):
            line += f" — {stage['error']}"
        print(line)

    return 0


def cmd_update_stage(args: argparse.Namespace) -> int:
    progress = _read_progress(args.workspace)
    if progress is None:
        print("No progress.json found. Run 'init' first.")
        return 1

    if args.stage not in STAGE_ORDER:
        print(f"Unknown stage: {args.stage}. Valid: {', '.join(STAGE_ORDER)}")
        return 1
    if args.status not in UPDATE_STATUSES:
        print(
            f"Invalid status: {args.status}. Valid: {', '.join(sorted(UPDATE_STATUSES))}"
        )
        if args.status == "needs_revision":
            print("Use 'reroute' to create a revision round.")
        return 1

    stage = progress["stages"][args.stage]
    prev_status = stage["status"]
    previous_current_stage = progress["workspace"]["current_stage"]
    stage["status"] = args.status

    if (
        args.status != prev_status
        and prev_status != "in_progress"
        and args.status in {"in_progress", "completed", "failed"}
    ):
        stage["attempts"] += 1

    now = _now_iso()
    if args.status == "in_progress" and prev_status != "in_progress":
        stage["started_at"] = now
        stage["completed_at"] = None
        stage["error"] = None
    if args.status in {"completed", "failed", "skipped"}:
        stage["completed_at"] = now
    if args.error:
        stage["error"] = args.error
    if args.status == "completed":
        stage["error"] = None
    if args.status in {"in_progress", "completed", "failed", "skipped"}:
        stage["revision_round"] = progress["workspace"].get("revision_round", 0)
    if args.verification_status:
        stage["verification_status"] = args.verification_status

    metadata_update: dict[str, object] = {}
    if args.metadata:
        try:
            parsed_metadata = json.loads(args.metadata)
        except json.JSONDecodeError as exc:
            print(f"Invalid metadata JSON: {exc}")
            return 1
        if not isinstance(parsed_metadata, dict):
            print("Invalid metadata JSON: expected a JSON object")
            return 1
        metadata_update = parsed_metadata

    if metadata_update:
        stage["metadata"].update(metadata_update)

    if args.status in {"completed", "skipped"}:
        idx = STAGE_ORDER.index(args.stage)
        if idx + 1 < len(STAGE_ORDER):
            progress["workspace"]["current_stage"] = STAGE_ORDER[idx + 1]
        else:
            progress["workspace"]["current_stage"] = args.stage
    elif args.status in {"in_progress", "failed"}:
        progress["workspace"]["current_stage"] = args.stage

    _finish_active_reroute_stage(progress, args.stage, args.status)
    _append_transition(
        progress,
        "stage_update",
        stage=args.stage,
        from_status=prev_status,
        to_status=args.status,
        from_stage=previous_current_stage,
        to_stage=progress["workspace"]["current_stage"],
    )

    _write_progress(args.workspace, progress)
    print(f"Updated {args.stage}: {prev_status} → {args.status}")
    return 0


def cmd_reroute(args: argparse.Namespace) -> int:
    progress = _read_progress(args.workspace)
    if progress is None:
        print("No progress.json found. Run 'init' first.")
        return 1

    if args.stage not in STAGE_ORDER:
        print(f"Unknown stage: {args.stage}. Valid: {', '.join(STAGE_ORDER)}")
        return 1

    reason = args.reason.strip()
    if not reason:
        print("Reroute reason must not be empty.")
        return 1

    workspace = progress["workspace"]
    from_stage = workspace["current_stage"]
    target_index = STAGE_ORDER.index(args.stage)
    current_index = STAGE_ORDER.index(from_stage)
    if target_index > current_index:
        print(
            "Reroute must target the current stage or an earlier stage. "
            "Use normal stage completion to move forward."
        )
        return 1

    revision_round = workspace.get("revision_round", 0) + 1
    workspace["revision_round"] = revision_round

    invalidated_stages: list[str] = []
    previous_statuses: dict[str, str] = {}
    previous_stage_states: dict[str, dict[str, Any]] = {}
    for stage_name in STAGE_ORDER[target_index:]:
        stage = progress["stages"][stage_name]
        previous_status = stage["status"]
        if stage_name != args.stage and previous_status == "not_started":
            continue

        previous_statuses[stage_name] = previous_status
        previous_stage_states[stage_name] = dict(stage)
        invalidated_stages.append(stage_name)
        stage.update(
            {
                "status": "needs_revision",
                "started_at": None,
                "completed_at": None,
                "error": None,
                "metadata": {},
                "verification_status": "not_started",
                "revision_round": revision_round,
            }
        )

    requested_at = _now_iso()
    active_reroute = {
        "revision_round": revision_round,
        "requested_at": requested_at,
        "from_stage": from_stage,
        "target_stage": args.stage,
        "reason": reason,
        "source_artifact": args.source_artifact,
        "pending_stages": invalidated_stages.copy(),
    }
    workspace["current_stage"] = args.stage
    workspace["active_reroute"] = active_reroute
    event = _append_transition(
        progress,
        "reroute",
        from_stage=from_stage,
        to_stage=args.stage,
        reason=reason,
        source_artifact=args.source_artifact,
        invalidated_stages=invalidated_stages,
        previous_statuses=previous_statuses,
        previous_stage_states=previous_stage_states,
    )

    _write_progress(args.workspace, progress)
    if args.json:
        print(
            json.dumps(
                {
                    "current_stage": args.stage,
                    "revision_round": revision_round,
                    "active_reroute": active_reroute,
                    "transition": event,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(
            f"Rerouted {from_stage} → {args.stage} "
            f"(revision round {revision_round})"
        )
        print(f"Marked for revision: {', '.join(invalidated_stages)}")
    return 0


def cmd_set_verification(args: argparse.Namespace) -> int:
    progress = _read_progress(args.workspace)
    if progress is None:
        print("No progress.json found. Run 'init' first.")
        return 1

    if args.stage not in STAGE_ORDER:
        print(f"Unknown stage: {args.stage}. Valid: {', '.join(STAGE_ORDER)}")
        return 1
    if args.verification_status not in VERIFICATION_STATUSES:
        print(
            "Invalid verification status: "
            f"{args.verification_status}. Valid: {', '.join(sorted(VERIFICATION_STATUSES))}"
        )
        return 1

    previous_status = progress["stages"][args.stage]["verification_status"]
    progress["stages"][args.stage]["verification_status"] = args.verification_status
    _append_transition(
        progress,
        "verification_update",
        stage=args.stage,
        from_status=previous_status,
        to_status=args.verification_status,
    )
    _write_progress(args.workspace, progress)
    print(f"Updated verification for {args.stage}: {args.verification_status}")
    return 0


def cmd_next_action(args: argparse.Namespace) -> int:
    progress = _read_progress(args.workspace)
    if progress is None:
        print("No progress.json found. Run 'init' first.")
        return 1

    actions = _compute_next_actions(progress)

    if args.json:
        print(
            json.dumps(
                {
                    "current_stage": progress["workspace"]["current_stage"],
                    "actions": actions,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    print(f"Current stage: {progress['workspace']['current_stage']}")
    for action in actions:
        print(f"- [{action['priority']}] {action['title']}")
        if action.get("reason"):
            print(f"  {action['reason']}")
    return 0


def _detect_stage_from_files(workspace: Path) -> str:
    """Fallback: determine stage from file existence for legacy workspaces."""
    if not (workspace / "TOPIC.md").exists():
        return "literature_search"

    literature_index = workspace / "papers" / "literature_index.json"
    if not literature_index.exists():
        return "literature_search"
    try:
        index = json.loads(literature_index.read_text(encoding="utf-8"))
        if not index.get("papers"):
            return "literature_search"
    except Exception:
        return "literature_search"

    hypothesis_dirs = sorted(workspace.glob("hypothesis_*/HYPOTHESIS.md"))
    if not hypothesis_dirs:
        return "hypothesis"

    config_files = sorted(
        workspace.glob("hypothesis_*/experiment_*/init/init_config.json")
    )
    if not config_files:
        return "experiment_config"

    replay_schemas = sorted(
        workspace.glob("hypothesis_*/experiment_*/run/replay/_schema.json")
    )
    if not replay_schemas:
        return "run_experiment"

    report_globs = (
        "presentation/hypothesis_*/report_zh.md",
        "presentation/hypothesis_*/report_en.md",
    )
    if not any(workspace.glob(pattern) for pattern in report_globs):
        return "analysis"

    return "generate_paper"


def cmd_where_am_i(args: argparse.Namespace) -> int:
    progress = _read_progress(args.workspace)

    if progress is not None:
        workspace = progress["workspace"]
        stage = workspace["current_stage"]
        stage_info = progress["stages"].get(stage, {})
        result = {
            "source": "progress.json",
            "current_stage": stage,
            "revision_round": workspace.get("revision_round", 0),
            "active_reroute": workspace.get("active_reroute"),
            "topic": workspace.get("topic", ""),
            "current_hypothesis_id": workspace.get("current_hypothesis_id"),
            "current_experiment_id": workspace.get("current_experiment_id"),
            "stage_status": stage_info.get("status", "unknown"),
            "stage_attempts": stage_info.get("attempts", 0),
            "verification_status": stage_info.get("verification_status", "not_started"),
            "next_recommended_actions": _compute_next_actions(progress),
        }
        if stage_info.get("error"):
            result["stage_error"] = stage_info["error"]
    else:
        stage = _detect_stage_from_files(args.workspace)
        result = {
            "source": "file_detection",
            "current_stage": stage,
            "note": "No progress.json found. Detected from workspace files.",
        }

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(f"Current stage: {result['current_stage']}")
        print(f"Source: {result['source']}")
        if result.get("current_hypothesis_id"):
            print(f"Current hypothesis: {result['current_hypothesis_id']}")
        if result.get("current_experiment_id"):
            print(f"Current experiment: {result['current_experiment_id']}")
        if result.get("verification_status"):
            print(f"Verification: {result['verification_status']}")
        if result.get("stage_error"):
            print(f"Stage error: {result['stage_error']}")

    return 0


# ── Main ──────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AgentSociety experiment progress tracker"
    )
    parser.add_argument(
        "--workspace", type=Path, default=Path("."), help="Workspace root path"
    )
    sub = parser.add_subparsers(dest="command")

    p_init = sub.add_parser("init", help="Initialize progress.json")
    p_init.add_argument("--topic", help="Research topic")
    p_init.add_argument(
        "--force", action="store_true", help="Overwrite existing progress.json"
    )

    p_status = sub.add_parser("status", help="Show current progress summary")
    p_status.add_argument("--json", action="store_true", help="JSON output")

    p_update = sub.add_parser("update-stage", help="Update a stage's status")
    p_update.add_argument("stage", help="Stage name")
    p_update.add_argument("status", help="New status")
    p_update.add_argument("--error", help="Error message (for failed status)")
    p_update.add_argument("--metadata", help="JSON metadata to merge")
    p_update.add_argument(
        "--verification-status",
        choices=sorted(VERIFICATION_STATUSES),
        help="Optional verification status to set together with the stage update",
    )

    p_reroute = sub.add_parser(
        "reroute", help="Reopen an earlier stage and invalidate downstream work"
    )
    p_reroute.add_argument("stage", help="Current or earlier stage to revisit")
    p_reroute.add_argument(
        "--reason", required=True, help="Auditable reason for the reroute"
    )
    p_reroute.add_argument(
        "--source-artifact", help="Review or analysis artifact that motivated the reroute"
    )
    p_reroute.add_argument("--json", action="store_true", help="JSON output")

    p_verify = sub.add_parser(
        "set-verification", help="Update a stage verification status"
    )
    p_verify.add_argument("stage", help="Stage name")
    p_verify.add_argument("verification_status", help="Verification status")

    p_next = sub.add_parser("next-action", help="Suggest the next recommended action")
    p_next.add_argument("--json", action="store_true", help="JSON output")

    p_wai = sub.add_parser("where-am-i", help="Determine current pipeline position")
    p_wai.add_argument("--json", action="store_true", help="JSON output")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        return 1

    commands = {
        "init": cmd_init,
        "status": cmd_status,
        "update-stage": cmd_update_stage,
        "reroute": cmd_reroute,
        "set-verification": cmd_set_verification,
        "next-action": cmd_next_action,
        "where-am-i": cmd_where_am_i,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
