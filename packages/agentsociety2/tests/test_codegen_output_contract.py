"""Common valid model formatting must not trigger another paid generation."""

import pytest

from agentsociety2.env.router_codegen import (
    CodeGenRouter,
    CodeStage,
    _strip_code_fence,
)


@pytest.mark.parametrize(
    "source",
    [
        "results['status'] = 'success'\nprint('done')",
        "results['status'] = 'success'\nresults['counter'] = 7\nprint('done')",
        "if ctx['ok']:\n    results['status'] = 'success'\n    print('ok')\nelse:\n    results['status'] = 'fail'\n    results['reason'] = 'fixture failure'\n    print('failed')",
        "try:\n    results['value'] = 1\n    results['status'] = 'success'\nexcept Exception as exc:\n    results['status'] = 'error'\n    results['reason'] = str(exc)\nprint('finished')",
        "try:\n    value = 1\nexcept Exception:\n    results['status'] = 'error'\nelse:\n    results['status'] = 'success'\nprint('finished')",
        "try:\n    value = 1\nfinally:\n    results['status'] = 'success'\nprint('finished')",
        "results['status'] = 'success'\nif ctx['ok']:\n    results['value'] = 1\nprint('finished')",
    ],
)
def test_structured_output_classification_is_accepted(source):
    safe, reason = CodeStage._validate_code_safety(CodeGenRouter, source)
    assert safe, reason


@pytest.mark.parametrize(
    "source",
    [
        "print('no result classification')",
        "results['status']: str",
        "if ctx['ok']:\n    results['status'] = 'success'\nprint('incomplete branch')",
        "try:\n    results['status'] = 'success'\nexcept Exception:\n    print('unclassified failure')",
        "for value in []:\n    results['status'] = 'success'\nprint('zero iterations')",
        "def classify():\n    results['status'] = 'success'\nprint('function never called')",
        "results['status'] = 'success'\nresults = {}\nprint('classification erased')",
        "results['status'] = 'success'\ndef results():\n    pass",
    ],
)
def test_unclassified_paths_are_still_rejected_before_execution(source):
    safe, reason = CodeStage._validate_code_safety(CodeGenRouter, source)
    assert not safe
    assert "results['status']" in reason


@pytest.mark.parametrize("status", ["unknown", " UNKNOWN ", "", None, 17])
async def test_actual_dynamic_classification_is_checked_after_execution(status):
    instance = CodeGenRouter(env_modules=[], final_summary_enabled=False)
    result = await CodeStage._execute_code(
        instance,
        "results['status'] = ctx['outcome']\nprint('done')",
        {"outcome": status},
        True,
    )
    assert not result["success"]
    assert "classified" in result["error"]


async def test_alias_mutation_cannot_erase_status_and_still_report_execution_success():
    instance = CodeGenRouter(env_modules=[], final_summary_enabled=False)
    source = (
        "alias = results\nresults['status'] = 'success'\nalias.clear()\nprint('done')"
    )
    result = await CodeStage._execute_code(instance, source, {}, True)
    assert not result["success"]
    assert "classified" in result["error"]


async def test_valid_try_except_executes_once_and_retains_classification():
    instance = CodeGenRouter(env_modules=[], final_summary_enabled=False)
    source = "try:\n    results['value'] = sum(ctx['values'])\n    results['status'] = 'success'\nexcept Exception as exc:\n    results['status'] = 'error'\n    results['reason'] = str(exc)\nprint('done')"
    result = await CodeStage._execute_code(
        instance, source, {"values": [1, 2, 3]}, True
    )
    assert result["success"] and result["results"] == {"value": 6, "status": "success"}
    assert result["print_outputs"] == ["done"]


@pytest.mark.parametrize("opening", ["```python", "```py", "```Python", "```"])
@pytest.mark.parametrize("closing", ["", "\n```"])
def test_python_fence_opener_does_not_require_a_closing_marker(opening, closing):
    code = "results['status'] = 'success'"
    assert _strip_code_fence(opening + "\n" + code + closing) == code


def test_unsupported_fence_language_remains_invalid_python():
    text = '```json\n{"value": 1}\n```'
    assert _strip_code_fence(text) == text


@pytest.mark.parametrize("finish_reason", ["stop", "length"])
async def test_actual_codegen_parser_preserves_truncation_guard_with_open_fence(
    finish_reason,
):
    from types import SimpleNamespace

    from agentsociety2.env.router_codegen import LLMCodegenProvider

    code = "results['status'] = 'success'"
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason=finish_reason,
                message=SimpleNamespace(content="```python\n" + code),
            )
        ],
        usage=None,
    )

    async def completion(**kwargs):
        return response

    instance = SimpleNamespace(
        acompletion_with_system_prompt=completion, max_codegen_tokens=4096
    )
    context = SimpleNamespace(dialog_history=[], codegen_error=None)
    parsed, _ = await LLMCodegenProvider._call_llm(instance, context)
    if finish_reason == "length":
        assert parsed == "" and "truncated" in context.codegen_error
    else:
        assert parsed == code
        assert CodeStage._validate_code_safety(CodeGenRouter, parsed) == (True, "")


@pytest.mark.parametrize(
    "binding",
    [
        "results = {}",
        "results: dict = {}",
        "results, other = {}, 1",
        "(results := {})",
        "for results in []:\n    pass",
        "import math as results",
        "from math import sqrt as results",
        "try:\n    value = 1\nexcept Exception as results:\n    pass",
        "def results():\n    pass",
        "del results",
    ],
)
def test_result_container_cannot_be_rebound_before_terminal_assignment(binding):
    safe, reason = CodeStage._validate_code_safety(
        CodeGenRouter, binding + "\nresults['status'] = 'success'"
    )
    assert not safe and "Rebinding results" in reason


@pytest.mark.parametrize("asynchronous", [False, True])
async def test_result_rebinding_is_rejected_before_mutating_tools(asynchronous):
    calls = []

    class Tool:
        def touch(self):
            calls.append("effect")

        async def atouch(self):
            calls.append("effect")

    instance = CodeGenRouter(env_modules=[], final_summary_enabled=False)
    instance._modules = {"Tool": Tool()}
    statement = (
        "await modules['Tool'].atouch()" if asynchronous else "modules['Tool'].touch()"
    )
    result = await CodeStage._execute_code(
        instance,
        "results = {}\n" + statement + "\nresults['status'] = 'success'",
        {},
        False,
    )
    assert not result["success"] and "Rebinding results" in result["error"]
    assert calls == []


@pytest.mark.parametrize("closing", ["", "\n```"])
def test_explanation_before_python_fence_uses_the_single_normalizer(closing):
    code = "results['counter'] = 7\nresults['status'] = 'success'"
    text = (
        "# Analysis\nThe status assignment must remain present.\n\n```python\n"
        + code
        + closing
    )
    assert _strip_code_fence(text) == code


def test_valid_python_with_markdown_string_data_is_preserved():
    code = 'message = """Example:\n```python\nvalue = 1\n```\n"""\nresults["status"] = "success"'
    assert _strip_code_fence(code) == code


def test_explanation_with_unsupported_fence_stays_invalid_python():
    text = 'Here is JSON:\n```json\n{"value": 1}\n```'
    assert _strip_code_fence(text) == text
