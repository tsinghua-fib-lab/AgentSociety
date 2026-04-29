"""轻量 ContextConfig（面向测试与阈值计算）。

该模块提供一个与 agent 上下文窗口治理相关的最小配置对象，主要用于 token 估算、
压缩阈值判断等纯函数逻辑的参数承载。

说明：本仓库不追求向后兼容；此模块的字段以测试与当前实现需要为准。
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_CONTEXT_WINDOW = 200_000


def get_model_context_window(model: str | None) -> int:
    """根据模型名返回上下文窗口大小（tokens）。

    :param model: LiteLLM 路由模型名。
    :returns: 上下文窗口大小（tokens）。
    """
    if not model:
        return DEFAULT_CONTEXT_WINDOW
    m = str(model).lower()
    # 主流：gpt-4o 128k（用于测试）
    if "gpt-4o" in m:
        return 128_000
    return DEFAULT_CONTEXT_WINDOW


@dataclass
class ContextConfig:
    """上下文阈值配置。"""

    model: str = ""

    # window split
    model_context_window: int = DEFAULT_CONTEXT_WINDOW
    output_reserve: int = 16_000
    prompt_overhead: int = 8_000

    # compaction ratios
    compact_warning_ratio: float = 0.60
    compact_trigger_ratio: float = 0.70
    compact_auto_ratio: float = 0.85
    compact_block_ratio: float = 0.95

    # circuit breaker
    max_retries: int = 3
    backoff: float = 2.0

    # thread defaults (用于测试)
    thread_max_messages: int = 40
    thread_compact_keep_recent: int = 6

    # summary defaults (用于测试)
    summary_char_budget: int = 6000
    summary_msg_limit: int = 1600

    def __post_init__(self) -> None:
        if self.model:
            self.model_context_window = get_model_context_window(self.model)

    @property
    def effective_window(self) -> int:
        """可用上下文窗口（扣除输出预留与 prompt 开销）。"""
        return self.model_context_window - self.output_reserve - self.prompt_overhead
