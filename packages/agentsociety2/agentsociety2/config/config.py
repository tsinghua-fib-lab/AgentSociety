"""LLM 配置（从环境变量读取）。

该模块集中管理 AgentSociety2 的 LLM 相关配置，并提供若干便捷函数：

- :class:`~agentsociety2.config.config.Config` ：从环境变量读取各类 API Key / ``base_url`` / model name 等。
- :func:`~agentsociety2.config.config.get_llm_router` ：获取（并缓存）指定用途的 LiteLLM :class:`litellm.router.Router` 。
- :func:`~agentsociety2.config.config.get_llm_router_and_model` ：同时返回 Router 与模型名。
- :func:`~agentsociety2.config.config.get_model_name` ：获取指定用途的模型名。
- :func:`~agentsociety2.config.config.extract_json` ：从 LLM 响应文本中提取 JSON 片段。

.. important::
   ``AGENTSOCIETY_LLM_API_KEY`` 与 ``AGENTSOCIETY_LLM_API_BASE`` 在模块导入时校验；未配置会直接抛出异常。
"""

from __future__ import annotations

import json
import os
import re
from functools import cache
from typing import Any, Literal

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"

from litellm.router import Router

from agentsociety2.logger import get_logger, setup_litellm_logging

__all__ = [
    "Config",
    "extract_json",
    "get_llm_api_type",
    "get_llm_router",
    "get_llm_router_and_model",
    "get_llm_thinking",
    "get_model_name",
]

logger = get_logger()


def _env_int(name: str, default: int) -> int:
    """读取整型环境变量；未设置或为空时回退到 ``default`` 。"""
    raw = os.getenv(name)
    return int(raw) if raw and raw.strip() else default


def _env_int_or_cpu(name: str) -> int:
    """读取整型环境变量；未设置或为空时回退到机器逻辑 CPU 核数。"""
    raw = os.getenv(name)
    return int(raw) if raw and raw.strip() else (os.cpu_count() or 1)


def _env_str(name: str) -> str | None:
    """读取去除首尾空白的环境变量；未设置或为空白时视为 ``None`` 。"""
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else None


def _env_bool(name: str, default: bool) -> bool:
    """读取布尔环境变量（``1``/``true``/``yes`` 视为 True）；未设置、为空或无法识别时回退到 ``default`` 。"""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_json_obj(name: str) -> dict[str, Any] | None:
    """解析持有 JSON 对象的环境变量；格式非法时告警并忽略。

    非法的环境变量绝不能中断一次运行，因此这里的所有失败路径都是记一条
    warning 并返回 ``None`` ，而不是抛异常。
    """
    raw = _env_str(name)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except ValueError:
        logger.warning("Ignoring %s: not valid JSON (%r)", name, raw[:120])
        return None
    if not isinstance(value, dict):
        logger.warning(
            "Ignoring %s: expected a JSON object, got %s", name, type(value).__name__
        )
        return None
    return value


_THINKING_ON = {"on", "1", "true", "yes", "enable", "enabled"}
_THINKING_OFF = {"off", "0", "false", "no", "disable", "disabled"}


def get_llm_api_type(role: str = "default") -> str:
    """显式选择接口协议；模型别名并不能标识所用协议。"""
    if role == "embedding":
        return "openai"
    value = (
        (_env_str("AGENTSOCIETY_CODER_LLM_API_TYPE") if role == "coder" else None)
        or _env_str("AGENTSOCIETY_LLM_API_TYPE")
        or "openai"
    )
    value = value.lower()
    if value not in {"openai", "anthropic"}:
        raise ValueError("AGENTSOCIETY_*_LLM_API_TYPE must be openai or anthropic")
    return value


def get_llm_thinking(role: str = "default") -> dict[str, Any]:
    """解析某角色的推理（thinking）开关，返回构造 ``ThinkingSettings`` 的参数。

    环境变量（``coder`` 角色优先读 ``AGENTSOCIETY_CODER_LLM_*`` ，未设时回退到默认组；其他角色只读默认组）：

    - ``AGENTSOCIETY_LLM_THINKING`` ：``on`` / ``off`` （兼容 ``1/0/true/false`` ）。**未设 = 不发送任何新参数**，出站请求与不启用该功能时逐字节相同。
    - ``AGENTSOCIETY_LLM_REASONING_EFFORT`` ：作为 ``reasoning_effort`` 发送。
    - ``AGENTSOCIETY_LLM_EXTRA_BODY`` ：JSON 对象，合并进 ``extra_body`` ，用于网关私有开关（如 ``{"enable_thinking": false}`` ）。

    ``ThinkingSettings`` 按实际接口生成开启或关闭参数；关闭不使用推理强度。
    ``extra_body`` 可提供网关原生的推理开关，其他字段继续保留。

    这里刻意在**调用时**读 ``os.getenv`` （而非只在 import 时读），以便测试用
    monkeypatch 覆盖；``Config`` 上的同名类属性仅作文档用途。

    :param role: ``default`` / ``coder`` / ``embedding`` 。
    :returns: ``{"policy": "inherit"|"on"|"off", "reasoning_effort": str|None,
        "extra_body": dict|None}``。
    """
    if role == "coder":

        def _read(suffix: str) -> str | None:
            return _env_str(f"AGENTSOCIETY_CODER_LLM_{suffix}") or _env_str(
                f"AGENTSOCIETY_LLM_{suffix}"
            )

        def _read_json(suffix: str) -> dict[str, Any] | None:
            coder_var = f"AGENTSOCIETY_CODER_LLM_{suffix}"
            if _env_str(coder_var) is not None:
                return _env_json_obj(coder_var)
            return _env_json_obj(f"AGENTSOCIETY_LLM_{suffix}")

        raw_policy = _read("THINKING")
        effort = _read("REASONING_EFFORT")
        control_format = _read("THINKING_FORMAT")
        extra_body = _read_json("EXTRA_BODY")
    else:
        raw_policy = _env_str("AGENTSOCIETY_LLM_THINKING")
        effort = _env_str("AGENTSOCIETY_LLM_REASONING_EFFORT")
        control_format = _env_str("AGENTSOCIETY_LLM_THINKING_FORMAT")
        extra_body = _env_json_obj("AGENTSOCIETY_LLM_EXTRA_BODY")

    if raw_policy is None:
        return {"policy": "inherit", "reasoning_effort": None, "extra_body": None}

    formats = {
        "reasoning_effort",
        "thinking",
        "enable_thinking",
        "chat_template_kwargs",
        "reasoning",
    }
    if control_format and control_format not in formats:
        raise ValueError("Unsupported AGENTSOCIETY_*_LLM_THINKING_FORMAT")
    format_settings = {"format": control_format} if control_format else {}
    lowered = raw_policy.lower()
    if lowered in _THINKING_ON:
        return {
            "policy": "on",
            "reasoning_effort": effort,
            "extra_body": extra_body,
            **format_settings,
        }
    if lowered in _THINKING_OFF:
        return {
            "policy": "off",
            "reasoning_effort": None,
            "extra_body": extra_body,
            **format_settings,
        }

    logger.warning(
        "Ignoring AGENTSOCIETY_*_LLM_THINKING=%r (expected on/off); "
        "sending no reasoning parameters",
        raw_policy,
    )
    return {"policy": "inherit", "reasoning_effort": None, "extra_body": None}


def _router_model_names(model_list: list[dict[str, Any]]) -> list[str]:
    return [str(entry.get("model_name", "")) for entry in model_list]


def _redact_router_config_for_log(obj: Any) -> Any:
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            if k in ("api_key", "api_base") and isinstance(v, str) and v:
                out[k] = (v[:4] + "…") if len(v) > 4 else "****"
            else:
                out[k] = _redact_router_config_for_log(v)
        return out
    if isinstance(obj, list):
        return [_redact_router_config_for_log(x) for x in obj]
    return obj


@cache
def _initialize_litellm_logging() -> None:
    """每进程配置一次 LiteLLM 日志。"""
    setup_litellm_logging()


class Config:
    """AgentSociety2 配置（环境变量来源）。

    该类以“类属性”的形式暴露配置项，便于在不实例化的情况下读取。

    主要环境变量（节选）：

    - ``AGENTSOCIETY_HOME_DIR`` ：数据目录
    - ``AGENTSOCIETY_LLM_API_KEY`` / ``AGENTSOCIETY_LLM_API_BASE`` / ``AGENTSOCIETY_LLM_MODEL`` ：默认模型配置
    - ``AGENTSOCIETY_CODER_LLM_*`` ：代码生成模型配置
    - ``AGENTSOCIETY_EMBEDDING_*`` ：embedding 配置
    """

    HOME_DIR: str = os.getenv("AGENTSOCIETY_HOME_DIR", "./agentsociety_data")
    """存储 agent 数据、记忆与持久化文件的基础目录路径。

    环境变量：``AGENTSOCIETY_HOME_DIR``
    默认："``./agentsociety_data``"

    该目录下会包含记忆、agent 状态等持久化数据的子目录。路径可为绝对路径，也可以是相对当前工作目录的相对路径。
    """

    # Default LLM settings
    # These are used for general-purpose language model operations throughout the system.

    LLM_API_KEY: str | None = os.getenv("AGENTSOCIETY_LLM_API_KEY")
    """默认 LLM 服务的认证 API key。

    环境变量：``AGENTSOCIETY_LLM_API_KEY``
    默认：None（系统要正常运行必须设置）

    这是大多数 LLM 操作使用的主 API key。若未设置，系统在创建 LLM Router 时会抛出异常。其他专用 LLM 配置（coder、embedding）在未提供各自 key 时会回退到该 key。
    """

    LLM_API_BASE: str = os.getenv(
        "AGENTSOCIETY_LLM_API_BASE", "https://api.openai.com/v1"
    )
    """默认 LLM API 服务的基础 URL 端点。

    环境变量：``AGENTSOCIETY_LLM_API_BASE``
    默认：``https://api.openai.com/v1``。

    应指向所选 LiteLLM provider 所要求的 API 端点。对 OpenAI 兼容网关，需包含协议（``https://``）与基础路径，但不包含具体模型端点（如 ``/chat/completions``）。
    """

    LLM_MODEL: str = os.getenv("AGENTSOCIETY_LLM_MODEL", "gpt-5.5")
    """通用操作所用默认 LLM 的模型标识。

    环境变量：``AGENTSOCIETY_LLM_MODEL``
    默认："gpt-5.5"

    该模型用于大多数无需专用模型的语言理解与生成任务。模型名应与 API 供应商处 LiteLLM 的 provider/model id 一致；"gpt-5.5" 只是默认的 OpenAI 示例。
    """

    # Coder LLM settings
    # These are specifically optimized for code generation and programming tasks.

    CODER_LLM_API_KEY: str | None = (
        os.getenv("AGENTSOCIETY_CODER_LLM_API_KEY") or LLM_API_KEY
    )
    """代码生成 LLM 服务的 API key。

    环境变量：``AGENTSOCIETY_CODER_LLM_API_KEY``
    默认：未设置时回退到 ``LLM_API_KEY``

    该 key 专用于代码相关操作。若未提供，系统会使用默认的 ``LLM_API_KEY``。单独设置该 key 可为代码生成任务使用不同的 API 供应商或账户，其速率限制或计费结构可能不同。
    """

    CODER_LLM_API_BASE: str = (
        os.getenv("AGENTSOCIETY_CODER_LLM_API_BASE") or LLM_API_BASE
    )
    """代码生成 LLM API 的基础 URL 端点。

    环境变量：``AGENTSOCIETY_CODER_LLM_API_BASE``
    默认：未设置时回退到 ``LLM_API_BASE``

    允许为代码生成任务单独使用不同的 API 端点。若希望把代码生成请求路由到其他服务或区域，以获得更好的性能或成本优化，会很有用。
    """

    CODER_LLM_MODEL: str = os.getenv("AGENTSOCIETY_CODER_LLM_MODEL") or LLM_MODEL
    """代码生成与编程任务的模型标识。

    环境变量：``AGENTSOCIETY_CODER_LLM_MODEL``
    默认：未设置时回退到 ``LLM_MODEL``

    该模型专用于代码生成、代码分析等编程相关操作。请选择针对代码理解与生成优化过的模型，例如在代码库上训练过的模型。
    """

    # Embedding model settings
    # These are used for converting text into vector embeddings for semantic search and similarity.

    EMBEDDING_API_KEY: str | None = (
        os.getenv("AGENTSOCIETY_EMBEDDING_API_KEY") or LLM_API_KEY
    )
    """Embedding 模型服务的 API key。

    环境变量：``AGENTSOCIETY_EMBEDDING_API_KEY``
    默认：未设置时回退到 ``LLM_API_KEY``

    该 key 专用于 embedding 操作——把文本转换为高维向量，用于语义搜索、相似度匹配与记忆操作。部分供应商提供计费不同的独立 embedding 服务。
    """

    EMBEDDING_API_BASE: str = (
        os.getenv("AGENTSOCIETY_EMBEDDING_API_BASE") or LLM_API_BASE
    )
    """Embedding API 服务的基础 URL 端点。

    环境变量：``AGENTSOCIETY_EMBEDDING_API_BASE``
    默认：未设置时回退到 ``LLM_API_BASE``

    允许为 embedding 操作单独使用不同的 API 端点。部分供应商提供专用的
    embedding 端点，可能为 embedding 任务提供更好的性能或不同的计费模式。
    """

    EMBEDDING_MODEL: str = os.getenv(
        "AGENTSOCIETY_EMBEDDING_MODEL", "text-embedding-3-large"
    )
    """文本 embedding 生成的模型标识。

    环境变量：``AGENTSOCIETY_EMBEDDING_MODEL``
    默认："text-embedding-3-large"

    该模型用于把文本转换为稠密向量表示（embedding）。embedding 用于语义搜索、相似度匹配以及把记忆存入向量数据库。请选择在你的使用场景与语言下能产出高质量 embedding 的模型。
    """

    EMBEDDING_DIMS: int = int(os.getenv("AGENTSOCIETY_EMBEDDING_DIMS", "1024"))
    """Embedding 模型产出的向量维度。

    环境变量：``AGENTSOCIETY_EMBEDDING_DIMS``
    默认：1024

    指定 embedding 的向量空间大小。维度越高能捕捉越细腻的语义信息，但存储与计算开销也更大。该值必须与所选 embedding 模型的实际输出维度一致；常见取值为 384、512、768、1024 或 1536，取决于具体模型。
    """

    # Env Ray actor concurrency ceiling (static, NOT AIMD). Only takes effect
    # (>1) when every mounted env module declares is_concurrency_safe();
    # otherwise the actor stays serial (concurrency=1). API rate-limit control
    # is handled by the inner LLMClient AIMD, not here.
    #
    # Default 64: with 300 agents the measured p50 of in-flight env asks is
    # ~59, so the old default of 8 starved the actor (env ask mean 38.2s at
    # concurrency 8 vs 2.5s at 64 in the same run shape). Concurrency-safe
    # modules still serialize on their own module locks; unsafe stacks keep
    # max_concurrency=1 regardless of this value.
    ENV_ACTOR_MAX_CONCURRENCY: int = _env_int(
        "AGENTSOCIETY_ENV_ACTOR_MAX_CONCURRENCY", 64
    )

    # Strict env resume: when a module's restore() raises, abort the run
    # instead of silently starting that module fresh. Fresh-start fallback
    # corrupts the continued simulation (module state resets to initial
    # values while SOCIETY_STEP.json keeps the old step count) and only
    # surfaces much later through downstream metrics. Set to 1/true to
    # restore the old degrade-with-ERROR-logs behavior.
    ENV_RESTORE_ALLOW_FRESH: bool = _env_bool(
        "AGENTSOCIETY_ENV_RESTORE_ALLOW_FRESH", False
    )

    # Adaptive concurrency control for LLM requests (per-worker AIMD).
    LLM_LATENCY_DEGRADE_FACTOR: float = float(
        os.getenv("AGENTSOCIETY_LLM_LATENCY_DEGRADE_FACTOR", "4.0")
    )
    """AIMD 的相对延迟退避因子。一次无错误的 LLM 调用，当延迟超过
    ``baseline * factor`` 时记为“慢”（并计入一次 AIMD 降并发），其中
    ``baseline`` 是近期健康延迟的滚动低分位数（P25）。

    环境变量：``AGENTSOCIETY_LLM_LATENCY_DEGRADE_FACTOR``
    默认：4.0

    baseline 跟踪快路径，因此只有调用相对近期良好表现确实变慢时才触发——对初始并发突发具有鲁棒性。设为很大的值（或 ``inf`` ）可禁用相对延迟退避，仅依赖限流（429）错误（即旧行为）。
    """

    LLM_SLOW_LATENCY_MS: float | None = (
        float(v) if (v := os.getenv("AGENTSOCIETY_LLM_SLOW_LATENCY_MS")) else None
    )
    """可选的绝对 SLO 上限（毫秒）。无错误的 LLM 调用只要慢于该值即记为“慢”，与滚动 baseline 无关。即便持续争用已把整体 baseline 抬高（此时相对因子失明），也能捕捉到病态长尾。

    环境变量：``AGENTSOCIETY_LLM_SLOW_LATENCY_MS``
    默认：未设置（仅启用相对因子退避）
    """

    LLM_ROUND_SAMPLE_CAP: int = int(
        os.getenv("AGENTSOCIETY_LLM_ROUND_SAMPLE_CAP", "64")
    )
    """AIMD 轮次规模的上限（每次调整评估的补全数）。不设上限时轮次规模会随并发上限增长，上限很大时自适应会变得迟钝（如上限 400 → 需 400 次补全才调整一次）。

    环境变量：``AGENTSOCIETY_LLM_ROUND_SAMPLE_CAP``
    默认：64
    """

    # Ray / local LLM dispatch configuration. Clients build litellm Routers in
    # their own process / event loop.
    LLM_RAY_MAX_WORKERS: int = _env_int_or_cpu("AGENTSOCIETY_LLM_RAY_MAX_WORKERS")
    """作为 Ray CPU 预算提示的上限（``ray.init(num_cpus=...)`` ）。

    环境变量：``AGENTSOCIETY_LLM_RAY_MAX_WORKERS``
    默认：机器逻辑 CPU 核数（``os.cpu_count()`` ）。

    限制每个 tick 并发运行的 ``step_agent_batch`` Ray Task 数（每个
    ``BATCH_SIZE`` 大小的 agent 分片一个 task）。可将其调低到物理核数之下，为 driver、env-router actor 以及 trace/replay actor 留出余量。
    """

    LLM_RAY_CONCURRENCY: int = _env_int("AGENTSOCIETY_LLM_RAY_CONCURRENCY", 16)
    """本地 LLM 调度的每进程初始并发。

    环境变量：``AGENTSOCIETY_LLM_RAY_CONCURRENCY``
    默认：16

    每个本地 ``LLMClient`` 的 AIMD 信号量由此初始并发出发进行调优。没有硬性上下限——各进程基于观测到的延迟与限流错误，通过 AIMD（加性增 / 乘性减）自由调整并发。
    """

    CODE_EXEC_TIMEOUT: int = _env_int("AGENTSOCIETY_CODE_EXEC_TIMEOUT", 10)
    """生成的代码与工具的执行时限（秒）。process 后端强制硬性墙钟时限；
    inprocess 使用协作式 Python 检查。

    环境变量：``AGENTSOCIETY_CODE_EXEC_TIMEOUT``
    """

    CODE_EXEC_BACKEND: str = os.getenv("AGENTSOCIETY_CODE_EXEC_BACKEND", "inprocess")
    """完整 Python 执行后端：默认 inprocess；process 启用 worker 隔离。

    Inprocess 使用协作式 Python 截止时间与部署级资源限制。环境变量：``AGENTSOCIETY_CODE_EXEC_BACKEND``
    """

    CODE_EXEC_MEMORY_MIB: int = _env_int("AGENTSOCIETY_CODE_EXEC_MEMORY_MIB", 512)
    """单个数值计算 worker 的地址空间上限（含其 Python/NumPy 运行时）。

    环境变量：``AGENTSOCIETY_CODE_EXEC_MEMORY_MIB``
    """

    CODE_EXEC_WORKERS: int = _env_int("AGENTSOCIETY_CODE_EXEC_WORKERS", 4)
    """同一事件循环上各 router 共享的数值计算 worker 数上限。

    环境变量：``AGENTSOCIETY_CODE_EXEC_WORKERS``
    """

    BATCH_SIZE: int = _env_int("AGENTSOCIETY_BATCH_SIZE", 256)
    """每个 ``step_agent_batch`` Ray Task 处理的 agent 数。

    环境变量：``AGENTSOCIETY_BATCH_SIZE``
    默认：256

    每个仿真 tick 把 agent id 列表按该大小分片，每片提交一个 Ray Task
    （``tasks = ceil(N / BATCH_SIZE)`` ）。并发运行的 task 至多
    ``LLM_RAY_MAX_WORKERS`` 个，因此应选取满足
    ``ceil(N / BATCH_SIZE) >= LLM_RAY_MAX_WORKERS`` 的取值以喂饱 worker；否则部分 worker 会闲置。分片过小增加调度开销；过大则一个慢 agent 会拖住整个分片。
    """

    WORKSPACE_READ_MAX_BYTES: int = _env_int(
        "AGENTSOCIETY_WORKSPACE_READ_MAX_BYTES", 65536
    )
    """agent ``read`` 工具返回字节数的硬上限。

    观测结果会并入 react 线程，并在后续每一轮重发（无缓存尾部），因此一个大文件会在本 step 余下的轮次中同时推高上下文与成本。超限的读取会被截断并附带标记；模型会被引导改用 ``grep`` 做定向提取。

    环境变量：``AGENTSOCIETY_WORKSPACE_READ_MAX_BYTES``
    默认：65536（64 KiB）
    """

    # 推理（thinking）开关。这些类属性只是文档用途：实际解析发生在
    # :func:`get_llm_thinking` 调用时（读取 os.getenv），以便按角色回退与测试覆盖。
    LLM_THINKING: str | None = os.getenv("AGENTSOCIETY_LLM_THINKING")
    """是否启用模型推理（thinking）：``on`` / ``off`` （兼容 ``1/0/true/false`` ）。

    环境变量：``AGENTSOCIETY_LLM_THINKING``
    默认：未设置（**不发送任何新参数**，行为与未启用该功能时完全一致）

    OpenAI 接口关闭时发送 ``reasoning_effort="none"`` ，开启时默认 ``medium`` 。
    Anthropic Messages 接口发送显式 ``thinking`` 开关，开启默认预算 1024 tokens。
    ``AGENTSOCIETY_LLM_EXTRA_BODY`` 可声明其他网关的原生开关。接口协议由 ``AGENTSOCIETY_LLM_API_TYPE`` 选择，默认 ``openai`` 。
    """

    LLM_REASONING_EFFORT: str | None = os.getenv("AGENTSOCIETY_LLM_REASONING_EFFORT")
    """显式的 ``reasoning_effort`` 取值（``minimal`` / ``low`` / ``medium`` / ``high`` / ``xhigh`` / ``max`` ）。

    环境变量：``AGENTSOCIETY_LLM_REASONING_EFFORT``
    默认：未设置（OpenAI 接口 ``on`` 默认 ``medium`` ；关闭不使用推理强度）
    """

    LLM_EXTRA_BODY: str | None = os.getenv("AGENTSOCIETY_LLM_EXTRA_BODY")
    """网关私有的 OpenAI 兼容开关，JSON 对象字符串，合并进请求的 ``extra_body`` 。

    环境变量：``AGENTSOCIETY_LLM_EXTRA_BODY``
    默认：未设置

    例：``{"enable_thinking": false}`` 、``{"thinking": {"type": "disabled"}}`` 、
    ``{"chat_template_kwargs": {"enable_thinking": false}}`` 。JSON 解析失败只记
    warning 并忽略，不会中断实验。
    """

    CODER_LLM_THINKING: str | None = (
        os.getenv("AGENTSOCIETY_CODER_LLM_THINKING") or LLM_THINKING
    )
    """``AGENTSOCIETY_LLM_THINKING`` 的 coder 角色覆盖（env router 的代码生成）。

    环境变量：``AGENTSOCIETY_CODER_LLM_THINKING``
    默认：回退到 ``AGENTSOCIETY_LLM_THINKING``
    """

    CODER_LLM_REASONING_EFFORT: str | None = (
        os.getenv("AGENTSOCIETY_CODER_LLM_REASONING_EFFORT") or LLM_REASONING_EFFORT
    )
    """``AGENTSOCIETY_LLM_REASONING_EFFORT`` 的 coder 角色覆盖。

    环境变量：``AGENTSOCIETY_CODER_LLM_REASONING_EFFORT``
    默认：回退到 ``AGENTSOCIETY_LLM_REASONING_EFFORT``
    """

    CODER_LLM_EXTRA_BODY: str | None = (
        os.getenv("AGENTSOCIETY_CODER_LLM_EXTRA_BODY") or LLM_EXTRA_BODY
    )
    """``AGENTSOCIETY_LLM_EXTRA_BODY`` 的 coder 角色覆盖。

    环境变量：``AGENTSOCIETY_CODER_LLM_EXTRA_BODY``
    默认：回退到 ``AGENTSOCIETY_LLM_EXTRA_BODY``
    """

    # Web Search API settings

    LITERATURE_SEARCH_MCP_URL: str = (
        os.getenv("LITERATURE_SEARCH_MCP_URL", "").strip()
        or "https://llmapi.fiblab.net/mcp/"
    )
    """学术文献检索的 MCP 网关 URL（Streamable HTTP）。

    环境变量：``LITERATURE_SEARCH_MCP_URL``
    默认：``https://llmapi.fiblab.net/mcp/``。
    """

    LITERATURE_SEARCH_API_KEY: str = os.getenv("LITERATURE_SEARCH_API_KEY", "").strip()
    """文献 MCP 鉴权使用的 Bearer token。

    环境变量：``LITERATURE_SEARCH_API_KEY``
    默认：""（为空；发起鉴权请求前必须设置）
    """

    @classmethod
    def get_router(cls, model_type: Literal["default", "coder"] = "default") -> Router:
        """获取指定用途的 LLM Router（不做全局缓存）。

        :param model_type: ``default`` / ``coder`` 。
        :returns: LiteLLM :class:`litellm.router.Router` 实例。
        :raises ValueError: 当所需 API key 未配置时抛出。
        """
        _initialize_litellm_logging()

        # Shared default-model definition (used as a fallback target below).
        default_api_key = cls.LLM_API_KEY
        default_api_base = cls.LLM_API_BASE
        default_model = cls.LLM_MODEL

        if model_type == "coder":
            # Coder model with fallback to default.
            coder_api_key = cls.CODER_LLM_API_KEY
            coder_api_base = cls.CODER_LLM_API_BASE
            coder_model = cls.CODER_LLM_MODEL

            if not coder_api_key:
                raise ValueError(
                    "API key not configured for coder model. "
                    "Set AGENTSOCIETY_CODER_LLM_API_KEY or AGENTSOCIETY_LLM_API_KEY"
                )
            if not default_api_key:
                raise ValueError(
                    "API key not configured for default model (fallback). "
                    "Set AGENTSOCIETY_LLM_API_KEY"
                )

            model_list = [
                {
                    "model_name": coder_model,
                    "litellm_params": {
                        "model": f"{get_llm_api_type('coder')}/{coder_model}",
                        "api_key": coder_api_key,
                        "api_base": coder_api_base.rstrip("/").removesuffix("/v1")
                        if get_llm_api_type("coder") == "anthropic"
                        else coder_api_base,
                    },
                },
                {
                    "model_name": default_model,
                    "litellm_params": {
                        "model": f"{get_llm_api_type()}/{default_model}",
                        "api_key": default_api_key,
                        "api_base": default_api_base.rstrip("/").removesuffix("/v1")
                        if get_llm_api_type() == "anthropic"
                        else default_api_base,
                    },
                },
            ]

            # Configure fallback chain: coder -> default
            fallbacks = [{coder_model: [default_model]}]

            logger.debug(
                "Coder router models: %s", [m.get("model_name") for m in model_list]
            )
            return Router(
                model_list=model_list,
                fallbacks=fallbacks,
                cache_responses=True,
                num_retries=10,
            )
        else:  # default
            if not default_api_key:
                raise ValueError(
                    "API key not configured for default model. "
                    "Set AGENTSOCIETY_LLM_API_KEY"
                )

            model_list = [
                {
                    "model_name": default_model,
                    "litellm_params": {
                        "model": f"{get_llm_api_type()}/{default_model}",
                        "api_key": default_api_key,
                        "api_base": default_api_base.rstrip("/").removesuffix("/v1")
                        if get_llm_api_type() == "anthropic"
                        else default_api_base,
                    },
                },
            ]

            logger.debug(
                "Default router models: %s", [m.get("model_name") for m in model_list]
            )
            return Router(
                model_list=model_list,
                cache_responses=True,
                num_retries=10,
            )

    @classmethod
    def get_literature_search_mcp_url(cls) -> str:
        """返回规范化后的学术文献 MCP 网关 URL。

        :returns: 取自 ``LITERATURE_SEARCH_MCP_URL`` 的 URL（环境变量优先于类默认值）。
        """
        from agentsociety2.skills.literature.mcp_client import (
            normalize_literature_mcp_url,
        )

        raw = (
            os.getenv("LITERATURE_SEARCH_MCP_URL", "").strip()
            or cls.LITERATURE_SEARCH_MCP_URL
        )
        return normalize_literature_mcp_url(raw)

    @classmethod
    def get_literature_search_api_key(cls) -> str:
        """返回文献 MCP 网关的 Bearer token。

        :returns: 取自 ``LITERATURE_SEARCH_API_KEY`` 的 key（环境变量优先于类默认值）。
        """
        return (
            os.getenv("LITERATURE_SEARCH_API_KEY", "").strip()
            or cls.LITERATURE_SEARCH_API_KEY
        )

    @classmethod
    def get_default_router(cls) -> Router:
        """:returns: 默认用途的 LLM Router。"""
        return cls.get_router("default")


# Validate required configuration at module load time
if not Config.LLM_API_KEY:
    raise ValueError(
        "AGENTSOCIETY_LLM_API_KEY is required. "
        "Please set this environment variable before running AgentSociety2."
    )
if not Config.LLM_API_BASE:
    raise ValueError(
        "AGENTSOCIETY_LLM_API_BASE is required. "
        "Please set this environment variable before running AgentSociety2."
    )


# Global router instances (lazy initialization)
_default_router: Router | None = None
_coder_router: Router | None = None


def get_llm_router(model_type: str = "default") -> Router:
    """获取（并缓存）指定用途的 LLM Router。

    :param model_type: ``default`` / ``coder`` 。
    :returns: LiteLLM :class:`litellm.router.Router` 实例（进程内单例缓存）。
    """
    global _default_router, _coder_router

    if model_type == "coder":
        if _coder_router is None:
            _coder_router = Config.get_router("coder")
        return _coder_router
    else:  # default
        if _default_router is None:
            _default_router = Config.get_router("default")
        return _default_router


def get_model_name(model_type: str = "default") -> str:
    """获取指定用途的模型名。

    :param model_type: ``default`` / ``coder`` 。
    :returns: 模型名字符串。
    """
    if model_type == "coder":
        return Config.CODER_LLM_MODEL
    else:  # default
        return Config.LLM_MODEL


def get_llm_connection(
    model_type: str = "default",
) -> tuple[str, str | None, str]:
    """返回某用途 LLM 的原始连接参数 ``(base_url, api_key, model_name)`` 。

    与 :func:`get_llm_router_and_model` 不同，这里不构建 Router，只返回连接参数，供 :class:`agentsociety2.config.llm_dispatcher.LLMClient` 携带跨 Ray 任务边界、在各 worker 进程内按需重建 Router。``coder``/``embedding`` 未单独配置时自动回退到 default（与 :class:`Config` 的回退语义一致）。

    :param model_type: ``default`` / ``coder`` / ``embedding`` 。
    :returns: ``(base_url, api_key, model_name)`` ；未配置的用途 ``api_key`` 可能为 ``None`` 。
    """
    if model_type == "coder":
        return (
            Config.CODER_LLM_API_BASE,
            Config.CODER_LLM_API_KEY,
            Config.CODER_LLM_MODEL,
        )
    if model_type == "embedding":
        return (
            Config.EMBEDDING_API_BASE,
            Config.EMBEDDING_API_KEY,
            Config.EMBEDDING_MODEL,
        )
    return Config.LLM_API_BASE, Config.LLM_API_KEY, Config.LLM_MODEL


def get_llm_router_and_model(model_type: str = "default") -> tuple[Router, str]:
    """同时获取 Router 与模型名（Router 使用缓存）。

    :param model_type: ``default`` / ``coder`` 。
    :returns: ``(router, model_name)`` 。
    """
    router = get_llm_router(model_type)
    model_name = get_model_name(model_type)
    return router, model_name


def extract_json(text: str) -> str | None:
    """从文本中尽量稳健地提取 JSON 字符串片段。

    该函数只做“截取”，不负责修复不合法 JSON；若需要修复，请配合 ``json_repair`` 等工具。

    :param text: 可能包含 JSON 的文本（例如 LLM 输出，可能夹杂 Markdown code fences）。
    :returns: 提取出的 JSON 文本；若未找到则返回 ``None`` 。
    """
    if not text:
        return None

    # Try to find JSON code blocks first (common in LLM responses)
    json_block_pattern = r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```"
    json_block_match = re.search(json_block_pattern, text, re.DOTALL)
    if json_block_match:
        return json_block_match.group(1)

    # Find the first occurrence of { or [
    start_idx = -1
    start_char = None
    end_char = None

    for i, char in enumerate(text):
        if char == "{":
            start_idx = i
            start_char = "{"
            end_char = "}"
            break
        elif char == "[":
            start_idx = i
            start_char = "["
            end_char = "]"
            break

    if start_idx == -1:
        return None

    # Find matching closing bracket/brace
    depth = 0
    in_string = False
    escape_next = False

    for i in range(start_idx, len(text)):
        char = text[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == start_char:
            depth += 1
        elif char == end_char:
            depth -= 1
            if depth == 0:
                # Found matching closing bracket
                return text[start_idx : i + 1]

    # If we didn't find a closing bracket, return what we have
    # (might be incomplete JSON, but let json_repair handle it)
    return text[start_idx:]
