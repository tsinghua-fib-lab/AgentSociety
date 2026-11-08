"""Workspace writes and backend requests enforce their access boundaries."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from agentsociety2.agent import PersonAgent
from agentsociety2.agent.base.agent import AgentBase
from agentsociety2.agent.base.workspace_fs import WorkspaceFS
from agentsociety2.backend.app import app


@pytest.mark.parametrize("method", ["write_text", "append_text", "delete"])
@pytest.mark.parametrize("alias", [False, True])
def test_runtime_files_cannot_be_mutated(tmp_path, method, alias):
    runtime = tmp_path / ".runtime"
    runtime.mkdir()
    owned = runtime / "state"
    owned.write_text("original")
    (tmp_path / "alias").symlink_to(runtime, target_is_directory=True)
    fs = WorkspaceFS(tmp_path)
    path = "alias/state" if alias else ".runtime/state"
    args = (path,) if method == "delete" else (path, "malicious")
    result = getattr(fs, method)(*args)
    assert not result.ok
    assert owned.read_text() == "original"


async def test_grep_child_has_own_session(tmp_path, monkeypatch):
    process = SimpleNamespace(
        communicate=AsyncMock(return_value=(b"", b"")), returncode=1
    )
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    await WorkspaceFS(tmp_path).grep("--pre=untrusted")
    assert spawn.call_args.kwargs.get("start_new_session") is True
    argv = spawn.call_args.args
    assert argv[argv.index("-e") + 1] == "--pre=untrusted"
    assert "--" in argv


async def test_fallback_grep_does_not_follow_workspace_symlinks(tmp_path, monkeypatch):
    import shutil

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("sensitive-needle")
    (workspace / "linked").symlink_to(outside, target_is_directory=True)
    original = shutil.which
    monkeypatch.setattr(
        shutil, "which", lambda command: None if command == "rg" else original(command)
    )
    assert await WorkspaceFS(workspace).grep("sensitive-needle") == []


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_backend_rejects_untrusted_origins_before_routing(method):
    response = TestClient(app, base_url="http://localhost").request(
        method, "/health", headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5173", "http://127.0.0.1:5173", "vscode-webview://a1-b2"],
)
def test_backend_allows_local_origins(origin):
    client = TestClient(app, base_url="http://localhost")
    assert client.get("/health", headers={"Origin": origin}).status_code == 200
    preflight = client.options(
        "/health", headers={"Origin": origin, "Access-Control-Request-Method": "POST"}
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin


def test_backend_rejects_rebinding_host_and_null_origin():
    client = TestClient(app, base_url="http://localhost")
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/health", headers={"Origin": "null"}).status_code == 403


@pytest.mark.parametrize(
    "path",
    [
        "subdir/../AGENT.json",
        "agent.json",
        "x/../memory/episodes.jsonl",
        "TODO.json",
        "state/todos_archive.jsonl",
    ],
)
def test_core_owned_paths_are_normalized(path):
    assert AgentBase._is_core_owned_workspace_path(path)
    assert not AgentBase._is_core_owned_workspace_path("notes.md")


@pytest.mark.parametrize("action", ["write", "append"])
@pytest.mark.parametrize("target_name", ["config.json", "TODO.json"])
async def test_react_writes_cannot_modify_core_files_through_symlinks(
    tmp_path, action, target_name
):
    target = tmp_path / target_name
    target.write_text("original")
    (tmp_path / "notes-link").symlink_to(target)
    agent = PersonAgent()
    agent._workspace_fs = WorkspaceFS(tmp_path)
    result = await agent.dispatch_react_tool(
        action, {"path": "notes-link", "content": "replacement"}
    )
    assert result.data["core_owned"] is True
    assert target.read_text() == "original"
