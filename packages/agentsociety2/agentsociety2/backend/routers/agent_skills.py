"""
Agent Skills API 路由

提供 agent skill 的列表、扫描自定义 skill、导入/创建/上传 skill 的 API 端点。

本路由基于 v2 skill 注册表 (:mod:`agentsociety2.agent.base.skill_registry`)，它是一个
**只读元数据注册表**：skill 是"始终存在"的目录，PersonAgent 在运行时按目录选择激活。
因此本路由**没有** enable/disable/reload/remove 端点（v2 模型无此概念）。

关联文件：
- @packages/agentsociety2/agentsociety2/agent/base/skill_registry.py - Skill 注册表
- @extension/src/apiClient.ts - VSCode 扩展 API 客户端
- @frontend/src/pages/Skills/index.tsx - Web 前端 Skill 管理页

API 端点：
- GET  /api/v1/agent-skills/list       — 列出所有已发现的 agent skill（built-in + custom + env）
- POST /api/v1/agent-skills/scan       — 扫描 workspace/custom/skills/ 下的自定义 skill
- POST /api/v1/agent-skills/import     — 从工作区内路径导入 skill 目录
- POST /api/v1/agent-skills/create     — 在线创建新 skill（SKILL.md + 可选脚本）
- POST /api/v1/agent-skills/upload     — 上传 zip 包导入 skill
- GET  /api/v1/agent-skills/{skill_id}/info — 获取 SKILL.md 内容
"""

from __future__ import annotations

import io
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

from agentsociety2.agent.base.skill_registry import (
    SkillDescriptor,
    get_skill_registry,
)
from agentsociety2.backend.path_security import (
    custom_skills_root,
    extract_zip_under,
    require_disjoint_copy_paths,
    require_safe_skill_name,
    resolve_path_under_directory,
    resolve_skill_relative,
    resolve_under_root,
    resolve_workspace_root,
    skill_install_dir,
)
from agentsociety2.logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/v1/agent-skills", tags=["agent-skills"])


# ── 请求/响应模型 ──


class SkillItem(BaseModel):
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
    success: bool
    skills: list[SkillItem]
    total: int


class ScanRequest(BaseModel):
    workspace_path: str | None = Field(None, description="工作区路径")


class ScanResponse(BaseModel):
    success: bool
    new_skills: list[str]
    total: int
    message: str


class ImportRequest(BaseModel):
    source_path: str = Field(..., description="工作区内 skill 目录的绝对路径")
    workspace_path: str | None = Field(None, description="工作区路径")


class ImportResponse(BaseModel):
    success: bool
    name: str
    message: str


class CreateRequest(BaseModel):
    name: str = Field(..., description="skill 名称（也作为目录名）")
    description: str = Field("", description="skill 描述")
    script: str = Field(
        "", description="subprocess 脚本相对路径（留空则为 prompt-only）"
    )
    body: str = Field("", description="SKILL.md 正文（frontmatter 之后的内容）")
    script_content: str = Field("", description="脚本文件内容（当 script 非空时使用）")
    workspace_path: str | None = Field(None, description="工作区路径")


class SimpleResponse(BaseModel):
    success: bool
    message: str


def _skill_has_skill_md(path_str: str) -> bool:
    return (Path(os.path.realpath(path_str)) / "SKILL.md").is_file()


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
        has_skill_md=_skill_has_skill_md(str(desc.root)),
        script=desc.script or "",
    )


# ── API 端点 ──


@router.get("/list", response_model=ListResponse)
async def list_skills():
    """列出所有已发现的 Agent Skill（built-in + custom + env）。"""
    reg = get_skill_registry()
    _ensure_custom_scanned(reg)
    _ensure_env_skills_scanned(reg)

    items = [_descriptor_to_item(d) for d in reg.list_all()]
    return ListResponse(success=True, skills=items, total=len(items))


@router.post("/scan", response_model=ScanResponse)
async def scan_custom_skills(req: ScanRequest):
    """扫描工作区的自定义 Agent Skill（{workspace}/custom/skills/）。"""
    workspace = _require_workspace(req.workspace_path)
    reg = get_skill_registry()
    new_ids = reg.scan_custom(custom_skills_root(workspace))

    return ScanResponse(
        success=True,
        new_skills=new_ids,
        total=len(reg.list_all()),
        message=f"发现 {len(new_ids)} 个新 skill" if new_ids else "未发现新 skill",
    )


@router.post("/import", response_model=ImportResponse)
async def import_skill(req: ImportRequest):
    """从工作区内路径导入 Agent Skill（复制到 custom/skills/）。"""
    workspace = _require_workspace(req.workspace_path)
    workspace_root = resolve_workspace_root(workspace)
    source = resolve_path_under_directory(workspace_root, req.source_path)
    if not source.is_dir():
        raise HTTPException(
            status_code=400, detail=f"Directory not found: {req.source_path}"
        )
    skill_md = resolve_under_root(source, "SKILL.md")
    scripts_dir = resolve_under_root(source, "scripts")
    if not skill_md.is_file() and not scripts_dir.is_dir():
        raise HTTPException(
            400, "Directory does not look like a skill (missing SKILL.md and scripts/)"
        )

    skill_name = require_safe_skill_name(source.name)
    dest = skill_install_dir(workspace, skill_name)
    require_disjoint_copy_paths(source, dest)
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, dest)

    reg = get_skill_registry()
    reg.scan_custom(custom_skills_root(workspace))

    logger.info(f"[Skills] Imported skill '{skill_name}' from {source} → {dest}")
    return ImportResponse(
        success=True,
        name=skill_name,
        message=f"Skill '{skill_name}' imported to {dest}",
    )


@router.post("/create", response_model=ImportResponse)
async def create_skill(req: CreateRequest):
    """在线创建新的自定义 Skill。

    在 custom/skills/{name}/ 下生成 SKILL.md（+ 可选脚本文件）。
    """
    workspace = _require_workspace(req.workspace_path)

    safe_name = require_safe_skill_name(req.name.strip())

    dest = skill_install_dir(workspace, safe_name)
    if dest.exists():
        raise HTTPException(
            400,
            f"Skill '{safe_name}' already exists. Remove it first or use a different name.",
        )
    dest.mkdir(parents=True, exist_ok=True)

    frontmatter_lines = ["---", f"name: {safe_name}", f"description: {req.description}"]
    if req.script:
        frontmatter_lines.append(f"script: {req.script}")
    frontmatter_lines.append("---")

    body = req.body.strip() or f"# {safe_name}\n\nCustom skill."
    skill_md_content = "\n".join(frontmatter_lines) + "\n\n" + body + "\n"
    resolve_under_root(dest, "SKILL.md").write_text(skill_md_content, encoding="utf-8")

    if req.script and req.script_content:
        script_path = resolve_skill_relative(dest, req.script.strip())
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(req.script_content, encoding="utf-8")

    reg = get_skill_registry()
    reg.scan_custom(custom_skills_root(workspace))

    log_name = safe_name.replace("\r", "\\r").replace("\n", "\\n")
    log_dest = str(dest).replace("\r", "\\r").replace("\n", "\\n")
    logger.info(f"[Skills] Created skill '{log_name}' at {log_dest}")
    return ImportResponse(
        success=True, name=safe_name, message=f"Skill '{safe_name}' created"
    )


@router.post("/upload", response_model=ImportResponse)
async def upload_skill(
    file: UploadFile = File(..., description="skill 目录的 zip 包"),
    workspace_path: str | None = None,
):
    """上传 zip 包导入 Skill。

    zip 包应包含一个顶层目录，内含 SKILL.md。
    """
    workspace = _require_workspace(workspace_path)

    data = await file.read()
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise HTTPException(400, "Invalid zip file") from e

    top_dirs = {n.split("/")[0] for n in zf.namelist() if "/" in n}
    if len(top_dirs) != 1:
        raise HTTPException(400, "Zip should contain exactly one top-level directory")
    skill_dir_name = require_safe_skill_name(top_dirs.pop())

    has_skill_md = any(
        n == f"{skill_dir_name}/SKILL.md" or n.endswith("/SKILL.md")
        for n in zf.namelist()
    )
    if not has_skill_md:
        raise HTTPException(400, "Zip does not contain a SKILL.md file")

    skills_dir = custom_skills_root(workspace)
    dest = skill_install_dir(workspace, skill_dir_name)
    if dest.exists():
        shutil.rmtree(dest)
    extract_zip_under(skills_dir, zf)
    zf.close()

    reg = get_skill_registry()
    reg.scan_custom(custom_skills_root(workspace))

    logger.info(f"[Skills] Uploaded skill '{skill_dir_name}' to {dest}")
    return ImportResponse(
        success=True,
        name=skill_dir_name,
        message=f"Skill '{skill_dir_name}' uploaded",
    )


@router.get("/{skill_id}/info")
async def get_skill_info(skill_id: str) -> dict[str, Any]:
    """获取 Skill 的详细信息（含 SKILL.md 内容）。

    ``skill_id`` 形如 ``built-in@daily-guidance`` 或 ``custom@my-skill``，由
    :meth:`SkillRegistry.list_all` 返回。
    """
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


def _ensure_custom_scanned(reg) -> None:
    """确保 custom skills 已扫描"""
    workspace = os.getenv("WORKSPACE_PATH")
    if workspace:
        reg.scan_custom(custom_skills_root(workspace))


def _ensure_env_skills_scanned(reg) -> None:
    """扫描已注册环境模块附带的 agent skill 到全局 registry。"""
    from agentsociety2.registry import get_registered_env_modules

    for _module_type, env_class in get_registered_env_modules():
        for skills_dir in env_class.skill_dirs():
            if skills_dir.is_dir():
                reg.scan_env(skills_dir, env_class.__name__)
