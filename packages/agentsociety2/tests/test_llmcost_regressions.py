"""Regressions found during repeated main/llmcost comparisons."""

import json
from types import SimpleNamespace

import pytest

from agentsociety2.agent.json_utils import loads_llm_json
from agentsociety2.env.router_codegen import (
    AskContext,
    CodeGenRouter,
    CodeStage,
    SummaryStage,
)


@pytest.mark.parametrize(
    "value",
    [
        "literal <think>keep this</think> text",
        'example: ```json\n{"nested": 1}\n```',
        '<tool_call>{"name":"read"}</tool_call>',
        "<|im_start|>assistant",
    ],
)
def test_clean_json_preserves_protocol_like_string_contents(value):
    expected = {"message": value}
    assert loads_llm_json(json.dumps(expected)) == expected


@pytest.mark.parametrize("value", ["北京", "hello", 'say "hello"', "a\\b", "two words"])
def test_missing_comma_preserves_complete_string_values(value):
    text = '{"message":' + json.dumps(value) + ' "receiver_id":2}'
    assert loads_llm_json(text) == {"message": value, "receiver_id": 2}


@pytest.mark.parametrize(
    "body",
    [
        'print("unknown")',
        'name = ctx.get("sender_name", "unknown")\nprint(name)',
        'results["location"] = "unknown"\nprint("Location unavailable")',
    ],
)
def test_unknown_business_data_does_not_reject_successful_code(body):
    code = body + '\nresults["status"] = "success"'
    assert CodeStage._validate_code_safety(CodeGenRouter, code) == (True, "")


@pytest.mark.parametrize(
    "code",
    [
        'results["status"] = "unknown"',
        'outcome = "unknown"\nresults["status"] = outcome',
    ],
)
def test_unknown_execution_status_remains_invalid(code):
    valid, reason = CodeStage._validate_code_safety(CodeGenRouter, code)
    assert not valid
    assert "unknown" in reason


async def test_dynamic_unknown_status_still_fails_without_summary():
    from datetime import datetime

    router = SimpleNamespace(_final_summary_enabled=False, t=datetime(2026, 11, 2))
    context = AskContext(ctx={}, instruction="read", readonly=True, template_mode=False)
    context.success_data = {
        "results": {"status": "unknown"},
        "status": "unknown",
        "process_text": "",
    }
    result = await SummaryStage().process(context, router)
    assert result.results["status"] == "fail"


def test_memory_consolidation_public_import_remains_compatible():
    from agentsociety2.agent import MemoryConsolidationResult

    assert (
        MemoryConsolidationResult(memory_md="  remember this  ").memory_md
        == "remember this"
    )
