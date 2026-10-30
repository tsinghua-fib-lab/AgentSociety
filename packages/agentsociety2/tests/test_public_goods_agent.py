from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from agentsociety2.contrib.agent.public_goods_agent import PublicGoodsAgent


def _agent() -> PublicGoodsAgent:
    agent = PublicGoodsAgent()
    agent._name = "Alice"
    agent._profile = {"name": "Alice", "personality": "cooperative"}
    agent.num_rounds = 2
    agent.num_agents = 2
    agent.initial_endowment = 20
    agent.public_pool_multiplier = 1.6
    agent.min_contribution = 0
    agent.max_contribution = 20
    agent.history = []
    return agent


def test_contribution_decision_requests_a_bounded_response() -> None:
    agent = _agent()
    request: dict = {}

    async def completion(messages, **kwargs):
        request.update(kwargs)
        message = SimpleNamespace(content="12 - Support the shared fund.")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    agent.acompletion = completion  # type: ignore[method-assign]
    contribution, explanation = asyncio.run(agent._decide_contribution(1, []))

    assert contribution == 12
    assert explanation == "Support the shared fund."
    assert request["max_tokens"] == 2048


@pytest.mark.parametrize(
    ("content", "finish_reason"), [("", "stop"), ("20 - incomplete", "length")]
)
def test_incomplete_decision_is_retried_before_parsing(content, finish_reason):
    agent = _agent()
    budgets = []

    async def completion(messages, **kwargs):
        budgets.append(kwargs["max_tokens"])
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=content if len(budgets) == 1 else "12 - Cooperate."
                    ),
                    finish_reason=finish_reason if len(budgets) == 1 else "stop",
                )
            ]
        )

    agent.acompletion = completion  # type: ignore[method-assign]
    assert asyncio.run(agent._decide_contribution(1, [])) == (12, "Cooperate.")
    assert budgets == [2048, 4096]


def test_empty_decisions_fail_after_bounded_retries_without_a_default_contribution():
    agent = _agent()
    budgets = []

    async def completion(messages, **kwargs):
        budgets.append(kwargs["max_tokens"])
        return SimpleNamespace(choices=[])

    agent.acompletion = completion  # type: ignore[method-assign]
    with pytest.raises(
        RuntimeError, match="empty or truncated responses after 3 attempts"
    ):
        asyncio.run(agent._decide_contribution(1, []))
    assert budgets == [2048, 4096, 8192]
