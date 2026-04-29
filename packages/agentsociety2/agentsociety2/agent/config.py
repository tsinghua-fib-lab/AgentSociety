"""Agent统一配置管理。

本模块提供Agent的统一配置系统。设计原则：

1. **开箱即用**: 大多数参数已写死，无需用户配置
2. **最小暴露**: 仅暴露真正需要调整的参数
3. **环境变量覆盖**: 核心参数支持环境变量动态调整

示例
====

基本使用::

    from agentsociety2.agent.config import AgentConfig

    config = AgentConfig()  # 使用默认值
    config = AgentConfig.from_env()  # 从环境变量加载

访问配置::

    config.model.context_window  # 200000
    config.loop.max_rounds  # 24
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# 环境变量白名单：允许传递给子进程的环境变量
ALLOWED_ENV_VARS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "PYTHONUNBUFFERED",
        "LITELLM_MODEL",
        "LITELLM_BASE_URL",
        "AGENT_MEMORY_MAX_ENTRIES",
        "AGENT_MEMORY_STRENGTH",
    }
)


def _int(name: str, default: int) -> int:
    """从环境变量读取整数配置。

    :param name: 环境变量名。
    :param default: 默认值。
    :return: 配置值。
    """
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


# ============================================================================
# 内部常量（写死，不暴露给用户）
# ============================================================================

# 上下文压缩阈值
_COMPACT_WARNING_RATIO = 0.60
_COMPACT_TRIGGER_RATIO = 0.75
_COMPACT_AUTO_RATIO = 0.85
_COMPACT_FORCE_RATIO = 0.90

# Thread 限制
_THREAD_MAX_MESSAGES = 50
_THREAD_MAX_TOKENS = 150_000
_THREAD_KEEP_RECENT = 12

# 输出限制
_STDOUT_MAX_CHARS = 10_000
_STDERR_MAX_CHARS = 5_000
_TOOL_RESULT_BUDGET = 32_000

# 工作区限制
_WORKSPACE_READ_CHUNK_CAP = 32_000
_WORKSPACE_CACHE_MAX_ENTRIES = 50

# 循环检测阈值
_MAX_TOOL_REPEATS = 5
_MAX_CONTENT_REPEATS = 10
_MAX_ERROR_REPEATS = 3
_LOOP_HISTORY_SIZE = 20

# 并发限制
_MAX_PARALLEL_TOOLS = 5
_MAX_LLM_CONCURRENT = 5
_MAX_SUBPROCESS = 8
_RATE_LIMIT_RPS = 10.0

# Tiktoken 编码
_TIKTOKEN_ENCODING = "cl100k_base"


# ============================================================================
# 用户可配置项
# ============================================================================


@dataclass
class ModelConfig:
    """模型配置。

    :ivar model: 模型名称。
    :ivar context_window: 上下文窗口大小（tokens）。
    """

    model: str = ""
    context_window: int = 200_000

    @property
    def effective_window(self) -> int:
        """有效上下文窗口大小（减去输出预留和开销）。"""
        return max(8192, self.context_window - 24_000)


@dataclass
class LoopConfig:
    """工具循环配置。

    :ivar max_rounds: 单步最大工具轮数。
    :ivar step_timeout: 整步超时时间（秒）。
    """

    max_rounds: int = 24
    step_timeout: int = 300

    # 以下参数写死，不暴露
    tool_timeout: float = 30.0
    bash_retries: int = 1
    llm_retries: int = 3
    llm_transient_retries: int = 2
    tool_decision_max_retries: int = 10


@dataclass
class PersistenceConfig:
    """持久化配置。

    :ivar checkpoint_interval: 检查点间隔（ticks）。
    :ivar checkpoint_max: 最大保留检查点数。
    :ivar thread_history_max_files: 最大保留的对话历史文件数。
    """

    checkpoint_interval: int = 10
    checkpoint_max: int = 20
    thread_history_max_files: int = 20

    # 以下参数写死
    checkpoint_include_workspace: bool = True
    max_log_files: int = 50
    max_memory_entries: int = 5000
    wal_max_entries: int = 1000
    llm_history_max_entries: int = 100
    enable_llm_history: bool = False
    archive_after_days: int = 30


@dataclass
class ContextConfig:
    """上下文管理配置（内部使用，大多数参数写死）。

    :ivar workspace_cache_max_entries: 工作区缓存最大条目数。
    :ivar preload_workspace_paths: 预加载的工作区路径列表。
    """

    workspace_cache_max_entries: int = 50
    preload_workspace_paths: list[str] = field(default_factory=list)

    # 压缩阈值（写死）
    compact_warning_ratio: float = field(default=_COMPACT_WARNING_RATIO, repr=False)
    compact_trigger_ratio: float = field(default=_COMPACT_TRIGGER_RATIO, repr=False)
    compact_auto_ratio: float = field(default=_COMPACT_AUTO_RATIO, repr=False)
    compact_force_ratio: float = field(default=_COMPACT_FORCE_RATIO, repr=False)

    # Thread 限制（写死）
    thread_max_messages: int = field(default=_THREAD_MAX_MESSAGES, repr=False)
    thread_max_tokens: int = field(default=_THREAD_MAX_TOKENS, repr=False)
    thread_keep_recent: int = field(default=_THREAD_KEEP_RECENT, repr=False)
    thread_compact_max_chars: int = field(default=100_000, repr=False)
    thread_compact_keep_recent: int = field(default=8, repr=False)

    # 输出限制（写死）
    stdout_max_chars: int = field(default=_STDOUT_MAX_CHARS, repr=False)
    stderr_max_chars: int = field(default=_STDERR_MAX_CHARS, repr=False)
    tool_result_budget: int = field(default=_TOOL_RESULT_BUDGET, repr=False)
    tool_result_thread_budget: int = field(default=64_000, repr=False)

    # 工作区限制（写死）
    workspace_read_chunk_cap: int = field(default=_WORKSPACE_READ_CHUNK_CAP, repr=False)
    workspace_chunk_size: int = field(default=32_768, repr=False)
    key_state_file_limit: int = field(default=5000, repr=False)

    # 其他（写死）
    tool_table_mode: str = field(default="full", repr=False)
    grep_max_files: int = field(default=2000, repr=False)
    grep_max_matches: int = field(default=1000, repr=False)
    grep_max_file_bytes: int = field(default=2 * 1024 * 1024, repr=False)
    summary_msg_limit: int = field(default=10, repr=False)
    summary_msg_short_limit: int = field(default=5, repr=False)
    summary_char_budget: int = field(default=4000, repr=False)
    model_context_window: int = field(default=200_000, repr=False)
    world_desc_max_chars: int = field(default=10_000, repr=False)
    workspace_snapshot_str_cap: int = field(default=5_000, repr=False)
    thread_key_state_paths: list[str] = field(default_factory=list, repr=False)
    system_prompt_max_identity_chars: int = field(default=10_000, repr=False)
    catalog_working_set_json: bool = field(default=False, repr=False)
    tiktoken_encoding: str = field(default=_TIKTOKEN_ENCODING, repr=False)
    profile_max_chars: int = field(default=4000, repr=False)


@dataclass
class LoopDetectionConfig:
    """循环检测配置（内部使用，参数写死）。"""

    max_tool_repeats: int = field(default=_MAX_TOOL_REPEATS, repr=False)
    max_content_repeats: int = field(default=_MAX_CONTENT_REPEATS, repr=False)
    max_error_repeats: int = field(default=_MAX_ERROR_REPEATS, repr=False)
    history_size: int = field(default=_LOOP_HISTORY_SIZE, repr=False)
    overuse_threshold: int = field(default=15, repr=False)


@dataclass
class ConcurrencyConfig:
    """并发控制配置（内部使用）。"""

    max_parallel_tools: int = field(default=_MAX_PARALLEL_TOOLS, repr=False)
    max_llm_concurrent: int = field(default=_MAX_LLM_CONCURRENT, repr=False)
    max_subprocess: int = field(default=_MAX_SUBPROCESS, repr=False)
    rate_limit_rps: float = field(default=_RATE_LIMIT_RPS, repr=False)


@dataclass
class StateConfig:
    """状态文件配置（内部使用）。"""

    builtin_states: dict[str, tuple[str, str]] = field(
        default_factory=lambda: {
            "emotion": ("emotion.json", "primary"),
            "intention": ("intention.json", "intention"),
            "needs": ("needs.json", "current_need"),
            "plan": ("plan_state.json", "target"),
        }
    )
    extra_states: dict[str, tuple[str, str]] = field(default_factory=dict)
    auto_discover: bool = True
    summary_max_length: int = 100

    def get_all_states(self) -> dict[str, tuple[str, str]]:
        """获取所有状态文件定义（内置 + 扩展）。"""
        result = dict(self.builtin_states)
        result.update(self.extra_states)
        return result


@dataclass
class AgentConfig:
    """Agent统一配置。

    整合所有子配置，提供统一的访问入口。

    :ivar model: 模型配置。
    :ivar loop: 工具循环配置。
    :ivar context: 上下文管理配置。
    :ivar persistence: 持久化配置。
    :ivar concurrency: 并发控制配置。
    :ivar loop_detection: 循环检测配置。
    :ivar state: 状态文件配置。
    :ivar workspace_path: 工作区路径（可选）。

    Example:

        >>> config = AgentConfig()
        >>> config = AgentConfig.from_env()
    """

    model: ModelConfig = field(default_factory=ModelConfig)
    loop: LoopConfig = field(default_factory=LoopConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    persistence: PersistenceConfig = field(default_factory=PersistenceConfig)
    concurrency: ConcurrencyConfig = field(default_factory=ConcurrencyConfig)
    loop_detection: LoopDetectionConfig = field(default_factory=LoopDetectionConfig)
    state: StateConfig = field(default_factory=StateConfig)
    workspace_path: str = ""

    @classmethod
    def from_env(cls) -> "AgentConfig":
        """从环境变量加载配置。

        支持的环境变量：
            - AGENT_MODEL: 模型名称
            - AGENT_CONTEXT_WINDOW: 上下文窗口大小
            - AGENT_MAX_TOOL_ROUNDS: 最大工具轮数
            - AGENT_STEP_TIMEOUT: 单步超时(秒)
            - AGENT_CHECKPOINT_INTERVAL: 检查点间隔

        :return: 配置实例。
        """
        return cls(
            model=ModelConfig(
                model=os.getenv("AGENT_MODEL", ""),
                context_window=_int("AGENT_CONTEXT_WINDOW", 200_000),
            ),
            loop=LoopConfig(
                max_rounds=_int("AGENT_MAX_TOOL_ROUNDS", 24),
                step_timeout=_int("AGENT_STEP_TIMEOUT", 300),
            ),
            persistence=PersistenceConfig(
                checkpoint_interval=_int("AGENT_CHECKPOINT_INTERVAL", 10),
            ),
        )

    @classmethod
    def from_kwargs(cls, kwargs: dict | None = None) -> "AgentConfig":
        """从 kwargs 字典创建配置实例（支持最小可用覆盖）。

        该方法用于把 `PersonAgent(..., **capability_kwargs)` 传入的少数关键参数
        映射到 `AgentConfig`。本仓库明确 **不需要向后兼容**：未识别的字段会被忽略，
        但已支持字段会严格生效（并做 clamp）。

        支持字段（约定名）：
        - max_tool_rounds -> loop.max_rounds
        - step_timeout -> loop.step_timeout
        - preload_workspace_paths -> context.preload_workspace_paths
        - thread_key_state_paths -> context.thread_key_state_paths
        - workspace_read_chunk_chars -> context.workspace_read_chunk_cap
        - tool_result_thread_budget_chars -> context.tool_result_thread_budget
        - catalog_working_set_json -> context.catalog_working_set_json
        - system_prompt_max_identity_chars -> context.system_prompt_max_identity_chars
        - profile_max_chars / profile_truncate_chars -> context.profile_max_chars
        - enable_llm_history -> persistence.enable_llm_history
        - llm_history_max_entries -> persistence.llm_history_max_entries
        """
        raw = kwargs or {}
        if not isinstance(raw, dict) or not raw:
            return cls()

        cfg = cls()

        def _as_int(v: object, default: int) -> int:
            try:
                return int(v)  # type: ignore[arg-type]
            except Exception:
                return default

        def _as_bool(v: object, default: bool = False) -> bool:
            if isinstance(v, bool):
                return v
            if isinstance(v, (int, float)):
                return bool(v)
            s = str(v).strip().lower()
            if s in {"1", "true", "yes", "y", "on"}:
                return True
            if s in {"0", "false", "no", "n", "off"}:
                return False
            return default

        def _as_list_str(v: object) -> list[str]:
            if v is None:
                return []
            if isinstance(v, list):
                return [str(x) for x in v if str(x).strip()]
            if isinstance(v, tuple):
                return [str(x) for x in v if str(x).strip()]
            s = str(v).strip()
            return [s] if s else []

        # loop
        if "max_tool_rounds" in raw:
            cfg.loop.max_rounds = max(
                1, _as_int(raw.get("max_tool_rounds"), cfg.loop.max_rounds)
            )
        if "step_timeout" in raw:
            cfg.loop.step_timeout = max(
                5, _as_int(raw.get("step_timeout"), cfg.loop.step_timeout)
            )

        # context: paths / budgets
        if "preload_workspace_paths" in raw:
            cfg.context.preload_workspace_paths = _as_list_str(
                raw.get("preload_workspace_paths")
            )
        if "thread_key_state_paths" in raw:
            cfg.context.thread_key_state_paths = _as_list_str(
                raw.get("thread_key_state_paths")
            )

        if "workspace_read_chunk_chars" in raw:
            cap = _as_int(
                raw.get("workspace_read_chunk_chars"),
                cfg.context.workspace_read_chunk_cap,
            )
            cfg.context.workspace_read_chunk_cap = max(1024, min(96_000, cap))

        if "tool_result_thread_budget_chars" in raw:
            bud = _as_int(
                raw.get("tool_result_thread_budget_chars"),
                cfg.context.tool_result_thread_budget,
            )
            cfg.context.tool_result_thread_budget = max(4096, min(256_000, bud))

        if "catalog_working_set_json" in raw:
            cfg.context.catalog_working_set_json = _as_bool(
                raw.get("catalog_working_set_json"), False
            )

        if "system_prompt_max_identity_chars" in raw:
            mx = _as_int(
                raw.get("system_prompt_max_identity_chars"),
                cfg.context.system_prompt_max_identity_chars,
            )
            cfg.context.system_prompt_max_identity_chars = max(2000, min(200_000, mx))

        if "profile_max_chars" in raw or "profile_truncate_chars" in raw:
            v = raw.get("profile_max_chars", raw.get("profile_truncate_chars"))
            mx = _as_int(v, cfg.context.profile_max_chars)
            cfg.context.profile_max_chars = max(512, min(200_000, mx))

        # persistence
        if "enable_llm_history" in raw:
            cfg.persistence.enable_llm_history = _as_bool(
                raw.get("enable_llm_history"), cfg.persistence.enable_llm_history
            )
        if "llm_history_max_entries" in raw:
            cfg.persistence.llm_history_max_entries = max(
                0,
                _as_int(
                    raw.get("llm_history_max_entries"),
                    cfg.persistence.llm_history_max_entries,
                ),
            )

        return cfg

    def to_dict(self) -> dict:
        """转换为字典。"""
        import dataclasses

        result = {}
        for name in [
            "model",
            "loop",
            "context",
            "persistence",
            "concurrency",
            "loop_detection",
        ]:
            result[name] = dataclasses.asdict(getattr(self, name))
        return result


# 默认配置实例
DEFAULT_CONFIG = AgentConfig()
