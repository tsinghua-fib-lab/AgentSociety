"""实验运行清单、恢复记录与随机种子的可复现性。"""

import json
import os
import random
from pathlib import Path

from agentsociety2.society.provenance import build_run_manifest, write_run_manifest


def test_run_manifest_records_hashes_and_seed(tmp_path: Path) -> None:
    config = tmp_path / "init_config.json"
    steps = tmp_path / "steps.yaml"
    config.write_text('{"agents": [], "env_modules": []}', encoding="utf-8")
    steps.write_text("steps: []\nstart_t: '2026-01-01T00:00:00'\n", encoding="utf-8")

    manifest = build_run_manifest(
        config,
        steps,
        seed=7,
        batch_size=4,
        replay_disabled=False,
        experiment_id="exp",
    )
    path = write_run_manifest(tmp_path, manifest, resume=False)
    saved = json.loads(path.read_text(encoding="utf-8"))

    assert saved["seed"] == 7
    assert saved["config"]["sha256"] == manifest["config"]["sha256"]
    assert saved["steps"]["sha256"] == manifest["steps"]["sha256"]
    assert saved["runtime"]["agentsociety2_version"]
    # Code provenance comes from the installed package, not the config location,
    # so a workspace outside the repo still records the dependency lock.
    assert saved["runtime"]["dependency_lock"]["sha256"]
    assert "workspace_git" in saved


def test_resume_manifest_does_not_overwrite_original(tmp_path: Path) -> None:
    config = tmp_path / "init_config.json"
    steps = tmp_path / "steps.yaml"
    config.write_text("{}", encoding="utf-8")
    steps.write_text("steps: [1]\n", encoding="utf-8")
    first = build_run_manifest(
        config,
        steps,
        seed=1,
        batch_size=None,
        replay_disabled=False,
        experiment_id=None,
    )
    write_run_manifest(tmp_path, first, resume=False)

    steps.write_text("steps: [2]\n", encoding="utf-8")
    second = build_run_manifest(
        config,
        steps,
        seed=1,
        batch_size=None,
        replay_disabled=False,
        experiment_id=None,
    )
    path = write_run_manifest(tmp_path, second, resume=True)

    assert path.name == "run_manifest.resume.json"
    original = json.loads((tmp_path / "run_manifest.json").read_text(encoding="utf-8"))
    assert original["steps"]["sha256"] == first["steps"]["sha256"]


def test_resume_manifest_records_changed_seed_with_identical_inputs(tmp_path):
    manifest = {"config": {"sha256": "a"}, "steps": {"sha256": "b"}, "seed": 1}
    primary = write_run_manifest(tmp_path, manifest, resume=False)
    resumed = write_run_manifest(tmp_path, {**manifest, "seed": 2}, resume=True)
    assert resumed != primary
    assert json.loads(primary.read_text())["seed"] == 1
    assert json.loads(resumed.read_text())["resume_of"]["changed_settings"] == ["seed"]


def test_worker_random_streams_are_repeatable_and_distinct(monkeypatch):
    from agentsociety2.society.provenance import apply_seed_from_env

    monkeypatch.setenv("AGENTSOCIETY_SEED", "7")

    def draw(tick, agent_ids):
        apply_seed_from_env("step", "ExampleAgent", tick, agent_ids)
        return random.random()

    first = draw(1, [0, 1])
    assert first == draw(1, [0, 1])
    assert len({first, draw(2, [0, 1]), draw(1, [2, 3])}) == 3
    assert os.environ["AGENTSOCIETY_SEED"] == "7"


def test_shared_run_manifest_records_only_public_llm_settings(monkeypatch):
    from agentsociety2.config import Config
    from agentsociety2.society.provenance import collect_llm_provenance

    monkeypatch.setattr(
        Config,
        "LLM_API_BASE",
        "https://user:sample@localhost:8443/private?token=sample",
    )
    monkeypatch.setattr(Config, "LLM_EXTRA_BODY", '{"custom_header":"private-value"}')
    llm = collect_llm_provenance()
    assert llm["api_base"] == "https://localhost:8443"
    assert llm["extra_body_configured"] is True
    assert "sample" not in json.dumps(llm) and "private-value" not in json.dumps(llm)
