"""Codegen examples must satisfy the guard; truncated output cannot execute."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentsociety2.env.router_codegen import (
    AskContext,
    CodeGenRouter,
    CodeStage,
    LLMCodegenProvider,
)


def test_prompt_example_passes_the_same_safety_check_as_generated_code():
    router = SimpleNamespace(_tools_pyi_dict={(True, None): ""}, _modules={})
    prompt = LLMCodegenProvider._build_prompt(router, "Observe", {}, True)
    example = prompt.split(
        "## Example (imitate the print style, not the exact tools)\n", 1
    )[1]
    example = example.split("\nYour generated code:", 1)[0]
    assert CodeStage._validate_code_safety(CodeGenRouter, example) == (True, "")


@pytest.mark.asyncio
async def test_truncated_code_is_discarded_and_correction_has_room_to_finish():
    code = "print('Ready')\nresults['status'] = 'success'"

    def response(finish_reason):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=code), finish_reason=finish_reason
                )
            ],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=8192),
        )

    router = SimpleNamespace(
        acompletion_with_system_prompt=AsyncMock(
            side_effect=[response("length"), response("stop")]
        )
    )
    ctx = AskContext(ctx={}, instruction="Observe", readonly=True, template_mode=False)
    result, usage = await LLMCodegenProvider._call_llm(router, ctx)
    assert result == ""
    assert usage == {"input_tokens": 100, "output_tokens": 8192}
    ctx.retry_count = 1
    result, _ = await LLMCodegenProvider._call_llm(router, ctx)
    assert result == code
    assert [
        call.kwargs["max_tokens"]
        for call in router.acompletion_with_system_prompt.call_args_list
    ] == [8192, 16384]
