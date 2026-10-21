"""Custom Environment Module Example.

Uses contrib WeatherEnvironment (Ray-discoverable). Changes weather via
intervene, then asks for temperature — stable onboarding path.
"""

from __future__ import annotations

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


async def main() -> None:
    run_dir = fresh_run_dir(Path("run_custom_env"))

    agent_specs = [
        {
            "id": i,
            "profile": {"id": i, "name": f"Agent{i}", "personality": "curious"},
            "config": {},
        }
        for i in range(1, 3)
    ]

    env_router = await create_env_router_proxy(
        ["WeatherEnvironment"],
        {"WeatherEnvironment": {}},
        run_dir=run_dir,
    )
    society = AgentSociety(
        agent_specs=agent_specs,
        agent_class_name="PersonAgent",
        env_router=env_router,
        start_t=datetime.now(),
        run_dir=run_dir,
    )
    await society.init()

    print("=== Custom Environment Module ===\n")
    t0 = time.perf_counter()
    print("1. Current weather?")
    a1 = str(
        await society.ask(
            "Ask the environment: what is the current weather and temperature?"
        )
    )
    print(f"Answer: {a1}\n")

    print("2. Change weather to rainy / 18C")
    a2 = str(
        await society.intervene(
            "Call change_weather with weather='rainy' and temperature=18"
        )
    )
    print(f"Result: {a2}\n")

    print("3. Temperature now?")
    a3 = str(
        await society.ask(
            "Ask the environment for the current temperature using get_average_temperature."
        )
    )
    print(f"Answer: {a3}\n")
    wall = time.perf_counter() - t0
    stats = society.all_token_stats()
    await society.close()
    require_no_critical_failures(run_dir)

    # Validate the observed post-intervention state.  The intervention request
    # itself contains the target values, so including ``a2`` here could turn a
    # refused or failed intervention into a false positive.
    ok = "18" in a3
    print(f"Token stats: {stats}")
    print(f"WALL_SEC={wall:.2f}")
    print(f"SUCCESS={ok}")
    if not ok:
        print("ERROR: expected rainy/18 after intervene", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
