"""PersonAgent 专属的工具 schema。

中文：集中定义 PersonAgent 专属的记忆抽取 / 合并 OpenAI function/tool schema。
English: Defines PersonAgent-specific memory extraction / consolidation
OpenAI function/tool schemas.

通用 ReAct 工具 schema（``react_tool_schemas`` / ``readonly_tool_names`` ）
已移至 :mod:`agentsociety2.agent.base.tool_schema` 。
Generic ReAct tool schemas (``react_tool_schemas`` / ``readonly_tool_names``)
have moved to :mod:`agentsociety2.agent.base.tool_schema`.
"""

from __future__ import annotations

from typing import Any

from agentsociety2.agent.memory import MemoryEpisodeType


def memory_episode_item_schema() -> dict[str, Any]:
    """单条记忆 episode 的 JSON schema。

    供 step 模式 ``finish`` 工具的 ``memories`` 参数使用
    (:func:`finish_step_tool_schema`)。

    :returns: 单个 episode 对象的 JSON schema dict。
    """
    episode_types = list(MemoryEpisodeType.__args__)
    return {
        "type": "object",
        "properties": {
            "type": {
                "type": "string",
                "enum": episode_types,
                "description": "Episode category; consolidation keys on this.",
            },
            "importance": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Salience in [0,1]; high values trigger consolidation.",
            },
            "keywords": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 12,
                "default": [],
            },
            "text": {
                "type": "string",
                "minLength": 1,
                "maxLength": 1000,
            },
            "source": {
                "type": "string",
                "maxLength": 80,
                "default": "step_result",
            },
            "refs": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 8,
                "default": [],
            },
        },
        "required": ["text", "type", "importance"],
        "additionalProperties": False,
    }


def finish_ask_tool_schema() -> dict[str, Any]:
    """ask / readonly 模式的 ``finish`` 工具:仅含答案。

    PersonAgent 在 ask 模式下用此 schema 覆盖基类 ``finish``,使模型只能返回
    外部答案(没有 ``final`` / ``memories``)。

    :returns: ask 模式 ``finish`` 的工具 schema dict。
    """
    return {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "End this external question and return your complete answer. This "
                "is the ONLY accepted way to deliver an answer — never write the "
                "answer as free assistant text and never reply with bare words "
                'like "done". Put the full answer (including any requested '
                "JSON/choice, copied verbatim) in a non-empty `answer`."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "Complete answer returned to the caller.",
                    },
                },
                "required": ["answer"],
                "additionalProperties": False,
            },
        },
    }


def finish_step_tool_schema() -> dict[str, Any]:
    """step 模式的 ``finish`` 工具:仅内联 step 记忆。

    PersonAgent 在 step 模式下用此 schema 覆盖基类 ``finish`` 。step 的结果
    完全以记忆 episode 形式记入 ``memories``(没有单独的 ``final`` 文本、也
    没有单独的抽取流程),因此 ``memories`` 是唯一必填参数;仅当本 tick 没有
    值得记录的事情时才传空列表。

    :returns: step 模式 ``finish`` 的工具 schema dict。
    """
    return {
        "type": "function",
        "function": {
            "name": "finish",
            "description": (
                "End this simulation step by recording the durable memory points "
                "worth keeping from this step in `memories` (key decisions, "
                "events, observations, intentions). Memory generation happens "
                "here — there is no separate memory pass — so `memories` MUST "
                "contain at least one item. An empty list is invalid and will be "
                "rejected; if nothing notable happened, still record one brief "
                "observation episode summarizing the step."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "memories": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 8,
                        "items": memory_episode_item_schema(),
                        "description": (
                            "Durable memory points extracted from this step. "
                            "Must be non-empty (at least one episode)."
                        ),
                    },
                },
                "required": ["memories"],
                "additionalProperties": False,
            },
        },
    }
