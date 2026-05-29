from __future__ import annotations

import re
import zipfile
from pathlib import Path

from fastapi import HTTPException

_SAFE_SEGMENT_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
_ARTIFACT_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*\.md$")


def _validated_user_path(path_str: str, *, field: str) -> Path:
    if not path_str or "\0" in path_str:
        raise HTTPException(status_code=400, detail=f"Invalid {field}")
    candidate = Path(path_str)
    if ".." in candidate.parts:
        raise HTTPException(status_code=400, detail=f"Invalid {field}")
    return candidate.expanduser().resolve()


def resolve_workspace_root(workspace_path: str) -> Path:
    root = _validated_user_path(workspace_path, field="workspace_path")
    if not root.is_dir():
        raise HTTPException(
            status_code=404, detail=f"Workspace not found: {workspace_path}"
        )
    return root


def require_safe_segment(value: str, *, field: str) -> str:
    if not _SAFE_SEGMENT_RE.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"Invalid {field}: {value}")
    return value


def resolve_under_root(root: Path, *parts: str) -> Path:
    target = root.joinpath(*parts).resolve()
    if target != root and root not in target.parents:
        raise HTTPException(status_code=400, detail="Path escapes workspace root")
    return target


def resolve_workspace_relative(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise HTTPException(status_code=400, detail="Invalid relative path")
    return resolve_under_root(root, *rel.parts)


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
    if not name or "/" in name or "\\" in name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="Invalid skill name")
    if ".." in Path(name).parts:
        raise HTTPException(status_code=400, detail="Invalid skill name")
    return name


def resolve_existing_directory(path_str: str) -> Path:
    target = _validated_user_path(path_str, field="path")
    if not target.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {path_str}")
    return target


def custom_skills_root(workspace_path: str) -> Path:
    return resolve_under_root(
        resolve_workspace_root(workspace_path), "custom", "skills"
    )


def skill_install_dir(workspace_path: str, skill_name: str) -> Path:
    return resolve_under_root(
        custom_skills_root(workspace_path), require_safe_skill_name(skill_name)
    )


def resolve_skill_relative(skill_dir: Path, relative: str) -> Path:
    return resolve_workspace_relative(skill_dir, relative)


def resolve_path_under_directory(root: Path, path_str: str) -> Path:
    target = _validated_user_path(path_str, field="path")
    if target != root and root not in target.parents:
        raise HTTPException(status_code=400, detail="Path escapes allowed directory")
    return target


def extract_zip_under(dest_dir: Path, zf: zipfile.ZipFile) -> None:
    dest_root = dest_dir.resolve()
    dest_root.mkdir(parents=True, exist_ok=True)
    for member in zf.namelist():
        if member.startswith("/") or member.startswith("\\"):
            raise HTTPException(status_code=400, detail="Unsafe zip entry path")
        member_path = Path(member)
        if ".." in member_path.parts:
            raise HTTPException(status_code=400, detail="Unsafe zip entry path")
        target = (dest_root / member).resolve()
        if target != dest_root and dest_root not in target.parents:
            raise HTTPException(status_code=400, detail="Unsafe zip entry path")
    zf.extractall(dest_root)
