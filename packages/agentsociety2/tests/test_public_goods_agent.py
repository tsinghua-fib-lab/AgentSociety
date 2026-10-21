from __future__ import annotations

import asyncio
from types import SimpleNamespace

from agentsociety2.contrib.agent.public_goods_agent import PublicGoodsAgent


def test_contribution_decision_requests_a_bounded_response() -> None:
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
