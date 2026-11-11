"""假设管理功能

提供 hypothesis 的创建、读取、更新与删除函数。
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from agentsociety2.logger import get_logger
from agentsociety2.skills.hypothesis.models import (
    ExperimentGroupModel,
    HypothesisDataModel,
)

logger = get_logger()


def validate_hypothesis_with_modules(
    hypothesis_data: dict[str, Any],
) -> tuple[bool, str | None, HypothesisDataModel | None, dict[str, Any] | None]:
    """校验 hypothesis 数据（含模块选择校验）

    这是增强版校验，检查以下内容：
    1. schema 合法性（通过 Pydantic）
    2. agent 与环境模块的选择（各至少需要选择一个）

    :param hypothesis_data: hypothesis 数据字典

    :returns: ``(is_valid, 错误消息, 已校验模型, 引导信息字典)`` 元组
    """
    # First, validate schema
    schema_valid, schema_error, hypothesis_model = validate_hypothesis_schema(
        hypothesis_data
    )
    if not schema_valid or hypothesis_model is None:
        return False, schema_error, None, None

    # Then validate module selection
    try:
        from agentsociety2.skills.experiment.module_discovery import (
            get_module_selection_guidance,
            validate_hypothesis_modules,
        )

        module_valid, module_errors, guidance = validate_hypothesis_modules(
            hypothesis_data
        )

        if not module_valid:
            # Generate helpful guidance
            topic = hypothesis_data.get("topic", "Research Topic")
            guidance_text = get_module_selection_guidance(
                topic=topic,
                agent_classes=hypothesis_model.agent_classes,
                env_modules=hypothesis_model.env_modules,
            )
            guidance["guidance_text"] = guidance_text

            error_msg = "Module validation failed:\n" + "\n".join(module_errors)
            return False, error_msg, hypothesis_model, guidance

        return True, None, hypothesis_model, guidance

    except ImportError:
        # If module_discovery is not available, just return schema validation
        logger.warning("module_discovery not available, skipping module validation")
        return True, None, hypothesis_model, None


def find_existing_hypotheses(workspace_path: Path) -> list[Path]:
    """查找已有的 hypothesis 目录

    :param workspace_path: 工作区目录路径

    :returns: 排序后的 hypothesis 目录路径列表
    """
    hypothesis_dirs = []
    for item in workspace_path.iterdir():
        if item.is_dir() and item.name.startswith("hypothesis_"):
            hypothesis_dirs.append(item)
    return sorted(hypothesis_dirs)


def get_next_hypothesis_id(workspace_path: Path) -> str:
    """获取下一个 hypothesis ID

    :param workspace_path: 工作区目录路径

    :returns: 字符串形式的下一个 hypothesis ID
    """
    existing = find_existing_hypotheses(workspace_path)
    if not existing:
        return "1"
    # Extract all IDs
    ids = []
    for hyp_dir in existing:
        match = re.search(r"hypothesis_(\d+)", hyp_dir.name)
        if match:
            ids.append(int(match.group(1)))
    if not ids:
        return "1"
    return str(max(ids) + 1)


def validate_hypothesis_schema(
    hypothesis_data: dict[str, Any],
) -> tuple[bool, str | None, HypothesisDataModel | None]:
    """按 schema 校验 hypothesis 数据

    :param hypothesis_data: hypothesis 数据字典

    :returns: ``(is_valid, 错误消息, 已校验模型)`` 元组
    """
    try:
        model = HypothesisDataModel(**hypothesis_data)
        return True, None, model
    except ValidationError as e:
        # Format validation errors
        errors = []
        for error in e.errors():
            field = " -> ".join(str(loc) for loc in error["loc"])
            msg = error["msg"]
            errors.append(f"{field}: {msg}")
        error_msg = "; ".join(errors)
        return False, error_msg, None


def create_hypothesis_structure(
    workspace_path: Path,
    hypothesis_id: str,
    hypothesis_model: HypothesisDataModel,
) -> Path:
    """创建 hypothesis 目录结构

    :param workspace_path: 工作区目录路径
    :param hypothesis_id: hypothesis ID
    :param hypothesis_model: 已校验的 hypothesis 数据模型

    :returns: 创建的 hypothesis 目录路径
    """
    hyp_dir = workspace_path / f"hypothesis_{hypothesis_id}"
    hyp_dir.mkdir(parents=True, exist_ok=True)

    # Create HYPOTHESIS.md
    hypothesis_md = hyp_dir / "HYPOTHESIS.md"
    hypothesis_content = generate_hypothesis_markdown(hypothesis_model)
    hypothesis_md.write_text(hypothesis_content, encoding="utf-8")

    # Create SIM_SETTINGS.json (basic structure)
    sim_settings = hyp_dir / "SIM_SETTINGS.json"
    sim_settings_data = generate_sim_settings(hypothesis_model)
    sim_settings.write_text(
        json.dumps(sim_settings_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Create experiment folders
    for idx, group in enumerate(hypothesis_model.groups, 1):
        exp_dir = hyp_dir / f"experiment_{idx}"
        exp_dir.mkdir(parents=True, exist_ok=True)

        # Create EXPERIMENT.md
        experiment_md = exp_dir / "EXPERIMENT.md"
        experiment_content = generate_experiment_markdown(group, idx)
        experiment_md.write_text(experiment_content, encoding="utf-8")

    return hyp_dir


def generate_hypothesis_markdown(hypothesis_model: HypothesisDataModel) -> str:
    """生成 ``HYPOTHESIS.md`` 内容

    :param hypothesis_model: 已校验的 hypothesis 数据模型

    :returns: ``HYPOTHESIS.md`` 的 Markdown 内容
    """
    lines = []
    lines.append("# Hypothesis")
    lines.append("")
    lines.append("## Description")
    lines.append("")
    lines.append(hypothesis_model.hypothesis.description)
    lines.append("")
    lines.append("## Rationale")
    lines.append("")
    lines.append(hypothesis_model.hypothesis.rationale)
    lines.append("")
    lines.append("## Experiment Groups")
    lines.append("")

    for idx, group in enumerate(hypothesis_model.groups, 1):
        lines.append(f"### Group {idx}: {group.name}")
        lines.append("")
        lines.append(f"**Type:** {group.group_type}")
        lines.append("")
        lines.append(f"**Description:** {group.description}")
        lines.append("")
        if group.agent_selection_criteria:
            lines.append(
                f"**Agent Selection Criteria:** {group.agent_selection_criteria}"
            )
            lines.append("")
        lines.append("")

    return "\n".join(lines)


def generate_experiment_markdown(group: ExperimentGroupModel, exp_idx: int) -> str:
    """生成 ``EXPERIMENT.md`` 内容

    :param group: 实验分组模型
    :param exp_idx: 实验序号

    :returns: ``EXPERIMENT.md`` 的 Markdown 内容
    """
    lines = []
    lines.append(f"# Experiment {exp_idx}")
    lines.append("")
    lines.append(f"**Group Name:** {group.name}")
    lines.append("")
    lines.append(f"**Group Type:** {group.group_type}")
    lines.append("")
    lines.append("## Description")
    lines.append("")
    lines.append(group.description)
    lines.append("")
    if group.agent_selection_criteria:
        lines.append("## Agent Selection Criteria")
        lines.append("")
        lines.append(group.agent_selection_criteria)
        lines.append("")
    lines.append("## Status")
    lines.append("")
    lines.append("Not initialized")
    lines.append("")

    return "\n".join(lines)


def generate_sim_settings(hypothesis_model: HypothesisDataModel) -> dict[str, Any]:
    """生成 ``SIM_SETTINGS.json`` 内容

    :param hypothesis_model: 已校验的 hypothesis 数据模型

    :returns: ``SIM_SETTINGS.json`` 对应的字典
    """
    sim_settings = {}

    # Add agent classes and env modules (if provided)
    if hypothesis_model.agent_classes is not None:
        sim_settings["agentClasses"] = hypothesis_model.agent_classes
    else:
        sim_settings["agentClasses"] = []

    if hypothesis_model.env_modules is not None:
        sim_settings["envModules"] = hypothesis_model.env_modules
    else:
        sim_settings["envModules"] = []

    return sim_settings


def add_hypothesis(
    workspace_path: Path,
    hypothesis_data: dict[str, Any],
) -> dict[str, Any]:
    """新增一个 hypothesis

    :param workspace_path: 工作区目录路径
    :param hypothesis_data: hypothesis 数据字典

    :returns: 包含成功状态与信息的结果字典
    """
    # Validate schema
    valid, error_msg, hypothesis_model = validate_hypothesis_schema(hypothesis_data)
    if not valid or hypothesis_model is None:
        return {
            "success": False,
            "error": f"Hypothesis validation failed: {error_msg}",
            "content": f"Hypothesis validation failed: {error_msg}",
        }

    # Create new hypothesis folder
    hyp_id = get_next_hypothesis_id(workspace_path)
    hyp_dir = create_hypothesis_structure(workspace_path, hyp_id, hypothesis_model)

    return {
        "success": True,
        "content": (
            f"Successfully added new hypothesis {hyp_id}:\n"
            f"- Description: {hypothesis_model.hypothesis.description}\n"
            f"- Path: {hyp_dir.relative_to(workspace_path)}\n"
            f"- Groups: {len(hypothesis_model.groups)}\n"
            f"\n"
            f"Note: You may want to update TOPIC.md to include this new hypothesis."
        ),
        "hypothesis_id": hyp_id,
        "path": str(hyp_dir.relative_to(workspace_path)),
        "hypothesis": {
            "id": hyp_id,
            "description": hypothesis_model.hypothesis.description,
        },
    }


def add_hypothesis_with_validation(
    workspace_path: Path,
    hypothesis_data: dict[str, Any],
    validate_modules: bool = True,
) -> dict[str, Any]:
    """新增一个 hypothesis（含增强模块校验）

    本函数提供增强版校验，检查以下内容：
    1. schema 合法性（通过 Pydantic）
    2. agent 与环境模块的选择（各至少需要选择一个）

    :param workspace_path: 工作区目录路径
    :param hypothesis_data: hypothesis 数据字典
    :param validate_modules: 是否校验模块选择（默认 True）

    :returns: 包含成功状态与信息的结果字典；若模块校验失败，还会附带模块选择引导信息。
    """
    if validate_modules:
        valid, error_msg, hypothesis_model, guidance = validate_hypothesis_with_modules(
            hypothesis_data
        )
        if not valid:
            return {
                "success": False,
                "error": error_msg,
                "content": error_msg,
                "guidance": guidance,
            }
    else:
        # Fallback to basic schema validation
        valid, error_msg, hypothesis_model = validate_hypothesis_schema(hypothesis_data)
        if not valid or hypothesis_model is None:
            return {
                "success": False,
                "error": f"Hypothesis validation failed: {error_msg}",
                "content": f"Hypothesis validation failed: {error_msg}",
            }

    # Create new hypothesis folder
    hyp_id = get_next_hypothesis_id(workspace_path)
    hyp_dir = create_hypothesis_structure(workspace_path, hyp_id, hypothesis_model)

    return {
        "success": True,
        "content": (
            f"Successfully added new hypothesis {hyp_id}:\n"
            f"- Description: {hypothesis_model.hypothesis.description}\n"
            f"- Path: {hyp_dir.relative_to(workspace_path)}\n"
            f"- Groups: {len(hypothesis_model.groups)}\n"
            f"- Agent Classes: {hypothesis_model.agent_classes or []}\n"
            f"- Environment Modules: {hypothesis_model.env_modules or []}\n"
            f"\n"
            f"Note: You may want to update TOPIC.md to include this new hypothesis."
        ),
        "hypothesis_id": hyp_id,
        "path": str(hyp_dir.relative_to(workspace_path)),
        "hypothesis": {
            "id": hyp_id,
            "description": hypothesis_model.hypothesis.description,
        },
        "agent_classes": hypothesis_model.agent_classes,
        "env_modules": hypothesis_model.env_modules,
    }


def get_hypothesis(
    workspace_path: Path,
    hypothesis_id: str | None = None,
    hypothesis_path: str | None = None,
) -> dict[str, Any]:
    """获取 hypothesis 详情

    :param workspace_path: 工作区目录路径
    :param hypothesis_id: hypothesis ID（如 '1'、'2'）
    :param hypothesis_path: hypothesis 文件夹的相对路径

    :returns: 包含 hypothesis 详情的结果字典
    """
    # Determine folder to get
    if hypothesis_path:
        hyp_dir = workspace_path / hypothesis_path
    elif hypothesis_id:
        hyp_dir = workspace_path / f"hypothesis_{hypothesis_id}"
    else:
        return {
            "success": False,
            "error": "Missing parameter",
            "content": "Either hypothesis_id or hypothesis_path must be provided",
        }

    if not hyp_dir.exists():
        return {
            "success": False,
            "error": "Hypothesis not found",
            "content": f"Hypothesis folder not found: {hyp_dir}",
        }

    if not hyp_dir.is_dir():
        return {
            "success": False,
            "error": "Invalid path",
            "content": f"Path is not a directory: {hyp_dir}",
        }

    # Read HYPOTHESIS.md
    hyp_md = hyp_dir / "HYPOTHESIS.md"
    hypothesis_content = ""
    if hyp_md.exists():
        hypothesis_content = hyp_md.read_text(encoding="utf-8")
    else:
        return {
            "success": False,
            "error": "HYPOTHESIS.md not found",
            "content": f"HYPOTHESIS.md not found in {hyp_dir}",
        }

    # Read SIM_SETTINGS.json
    sim_settings = hyp_dir / "SIM_SETTINGS.json"
    sim_settings_data = {}
    if sim_settings.exists():
        try:
            sim_settings_data = json.loads(sim_settings.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Failed to parse SIM_SETTINGS.json: {e}")

    # List experiment folders
    experiment_dirs = []
    for item in hyp_dir.iterdir():
        if item.is_dir() and item.name.startswith("experiment_"):
            experiment_dirs.append(item.name)

    # Extract hypothesis ID
    match = re.search(r"hypothesis_(\d+)", hyp_dir.name)
    hyp_id = match.group(1) if match else "unknown"

    return {
        "success": True,
        "content": (
            f"Hypothesis {hyp_id} details:\n"
            f"Path: {hyp_dir.relative_to(workspace_path)}\n\n"
            f"{hypothesis_content}\n\n"
            f"Simulation Settings:\n{json.dumps(sim_settings_data, ensure_ascii=False, indent=2)}\n\n"
            f"Experiments: {', '.join(sorted(experiment_dirs))}"
        ),
        "hypothesis_id": hyp_id,
        "path": str(hyp_dir.relative_to(workspace_path)),
        "hypothesis_content": hypothesis_content,
        "sim_settings": sim_settings_data,
        "experiments": sorted(experiment_dirs),
    }


def list_hypotheses(workspace_path: Path) -> dict[str, Any]:
    """列出全部 hypothesis

    :param workspace_path: 工作区目录路径

    :returns: 包含 hypothesis 列表的结果字典
    """
    hypothesis_dirs = find_existing_hypotheses(workspace_path)

    if not hypothesis_dirs:
        return {
            "success": True,
            "content": "No hypotheses found in the workspace.",
            "hypotheses": [],
            "total": 0,
        }

    hypotheses_info = []
    for hyp_dir in hypothesis_dirs:
        # Extract hypothesis ID
        match = re.search(r"hypothesis_(\d+)", hyp_dir.name)
        hyp_id = match.group(1) if match else "unknown"

        # Read hypothesis description
        hyp_md = hyp_dir / "HYPOTHESIS.md"
        description = ""
        if hyp_md.exists():
            try:
                content = hyp_md.read_text(encoding="utf-8")
                # Try to extract description
                if "## Description" in content:
                    desc_start = content.find("## Description") + len("## Description")
                    desc_end = content.find("##", desc_start)
                    if desc_end == -1:
                        description = content[desc_start:].strip()
                    else:
                        description = content[desc_start:desc_end].strip()
            except Exception:
                logger.debug("Failed to parse hypothesis description", exc_info=True)

        hypotheses_info.append(
            {
                "id": hyp_id,
                "path": str(hyp_dir.relative_to(workspace_path)),
                "description": description[:200] if description else "",
            }
        )

    content_parts = [f"Found {len(hypotheses_info)} hypothesis(es):\n"]
    for hyp in hypotheses_info:
        content_parts.append(f"- Hypothesis {hyp['id']}: {hyp['description'][:100]}...")
        content_parts.append(f"  Path: {hyp['path']}")

    return {
        "success": True,
        "content": "\n".join(content_parts),
        "hypotheses": hypotheses_info,
        "total": len(hypotheses_info),
    }


def delete_hypothesis(
    workspace_path: Path,
    hypothesis_id: str | None = None,
    hypothesis_path: str | None = None,
) -> dict[str, Any]:
    """删除 hypothesis 文件夹

    :param workspace_path: 工作区目录路径
    :param hypothesis_id: hypothesis ID（如 '1'、'2'）
    :param hypothesis_path: hypothesis 文件夹的相对路径

    :returns: 包含删除状态的结果字典
    """
    # Determine folder to delete
    if hypothesis_path:
        hyp_dir = workspace_path / hypothesis_path
    elif hypothesis_id:
        hyp_dir = workspace_path / f"hypothesis_{hypothesis_id}"
    else:
        return {
            "success": False,
            "error": "Missing parameter",
            "content": "Either hypothesis_id or hypothesis_path must be provided",
        }

    if not hyp_dir.exists():
        return {
            "success": False,
            "error": "Hypothesis not found",
            "content": f"Hypothesis folder not found: {hyp_dir}",
        }

    if not hyp_dir.is_dir():
        return {
            "success": False,
            "error": "Invalid path",
            "content": f"Path is not a directory: {hyp_dir}",
        }

    # Delete folder
    shutil.rmtree(hyp_dir)
    logger.info(f"Deleted hypothesis folder: {hyp_dir}")

    return {
        "success": True,
        "content": (
            f"Successfully deleted hypothesis: {hyp_dir.name}\n"
            f"\n"
            f"Note: You may want to update TOPIC.md to remove this hypothesis."
        ),
        "deleted_path": str(hyp_dir.relative_to(workspace_path)),
    }
