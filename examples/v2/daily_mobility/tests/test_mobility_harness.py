"""Mobility harness verification and Daily Mobility gate checks."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from agentsociety2.skills.experiment.models import split_agent_kwargs
from daily_mobility.mobility_snapshot import verify_move_effect
from daily_mobility.tools.check_daily_mobility_run import evaluate_gates


@pytest.fixture
def config_env(tmp_path):
    profiles = tmp_path / "profiles.json"
    profiles.write_text(json.dumps([{"id": i, "home": 10, "work": 20} for i in (1, 2)]))
    map_path = tmp_path / "map.pb"
    map_path.touch()  # Config generation only records the map location.
    return {
        **{k: v for k, v in os.environ.items() if not k.startswith("DAILY_MOBILITY_")},
        "DAILY_MOBILITY_PROFILES_PATH": str(profiles),
        "DAILY_MOBILITY_MAP_PATH": str(map_path),
        "DAILY_MOBILITY_INIT_DIR": str(tmp_path / "init"),
        "DAILY_MOBILITY_RUN_DIR": str(tmp_path / "run"),
        "DAILY_MOBILITY_PRESET": "benchmark",
        "DAILY_MOBILITY_NUM_AGENTS": "2",
    }


def test_verify_move_effect_accepts_live_target_trip():
    result = verify_move_effect(
        before={"status": "idle", "aoi_id": 1},
        after={"status": "moving", "aoi_id": None, "target_aoi_id": 2},
        target_id=2,
    )
    assert result["ok"] is True


def test_verify_move_effect_rejects_unchanged_state():
    result = verify_move_effect(
        before={"status": "idle", "aoi_id": 1},
        after={"status": "idle", "aoi_id": 1, "target_aoi_id": None},
        target_id=2,
    )
    assert result["ok"] is False


def test_daily_mobility_gate_fails_for_location_intention_mismatch():
    report = {"totals": {"work_while_home": 3}, "agents": {}}
    gate = evaluate_gates(report)
    assert gate["status"] == "FAIL"
    assert gate["failures"][0]["issue"] == "work_while_home"


def test_benchmark_config_activates_daily_guidance_without_template_cache(
    tmp_path, config_env
):
    script = Path(__file__).resolve().parents[1] / "init" / "config_params.py"

    subprocess.run([sys.executable, str(script)], check=True, env=config_env)

    cfg_path = tmp_path / "init" / "init_config.json"
    config = json.loads(cfg_path.read_text(encoding="utf-8"))
    agents = config["agents"]
    assert len(agents) == 2
    for agent in agents:
        profile, settings = split_agent_kwargs(agent["agent_id"], agent["kwargs"])
        assert profile["id"] == agent["agent_id"]
        assert "home AOI 10" in profile["description"]
        assert settings["default_activated_skill_ids"] == [
            "built-in@daily-guidance", "env:MobilitySpace@mobility"
        ]
        assert "disabled_skill_ids" not in settings

    steps_path = tmp_path / "init" / "steps.yaml"
    steps = yaml.safe_load(steps_path.read_text(encoding="utf-8"))["steps"]
    questionnaires = [step for step in steps if step["type"] == "questionnaire"]
    run_steps = sum(step.get("num_steps", 0) for step in steps if step["type"] == "run")
    assert len(questionnaires) == 48
    assert run_steps == 96
    first_prompt = questionnaires[0]["questions"][0]["prompt"]
    assert "time slot 1 of 48" in first_prompt
    assert "30-minute period" in first_prompt
    assert "dominant" in first_prompt.casefold()
    assert "current" in first_prompt.casefold()
    # The agent now reasons via its ReAct loop; the prompt no longer hard-codes
    # benchmark clock rules (those moved to postprocess normalization).
    assert "22:00-06:30" not in first_prompt
    assert "State first" not in first_prompt


def test_benchmark_config_can_generate_48_hour_run(tmp_path, config_env):
    script = Path(__file__).resolve().parents[1] / "init" / "config_params.py"
    config_env["DAILY_MOBILITY_DURATION_HOURS"] = "48"

    subprocess.run([sys.executable, str(script)], check=True, env=config_env)

    steps_path = tmp_path / "init" / "steps.yaml"
    steps = yaml.safe_load(steps_path.read_text(encoding="utf-8"))["steps"]
    questionnaires = [step for step in steps if step["type"] == "questionnaire"]
    run_steps = sum(step.get("num_steps", 0) for step in steps if step["type"] == "run")

    assert len(questionnaires) == 96
    assert run_steps == 192
    last_prompt = questionnaires[-1]["questions"][0]["prompt"]
    assert "time slot 96 of 96" in last_prompt
    assert "dominant" in last_prompt.casefold()
