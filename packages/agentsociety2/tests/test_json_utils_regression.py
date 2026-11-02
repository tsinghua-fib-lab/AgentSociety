"""Broader regression for LLM JSON parsing (clean identity + AS2 surfaces)."""

from __future__ import annotations

import json

import pytest

from agentsociety2.agent.json_utils import jr_or_json, jr_parse_from_llm, loads_llm_json

CLEAN_OBJECTS = [
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
