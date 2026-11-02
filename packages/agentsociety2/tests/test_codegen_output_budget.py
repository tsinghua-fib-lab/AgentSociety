"""截断输出不能执行，且必须记录 token 成本并停止无效语法重试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agentsociety2.env.router_codegen import (
    AskContext,
    CodeGenRouter,
    CodeStage,
    LLMCodegenProvider,
)


def _router(finish_reason, content, budget=16384):
    router = CodeGenRouter([], template_cache_enabled=False, max_codegen_tokens=budget)
    router._tools_pyi_dict[(True, None)] = ""
    router._tools_pyi_dict[(True, "observe")] = ""
    router._code_provider_chain = [LLMCodegenProvider()]
    router.acompletion_with_system_prompt = AsyncMock(
        return_value=SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=finish_reason,
                    message=SimpleNamespace(content=content),
                )
            ],
            usage=SimpleNamespace(prompt_tokens=120, completion_tokens=4096),
        )
    )
    return router


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content", [None, "```python\nresults['status'] = 'success'\n```"]
)
async def test_truncation_never_executes_even_syntactically_valid_code(
    monkeypatch, content
):
    router = _router("length", content)
    execute = AsyncMock()
    monkeypatch.setattr(CodeStage, "_execute_code", execute)
    ctx = AskContext(
        ctx={}, instruction="read state", readonly=True, template_mode=False
    )
    result = await CodeStage().process(ctx, router)
    assert result.early_return[0]["status"] == "error"
    assert "finish_reason=length" in result.early_return[1]
    assert result.token_usage_responses == [
        {"input_tokens": 120, "output_tokens": 4096}
    ]
    router.acompletion_with_system_prompt.assert_awaited_once()
    execute.assert_not_awaited()
    assert not result.execution_attempted


@pytest.mark.asyncio
async def test_initialization_truncation_preserves_cost_and_fails_without_retry(
    monkeypatch,
):
    router = _router("length", "results = {}")
    execute = AsyncMock()
    monkeypatch.setattr(CodeStage, "_execute_code", execute)
    with pytest.raises(ValueError, match="finish_reason=length"):
        await router._generate_initialization_code_with_retry("observe", {}, "observe")
    assert router._cache_stats.total_input_tokens == 120
    assert router._cache_stats.total_output_tokens == 4096
    router.acompletion_with_system_prompt.assert_awaited_once()
    execute.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [8192, 16384])
async def test_complete_code_uses_explicit_configured_budget(budget):
    router = _router("stop", "```python\nresults['status'] = 'success'\n```", budget)
    ctx = AskContext(
        ctx={}, instruction="read state", readonly=True, template_mode=False
    )
    code = await LLMCodegenProvider().get_code(ctx, router)
    assert code == "results['status'] = 'success'"
    assert ctx.codegen_error is None
    assert (
        router.acompletion_with_system_prompt.await_args.kwargs["max_tokens"] == budget
    )


def test_codegen_budget_must_be_positive():
    with pytest.raises(ValueError, match="max_codegen_tokens"):
        CodeGenRouter([], max_codegen_tokens=0)
