"""管理可发现的智能体行为技能。

提供技能列表、工作区扫描、目录导入、创建、ZIP 上传与内容查询。元数据由 :mod:`agentsociety2.agent.base.skill_registry` 管理；技能的激活与执行发生在仿真运行时，见 :doc:`/agent_skills`。"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from threading import Lock
from typing import Any

import yaml
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from agentsociety2.agent.base.skill_registry import (
    SkillDescriptor,
    SkillRegistry,
    describe_custom_skill,
    get_skill_registry,
)
from agentsociety2.backend.path_security import (
    custom_skills_root,
    extract_zip_under,
    require_disjoint_copy_paths,
    require_safe_skill_name,
    resolve_path_under_directory,
    resolve_skill_relative,
    resolve_workspace_root,
    skill_install_dir,
)
from agentsociety2.logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/v1/agent-skills", tags=["agent-skills"])

MAX_SKILL_ZIP_BYTES = 32 * 1024 * 1024
# Serialize publication and reads of the backend's process-local registry.
_SKILLS_LOCK = Lock()


# ── 请求/响应模型 ──


class SkillItem(BaseModel):
    """已发现的行为技能及其来源、脚本与目录信息。"""

    skill_id: str
    name: str
    namespace: str
    description: str
    source: str
    source_label: str
    path: str
    has_skill_md: bool
    script: str = ""


class ListResponse(BaseModel):
    """行为技能列表和技能总数。"""

    success: bool
    skills: list[SkillItem]
    total: int


class ScanRequest(BaseModel):
    """需要扫描自定义技能的工作区。"""

    workspace_path: str | None = Field(None, description="工作区路径")


class ScanResponse(BaseModel):
    """扫描新增的技能标识和当前技能总数。"""

    success: bool
    new_skills: list[str]
    total: int
    message: str


class ImportRequest(BaseModel):
    """待导入技能的源目录与目标工作区。"""

    source_path: str = Field(..., description="工作区内 skill 目录的绝对路径")
    workspace_path: str | None = Field(None, description="工作区路径")


class ImportResponse(BaseModel):
    """技能安装结果及安装后的名称。"""

    success: bool
    name: str
    message: str


class CreateRequest(BaseModel):
    """创建行为技能所需的名称、说明和可选脚本。"""

    name: str = Field(..., description="skill 名称（也作为目录名）")
    description: str = Field("", description="skill 描述")
    script: str = Field(
        "", description="subprocess 脚本相对路径（留空则为 prompt-only）"
    )
    body: str = Field("", description="SKILL.md 正文（frontmatter 之后的内容）")
    script_content: str = Field("", description="脚本文件内容（当 script 非空时使用）")
    workspace_path: str | None = Field(None, description="工作区路径")


class SimpleResponse(BaseModel):
    """操作状态与结果说明。"""

    success: bool
    message: str


def _require_workspace(workspace_path: str | None) -> str:
    workspace = workspace_path or os.getenv("WORKSPACE_PATH")
    if not workspace:
        raise HTTPException(
            400, "workspace_path not provided and WORKSPACE_PATH not set"
        )
    return workspace


def _descriptor_to_item(desc: SkillDescriptor) -> SkillItem:
    return SkillItem(
        skill_id=desc.skill_id,
        name=desc.name,
        namespace=desc.namespace,
        description=desc.description,
        source=desc.source,
        source_label=desc.source_label,
        path=str(desc.root),
        has_skill_md=(desc.root / "SKILL.md").is_file(),
        script=desc.script or "",
    )


# ── API 端点 ──


@router.get("/list", response_model=ListResponse)
def list_skills() -> ListResponse:
    """列出所有已发现的 Agent Skill（built-in + custom + env）。"""
    with _SKILLS_LOCK:
        reg = get_skill_registry()
        workspace = os.getenv("WORKSPACE_PATH")
        if workspace:
            reg.scan_custom(custom_skills_root(workspace))
        _ensure_env_skills_scanned(reg)
        items = [_descriptor_to_item(d) for d in reg.list_all()]
    return ListResponse(success=True, skills=items, total=len(items))


@router.post("/scan", response_model=ScanResponse)
def scan_custom_skills(req: ScanRequest) -> ScanResponse:
    """扫描工作区的自定义 Agent Skill（{workspace}/custom/skills/）。"""
    skills_root = custom_skills_root(_require_workspace(req.workspace_path))
    with _SKILLS_LOCK:
        reg = get_skill_registry()
        new_ids = reg.scan_custom(skills_root)
        total = len(reg.list_all())
    return ScanResponse(
        success=True,
        new_skills=new_ids,
        total=total,
        message=f"发现 {len(new_ids)} 个新 skill" if new_ids else "未发现新 skill",
    )


@router.post("/import", response_model=ImportResponse)
def import_skill(req: ImportRequest) -> ImportResponse:
    """从工作区导入 Agent Skill；目录名必须匹配 SKILL.md 中的 name。"""
    workspace = _require_workspace(req.workspace_path)
    workspace_root = resolve_workspace_root(workspace)
    source = resolve_path_under_directory(workspace_root, req.source_path)
    if not source.is_dir():
        raise HTTPException(
            status_code=400, detail=f"Directory not found: {req.source_path}"
        )
    skill_name = require_safe_skill_name(source.name)
    dest = skill_install_dir(workspace, skill_name)
    require_disjoint_copy_paths(source, dest)
    _install_skill(dest, lambda staged: _copy_skill(source, staged))

    logger.info(
        "[Skills] Imported skill %r from %r to %r", skill_name, str(source), str(dest)
    )
    return ImportResponse(
        success=True,
        name=skill_name,
        message=f"Skill '{skill_name}' imported to {dest}",
    )


@router.post("/create", response_model=ImportResponse)
def create_skill(req: CreateRequest) -> ImportResponse:
    """在线创建新的自定义 Skill。

    在 custom/skills/{name}/ 下生成 SKILL.md（+ 可选脚本文件）。
    """
    workspace = _require_workspace(req.workspace_path)
    skill_name = require_safe_skill_name(req.name.strip())
    dest = skill_install_dir(workspace, skill_name)
    _install_skill(
        dest, lambda staged: _write_created_skill(staged, req), overwrite=False
    )

    logger.info("[Skills] Created skill %r at %r", skill_name, str(dest))
    return ImportResponse(
        success=True, name=skill_name, message=f"Skill '{skill_name}' created"
    )


@router.post("/upload", response_model=ImportResponse)
def upload_skill(
    file: UploadFile = File(..., description="skill 目录的 zip 包"),
    workspace_path: str | None = None,
) -> ImportResponse:
    """上传 zip 包导入 Skill。

    ZIP 包须包含一个顶层目录，其名称必须匹配 SKILL.md 中的 name。
    """
    workspace = _require_workspace(workspace_path)

    data = file.file.read(MAX_SKILL_ZIP_BYTES + 1)
    if len(data) > MAX_SKILL_ZIP_BYTES:
        raise HTTPException(
            413, f"Skill zip exceeds the {MAX_SKILL_ZIP_BYTES}-byte limit"
        )
    dest = _install_zip_skill(custom_skills_root(workspace), data)
    logger.info("[Skills] Uploaded skill %r to %r", dest.name, str(dest))
    return ImportResponse(
        success=True, name=dest.name, message=f"Skill '{dest.name}' uploaded"
    )


@router.get("/{skill_id}/info")
def get_skill_info(skill_id: str) -> dict[str, Any]:
    """获取 Skill 的详细信息（含 SKILL.md 内容）。

    ``skill_id`` 形如 ``built-in@daily-guidance`` 或 ``custom@my-skill`` ，由
    :meth:`SkillRegistry.list_all` 返回。
    """
    with _SKILLS_LOCK:
        reg = get_skill_registry()
        desc = reg.get(skill_id)
        if desc is None:
            raise HTTPException(404, f"Skill '{skill_id}' not found")
        return {
            "success": True,
            "skill_id": desc.skill_id,
            "name": desc.name,
            "namespace": desc.namespace,
            "description": desc.description,
            "source": desc.source,
            "source_label": desc.source_label,
            "path": str(desc.root),
            "script": desc.script or "",
            "skill_md": reg.read_skill_doc(desc.skill_id),
        }


# ── 辅助函数 ──


def _copy_skill(source: Path, staged: Path) -> None:
    """Copy a skill without following links or accepting a partial source tree."""
    try:
        shutil.copytree(source, staged, symlinks=True)
    except (shutil.Error, FileNotFoundError) as exc:
        raise HTTPException(400, "Could not copy skill directory") from exc
    if any(path.is_symlink() for path in staged.rglob("*")):
        raise HTTPException(400, "Skill directories must not contain symbolic links")


def _write_created_skill(staged: Path, req: CreateRequest) -> None:
    staged.mkdir()
    frontmatter = {"name": staged.name, "description": req.description}
    script = req.script.strip()
    if script:
        frontmatter["script"] = script
    header = yaml.safe_dump(frontmatter, allow_unicode=True, sort_keys=False).strip()
    body = req.body.strip() or f"# {staged.name}\n\nCustom skill."
    (staged / "SKILL.md").write_text(
        f"---\n{header}\n---\n\n{body}\n", encoding="utf-8"
    )
    if script:
        path = resolve_skill_relative(staged, script)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("x", encoding="utf-8") as file:
                file.write(req.script_content)
        except (FileExistsError, IsADirectoryError, NotADirectoryError) as exc:
            raise HTTPException(400, "Invalid skill script path") from exc


def _install_zip_skill(skills_root: Path, data: bytes) -> Path:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            names = archive.namelist()
            top_dirs = {name.partition("/")[0] for name in names}
            if len(top_dirs) != 1 or any("/" not in name for name in names):
                raise HTTPException(
                    400, "Zip must contain exactly one top-level directory"
                )
            name = require_safe_skill_name(top_dirs.pop())
            if names.count(f"{name}/SKILL.md") != 1:
                raise HTTPException(
                    400, "Zip must contain exactly one <top-level>/SKILL.md"
                )
            dest = skills_root / name
            _install_skill(
                dest, lambda staged: _extract_skill_zip(staged.parent, archive)
            )
    except (zipfile.BadZipFile, UnicodeError) as exc:
        raise HTTPException(400, "Invalid zip file") from exc
    return dest


def _extract_skill_zip(staging_root: Path, archive: zipfile.ZipFile) -> None:
    try:
        extract_zip_under(staging_root, archive)
    except (FileExistsError, IsADirectoryError, NotADirectoryError) as exc:
        raise HTTPException(
            400, "Conflicting file and directory entries in skill zip"
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(400, "Unsupported skill zip format") from exc


def _install_skill(
    dest: Path, populate: Callable[[Path], None], *, overwrite: bool = True
) -> None:
    """Validate an isolated tree before replacing the installed skill."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    transaction = Path(tempfile.mkdtemp(prefix=".install-", dir=dest.parent))
    staged = transaction / "incoming" / dest.name
    backup = transaction / "previous"
    committed = False
    try:
        staged.parent.mkdir()
        populate(staged)
        try:
            descriptor = describe_custom_skill(staged)
        except (UnicodeError, yaml.YAMLError, RecursionError) as exc:
            raise HTTPException(
                400, "SKILL.md must be UTF-8 with valid YAML frontmatter"
            ) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        with _SKILLS_LOCK:
            _publish_skill(staged, dest, backup, descriptor, overwrite=overwrite)
            committed = True
    finally:
        if not committed and backup.exists():
            logger.error(
                "[Skills] Could not restore %r; backup retained at %r",
                str(dest),
                str(backup),
            )
        else:
            try:
                shutil.rmtree(transaction)
            except OSError:
                logger.warning(
                    "[Skills] Could not clean up %r", str(transaction), exc_info=True
                )


def _publish_skill(
    staged: Path,
    dest: Path,
    backup: Path,
    descriptor: SkillDescriptor,
    *,
    overwrite: bool,
) -> None:
    """Publish the directory and its descriptor while holding the skill lock."""
    had_previous = dest.exists()
    if dest.is_symlink() or (had_previous and not dest.is_dir()):
        raise HTTPException(400, "Skill destination must be a directory")
    if had_previous:
        # A case-insensitive volume can resolve a different name to the same tree.
        if dest.name not in os.listdir(dest.parent):
            raise HTTPException(
                400, "Skill destination exists with a different spelling"
            )
        if not overwrite:
            raise HTTPException(400, f"Skill '{dest.name}' already exists")
    registry = get_skill_registry()
    if had_previous:
        os.replace(dest, backup)
    published = False
    try:
        os.replace(staged, dest)
        published = True
        registry.register_installed_custom(descriptor, dest)
    except BaseException:
        if published:
            os.replace(dest, staged)
        if had_previous:
            os.replace(backup, dest)
        raise


def _ensure_env_skills_scanned(reg: SkillRegistry) -> None:
    """扫描已注册环境模块附带的 agent skill 到全局 registry。"""
    from agentsociety2.registry import get_registered_env_modules

    for _module_type, env_class in get_registered_env_modules():
        for skills_dir in env_class.skill_dirs():
            if skills_dir.is_dir():
                reg.scan_env(skills_dir, env_class.__name__)
