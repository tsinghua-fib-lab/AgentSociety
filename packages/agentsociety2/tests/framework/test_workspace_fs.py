import shutil

import pytest

from agentsociety2.agent.base.workspace_fs import WorkspaceFS


@pytest.mark.asyncio
async def test_workspace_fs_file_ops_and_grep(tmp_path):
    fs = WorkspaceFS(tmp_path)

    fs.write_text("state/a.txt", "hello\nworld\n")
    fs.append_text("state/a.txt", "hello again\n")

    assert fs.read_text("state/a.txt") == "hello\nworld\nhello again\n"
    assert fs.exists("state/a.txt")
    assert [item.path for item in fs.list("state")] == ["state/a.txt"]

    matches = await fs.grep("hello", "state")
    assert [(item.path, item.line) for item in matches] == [
        ("state/a.txt", 1),
        ("state/a.txt", 3),
    ]

    result = fs.delete("state/a.txt")
    assert result.ok
    assert not fs.exists("state/a.txt")


@pytest.mark.asyncio
async def test_workspace_fs_grep_python_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    fs = WorkspaceFS(tmp_path)
    fs.write_text("state/a.txt", "hello\nworld\nhello again\n")

    matches = await fs.grep("hello", "state")
    assert [(item.path, item.line) for item in matches] == [
        ("state/a.txt", 1),
        ("state/a.txt", 3),
    ]


def test_workspace_fs_path_escape_without_size_limit(tmp_path):
    fs = WorkspaceFS(tmp_path)
    fs.write_text("big.txt", "12345")

    with pytest.raises(ValueError):
        fs.read_text("../escape.txt")

    assert fs.read_text("big.txt") == "12345"


@pytest.mark.asyncio
async def test_workspace_fs_command_allowlist(tmp_path):
    fs = WorkspaceFS(tmp_path)

    blocked = await fs.run_command(["bash", "-lc", "echo bad"])

    assert not blocked.ok
    assert blocked.error_type == "validation"
