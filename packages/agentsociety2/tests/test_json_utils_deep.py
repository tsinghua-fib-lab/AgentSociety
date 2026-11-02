"""Behavioral regressions for hybrid LLM JSON parsing."""

from __future__ import annotations

import json

import pytest

from agentsociety2.agent.json_utils import loads_llm_json


def _usable_tool(obj) -> bool:
    if isinstance(obj, list):
        return any(_usable_tool(x) for x in obj)
    if not isinstance(obj, dict):
        return False
    name_ok = any(k in obj for k in ("name", "tool", "function"))
    args_ok = any(k in obj for k in ("arguments", "args", "parameters"))
    if name_ok and args_ok:
        return True
    ans = obj.get("answer")
    return ans is not None and ans != ""


def test_clean_identity_bulk() -> None:
    payloads = [
        {"name": "ask_env", "arguments": {"question": "x", "readonly": True}},
        {"answer": "hello"},
        {"plan": ["a", "b"], "answer": None},
        {"rows": [{"i": 1}, {"i": 2}]},
        [1, 2, {"k": "v"}],
        {"nested": {"a": {"b": [True, False, None]}}},
    ]
    for obj in payloads:
        text = json.dumps(obj, ensure_ascii=False)
        assert loads_llm_json(text) == obj


def test_refuse_common_prose() -> None:
    for text in (
        "抱歉，我无法调用工具。",
        "TODO: implement answer later",
        "Note: please try again later",
        "I cannot help with that request.",
    ):
        with pytest.raises(ValueError):
            loads_llm_json(text)


def test_fatal_truncation_not_usable_tool() -> None:
    """Even if a fragment object is produced, it must not look like a tool call."""
    try:
        out = loads_llm_json('{"na')
    except ValueError:
        return
    assert not _usable_tool(out)
