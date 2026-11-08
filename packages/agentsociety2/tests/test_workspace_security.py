"""Workspace tools reject protected and escaping paths."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentsociety2.agent.base.workspace_fs import WorkspaceFS


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
