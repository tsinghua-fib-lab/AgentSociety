"""Regressions for replacing an installed custom skill through the API."""

from __future__ import annotations

import os
import zipfile
from collections.abc import Iterator
from io import BytesIO
from pathlib import Path

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from httpx import Response

from agentsociety2.agent.base.skill_registry import SkillRegistry
from agentsociety2.backend.routers import agent_skills

_SKILLS_URL = "/api/v1/agent-skills"
_INFO_URL = f"{_SKILLS_URL}/custom@demo/info"


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    registry = SkillRegistry()
    monkeypatch.setattr(agent_skills, "get_skill_registry", lambda: registry)
    monkeypatch.setenv("WORKSPACE_PATH", str(tmp_path))
    app = FastAPI()
    app.include_router(agent_skills.router)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def source(tmp_path: Path) -> Path:
    skill = tmp_path / "drafts" / "demo"
    skill.mkdir(parents=True)
    return skill


def _skill_doc(description: str, *, script: str = "") -> str:
    script_line = f"script: {script}\n" if script else ""
    return f'---\nname: demo\ndescription: "{description}"\n{script_line}---\n# Demo\n'


def _import_skill(client: TestClient, source: Path) -> Response:
    return client.post(f"{_SKILLS_URL}/import", json={"source_path": str(source)})


@pytest.fixture
def installed_skill(client: TestClient, source: Path, tmp_path: Path) -> Path:
    (source / "SKILL.md").write_text(_skill_doc("Original"), encoding="utf-8")
    (source / "original.txt").write_text("original resource", encoding="utf-8")
    response = _import_skill(client, source)
    assert response.status_code == 200, response.text
    return tmp_path.resolve() / "custom" / "skills" / "demo"


def test_reimport_updates_skill_info_and_files(
    client: TestClient, source: Path, installed_skill: Path
) -> None:
    description = "Updated --- description"
    doc = _skill_doc(description)
    (source / "SKILL.md").write_text(doc, encoding="utf-8")
    (source / "original.txt").unlink()
    (source / "updated.txt").write_text("new resource", encoding="utf-8")

    response = _import_skill(client, source)

    assert response.status_code == 200, response.text
    info = client.get(_INFO_URL).json()
    assert info["description"] == description
    assert info["skill_md"] == doc
    updated_resource = installed_skill / "updated.txt"
    assert updated_resource.read_text(encoding="utf-8") == "new resource"
    assert not (installed_skill / "original.txt").exists()


def test_incomplete_import_keeps_installed_skill(
    client: TestClient, source: Path, installed_skill: Path
) -> None:
    doc = _skill_doc("Incomplete", script="scripts/run.py")
    (source / "SKILL.md").write_text(doc, encoding="utf-8")

    response = _import_skill(client, source)

    assert response.status_code == 400, response.text
    assert client.get(_INFO_URL).json()["skill_md"] == _skill_doc("Original")
    assert (installed_skill / "original.txt").read_text(encoding="utf-8") == (
        "original resource"
    )


def test_failed_upload_restores_installed_skill(
    client: TestClient, installed_skill: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data = BytesIO()
    with zipfile.ZipFile(data, "w") as archive:
        archive.writestr("demo/SKILL.md", _skill_doc("Updated"))
        archive.writestr("demo/updated.txt", "new resource")

    replace = os.replace
    publish_attempted = False

    def fail_publish(source: Path, target: Path) -> None:
        nonlocal publish_attempted
        if target == installed_skill and (source / "updated.txt").is_file():
            publish_attempted = True
            raise OSError("simulated publication failure")
        replace(source, target)

    monkeypatch.setattr(agent_skills.os, "replace", fail_publish)
    response = client.post(
        f"{_SKILLS_URL}/upload", files={"file": ("demo.zip", data.getvalue())}
    )

    assert publish_attempted
    assert response.status_code == 500, response.text
    info = client.get(_INFO_URL).json()
    assert info["description"] == "Original"
    assert info["skill_md"] == _skill_doc("Original")
    assert (installed_skill / "original.txt").read_text(encoding="utf-8") == (
        "original resource"
    )


def test_custom_module_scanner_runs_without_backend_workspace_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agentsociety2.backend.services.custom.scanner import CustomModuleScanner

    monkeypatch.delenv("WORKSPACE_PATH", raising=False)
    (tmp_path / "custom" / "envs").mkdir(parents=True)
    (tmp_path / "custom" / "agents").mkdir()

    internal = CustomModuleScanner(tmp_path, validate_workspace_root=False)
    result = internal.scan_all()

    assert result["errors"] == []
    with pytest.raises(HTTPException):
        CustomModuleScanner(tmp_path)
