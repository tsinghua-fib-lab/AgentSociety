"""ReAct 循环基础数据结构与脚手架。

中文：提供 ReAct 循环的数据结构（``ReactDecision`` / ``ReactToolResult`` ）。
English: Provides the ReAct loop data structures (``ReactDecision`` / ``ReactToolResult``).

具体的 ReAct 循环编排(消息构建、LLM 调度、工具执行)位于 agent 子类及其
支撑模块(``person_prompt.py`` 、``person_tools.py``)。本模块只持有共享的
dataclass,使基础工具分发与 person 专属 react 循环引用同一份规范定义。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

__all__ = [
    "ReactDecision",
    "ReactToolResult",
    "ReactTurn",
]


@dataclass(frozen=True)
class ReactDecision:
    """一条解析后的 ReAct 工具决策。

    :param action: 工具/动作名。
    :param args: 解析出的工具参数。
    :param final: 动作为 ``finish`` 时的最终文本。
    :param call_id: 该决策对应的 provider tool-call id。当决策来自文本
        解析回退(以文本而非原生 tool call 形式发出调用的模型)时为空——
        该路径没有 id。ReAct 循环会在 ``role: "tool"`` 回复中原样回填,使
        原生轮次的 id 逐一得到应答,下一个请求保持有效。
    """

    action: str
    args: dict[str, Any]
    final: str
    call_id: str = ""


@dataclass(frozen=True)
class ReactTurn:
    """一次 ReAct 补全:解析出的内容与待追加进线程的内容。

    循环会追加 ``assistant_message``(其后跟随工具回复,或 ``error`` 置位
    时跟随错误文本),使每个请求都是前一个请求的严格前缀扩展——正因如此,
    provider 的 prompt-prefix 缓存才能跨轮增长而非每轮重置。

    :param decisions: 解析出的决策(响应不可用时为空)。
    :param error: schema/解析错误文本;轮次干净时为 ``""`` 。
    :param assistant_message: 待追加的规范化 assistant 消息;provider 未
        返回任何可追加内容(无 choices / 无 content)时为 ``None`` 。
    """

    decisions: list[ReactDecision]
    error: str
    assistant_message: dict[str, Any] | None = None


@dataclass(frozen=True)
class ReactToolResult:
    """一次 ReAct 工具分发的返回结果。

    :param ok: 工具调用是否成功。
    :param observation: 展示给下一个 ReAct 轮次的文本。
    :param data: 供 tracing 与测试使用的结构化结果数据。
    """

    ok: bool
    observation: str
    data: dict[str, Any]
