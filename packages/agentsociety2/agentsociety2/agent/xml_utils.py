"""Agent XML 工具。

中文:当前 Agent 运行时使用的轻量 XML 标签提取工具,与 ``json_utils`` 平行。
English: Lightweight XML tag extraction helpers for the agent runtime,
parallel to ``json_utils``.
"""

from __future__ import annotations

import re


def extract_xml_tag_value(
    text: str,
    tag: str,
    value_pattern: str = r".*?",
    *,
    dotall: bool = False,
) -> str | None:
    """提取文本中第一处 ``<tag>值</tag>`` 的值。

    供 LLM 输出的结构化 XML 标签解析复用(如博弈 agent 的
    ``<action>`` / ``<extraction>`` / ``<explanation>``),替代各 agent
    手写同构正则。标签名大小写不敏感;值可为多行文本时传
    ``dotall=True`` 。

    :param text: 待解析的原始文本,通常是一段 LLM 输出。
    :param tag: 标签名,不含尖括号,如 ``"action"`` 。
    :param value_pattern: 值的正则片段,整组捕获。默认 ``".*?"`` 匹配
        任意非贪婪内容(含空串);枚举值场景传形如 ``"Yes|No"`` 。
    :param dotall: 是否允许值跨行(``re.DOTALL``)。解释类长文本应为
        ``True`` 。
    :returns: 首个匹配的值(已去除首尾空白);未命中返回 ``None``,
        由调用方决定回退策略。
    """
    flags = re.IGNORECASE | (re.DOTALL if dotall else 0)
    match = re.search(
        rf"<{tag}>\s*({value_pattern})\s*</{tag}>",
        text,
        flags,
    )
    if match is None:
        return None
    return match.group(1).strip()
