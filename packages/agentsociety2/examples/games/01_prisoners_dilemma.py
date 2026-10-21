"""Prisoner's Dilemma example (2 agents × 2 rounds).

Requires LLM credentials. Exits non-zero if rounds are not recorded or LLM
dispatch collapsed into CRITICAL FAILURE defaults.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("MEM0_TELEMETRY", "False")
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import asyncio
from datetime import datetime

from agentsociety2.env import create_env_router_proxy
from agentsociety2.society import AgentSociety

_EXAMPLES_ROOT = Path(__file__).resolve().parents[1]
if str(_EXAMPLES_ROOT) not in sys.path:
    sys.path.insert(0, str(_EXAMPLES_ROOT))
from _checks import fresh_run_dir, require_no_critical_failures

NUM_ROUNDS = 2
MODULE = "PrisonersDilemmaEnv"


def _history(run_dir: Path) -> list:
    path = run_dir / "env" / MODULE / "state" / "ENV_STATE.json"
    if not path.is_file():
        return []
    return list(json.loads(path.read_text(encoding="utf-8")).get("round_history") or [])


async def main() -> None:
    run_dir = fresh_run_dir(Path("run_prisoners_dilemma"))
    agent_names = ["Agent A", "Agent B"]
    agent_specs = [
        {"id": i + 1, "profile": {"id": i + 1, "name": name}, "config": {}}
        for i, name in enumerate(agent_names)
    ]

    env_router = await create_env_router_proxy([MODULE], {MODULE: {}}, run_dir=run_dir)
    society = AgentSociety(
        agent_specs=agent_specs,
        agent_class_name="PrisonersDilemmaAgent",
        env_router=env_router,
        start_t=datetime.now(),
        run_dir=run_dir,
        enable_replay=True,
    )
    await society.init()

    print("=== Prisoner's Dilemma ===\n")
    print(f"Running {NUM_ROUNDS} rounds with {agent_names}...\n")
    t0 = time.perf_counter()
    for round_num in range(1, NUM_ROUNDS + 1):
        print(f"--- Round {round_num}/{NUM_ROUNDS} ---")
        await society.step(tick=1)
        hist = _history(run_dir)
        if hist:
            latest = hist[-1]
            print(
                f"  A={latest.get('agent_a_action')} "
                f"B={latest.get('agent_b_action')} "
                f"payoffs=({latest.get('agent_a_payoff')}, "
                f"{latest.get('agent_b_payoff')})"
            )
        else:
            print("  (no round settled yet)")
    wall = time.perf_counter() - t0
    stats = society.all_token_stats()
    await society.close()
    require_no_critical_failures(run_dir)
    history = _history(run_dir)
    ok = len(history) == NUM_ROUNDS
    print(f"\nDone. ENV state / replay under {run_dir}")
    print(f"Rounds recorded: {len(history)}")
    print(f"Token stats: {stats}")
    print(f"WALL_SEC={wall:.2f}")
    print(f"SUCCESS={ok}")
    if not ok:
        print(
            f"ERROR: expected {NUM_ROUNDS} rounds, got {len(history)}",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
