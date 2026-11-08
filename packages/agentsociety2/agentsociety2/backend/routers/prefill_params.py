"""预填充参数查询API路由（只读）

关联文件：
- @packages/agentsociety2/agentsociety2/backend/app.py - 主应用，注册此路由 (/api/v1/prefill-params)
- @extension/src/prefillParamsViewProvider.ts - VSCode插件前端调用此API
- @extension/src/webview/prefillParams/ - 前端展示组件

读取文件：
- {workspace}/.agentsociety/prefill_params.json - 预填充参数配置
"""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi import Path as PathParam

from agentsociety2.backend.path_security import (
    resolve_under_root,
    resolve_workspace_root,
)
from agentsociety2.logger import get_logger

logger = get_logger()

router = APIRouter(prefix="/api/v1/prefill-params", tags=["prefill-params"])


def _load_prefill_params_file(workspace_path: str) -> dict[str, Any]:
    """加载全局预填充参数文件"""
    workspace = resolve_workspace_root(workspace_path)
    prefill_file = resolve_under_root(workspace, ".agentsociety", "prefill_params.json")

    if not prefill_file.is_file():
        return {"version": "1.0", "env_modules": {}, "agents": {}}

    try:
        content = prefill_file.read_text(encoding="utf-8")
        return json.loads(content)
    except Exception as e:
        logger.error(f"Failed to load prefill params file: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to load prefill params file: {e!s}"
        ) from None


@router.get("")
async def get_prefill_params(
    workspace_path: str = Query(..., description="工作区路径"),
) -> dict[str, Any]:
    """
    获取全局预填充参数

    返回工作区中所有类（Agent和环境模块）的预填充参数配置。

    :param workspace_path: 工作区根目录路径

    :returns: Dict[str, Any]: 预填充参数配置，包含： - success: 是否成功 - data: 参数数据，结构为： - version: 配置版本 - env_modules: 环境模块预填充参数字典 - agents: Agent预填充参数字典
    :raises HTTPException: 500 - 读取配置文件失败

    Note:
        如果配置文件不存在，返回空配置结构。
    """
    try:
        prefill_params = _load_prefill_params_file(workspace_path)
        return {"success": True, "data": prefill_params}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get prefill params: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get prefill params: {e!s}"
        ) from None


@router.get("/{class_kind}/{class_name}")
async def get_class_prefill_params(
    class_kind: Literal["env_module", "agent"] = PathParam(
        ..., description="类类型：env_module 或 agent"
    ),
    class_name: str = PathParam(
        ..., description="类名，如 mobility_space, basic_agent"
    ),
    workspace_path: str = Query(..., description="工作区路径"),
) -> dict[str, Any]:
    """
    获取特定类的预填充参数

    返回指定类（Agent或环境模块）的预填充参数配置。

    :param class_kind: 类类型，可选值： - env_module: 环境模块 - agent: Agent类
    :param class_name: 类名，如 mobility_space, basic_agent 等
    :param workspace_path: 工作区根目录路径

    :returns: Dict[str, Any]: 类的预填充参数，包含： - success: 是否成功 - class_kind: 类类型 - class_name: 类名 - params: 该类的预填充参数字典（如无配置则为空字典）
    :raises HTTPException: 500 - 读取配置文件失败

    用法示例::

        GET /api/v1/prefill-params/env_module/mobility_space?workspace_path=/path/to/workspace
    """
    try:
        prefill_params = _load_prefill_params_file(workspace_path)

        # 根据class_kind选择对应的键
        params_key = "env_modules" if class_kind == "env_module" else "agents"
        class_params = prefill_params.get(params_key, {}).get(class_name, {})

        return {
            "success": True,
            "class_kind": class_kind,
            "class_name": class_name,
            "params": class_params,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get class prefill params: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to get class prefill params: {e!s}"
        ) from None
