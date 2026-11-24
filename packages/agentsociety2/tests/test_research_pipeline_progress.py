from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPO_ROOT
    / "extension/skills/agentsociety-research-pipeline/scripts/progress.py"
)
STAGES = [
    "literature_search",
    "hypothesis",
    "experiment_config",
    "run_experiment",
    "analysis",
    "generate_paper",
]


def run_progress(
    workspace: Path, *args: str, expected_returncode: int = 0
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--workspace",
            str(workspace),
            *args,
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert completed.returncode == expected_returncode, (
        completed.stderr or completed.stdout
    )
    return completed


def read_progress(workspace: Path) -> dict[str, Any]:
    return json.loads(
        (workspace / ".agentsociety/progress.json").read_text(encoding="utf-8")
    )


def complete_initial_pipeline(workspace: Path) -> None:
    run_progress(workspace, "init", "--topic", "feedback loop")
    for stage in STAGES:
        run_progress(workspace, "update-stage", stage, "in_progress")
        run_progress(workspace, "update-stage", stage, "completed")


def test_reroute_reopens_target_and_completed_downstream_stages(
    tmp_path: Path,
) -> None:
    complete_initial_pipeline(tmp_path)

    reroute = run_progress(
        tmp_path,
        "reroute",
        "analysis",
        "--reason",
        "MetaReview requires uncertainty estimates",
        "--source-artifact",
        "paper/reviews/acl-arr-review-r1.md",
        "--json",
    )
    payload = json.loads(reroute.stdout)
    progress = read_progress(tmp_path)

    assert progress["version"] == "1.3"
    assert payload["current_stage"] == "analysis"
    assert payload["revision_round"] == 1
    assert payload["active_reroute"]["pending_stages"] == [
        "analysis",
        "generate_paper",
    ]
    assert progress["workspace"]["current_stage"] == "analysis"
    assert progress["workspace"]["revision_round"] == 1
    assert progress["stages"]["run_experiment"]["status"] == "completed"
    assert progress["stages"]["analysis"]["status"] == "needs_revision"
    assert progress["stages"]["generate_paper"]["status"] == "needs_revision"
    assert progress["stages"]["analysis"]["attempts"] == 1
    assert progress["transitions"][-1]["kind"] == "reroute"
    assert progress["transitions"][-1]["previous_statuses"] == {
        "analysis": "completed",
        "generate_paper": "completed",
    }
    assert progress["transitions"][-1]["previous_stage_states"]["analysis"][
        "completed_at"
    ]
    assert (
        progress["transitions"][-1]["previous_stage_states"]["analysis"]["attempts"]
        == 1
    )

    location = json.loads(run_progress(tmp_path, "where-am-i", "--json").stdout)
    assert location["current_stage"] == "analysis"
    assert location["revision_round"] == 1
    assert location["next_recommended_actions"][0]["kind"] == "revise"
    assert location["active_reroute"]["source_artifact"] == (
        "paper/reviews/acl-arr-review-r1.md"
    )


def test_rerouted_pipeline_advances_until_the_loop_is_resolved(tmp_path: Path) -> None:
    complete_initial_pipeline(tmp_path)
    run_progress(
        tmp_path,
        "reroute",
        "experiment_config",
        "--reason",
        "The control condition cannot identify the claimed effect",
    )

    rerun_stages = [
        "experiment_config",
        "run_experiment",
        "analysis",
        "generate_paper",
    ]
    for stage in rerun_stages:
        before = read_progress(tmp_path)
        assert before["workspace"]["current_stage"] == stage
        assert before["stages"][stage]["status"] == "needs_revision"
        run_progress(tmp_path, "update-stage", stage, "in_progress")
        run_progress(tmp_path, "update-stage", stage, "completed")

    progress = read_progress(tmp_path)
    assert progress["workspace"]["active_reroute"] is None
    assert progress["workspace"]["current_stage"] == "generate_paper"
    assert progress["workspace"]["revision_round"] == 1
    assert all(
        progress["stages"][stage]["status"] == "completed" for stage in rerun_stages
    )
    assert all(progress["stages"][stage]["attempts"] == 2 for stage in rerun_stages)

    location = json.loads(run_progress(tmp_path, "where-am-i", "--json").stdout)
    assert location["next_recommended_actions"][0]["kind"] == "review_or_finish"


def test_reroute_rejects_forward_transitions_without_mutating_state(
    tmp_path: Path,
) -> None:
    run_progress(tmp_path, "init")
    before = read_progress(tmp_path)

    completed = run_progress(
        tmp_path,
        "reroute",
        "analysis",
        "--reason",
        "invalid forward jump",
        expected_returncode=1,
    )

    assert "must target the current stage or an earlier stage" in completed.stdout
    assert read_progress(tmp_path) == before

    manual_revision = run_progress(
        tmp_path,
        "update-stage",
        "literature_search",
        "needs_revision",
        expected_returncode=1,
    )
    assert "Use 'reroute' to create a revision round" in manual_revision.stdout
    assert read_progress(tmp_path) == before


def test_reroute_does_not_mark_never_started_downstream_work_as_revision(
    tmp_path: Path,
) -> None:
    run_progress(tmp_path, "init")
    for stage in STAGES[:-1]:
        run_progress(tmp_path, "update-stage", stage, "completed")

    run_progress(
        tmp_path,
        "reroute",
        "analysis",
        "--reason",
        "Analysis interpretation needs revision before paper generation",
    )
    progress = read_progress(tmp_path)

    assert progress["stages"]["analysis"]["status"] == "needs_revision"
    assert progress["stages"]["generate_paper"]["status"] == "not_started"
    assert progress["workspace"]["active_reroute"]["pending_stages"] == ["analysis"]

    run_progress(tmp_path, "update-stage", "analysis", "completed")
    progress = read_progress(tmp_path)
    assert progress["workspace"]["active_reroute"] is None
    assert progress["workspace"]["current_stage"] == "generate_paper"
    assert progress["stages"]["generate_paper"]["status"] == "not_started"


def test_legacy_progress_is_normalized_without_losing_completed_work(
    tmp_path: Path,
) -> None:
    progress_path = tmp_path / ".agentsociety/progress.json"
    progress_path.parent.mkdir(parents=True)
    progress_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "workspace": {
                    "topic": "legacy",
                    "created_at": "2025-01-01T00:00:00+00:00",
                    "current_stage": "hypothesis",
                    "current_hypothesis_id": None,
                    "current_experiment_id": None,
                },
                "stages": {
                    "literature_search": {
                        "status": "completed",
                        "started_at": None,
                        "completed_at": "2025-01-01T00:00:00+00:00",
                        "attempts": 1,
                        "error": None,
                        "metadata": {"paper_count": 12},
                    }
                },
                "hypotheses": {},
            }
        ),
        encoding="utf-8",
    )

    run_progress(tmp_path, "set-verification", "literature_search", "complete")
    progress = read_progress(tmp_path)

    assert progress["version"] == "1.3"
    assert progress["workspace"]["revision_round"] == 0
    assert progress["workspace"]["active_reroute"] is None
    assert progress["stages"]["literature_search"]["status"] == "completed"
    assert progress["stages"]["literature_search"]["metadata"] == {"paper_count": 12}
    assert progress["stages"]["literature_search"]["revision_round"] == 0
    assert progress["transitions"][-1]["kind"] == "verification_update"


def test_workspace_initializers_emit_revision_capable_progress_schema() -> None:
    workspace_manager_text = (
        REPO_ROOT / "extension/src/workspaceManager.ts"
    ).read_text(encoding="utf-8")
    workspace_cli_text = (
        REPO_ROOT / "packages/agentsociety2/agentsociety2/society/workspace.py"
    ).read_text(encoding="utf-8")

    for text in (workspace_manager_text, workspace_cli_text):
        assert "revision_round" in text
        assert "active_reroute" in text
        assert "transitions" in text
    assert "version: '1.3'" in workspace_manager_text
    assert '"version": "1.3"' in workspace_cli_text
    assert "needs_revision" in SCRIPT_PATH.read_text(encoding="utf-8")
