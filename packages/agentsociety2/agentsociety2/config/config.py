"""LLM 配置（从环境变量读取）。

该模块集中管理 AgentSociety2 的 LLM 相关配置，并提供若干便捷函数：

- :class:`~agentsociety2.config.config.Config`：从环境变量读取各类 API Key / base_url / model name 等。
- :func:`~agentsociety2.config.config.get_llm_router`：获取（并缓存）指定用途的 LiteLLM :class:`litellm.router.Router`。
- :func:`~agentsociety2.config.config.get_llm_router_and_model`：同时返回 Router 与模型名。
- :func:`~agentsociety2.config.config.get_model_name`：获取指定用途的模型名。
- :func:`~agentsociety2.config.config.extract_json`：从 LLM 响应文本中提取 JSON 片段。

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
    "get_llm_router",
    "get_llm_router_and_model",
    "get_llm_thinking",
    "get_model_name",
]

logger = get_logger()


def _env_int(name: str, default: int) -> int:
    """Read an int env var, falling back to ``default`` when unset/empty."""
    raw = os.getenv(name)
    return int(raw) if raw and raw.strip() else default


def _env_int_or_cpu(name: str) -> int:
    """Read an int env var, falling back to the machine logical CPU count."""
    raw = os.getenv(name)
    return int(raw) if raw and raw.strip() else (os.cpu_count() or 1)


def _env_str(name: str) -> str | None:
    """Read a stripped env var, treating unset/blank as ``None``."""
    raw = os.getenv(name)
    return raw.strip() if raw and raw.strip() else None


def _env_bool(name: str, default: bool) -> bool:
    """Read a bool env var (``1``/``true``/``yes`` → True), falling back to
    ``default`` when unset/empty/unrecognized."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_json_obj(name: str) -> dict[str, Any] | None:
    """Parse an env var holding a JSON object; warn and ignore if malformed.

    A malformed env var must never abort a run, so every failure path here is a
    warning plus ``None`` rather than an exception.
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

# ``off`` 时若没配 extra_body，我们唯一做的假设：OpenAI Chat Completions 的
# reasoning_effort 取最低档。网关若不认这个值，用
# AGENTSOCIETY_LLM_EXTRA_BODY 覆盖（配了 extra_body 就只发 extra_body）。
_DEFAULT_THINKING_OFF_EFFORT = "minimal"


def get_llm_thinking(role: str = "default") -> dict[str, Any]:
    """解析某角色的推理（thinking）开关，返回构造 ``ThinkingSettings`` 的参数。

    环境变量（``coder`` 角色优先读 ``AGENTSOCIETY_CODER_LLM_*``，未设时回退到
    默认组；其他角色只读默认组）：

    - ``AGENTSOCIETY_LLM_THINKING``：``on`` / ``off``（兼容 ``1/0/true/false``）。
      **未设 = 不发送任何新参数**，出站请求与不启用该功能时逐字节相同。
    - ``AGENTSOCIETY_LLM_REASONING_EFFORT``：作为 ``reasoning_effort`` 发送。
    - ``AGENTSOCIETY_LLM_EXTRA_BODY``：JSON 对象，合并进 ``extra_body``，用于
      网关私有开关（如 ``{"enable_thinking": false}``）。

    ``off`` 的确切语义：**配了 extra_body 就只发 extra_body，不发
    ``reasoning_effort``**（避免网关同时收到两个开关而报错）；没配则发
    ``reasoning_effort``，取 ``REASONING_EFFORT``，缺省 ``"minimal"``。

    这里刻意在**调用时**读 ``os.getenv``（而非只在 import 时读），以便测试用
    monkeypatch 覆盖；``Config`` 上的同名类属性仅作文档用途。

    :param role: ``default`` / ``coder`` / ``embedding``。
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
        extra_body = _read_json("EXTRA_BODY")
    else:
        raw_policy = _env_str("AGENTSOCIETY_LLM_THINKING")
        effort = _env_str("AGENTSOCIETY_LLM_REASONING_EFFORT")
        extra_body = _env_json_obj("AGENTSOCIETY_LLM_EXTRA_BODY")

    if raw_policy is None:
        return {"policy": "inherit", "reasoning_effort": None, "extra_body": None}

    lowered = raw_policy.lower()
    if lowered in _THINKING_ON:
        return {"policy": "on", "reasoning_effort": effort, "extra_body": extra_body}
    if lowered in _THINKING_OFF:
        if extra_body is not None:
            # 网关私有开关优先，且不叠加 reasoning_effort。
            return {"policy": "off", "reasoning_effort": None, "extra_body": extra_body}
        return {
            "policy": "off",
            "reasoning_effort": effort or _DEFAULT_THINKING_OFF_EFFORT,
            "extra_body": None,
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
    """Configure LiteLLM logging once per process."""
    setup_litellm_logging()


class Config:
    """AgentSociety2 配置（环境变量来源）。

    该类以“类属性”的形式暴露配置项，便于在不实例化的情况下读取。

    主要环境变量（节选）：

    - ``AGENTSOCIETY_HOME_DIR``：数据目录
    - ``AGENTSOCIETY_LLM_API_KEY`` / ``AGENTSOCIETY_LLM_API_BASE`` / ``AGENTSOCIETY_LLM_MODEL``：默认模型配置
    - ``AGENTSOCIETY_CODER_LLM_*``：代码生成模型配置
    - ``AGENTSOCIETY_EMBEDDING_*``：embedding 配置
    """

    HOME_DIR: str = os.getenv("AGENTSOCIETY_HOME_DIR", "./agentsociety_data")
    """
    Base directory path for storing agent data, memories, and persistent files.

    Environment variable: AGENTSOCIETY_HOME_DIR
    Default: "./agentsociety_data"

    This directory will contain subdirectories for memories, agent states, and other
    persistent data. The path can be absolute or relative to the current working directory.
    """

    # Default LLM settings
    # These are used for general-purpose language model operations throughout the system.

    LLM_API_KEY: str | None = os.getenv("AGENTSOCIETY_LLM_API_KEY")
    """
    API key for authenticating with the default LLM service.

    Environment variable: AGENTSOCIETY_LLM_API_KEY
    Default: None (must be set for the system to function)

    This is the primary API key used for most LLM operations. If not set, the system
    will raise an error when attempting to create LLM routers. Other specialized LLM
    configurations (coder, embedding) will fall back to this key if their specific
    keys are not provided.
    """

    LLM_API_BASE: str = os.getenv(
        "AGENTSOCIETY_LLM_API_BASE", "https://api.openai.com/v1"
    )
    """
    Base URL endpoint for the default LLM API service.

    Environment variable: AGENTSOCIETY_LLM_API_BASE
    Default: "https://api.openai.com/v1"

    This should point to the API endpoint expected by the selected LiteLLM provider.
    For OpenAI-compatible gateways, include the protocol (https://) and base path,
    but not the specific model endpoint (e.g., /chat/completions).
    """

    LLM_MODEL: str = os.getenv("AGENTSOCIETY_LLM_MODEL", "gpt-5.5")
    """
    Model identifier for the default LLM used in general operations.

    Environment variable: AGENTSOCIETY_LLM_MODEL
    Default: "gpt-5.5"

    This model is used for most language understanding and generation tasks that don't
    require specialized models. The model name should match the LiteLLM provider/model id
    used by your API provider; "gpt-5.5" is only the default OpenAI example.
    """

    # Coder LLM settings
    # These are specifically optimized for code generation and programming tasks.

    CODER_LLM_API_KEY: str | None = (
        os.getenv("AGENTSOCIETY_CODER_LLM_API_KEY") or LLM_API_KEY
    )
    """
    API key for the code generation LLM service.

    Environment variable: AGENTSOCIETY_CODER_LLM_API_KEY
    Default: Falls back to LLM_API_KEY if not set

    This key is used specifically for code-related operations. If not provided, the system
    will use the default LLM_API_KEY. Setting a separate key allows you to use a different
    API provider or account for code generation tasks, which may have different rate limits
    or pricing structures.
    """

    CODER_LLM_API_BASE: str = (
        os.getenv("AGENTSOCIETY_CODER_LLM_API_BASE") or LLM_API_BASE
    )
    """
    Base URL endpoint for the code generation LLM API.

    Environment variable: AGENTSOCIETY_CODER_LLM_API_BASE
    Default: Falls back to LLM_API_BASE if not set

    Allows you to use a different API endpoint specifically for code generation tasks.
    This is useful if you want to route code generation requests to a different service
    or region for better performance or cost optimization.
    """

    CODER_LLM_MODEL: str = os.getenv("AGENTSOCIETY_CODER_LLM_MODEL") or LLM_MODEL
    """
    Model identifier for code generation and programming tasks.

    Environment variable: AGENTSOCIETY_CODER_LLM_MODEL
    Default: Falls back to LLM_MODEL if not set

    This model is specifically used for code generation, code analysis, and other
    programming-related operations. Choose a model that is optimized for code understanding
    and generation, such as models trained on codebases.
    """

    # Embedding model settings
    # These are used for converting text into vector embeddings for semantic search and similarity.

    EMBEDDING_API_KEY: str | None = (
        os.getenv("AGENTSOCIETY_EMBEDDING_API_KEY") or LLM_API_KEY
    )
    """
    API key for the embedding model service.

    Environment variable: AGENTSOCIETY_EMBEDDING_API_KEY
    Default: Falls back to LLM_API_KEY if not set

    This key is used specifically for embedding operations, which convert text into
    high-dimensional vectors for semantic search, similarity matching, and memory
    operations. Some providers offer separate embedding services with different pricing.
    """

    EMBEDDING_API_BASE: str = (
        os.getenv("AGENTSOCIETY_EMBEDDING_API_BASE") or LLM_API_BASE
    )
    """
    Base URL endpoint for the embedding API service.

    Environment variable: AGENTSOCIETY_EMBEDDING_API_BASE
    Default: Falls back to LLM_API_BASE if not set

    Allows you to use a different API endpoint specifically for embedding operations.
    Some providers have dedicated embedding endpoints that may offer better performance
    or different pricing models for embedding tasks.
    """

    EMBEDDING_MODEL: str = os.getenv(
        "AGENTSOCIETY_EMBEDDING_MODEL", "text-embedding-3-large"
    )
    """
    Model identifier for text embedding generation.

    Environment variable: AGENTSOCIETY_EMBEDDING_MODEL
    Default: "text-embedding-3-large"

    This model is used to convert text into dense vector representations (embeddings).
    The embeddings are used for semantic search, similarity matching, and storing
    memories in vector databases. Choose a model that produces high-quality embeddings
    for your use case and language.
    """

    EMBEDDING_DIMS: int = int(os.getenv("AGENTSOCIETY_EMBEDDING_DIMS", "1024"))
    """
    Dimensionality of the embedding vectors produced by the embedding model.

    Environment variable: AGENTSOCIETY_EMBEDDING_DIMS
    Default: 1024

    This specifies the size of the vector space for embeddings. Higher dimensions
    can capture more nuanced semantic information but require more storage and computation.
    The value must match the actual output dimensionality of the selected embedding model.
    Common values are 384, 512, 768, 1024, or 1536 depending on the model.
    """

    # Trace writer: flush spans via a background thread (default on for
    # production so span writes never block the agent event loop). Tests set
    # this False via conftest for deterministic synchronous reads.
    TRACE_WRITER_ASYNC: bool = os.getenv(
        "AGENTSOCIETY_TRACE_WRITER_ASYNC", "1"
    ) not in (
        "0",
        "",
        "false",
        "False",
    )
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
    """
    Relative latency backoff factor for AIMD. A non-error LLM call is counted
    as "slow" (and contributes to an AIMD decrease) when its latency exceeds
    ``baseline * factor``, where ``baseline`` is a rolling low-percentile
    (P25) of recent healthy latencies.

    Environment variable: AGENTSOCIETY_LLM_LATENCY_DEGRADE_FACTOR
    Default: 4.0

    The baseline tracks the fast path, so this triggers when calls are
    genuinely slow relative to recent good performance — robust to the
    initial concurrent burst. Set to a very large value (or ``inf``) to
    disable relative latency backoff and rely on rate-limit (429) errors
    alone (the previous behavior).
    """

    LLM_SLOW_LATENCY_MS: float | None = (
        float(v) if (v := os.getenv("AGENTSOCIETY_LLM_SLOW_LATENCY_MS")) else None
    )
    """
    Optional absolute SLO ceiling in milliseconds. A non-error LLM call slower
    than this counts as "slow" regardless of the rolling baseline. Catches
    pathological tails even when sustained contention has pushed the whole
    baseline up (where the relative factor goes blind).

    Environment variable: AGENTSOCIETY_LLM_SLOW_LATENCY_MS
    Default: unset (relative-factor backoff only)
    """

    LLM_ROUND_SAMPLE_CAP: int = int(
        os.getenv("AGENTSOCIETY_LLM_ROUND_SAMPLE_CAP", "64")
    )
    """
    Upper bound on AIMD round size (completions evaluated per adjustment).
    Without this cap, round size grows with the limit, so a large limit makes
    adaptation sluggish (e.g. limit 400 → 400 completions before any adjust).

    Environment variable: AGENTSOCIETY_LLM_ROUND_SAMPLE_CAP
    Default: 64
    """

    # Ray / local LLM dispatch configuration. Clients build litellm Routers in
    # their own process / event loop.
    LLM_RAY_MAX_WORKERS: int = _env_int_or_cpu("AGENTSOCIETY_LLM_RAY_MAX_WORKERS")
    """
    Upper bound used as the Ray CPU budget hint (``ray.init(num_cpus=...)``).

    Environment variable: AGENTSOCIETY_LLM_RAY_MAX_WORKERS
    Default: machine logical CPU count (``os.cpu_count()``).

    Caps how many ``step_agent_batch`` Ray Tasks run concurrently per tick
    (one task per ``BATCH_SIZE`` chunk of agents). Lower this below the
    physical core count to leave headroom for the driver, the env-router
    actor, and the trace/replay actors.
    """

    LLM_RAY_CONCURRENCY: int = _env_int("AGENTSOCIETY_LLM_RAY_CONCURRENCY", 16)
    """
    Initial per-process concurrency for local LLM dispatching.

    Environment variable: AGENTSOCIETY_LLM_RAY_CONCURRENCY
    Default: 16

    The starting concurrency each local ``LLMClient`` AIMD semaphore tunes
    from. There is no hard upper/lower cap — each process adjusts its
    concurrency freely via AIMD (additive increase / multiplicative
    decrease) based on observed latency and rate-limit errors.
    """

    BATCH_SIZE: int = _env_int("AGENTSOCIETY_BATCH_SIZE", 256)
    """
    Number of agents per ``step_agent_batch`` Ray Task.

    Environment variable: AGENTSOCIETY_BATCH_SIZE
    Default: 256

    Each simulation tick chunks the agent id list into batches of this size
    and submits one Ray Task per chunk (``tasks = ceil(N / BATCH_SIZE)``).
    At most ``LLM_RAY_MAX_WORKERS`` tasks run concurrently, so choose a size
    where ``ceil(N / BATCH_SIZE) >= LLM_RAY_MAX_WORKERS`` to saturate the
    workers; otherwise some workers sit idle. Smaller batches add scheduling
    overhead; larger batches mean one slow agent can stall its whole batch.
    """

    # 推理（thinking）开关。这些类属性只是文档用途：实际解析发生在
    # :func:`get_llm_thinking` 调用时（读取 os.getenv），以便按角色回退与测试覆盖。
    LLM_THINKING: str | None = os.getenv("AGENTSOCIETY_LLM_THINKING")
    """
    是否启用模型推理（thinking）：``on`` / ``off``（兼容 ``1/0/true/false``）。

    Environment variable: AGENTSOCIETY_LLM_THINKING
    Default: unset（**不发送任何新参数**，行为与未启用该功能时完全一致）

    ``off`` 时发送 ``reasoning_effort``（取 ``AGENTSOCIETY_LLM_REASONING_EFFORT``，
    缺省 ``"minimal"``）；若同时配置了 ``AGENTSOCIETY_LLM_EXTRA_BODY``，则只发
    ``extra_body`` 而不发 ``reasoning_effort``，以适配网关私有开关。

    仅适用于 OpenAI 兼容 chat-completions 接口，不做模型族自动探测。
    """

    LLM_REASONING_EFFORT: str | None = os.getenv("AGENTSOCIETY_LLM_REASONING_EFFORT")
    """
    显式的 ``reasoning_effort`` 取值（``minimal`` / ``low`` / ``medium`` / ``high``）。

    Environment variable: AGENTSOCIETY_LLM_REASONING_EFFORT
    Default: unset（``off`` 时回退到 ``"minimal"``；``on`` 时不发送该字段）
    """

    LLM_EXTRA_BODY: str | None = os.getenv("AGENTSOCIETY_LLM_EXTRA_BODY")
    """
    网关私有的 OpenAI 兼容开关，JSON 对象字符串，合并进请求的 ``extra_body``。

    Environment variable: AGENTSOCIETY_LLM_EXTRA_BODY
    Default: unset

    例：``{"enable_thinking": false}``、``{"thinking": {"type": "disabled"}}``、
    ``{"chat_template_kwargs": {"enable_thinking": false}}``。JSON 解析失败只记
    warning 并忽略，不会中断实验。
    """

    CODER_LLM_THINKING: str | None = (
        os.getenv("AGENTSOCIETY_CODER_LLM_THINKING") or LLM_THINKING
    )
    """
    ``AGENTSOCIETY_LLM_THINKING`` 的 coder 角色覆盖（env router 的代码生成）。

    Environment variable: AGENTSOCIETY_CODER_LLM_THINKING
    Default: 回退到 ``AGENTSOCIETY_LLM_THINKING``
    """

    CODER_LLM_REASONING_EFFORT: str | None = (
        os.getenv("AGENTSOCIETY_CODER_LLM_REASONING_EFFORT") or LLM_REASONING_EFFORT
    )
    """
    ``AGENTSOCIETY_LLM_REASONING_EFFORT`` 的 coder 角色覆盖。

    Environment variable: AGENTSOCIETY_CODER_LLM_REASONING_EFFORT
    Default: 回退到 ``AGENTSOCIETY_LLM_REASONING_EFFORT``
    """

    CODER_LLM_EXTRA_BODY: str | None = (
        os.getenv("AGENTSOCIETY_CODER_LLM_EXTRA_BODY") or LLM_EXTRA_BODY
    )
    """
    ``AGENTSOCIETY_LLM_EXTRA_BODY`` 的 coder 角色覆盖。

    Environment variable: AGENTSOCIETY_CODER_LLM_EXTRA_BODY
    Default: 回退到 ``AGENTSOCIETY_LLM_EXTRA_BODY``
    """

    # Web Search API settings

    LITERATURE_SEARCH_MCP_URL: str = (
        os.getenv("LITERATURE_SEARCH_MCP_URL", "").strip()
        or "https://llmapi.fiblab.net/mcp/"
    )
    """
    MCP gateway URL for academic literature search (Streamable HTTP).

    Environment variable: LITERATURE_SEARCH_MCP_URL
    Default: "https://llmapi.fiblab.net/mcp/"
    """

    LITERATURE_SEARCH_API_KEY: str = os.getenv("LITERATURE_SEARCH_API_KEY", "").strip()
    """
    Bearer token for literature MCP authentication.

    Environment variable: LITERATURE_SEARCH_API_KEY
    Default: "" (empty, must be set for authenticated requests)
    """

    @classmethod
    def get_router(cls, model_type: Literal["default", "coder"] = "default") -> Router:
        """获取指定用途的 LLM Router（不做全局缓存）。

        :param model_type: ``default`` / ``coder``。
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
                        "model": f"openai/{coder_model}",
                        "api_key": coder_api_key,
                        "api_base": coder_api_base,
                    },
                },
                {
                    "model_name": default_model,
                    "litellm_params": {
                        "model": f"openai/{default_model}",
                        "api_key": default_api_key,
                        "api_base": default_api_base,
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
                        "model": f"openai/{default_model}",
                        "api_key": default_api_key,
                        "api_base": default_api_base,
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
        """Return the normalized academic literature MCP gateway URL.

        :returns: URL from ``LITERATURE_SEARCH_MCP_URL`` (environment overrides class default).
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
        """Return the Bearer token for the literature MCP gateway.

        :returns: Key from ``LITERATURE_SEARCH_API_KEY`` (environment overrides class default).
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

    :param model_type: ``default`` / ``coder``。
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

    :param model_type: ``default`` / ``coder``。
    :returns: 模型名字符串。
    """
    if model_type == "coder":
        return Config.CODER_LLM_MODEL
    else:  # default
        return Config.LLM_MODEL


def get_llm_connection(
    model_type: str = "default",
) -> tuple[str, str | None, str]:
    """返回某用途 LLM 的原始连接参数 ``(base_url, api_key, model_name)``。

    与 :func:`get_llm_router_and_model` 不同，这里不构建 Router，只返回连接
    参数，供 :class:`agentsociety2.config.llm_dispatcher.LLMClient` 携带跨 Ray 任务
    边界、在各 worker 进程内按需重建 Router。``coder``/``embedding`` 未单独配置时
    自动回退到 default（与 :class:`Config` 的回退语义一致）。

    :param model_type: ``default`` / ``coder`` / ``embedding``。
    :returns: ``(base_url, api_key, model_name)``；未配置的用途 ``api_key`` 可能为 ``None``。
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

    :param model_type: ``default`` / ``coder``。
    :returns: ``(router, model_name)``。
    """
    router = get_llm_router(model_type)
    model_name = get_model_name(model_type)
    return router, model_name


def extract_json(text: str) -> str | None:
    """从文本中尽量稳健地提取 JSON 字符串片段。

    该函数只做“截取”，不负责修复不合法 JSON；若需要修复，请配合 ``json_repair`` 等工具。

    :param text: 可能包含 JSON 的文本（例如 LLM 输出，可能夹杂 Markdown code fences）。
    :returns: 提取出的 JSON 文本；若未找到则返回 ``None``。
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
