#!/usr/bin/env python3
"""生成 DailyMobility 示例的 init_config.json 与 steps.yaml。

运行：
  uv run python examples/v2/daily_mobility/init/config_params.py

环境变量：
  DAILY_MOBILITY_PRESET   benchmark | smoke（默认 benchmark）
  DAILY_MOBILITY_NUM_AGENTS
  DAILY_MOBILITY_START_T  默认 2018-06-13T00:00:00（周三，避开周末）
  DAILY_MOBILITY_DURATION_HOURS  benchmark 时长，默认 24
  DAILY_MOBILITY_TICK_SEC  每个 step 秒数，默认 900
  DAILY_MOBILITY_RUN_DIR  运行产物目录，默认 examples/v2/daily_mobility/tmp/run
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml

SCRIPT_DIR = Path(__file__).resolve().parent
EXP_DIR = SCRIPT_DIR.parent
REPO_ROOT = EXP_DIR.parents[2]
TMP_DIR = EXP_DIR / "tmp"
# Isolate generated configs when multiple experiments run concurrently.
TMP_INIT_DIR = Path(os.environ.get("DAILY_MOBILITY_INIT_DIR", str(TMP_DIR / "init")))
TMP_RUN_DIR = TMP_DIR / "run"

if str(EXP_DIR) not in sys.path:
    sys.path.insert(0, str(EXP_DIR))

from daily_mobility.intentions import (
    INTENTION_CHOICES,
    build_primary_intention_prompt,
)

INTENTION_CHOICE_LABELS = INTENTION_CHOICES


def _profile_block(p: dict, tick: int) -> str:
    aid = p["id"]
    return (
        f"Agent-{aid}, age {p.get('age', '?')}, gender {p.get('gender', '?')}, "
        f"education {p.get('education', '?')}, occupation {p.get('occupation', '?')}, "
        f"home AOI {p.get('home')}, work AOI {p.get('work')}. "
        "You are simulating an ordinary day in an urban mobility environment. "
        f"Each simulation step advances about {tick / 60:g} minutes on the same calendar day. "
        "Use mobility tools as a real person would for commuting, errands, meals, and leisure, "
        "consistent with your profile."
    )


def questionnaire_step(
    slot_index: int,
    *,
    total_slots: int,
    slot_minutes: int,
) -> dict:
    prompt = build_primary_intention_prompt(
        slot_index,
        total_slots=total_slots,
        slot_minutes=slot_minutes,
    )
    return {
        "type": "questionnaire",
        "questionnaire_id": f"daily_mobility_intention_slot_{slot_index}",
        "title": f"Daily mobility intention ({slot_minutes} min)",
        "description": "",
        "questions": [
            {
                "id": "primary_intention",
                "prompt": prompt,
                "response_type": "choice",
                "choices": list(INTENTION_CHOICE_LABELS),
            }
        ],
    }


def _slot_run_steps(tick: int, slot_minutes: int) -> int:
    slot_seconds = slot_minutes * 60
    if tick <= 0 or slot_seconds % tick != 0:
        raise ValueError(
            "DAILY_MOBILITY_TICK_SEC must divide the questionnaire slot duration; "
            "use a divisor of DAILY_MOBILITY_SLOT_MINUTES * 60."
        )
    return slot_seconds // tick


def build_steps_benchmark(
    target_ids: list[int],
    tick: int,
    *,
    duration_hours: int = 24,
    slot_minutes: int = 30,
) -> list[dict]:
    total_slots = max(1, duration_hours * 60 // slot_minutes)
    steps: list[dict] = []
    runs_per_slot = _slot_run_steps(tick, slot_minutes)
    for slot in range(total_slots):
        q = questionnaire_step(
            slot,
            total_slots=total_slots,
            slot_minutes=slot_minutes,
        )
        q["target_agent_ids"] = target_ids
        steps.append(q)
        steps.append({"type": "run", "num_steps": runs_per_slot, "tick": tick})
    return steps


def build_steps_smoke(tick: int) -> list[dict]:
    return [{"type": "run", "num_steps": 2, "tick": tick}]


def input_file(variable: str, defaults: list[Path]) -> Path:
    configured = os.environ.get(variable)
    candidates = [Path(configured).expanduser()] if configured else defaults
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise FileNotFoundError(
        f"Set {variable} to an existing file (tried {', '.join(map(str, candidates))})"
    )


def main() -> None:
    preset = os.environ.get("DAILY_MOBILITY_PRESET", "benchmark").strip().lower()
    start_t = os.environ.get("DAILY_MOBILITY_START_T", "2018-06-13T00:00:00").strip()
    tick = int(os.environ.get("DAILY_MOBILITY_TICK_SEC", "900"))
    slot_minutes = int(os.environ.get("DAILY_MOBILITY_SLOT_MINUTES", "30"))
    duration_hours = int(os.environ.get("DAILY_MOBILITY_DURATION_HOURS", "24"))

    profiles_path = input_file(
        "DAILY_MOBILITY_PROFILES_PATH",
        [
            REPO_ROOT / "profiles.json",
            REPO_ROOT / "packages/agentsociety2/profiles.json",
        ],
    )
    data_dir = Path(
        os.environ.get("AGENTSOCIETY_HOME_DIR") or "agentsociety_data"
    ).expanduser()
    map_path = input_file(
        "DAILY_MOBILITY_MAP_PATH",
        [
            directory / name
            for directory in (data_dir, REPO_ROOT / "agentsociety_data")
            for name in ("beijing.pb", "agentsociety_beijing.pb")
        ],
    )

    with open(profiles_path, encoding="utf-8") as f:
        profiles: list[dict] = json.load(f)

    if preset == "smoke":
        num = int(os.environ.get("DAILY_MOBILITY_NUM_AGENTS", "2"))
        num = min(num, len(profiles))
        use = profiles[:num]
        steps_list = build_steps_smoke(tick)
    else:
        num = int(os.environ.get("DAILY_MOBILITY_NUM_AGENTS", "100"))
        num = min(num, len(profiles))
        use = profiles[:num]
        actual_ids = [p["id"] for p in use]
        steps_list = build_steps_benchmark(
            actual_ids,
            tick,
            duration_hours=duration_hours,
            slot_minutes=slot_minutes,
        )

    actual_ids = [p["id"] for p in use]
    TMP_INIT_DIR.mkdir(parents=True, exist_ok=True)
    run_dir = Path(os.environ.get("DAILY_MOBILITY_RUN_DIR", str(TMP_RUN_DIR))).resolve()
    mobility_home = (run_dir / "mobility_workspace").resolve()
    mobility_home.mkdir(parents=True, exist_ok=True)

    persons = [
        {
            "id": p["id"],
            "position": {"kind": "aoi", "aoi_id": p["home"]},
            "home_aoi": p["home"],
            "work_aoi": p.get("work"),
        }
        for p in use
    ]

    agents = []
    for p in use:
        aid = p["id"]
        agent_kwargs = {
            "id": aid,
            "profile": {"description": _profile_block(p, tick)},
            "max_react_turns": int(
                os.environ.get("DAILY_MOBILITY_MAX_TOOL_ROUNDS")
                or (6 if len(use) > 20 else 8)
            ),
            "default_activated_skill_ids": [
                "built-in@daily-guidance",
                "env:MobilitySpace@mobility",
            ],
        }
        agents.append(
            {
                "agent_id": aid,
                "agent_type": "PersonAgent",
                "kwargs": agent_kwargs,
            }
        )

    init_cfg = {
        "env_modules": [
            {
                "module_type": "MobilitySpace",
                "kwargs": {
                    "file_path": str(map_path.resolve()),
                    "home_dir": str(mobility_home),
                    "persons": persons,
                },
            },
        ],
        "agents": agents,
    }

    steps_yaml = {"start_t": start_t, "steps": steps_list}

    out_cfg = TMP_INIT_DIR / "init_config.json"
    out_steps = TMP_INIT_DIR / "steps.yaml"
    # The simulator reads this JSON directly. Keep profile data owner-readable
    # even when replacing an existing config with broader permissions.
    with NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=TMP_INIT_DIR, delete=False
    ) as temp:
        private_config = Path(temp.name)
        try:
            json.dump(init_cfg, temp, ensure_ascii=False, indent=2)
            temp.close()
            private_config.replace(out_cfg)
        finally:
            private_config.unlink(missing_ok=True)
    out_steps.write_text(
        yaml.safe_dump(steps_yaml, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    print(f"Wrote {out_cfg}")
    print(f"Wrote {out_steps}")
    print(
        f"preset={preset} agents={len(use)} tick={tick} "
        f"duration_hours={duration_hours} ids[:8]={actual_ids[:8]}"
    )


if __name__ == "__main__":
    main()
