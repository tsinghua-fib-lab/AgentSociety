from __future__ import annotations

import os
import re
import shutil
import zipfile
from pathlib import Path

from fastapi import HTTPException

_SAFE_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
# Allow normal segments and single-dot hidden names (e.g. `.agentsociety`).
# Reject `.` / `..` and any segment that is only dots.
_SAFE_PATH_PART_RE = re.compile(
    r"^(?:[A-Za-z0-9_]|[.][A-Za-z0-9_])(?:[A-Za-z0-9_-]|[.][A-Za-z0-9_-])*$"
)
_ARTIFACT_NAME_RE = re.compile(r"^(?:[a-zA-Z0-9][a-zA-Z0-9_.-]*\.md|questionnaire_step_[0-9]+_[0-9]{8}_[0-9]{6}\.json)$")


def _configured_workspace_root() -> str:
    workspace_path = os.getenv("WORKSPACE_PATH", "").strip()
    if not workspace_path or "\0" in workspace_path:
        raise HTTPException(status_code=500, detail="WORKSPACE_PATH is not configured")
    return os.path.realpath(os.path.expanduser(workspace_path))


def resolve_workspace_root(workspace_path: str) -> Path:
    requested = workspace_path.strip()
    if not requested or "\0" in requested:
        raise HTTPException(status_code=400, detail="Invalid workspace_path")
    allowed_root = _configured_workspace_root()
    requested_root = os.path.realpath(os.path.expanduser(requested))
    if requested_root != allowed_root:
        raise HTTPException(status_code=403, detail="Workspace path is not allowed")
    if not os.path.isdir(allowed_root):
        raise HTTPException(
            status_code=404, detail=f"Workspace not found: {workspace_path}"
        )
    return Path(allowed_root)


def require_safe_segment(value: str, *, field: str) -> str:
    if not _SAFE_SEGMENT_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"Invalid {field}: {value}")
    return value


def _ensure_under(
    base: Path | str,
    candidate: Path | str,
    *,
    detail: str = "Path escapes allowed directory",
) -> Path:
    """Resolve ``candidate``, require it stays under ``base``, and rebuild it.

    Each remaining path segment must match ``_SAFE_PATH_PART_RE`` so the
    returned path is reconstructed from allowlisted tokens, not the raw input.
    """
    base_resolved = Path(os.path.realpath(os.fspath(base)))
    target_resolved = Path(os.path.realpath(os.fspath(candidate)))
    if not target_resolved.is_relative_to(base_resolved):
        raise HTTPException(status_code=400, detail=detail)

    safe = base_resolved
    for part in target_resolved.relative_to(base_resolved).parts:
        if not _SAFE_PATH_PART_RE.fullmatch(part):
            raise HTTPException(status_code=400, detail=detail)
        safe = safe / part
    return safe


def resolve_under_root(root: Path, *parts: str) -> Path:
    for part in parts:
        if "\0" in part:
            raise HTTPException(status_code=400, detail="Invalid path component")
    base = Path(os.path.realpath(os.fspath(root)))
    return _ensure_under(
        base,
        Path(os.path.join(os.fspath(base), *parts)),
        detail="Path escapes workspace root",
    )


def resolve_workspace_relative(root: Path, relative: str) -> Path:
    return resolve_under_root(root, relative)


def resolve_experiment_dir(
    workspace_path: str,
    hypothesis_id: str,
    experiment_id: str,
) -> Path:
    root = resolve_workspace_root(workspace_path)
    require_safe_segment(hypothesis_id, field="hypothesis_id")
    require_safe_segment(experiment_id, field="experiment_id")
    return resolve_under_root(
        root,
        f"hypothesis_{hypothesis_id}",
        f"experiment_{experiment_id}",
    )


def resolve_experiment_db(
    workspace_path: str,
    hypothesis_id: str,
    experiment_id: str,
) -> Path:
    db_path = resolve_under_root(
        resolve_experiment_dir(workspace_path, hypothesis_id, experiment_id),
        "run",
        "sqlite.db",
    )
    if not db_path.is_file():
        raise HTTPException(status_code=404, detail=f"Database not found: {db_path}")
    return db_path


def resolve_experiment_replay_dir(
    workspace_path: str,
    hypothesis_id: str,
    experiment_id: str,
) -> Path:
    replay_dir = resolve_under_root(
        resolve_experiment_dir(workspace_path, hypothesis_id, experiment_id),
        "run",
        "replay",
    )
    if not replay_dir.is_dir():
        raise HTTPException(
            status_code=404, detail=f"Replay directory not found: {replay_dir}"
        )
    schema_path = replay_dir / "_schema.json"
    if not schema_path.is_file():
        raise HTTPException(
            status_code=404, detail=f"Replay schema not found: {schema_path}"
        )
    return replay_dir


def resolve_artifact_path(
    workspace_path: str,
    hypothesis_id: str,
    experiment_id: str,
    artifact_name: str,
) -> Path:
    if "/" in artifact_name or "\\" in artifact_name or artifact_name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid artifact name")
    if not _ARTIFACT_NAME_RE.fullmatch(artifact_name):
        raise HTTPException(status_code=400, detail="Invalid artifact name")
    return resolve_under_root(
        resolve_experiment_dir(workspace_path, hypothesis_id, experiment_id),
        "run",
        "artifacts",
        artifact_name,
    )


def require_safe_skill_name(name: str) -> str:
    """Return ``name`` when it matches the skill-name allowlist.

    :param name: Proposed skill directory name.
    :returns: The validated name.
    :raises HTTPException: When the name is empty or contains unsafe characters.
    """
    if not _SAFE_SEGMENT_RE.fullmatch(name):
        raise HTTPException(status_code=400, detail="Invalid skill name")
    return name


def resolve_existing_directory(path_str: str) -> Path:
    target = resolve_path_under_directory(
        resolve_workspace_root(os.getenv("WORKSPACE_PATH", "")), path_str
    )
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {path_str}")
    return target


def custom_skills_root(workspace_path: str) -> Path:
    return resolve_under_root(
        resolve_workspace_root(workspace_path), "custom", "skills"
    )


def skill_install_dir(workspace_path: str, skill_name: str) -> Path:
    root = custom_skills_root(workspace_path)
    name = require_safe_skill_name(skill_name)
    target = resolve_under_root(root, name)
    if target != root / name:
        raise HTTPException(400, "Skill destination must not be a symbolic link")
    return target


def resolve_skill_relative(skill_dir: Path, relative: str) -> Path:
    return resolve_workspace_relative(skill_dir, relative)


def resolve_path_under_directory(root: Path, path_str: str) -> Path:
    if not path_str or "\0" in path_str:
        raise HTTPException(status_code=400, detail="Invalid path")
    return _ensure_under(
        root,
        Path(os.path.expanduser(path_str.strip())),
        detail="Path escapes allowed directory",
    )


def require_disjoint_copy_paths(source: Path, destination: Path) -> None:
    source_path = os.path.normcase(os.path.realpath(os.fspath(source)))
    destination_path = os.path.normcase(os.path.realpath(os.fspath(destination)))
    source_prefix = (
        source_path if source_path.endswith(os.sep) else source_path + os.sep
    )
    destination_prefix = (
        destination_path
        if destination_path.endswith(os.sep)
        else destination_path + os.sep
    )
    if (
        source_path == destination_path
        or destination_path.startswith(source_prefix)
        or source_path.startswith(destination_prefix)
    ):
        raise HTTPException(status_code=400, detail="Source and destination overlap")


MAX_ZIP_ENTRIES = 2000
MAX_ZIP_UNCOMPRESSED_BYTES = 128 * 1024 * 1024


def extract_zip_under(dest_dir: Path, zf: zipfile.ZipFile) -> None:
    """把 zip 解压到 ``dest_dir``，并限制条目数与解压总量。

    :param dest_dir: 解压目标目录。
    :param zf: 已打开的 zip 文件。
    :raises HTTPException: 条目数或解压总量超过上限时抛出。
    """
    dest_root = Path(os.path.realpath(os.fspath(dest_dir)))
    dest_root.mkdir(parents=True, exist_ok=True)
    infos = zf.infolist()
    if len(infos) > MAX_ZIP_ENTRIES:
        raise HTTPException(
            status_code=413,
            detail=f"Zip contains too many entries (>{MAX_ZIP_ENTRIES})",
        )
    total_uncompressed = sum(max(0, info.file_size) for info in infos)
    if total_uncompressed > MAX_ZIP_UNCOMPRESSED_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "Zip uncompressed size exceeds the "
                f"{MAX_ZIP_UNCOMPRESSED_BYTES}-byte limit"
            ),
        )
    for member in infos:
        target = resolve_under_root(dest_root, member.filename)
        if member.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(member, "r") as source, target.open("wb") as destination:
            shutil.copyfileobj(source, destination)
