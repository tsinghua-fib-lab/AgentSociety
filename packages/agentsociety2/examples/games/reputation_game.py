"""Reputation game example (3 agents × 2 steps, seeded personalities).

Requires LLM credentials. Exits non-zero unless steps complete and replay
schema exists, and LLM dispatch did not collapse.
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

POPULATION = 3
NUM_STEPS = 2
TICK_SECONDS = 2
MODULE = "ReputationGameEnv"

PERSONALITIES = [
    "You are a rational and cautious agent, tending to maximize long-term benefits.",
    "You are a fair-minded agent, tending to help those with good reputation.",
    "You are an optimistic agent, believing that cooperation will bring better results.",
]


async def main() -> None:
    run_dir = fresh_run_dir(Path("run_reputation_game"))
    env_config = {
        "Z": POPULATION,
        "BENEFIT": 5,
        "COST": 1,
        "norm_type": "stern_judging",
        "seed": 42,
    }

    agent_specs = []
    for i in range(POPULATION):
        agent_specs.append(
            {
                "id": i,
                "profile": {
                    "id": i,
                    "name": f"Agent {i}",
                    "custom_fields": {
                        "learning_frequency": 5,
                        "personality": PERSONALITIES[i],
                    },
                },
                "config": {},
            }
        )

    env_router = await create_env_router_proxy(
        [MODULE],
        {MODULE: {"config": env_config}},
        run_dir=run_dir,
    )
    society = AgentSociety(
        agent_specs=agent_specs,
        agent_class_name="LLMDonorAgent",
        env_router=env_router,
        start_t=datetime.now(),
        run_dir=run_dir,
        enable_replay=True,
    )
    await society.init()

    print("=== Reputation Game ===\n")
    print(
        f"Population={POPULATION}, steps={NUM_STEPS}, norm={env_config['norm_type']}\n"
    )
    t0 = time.perf_counter()
    for step_idx in range(1, NUM_STEPS + 1):
        print(f"--- Step {step_idx}/{NUM_STEPS} ---")
        await society.step(tick=TICK_SECONDS)
    wall = time.perf_counter() - t0
    stats = society.all_token_stats()
    await society.close()
    require_no_critical_failures(run_dir)

    schema_ok = (run_dir / "replay" / "_schema.json").is_file()
    step_path = run_dir / "SOCIETY_STEP.json"
    step_ok = False
    step_count = 0
    if step_path.is_file():
        step_meta = json.loads(step_path.read_text(encoding="utf-8"))
        step_count = int(step_meta.get("step_count") or 0)
        step_ok = step_count >= NUM_STEPS
    ok = schema_ok and step_ok
    print(f"Token stats: {stats}")
    print(f"WALL_SEC={wall:.2f}")
    print(f"SUCCESS={ok}")
    print(f"step_count={step_count}")
    print(f"\nDone. Artifacts under {run_dir}")
    if not ok:
        print(
            f"ERROR: schema_ok={schema_ok} step_ok={step_ok} step_count={step_count}",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
