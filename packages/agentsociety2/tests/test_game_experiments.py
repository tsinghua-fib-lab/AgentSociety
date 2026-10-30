"""Game experiment entry points use strict workspace and settlement contracts."""

from datetime import datetime
from types import SimpleNamespace

import pytest

from agentsociety2.config.llm_dispatcher import LLMClient
from agentsociety2.contrib.agent.commons_tragedy_agent import CommonsTragedyAgent
from agentsociety2.contrib.env.trust_game import TrustGameEnv
from experiments._games import GAMES, game_configuration


def test_every_game_builds_explicit_workspace_specs():
    for game in GAMES:
        count = 2 if game in {"prisoners_dilemma", "trust_game"} else 4
        env, specs = game_configuration(game, count, rounds=3)
        assert env
        assert [spec["id"] for spec in specs] == list(range(1, count + 1))
        assert all(spec["profile"]["name"] for spec in specs)
        assert all(spec["config"]["num_rounds"] == 3 for spec in specs)


def test_games_reject_invalid_player_counts():
    with pytest.raises(ValueError, match="exactly two"):
        game_configuration("prisoners_dilemma", 3, rounds=1)
    with pytest.raises(ValueError, match="even number"):
        game_configuration("trust_game", 3, rounds=1)


@pytest.mark.asyncio
async def test_trust_game_requires_both_explicit_decisions():
    env = TrustGameEnv(num_pairs=1, initial_funds=10, multiplication_factor=3)
    env.set_partner_mapping(
        {"Alice_Trustor_G1": "Bob_Trustee_G1", "Bob_Trustee_G1": "Alice_Trustor_G1"}
    )
    await env.init(datetime.now())

    with pytest.raises(ValueError, match="Wait for"):
        await env.submit_return("Bob_Trustee_G1", 0)
    with pytest.raises(ValueError, match="Unknown trustor"):
        await env.submit_investment("Alice", 5)
    with pytest.raises(ValueError, match="between zero"):
        await env.submit_investment("Alice_Trustor_G1", 11)

    await env.submit_investment("Alice_Trustor_G1", 5)
    await env.step(1, datetime.now())
    assert env.round_history == []
    await env.submit_return("Bob_Trustee_G1", 4)
    await env.step(1, datetime.now())
    assert env.round_history[0]["trustor_investments"] == {"Alice_Trustor_G1": 5}
    assert env.round_history[0]["trustee_returns"] == {"Bob_Trustee_G1": 4}


def test_llm_client_repr_never_contains_api_key():
    client = LLMClient("model", "https://example.test/v1", "top-secret")
    assert "top-secret" not in repr(client)


@pytest.mark.asyncio
async def test_completion_text_retries_empty_responses_without_default_action():
    agent = CommonsTragedyAgent()
    agent._name = "Agent A"
    responses = iter(
        [
            SimpleNamespace(choices=[]),
            SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=""))]),
            SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="valid decision"))]
            ),
        ]
    )

    async def complete(*args, **kwargs):
        return next(responses)

    agent.acompletion = complete
    assert await agent._completion_text([]) == "valid decision"
