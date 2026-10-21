import os
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from fastapi import HTTPException

from agentsociety2.backend.path_security import (
    extract_zip_under,
    require_disjoint_copy_paths,
    require_safe_skill_name,
    resolve_path_under_directory,
    resolve_under_root,
    resolve_workspace_root,
)
from agentsociety2.backend.services.custom.compatibility import (
    ensure_relative_to_workspace,
)


def test_workspace_root_is_fixed_by_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    sibling = tmp_path / "sibling"
    sibling.mkdir()
    monkeypatch.setenv("WORKSPACE_PATH", str(workspace))

    assert resolve_workspace_root(str(workspace)) == workspace.resolve()
    with pytest.raises(HTTPException, match="Workspace path is not allowed"):
        resolve_workspace_root(str(sibling))


def test_resolve_under_root_rejects_traversal(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    similar_prefix = tmp_path / "workspace-escape"
    similar_prefix.mkdir()

    with pytest.raises(HTTPException, match="Path escapes workspace root"):
        resolve_under_root(workspace, "..", "outside")
    with pytest.raises(HTTPException, match="Path escapes workspace root"):
        resolve_under_root(workspace, str(similar_prefix))
    with pytest.raises(HTTPException, match="Path escapes workspace root"):
        resolve_under_root(workspace, "foo bar.md")


def test_resolve_under_root_rebuilds_allowlisted_segments(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    resolved = resolve_under_root(workspace, "scripts", "run.py")
    assert resolved == (workspace / "scripts" / "run.py").resolve()
    hidden = resolve_under_root(workspace, ".agentsociety", "prefill_params.json")
    assert hidden == (workspace / ".agentsociety" / "prefill_params.json").resolve()
    for part in ("...", ".bad name", "foo bar"):
        with pytest.raises(HTTPException, match="Path escapes workspace root"):
            resolve_under_root(workspace, part)


def test_resolve_under_root_handles_root_and_symlink_escape(tmp_path: Path) -> None:
    assert resolve_under_root(Path(os.path.abspath(os.sep)), "tmp").is_absolute()

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (workspace / "link").symlink_to(outside, target_is_directory=True)

    with pytest.raises(HTTPException, match="Path escapes workspace root"):
        resolve_under_root(workspace, "link", "file.txt")


def test_resolve_path_under_directory_stays_inside_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    source = workspace / "drafts" / "my-skill"
    source.mkdir(parents=True)
    assert resolve_path_under_directory(workspace, str(source)) == source.resolve()

    outside = tmp_path / "outside" / "evil"
    outside.mkdir(parents=True)
    with pytest.raises(HTTPException, match="Path escapes allowed directory"):
        resolve_path_under_directory(workspace, str(outside))


def test_relative_workspace_path_rejects_similar_prefix(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    child = workspace / "custom" / "skill.py"
    child.parent.mkdir()
    child.touch()
    outside = tmp_path / "workspace-escape" / "skill.py"
    outside.parent.mkdir()
    outside.touch()

    assert ensure_relative_to_workspace(workspace, child) == os.path.join(
        "custom", "skill.py"
    )
    with pytest.raises(ValueError, match="Target path escapes workspace"):
        ensure_relative_to_workspace(workspace, outside)


def test_extract_zip_under_rejects_traversal(tmp_path: Path) -> None:
    archive_data = BytesIO()
    with ZipFile(archive_data, "w") as archive:
        archive.writestr("../outside.txt", "unsafe")
    archive_data.seek(0)

    with ZipFile(archive_data) as archive:
        with pytest.raises(HTTPException, match="Path escapes workspace root"):
            extract_zip_under(tmp_path / "destination", archive)


def test_extract_zip_under_rejects_absolute_path(tmp_path: Path) -> None:
    archive_data = BytesIO()
    with ZipFile(archive_data, "w") as archive:
        archive.writestr("/outside.txt", "unsafe")
    archive_data.seek(0)

    with ZipFile(archive_data) as archive:
        with pytest.raises(HTTPException, match="Path escapes workspace root"):
            extract_zip_under(tmp_path / "destination", archive)


def test_require_safe_skill_name() -> None:
    assert require_safe_skill_name("daily-guidance") == "daily-guidance"
    for name in ("../evil", "a/b", "my skill", ".", ""):
        with pytest.raises(HTTPException, match="Invalid skill name"):
            require_safe_skill_name(name)


@pytest.mark.parametrize(
    "source_suffix,dest_suffix",
    [("skill", "skill"), ("skill", "skill/copy"), ("skill/copy", "skill")],
)
def test_copy_paths_must_not_overlap(
    tmp_path: Path, source_suffix: str, dest_suffix: str
) -> None:
    source = tmp_path / source_suffix
    destination = tmp_path / dest_suffix

    with pytest.raises(HTTPException, match="Source and destination overlap"):
        require_disjoint_copy_paths(source, destination)


@pytest.mark.parametrize("source", ["auto", "output.log", "stderr.log"])
def test_log_path_rejects_symlink_escape(tmp_path: Path, source: str) -> None:
    from agentsociety2.backend.routers.experiments import _resolve_experiment_log_path

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    secret = tmp_path / "secret.txt"
    secret.write_text("private")
    name = "stderr.log" if source == "stderr.log" else "output.log"
    (run_dir / name).symlink_to(secret)
    with pytest.raises(HTTPException, match="Path escapes workspace root"):
        _resolve_experiment_log_path(run_dir, source)


@pytest.mark.parametrize(
    "source", ["../secret.txt", "/etc/passwd", "output.log/..", ""]
)
def test_log_path_rejects_unknown_sources(tmp_path: Path, source: str) -> None:
    from agentsociety2.backend.routers.experiments import _resolve_experiment_log_path

    with pytest.raises(HTTPException, match="Unsupported log source"):
        _resolve_experiment_log_path(tmp_path, source)


def test_log_path_auto_fallback_and_explicit_selection(tmp_path: Path) -> None:
    from agentsociety2.backend.routers.experiments import _resolve_experiment_log_path

    stderr = tmp_path / "stderr.log"
    stderr.write_text("stderr")
    assert _resolve_experiment_log_path(tmp_path, "auto") == stderr
    with pytest.raises(HTTPException) as exc:
        _resolve_experiment_log_path(tmp_path, "output.log")
    assert exc.value.status_code == 404
    output = tmp_path / "output.log"
    output.write_text("stdout")
    assert _resolve_experiment_log_path(tmp_path, "auto") == output
    assert _resolve_experiment_log_path(tmp_path, "stderr.log") == stderr
