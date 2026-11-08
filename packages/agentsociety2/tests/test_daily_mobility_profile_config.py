"""The scenario supplies commute locations and activates its known action skill."""

import importlib.util
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "tick,expected_minutes", [(900, "15"), (1800, "30"), (45, "0.75")]
)
def test_generated_config_preserves_commute_fields_and_activates_mobility(
    tmp_path, monkeypatch, tick, expected_minutes
):
    source = (
        Path(__file__).resolve().parents[3]
        / "examples/v2/daily_mobility/init/config_params.py"
    )
    spec = importlib.util.spec_from_file_location(
        "daily_mobility_profile_config", source
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    profiles = tmp_path / "profiles.json"
    profiles.write_text(
        json.dumps(
            [
                {"id": 1, "home": 500000001, "work": 500000002},
                {"id": 2, "home": 500000003},
            ]
        )
    )
    mapfile = tmp_path / "owned-map.pb"
    mapfile.write_bytes(b"owned-config-fixture")
    monkeypatch.setenv("DAILY_MOBILITY_PROFILES_PATH", str(profiles))
    monkeypatch.setenv("DAILY_MOBILITY_MAP_PATH", str(mapfile))
    monkeypatch.setenv("DAILY_MOBILITY_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("DAILY_MOBILITY_PRESET", "smoke")
    monkeypatch.setenv("DAILY_MOBILITY_TICK_SEC", str(tick))
    monkeypatch.setenv("DAILY_MOBILITY_SLOT_MINUTES", "30")
    monkeypatch.setenv("DAILY_MOBILITY_NUM_AGENTS", "2")
    monkeypatch.setattr(module, "TMP_INIT_DIR", tmp_path / "init")
    monkeypatch.setattr(module, "TMP_RUN_DIR", tmp_path / "run")
    module.main()
    config = json.loads((tmp_path / "init/init_config.json").read_text())
    persons = config["env_modules"][0]["kwargs"]["persons"]
    assert [(p["home_aoi"], p["work_aoi"]) for p in persons] == [
        (500000001, 500000002),
        (500000003, None),
    ]
    for agent in config["agents"]:
        assert (
            f"Each simulation step advances about {expected_minutes} minutes"
            in agent["kwargs"]["profile"]
        )
        assert agent["kwargs"]["default_activated_skill_ids"] == [
            "built-in@daily-guidance",
            "env:MobilitySpace@mobility",
        ]
