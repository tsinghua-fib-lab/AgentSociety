"""Regression checks for an experiment prepared through the research skills."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from agentsociety2.contrib.agent.specialist_agent import SpecialistAgent
from agentsociety2.skills.experiment.config import get_experiment_paths
from agentsociety2.skills.experiment.models import split_agent_kwargs
from agentsociety2.skills.experiment.runner import get_experiment_status
from agentsociety2.society.cli import ExperimentRunner
from agentsociety2.society.models import QuestionItem
from agentsociety2.society.questionnaire import Questionnaire, QuestionnaireRunner


def test_agent_records_accept_flat_and_nested_fields():
    kwargs = {
        "id": 1,
        "name": "legacy",
        "age": 22,
        "max_react_turns": 4,
        "profile": {"name": "Participant 1"},
        "config": {"enable_memory": False, "own_option": "custom"},
    }
    profile, config = split_agent_kwargs(1, kwargs)
    assert profile == {"id": 1, "name": "Participant 1", "age": 22}
    assert config == {
        "max_react_turns": 4,
        "enable_memory": False,
        "own_option": "custom",
    }
    with pytest.raises(ValueError, match="must match"):
        split_agent_kwargs(2, kwargs)


def test_choice_questions_require_options_when_omitted():
    with pytest.raises(ValidationError, match="choices are required"):
        QuestionItem(id="item", prompt="Which?", response_type="choice")


@pytest.mark.asyncio
async def test_contrib_agent_can_answer_at_the_simulation_time():
    agent = SpecialistAgent()
    agent._id, agent._name = 1, "Participant"
    agent._config = {"specialty": "metrology"}
    survey = Questionnaire(
        questionnaire_id="lines",
        questions=[QuestionItem(id="item", prompt="Your specialty?")],
    )
    result = await QuestionnaireRunner().run(
        survey, [agent], t=datetime(2026, 1, 1), step_count=0
    )
    assert "metrology" in result.responses[0].answers[0].raw_text


@pytest.mark.asyncio
async def test_status_reads_the_specified_run(tmp_path: Path):
    paths = get_experiment_paths(tmp_path, "1", "2", "repeat")
    paths["run"].mkdir(parents=True)
    paths["pid_file"].write_text('{"status":"completed"}')
    assert (
        await get_experiment_status(tmp_path, "1", "2", "repeat")
    ).status == "completed"
    assert (await get_experiment_status(tmp_path, "1", "2")).status != "completed"
    with pytest.raises(ValueError, match="run_id"):
        get_experiment_paths(tmp_path, "1", "2", "init")


@pytest.mark.asyncio
async def test_questionnaire_artifact_round_trip(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from agentsociety2.backend.routers.experiments import get_artifact, list_artifacts

    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    artifacts = tmp_path / "hypothesis_1/experiment_1/run/artifacts"
    artifacts.mkdir(parents=True)
    name = "questionnaire_step_0_20260101_120000.json"
    (artifacts / name).write_text('{"responses":[]}')
    (artifacts / "private.json").write_text("{}")
    listed = await list_artifacts("1", "1", str(tmp_path))
    assert [(row["type"], row["name"]) for row in listed] == [("questionnaire", name)]
    assert (await get_artifact("1", "1", name, str(tmp_path)))[
        "content"
    ] == '{"responses":[]}'
    with pytest.raises(HTTPException, match="Invalid artifact name"):
        await get_artifact("1", "1", "private.json", str(tmp_path))


@pytest.mark.parametrize("value", ["2026-01-01T12:00:00", '"2026-01-01T12:00:00"'])
def test_yaml_timestamp_with_or_without_quotes(tmp_path: Path, value: str):
    runner = ExperimentRunner(tmp_path)
    steps = tmp_path / "steps.yaml"
    steps.write_text(
        f"start_t: {value}\nsteps: [{{type: ask, question: Hello}}]", encoding="utf-8"
    )
    assert runner._load_steps(steps).start_t == "2026-01-01T12:00:00"


def test_duplicate_agent_ids_rejected(tmp_path: Path) -> None:
    runner = ExperimentRunner(run_dir=tmp_path)
    agent_args = [
        {"agent_id": 1, "agent_type": "PersonAgent", "kwargs": {"id": 1}},
        {"agent_id": 1, "agent_type": "PersonAgent", "kwargs": {"id": 1}},
    ]
    with pytest.raises(ValueError, match="Duplicate agent id"):
        runner._build_agent_specs(agent_args)


def test_fresh_run_guard_rejects_and_overwrite_clears(tmp_path: Path) -> None:
    from agentsociety2.society.cli import _guard_fresh_run

    (tmp_path / "SOCIETY.json").write_text("{}", encoding="utf-8")
    (tmp_path / "replay").mkdir()
    with pytest.raises(SystemExit, match="--resume"):
        _guard_fresh_run(tmp_path, resume=False, overwrite=False)

    _guard_fresh_run(tmp_path, resume=False, overwrite=True)
    assert not (tmp_path / "SOCIETY.json").exists()
    assert not (tmp_path / "replay").exists()


def test_experiment_ids_reject_path_traversal(tmp_path: Path) -> None:
    from agentsociety2.skills.experiment.config import get_experiment_paths

    with pytest.raises(ValueError, match="hypothesis_id"):
        get_experiment_paths(tmp_path, "../../escape", "1")
    with pytest.raises(ValueError, match="experiment_id"):
        get_experiment_paths(tmp_path, "1", "..")


def test_simulator_process_uses_its_working_directory(tmp_path, monkeypatch):
    from unittest.mock import Mock

    from agentsociety2.skills.experiment.runner import _experiment_process

    process = Mock()
    process.cwd.return_value = str(tmp_path)
    monkeypatch.setattr(
        "agentsociety2.skills.experiment.runner.psutil.Process", lambda pid: process
    )
    command = [sys.executable, "-m", "agentsociety2.society.cli"]
    assert (
        _experiment_process(123, tmp_path, {"run_dir": str(tmp_path / "other")}) is None
    )
    process.cmdline.return_value = command
    assert _experiment_process(123, tmp_path, {}) is process
    process.cmdline.return_value = [*command, "--run-dir=trial-10"]
    assert _experiment_process(123, tmp_path / "trial-10", {}) is process
    assert _experiment_process(123, tmp_path / "trial-1", {}) is None


@pytest.mark.asyncio
async def test_documented_experiment_preparation_api(tmp_path):
    from agentsociety2.skills.experiment import start_experiment

    init = tmp_path / "hypothesis_1/experiment_1/init"
    init.mkdir(parents=True)
    (init / "init_config.json").write_text("{}")
    (init / "steps.yaml").write_text("steps: []")
    result = await start_experiment(tmp_path, "1", "1")
    assert result["success"]
    assert Path(result["run_dir"]).is_dir()
    assert Path(result["steps_file"]) == init / "steps.yaml"


@pytest.mark.asyncio
async def test_completed_with_errors_is_terminal_for_status_and_list(tmp_path):
    from agentsociety2.skills.experiment import get_experiment_status, list_experiments

    run = tmp_path / "hypothesis_1/experiment_1/run"
    run.mkdir(parents=True)
    (run / "pid.json").write_text(
        json.dumps({"pid": os.getpid(), "status": "completed_with_errors"})
    )
    status = await get_experiment_status(tmp_path, "1", "1")
    experiments = await list_experiments(tmp_path, "1")
    for result in (status, experiments[0]):
        assert not result.is_running
        assert result.status == "completed_with_errors"
