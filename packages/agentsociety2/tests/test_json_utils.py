"""Tests for hybrid LLM JSON parsing."""

from __future__ import annotations

import pytest

from agentsociety2.agent.json_utils import loads_llm_json


def test_clean_object() -> None:
    assert loads_llm_json('{"a": 1, "b": true}') == {"a": 1, "b": True}


def test_markdown_fence_and_prose() -> None:
    text = '好的：\n```json\n{"name":"ask_env","arguments":{"question":"气温"}}\n```\n完成'
    assert loads_llm_json(text) == {
        "name": "ask_env",
        "arguments": {"question": "气温"},
    }


def test_hermes_parallel_tags() -> None:
    text = (
        '<tool_call>\n{"name":"ask_env","arguments":{"q":"a"}}\n</tool_call>\n'
        '<tool_call>\n{"name":"workspace_ls","arguments":{"path":"."}}\n</tool_call>'
    )
    out = loads_llm_json(text)
    assert isinstance(out, list)
    assert out[0]["name"] == "ask_env"
    assert out[1]["name"] == "workspace_ls"


def test_trailing_comma_and_py_true() -> None:
    text = '{"name":"ask_env","arguments":{"readonly":True,},}'
    out = loads_llm_json(text)
    assert out["name"] == "ask_env"
    assert out["arguments"]["readonly"] is True


def test_tool_alias_normalization() -> None:
    text = '{"tool":"ask_env","args":{"question":"x"}}'
    assert loads_llm_json(text) == {
        "name": "ask_env",
        "arguments": {"question": "x"},
    }


def test_plan_step_tool_key_preserved() -> None:
    text = (
        '{"steps":[{"op":"call","tool":"observe","kwargs":{"agent_id":1}}],'
        '"rationale":"ok"}'
    )
    out = loads_llm_json(text)
    assert out["steps"][0]["tool"] == "observe"
    assert "name" not in out["steps"][0]


def test_args_double_encoded_string() -> None:
    text = '{"name":"ask_env","arguments":"{\\"question\\":\\"气温\\"}"}'
    out = loads_llm_json(text)
    assert out["arguments"] == {"question": "气温"}


def test_sse_data_prefix() -> None:
    text = 'data: {"name":"ask_env","arguments":{"question":"雨"}}\n\ndata: [DONE]'
    out = loads_llm_json(text)
    assert out["name"] == "ask_env"


def test_finish_call_wrapper() -> None:
    text = 'finish({"answer": "先走地铁"})'
    assert loads_llm_json(text) == {"answer": "先走地铁"}


def test_invoke_xml() -> None:
    text = (
        '<invoke name="ask_env">\n'
        '<parameter name="question">风速</parameter>\n'
        '<parameter name="readonly">true</parameter>\n'
        "</invoke>"
    )
    out = loads_llm_json(text)
    assert out["name"] == "ask_env"
    assert out["arguments"]["question"] == "风速"
    assert out["arguments"]["readonly"] is True


def test_refuse_prose() -> None:
    with pytest.raises(ValueError):
        loads_llm_json("抱歉，我无法调用工具。")


def test_expect_object_rejects_array() -> None:
    with pytest.raises(ValueError):
        loads_llm_json("[1,2,3]", expect="object")
