"""LLM JSON parsing and tool-call normalization."""

from __future__ import annotations

import json

import pytest

from agentsociety2.agent.json_utils import jr_or_json, jr_parse_from_llm, loads_llm_json

CLEAN_OBJECTS = [
    {"a": 1, "b": True},
    {"name": "ask_env", "arguments": {"question": "天气", "readonly": True}},
    {"answer": "ok"},
    {"qid": "Q1", "choice": "A", "confidence": 0.9},
    {"steps": [{"op": "call", "tool": "observe", "kwargs": {"agent_id": 1}}]},
    {"rows": [{"aoi": "A1", "flow": 10}]},
]


@pytest.mark.parametrize("obj", CLEAN_OBJECTS)
def test_clean_json_roundtrip_identity(obj: dict) -> None:
    text = json.dumps(obj, ensure_ascii=False)
    assert loads_llm_json(text) == obj
    assert jr_or_json(text) == obj
    assert jr_parse_from_llm(text) == obj


def test_native_fragment_trailing_comma() -> None:
    assert loads_llm_json('{"question":"x","readonly":true,}') == {
        "question": "x",
        "readonly": True,
    }


def test_think_tag_then_tool() -> None:
    text = '<think>need readonly</think>\n{"name":"ask_env","arguments":{"question":"湿度","readonly":true}}'
    out = loads_llm_json(text)
    assert out["name"] == "ask_env"
    assert out["arguments"]["readonly"] is True


def test_chatml_noise() -> None:
    text = '<|im_start|>assistant\n{"name":"workspace_ls","arguments":{"path":"."}}\n<|im_end|>'
    assert loads_llm_json(text)["name"] == "workspace_ls"


def test_single_quotes_py_literals() -> None:
    text = "{'name': 'ask_env', 'arguments': {'question': '能见度', 'readonly': True}}"
    out = loads_llm_json(text)
    assert out["arguments"]["readonly"] is True


def test_jsonc_comments() -> None:
    text = '{\n  // tool\n  "name": "ask_env",\n  "arguments": {"question": "紫外线", "readonly": true}\n}'
    assert loads_llm_json(text)["name"] == "ask_env"


def test_array_batch_tools() -> None:
    text = (
        '[{"name":"ask_env","arguments":{"question":"q1","readonly":true}},'
        '{"name":"ask_env","arguments":{"question":"q2","readonly":true}}]'
    )
    out = loads_llm_json(text)
    assert isinstance(out, list) and len(out) == 2


def test_unrecoverable_empty_and_todo() -> None:
    for bad in (
        "",
        "   ",
        "TODO: implement answer later",
        "今天天气不错，我们聊点别的吧。",
    ):
        with pytest.raises(ValueError):
            loads_llm_json(bad)


def test_expect_array() -> None:
    assert loads_llm_json("[1, 2]", expect="array") == [1, 2]
    with pytest.raises(ValueError):
        loads_llm_json('{"a":1}', expect="array")


def test_mixed_fence_single_quote_trailing() -> None:
    text = "```json\n{'name': 'ask_env', 'arguments': {'question': '混合', 'readonly': True,},}\n```"
    out = loads_llm_json(text)
    assert out == {
        "name": "ask_env",
        "arguments": {"question": "混合", "readonly": True},
    }


def test_function_alias() -> None:
    text = '{"function":"activate_skill","arguments":{"skill":"daily-guidance"}}'
    assert loads_llm_json(text) == {
        "name": "activate_skill",
        "arguments": {"skill": "daily-guidance"},
    }


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


def test_fatal_truncation_not_usable_tool() -> None:
    """截断的片段即使被解析出来，也不能伪装成可执行的工具调用。"""
    try:
        out = loads_llm_json('{"na')
    except ValueError:
        return
    if isinstance(out, dict):
        assert not (
            any(key in out for key in ("name", "tool", "function"))
            and any(key in out for key in ("arguments", "args", "parameters"))
        )
    else:
        assert out is not None
