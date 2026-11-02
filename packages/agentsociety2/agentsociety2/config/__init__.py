"""LLM 配置模块。

本模块提供 LLM 路由器和配置管理功能：

- **Config**: 配置类，管理 API 密钥、模型名称等
- **get_llm_router**: 获取指定角色的 litellm Router 实例
- **get_llm_router_and_model**: 同时获取 Router 与模型名称
- **get_model_name**: 获取指定角色的模型名称
- **extract_json**: 从 LLM 响应中提取 JSON
- **get_dispatcher**: 获取指定 role 的 :class:`LLMClient` （per-process 调度）

角色类型：
- ``default``: 默认 LLM（通用任务）
- ``coder``: 代码生成 LLM（更强大的模型）
- ``embedding``: 嵌入模型

环境变量配置：
- ``AGENTSOCIETY_LLM_API_KEY``: 主 API 密钥（必需）
- ``AGENTSOCIETY_LLM_API_BASE``: API 基础 URL（必需）
- ``AGENTSOCIETY_LLM_MODEL``: 默认模型名称
- ``AGENTSOCIETY_CODER_LLM_*``: Coder 角色配置
- ``AGENTSOCIETY_EMBEDDING_*``: Embedding 模型配置
- ``AGENTSOCIETY_LLM_RAY_MAX_WORKERS``: Ray CPU 预算上限提示，默认机器 CPU 核数
- ``AGENTSOCIETY_LLM_RAY_CONCURRENCY``: 每个本地 LLMClient 的 AIMD 初始并发（默认 16，无硬上下限）
- ``AGENTSOCIETY_BATCH_SIZE``: 每个 step_agent_batch Ray Task 处理的 agent 数（默认 256）
"""

from .config import (
    Config,
    extract_json,
    get_llm_connection,
    get_llm_router,
    get_llm_router_and_model,
    get_model_name,
)
from .llm_dispatcher import (
    LLMClient,
    LLMDispatchError,
    build_client_for_role,
    init_dispatchers,
    is_rate_limit_like_error,
    merge_token_stats,
    shutdown_dispatchers,
)

__all__ = [
    "Config",
    "LLMClient",
    "LLMDispatchError",
    "build_client_for_role",
    "extract_json",
    "get_llm_connection",
    "get_llm_router",
    "get_llm_router_and_model",
    "get_model_name",
    "init_dispatchers",
    "is_rate_limit_like_error",
    "merge_token_stats",
    "shutdown_dispatchers",
]
