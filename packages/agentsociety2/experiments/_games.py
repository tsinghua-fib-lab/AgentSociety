"""Run game experiments through the same Ray/workspace contract as the CLI."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from datetime import datetime
from pathlib import Path

from agentsociety2.env import create_env_router_proxy
from agentsociety2.society import AgentSociety

GAMES = {
    "commons_tragedy": ("CommonsTragedyEnv", "CommonsTragedyAgent"),
    "prisoners_dilemma": ("PrisonersDilemmaEnv", "PrisonersDilemmaAgent"),
    "public_goods": ("PublicGoodsEnv", "PublicGoodsAgent"),
    "trust_game": ("TrustGameEnv", "TrustGameAgent"),
    "volunteer_dilemma": ("VolunteerDilemmaEnv", "VolunteerDilemmaAgent"),
}


def game_configuration(game: str, count: int, rounds: int) -> tuple[dict, list[dict]]:
    """Return environment kwargs and explicit agent metadata for one game."""
    if game == "prisoners_dilemma" and count != 2:
        raise ValueError("Prisoner's dilemma requires exactly two agents")
    if game == "trust_game" and count % 2:
        raise ValueError("Trust game requires an even number of agents")
    env = {
        "commons_tragedy": {
            "num_agents": count,
            "initial_pool_resources": 100,
            "max_extraction_per_agent": 10,
        },
        "prisoners_dilemma": {
            "payoff_cc": 3,
            "payoff_cd": 0,
            "payoff_dc": 5,
            "payoff_dd": 1,
        },
        "public_goods": {
            "num_agents": count,
            "initial_endowment": 20,
            "public_pool_multiplier": 1.6,
        },
        "trust_game": {
            "num_pairs": count // 2,
            "initial_funds": 10,
            "multiplication_factor": 3,
        },
        "volunteer_dilemma": {"num_agents": count, "benefit_b": 100, "cost_c": 40},
    }[game]
    specs = []
    for index in range(count):
        agent_id = index + 1
        config = {**env, "num_rounds": rounds}
        name = f"Agent {chr(65 + index)}"
        instruction = f"Participate in {game.replace('_', ' ')}. Submit exactly one valid decision each round using the environment tools."
        if game == "trust_game":
            pairs = count // 2
            pair = index % pairs + 1
            role = "Trustor" if index < pairs else "Trustee"
            name = f"Agent-{agent_id}_{role}_G{pair}"
            partner_id = agent_id + pairs if role == "Trustor" else agent_id - pairs
            partner_role = "Trustee" if role == "Trustor" else "Trustor"
            config.update(
                role=role, partner_name=f"Agent-{partner_id}_{partner_role}_G{pair}"
            )
            instruction += f" Your role is {role}; your partner is {config['partner_name']}. Trustees must wait for the current investment before choosing a return."
        specs.append(
            {
                "id": agent_id,
                "profile": {"id": agent_id, "name": name, "instructions": instruction},
                "config": config,
            }
        )
    return env, specs


def round_history(run_dir: Path, module: str) -> list[dict]:
    state = json.loads(
        (run_dir / "env" / module / "state" / "ENV_STATE.json").read_text()
    )
    return state["round_history"]


async def run_game(
    game: str,
    *,
    num_games: int,
    num_rounds: int,
    num_agents: int,
    output: Path,
    person_agent: bool = False,
) -> dict:
    """Persist real environment rounds; incomplete rounds are errors, never zero payoffs."""
    if min(num_games, num_rounds, num_agents) < 1:
        raise ValueError("Game, round and agent counts must be positive")
    module, agent_class = GAMES[game]
    env, specs = game_configuration(game, num_agents, num_rounds)
    if person_agent:
        agent_class = "PersonAgent"
        for spec in specs:
            spec["config"] = {"max_react_turns": 20}
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    report = {
        "game": game,
        "agent_class": agent_class,
        "num_agents": num_agents,
        "num_rounds": num_rounds,
        "games": [],
    }
    start = time.perf_counter()
    for index in range(num_games):
        run_dir = output / f"game_{index + 1}"
        router = await create_env_router_proxy([module], {module: env}, run_dir=run_dir)
        society = AgentSociety(
            agent_specs=specs,
            agent_class_name=agent_class,
            env_router=router,
            start_t=datetime.now(),
            run_dir=run_dir,
            enable_replay=True,
        )
        try:
            await society.init()
            for round_number in range(1, num_rounds + 1):
                # Trust transfers and returns are separate decisions. Other games
                # settle in a single tick; no successful round may be skipped.
                for _ in range(3 if game == "trust_game" else 1):
                    await asyncio.wait_for(society.step(tick=1), timeout=600)
                    history = round_history(run_dir, module)
                    if len(history) == round_number:
                        break
                else:
                    raise RuntimeError(f"{game}: round {round_number} did not settle")
                print(
                    f"game={index + 1} round={round_number} result={json.dumps(history[-1], ensure_ascii=False)}",
                    flush=True,
                )
            report["games"].append(
                {"rounds": history, "token_stats": society.all_token_stats()}
            )
        finally:
            await society.close()
    report["seconds"] = round(time.perf_counter() - start, 3)
    (output / "results.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    print(
        f"SUCCESS=True games={num_games} rounds={num_games * num_rounds} seconds={report['seconds']}"
    )
    return report


def main(game: str | None = None, *, person_agent: bool = False) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    if game is None:
        parser.add_argument("game", choices=GAMES)
    parser.add_argument("--games", type=int, default=5)
    parser.add_argument("--rounds", type=int, default=10)
    parser.add_argument("--agents", type=int)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    game = game or args.game
    output = args.output or Path(f"result_{game}") / datetime.now().strftime(
        "%Y%m%d-%H%M%S-%f"
    )
    asyncio.run(
        run_game(
            game,
            num_games=args.games,
            num_rounds=args.rounds,
            num_agents=args.agents or (2 if game == "prisoners_dilemma" else 4),
            output=output,
            person_agent=person_agent,
        )
    )
