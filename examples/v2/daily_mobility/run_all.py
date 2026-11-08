#!/usr/bin/env python3
"""Daily Mobility one-stop runner.

Stages:
1. generate init_config.json and steps.yaml
2. optionally generate world_description with MobilitySpace via --stage world-description
3. run simulation through agentsociety2.society.cli
4. compute metrics
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

EXP_DIR = Path(__file__).resolve().parent
REPO_ROOT = EXP_DIR.parents[2]
INIT_SCRIPT = EXP_DIR / "init" / "config_params.py"
EVAL_SCRIPT = EXP_DIR / "tools" / "eval_metrics.py"
# Follow the same per-experiment config directory as init/config_params.py.
DEFAULT_INIT_DIR = Path(
    os.environ.get("DAILY_MOBILITY_INIT_DIR", str(EXP_DIR / "tmp" / "init"))
)
DEFAULT_RUN_DIR = EXP_DIR / "tmp" / "run"


def _run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+ " + " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=REPO_ROOT, env=env, check=True)


def _stage_env(args: argparse.Namespace) -> dict[str, str]:
    env = os.environ.copy()
    env["DAILY_MOBILITY_PRESET"] = args.preset
    env["DAILY_MOBILITY_NUM_AGENTS"] = str(args.num_agents)
    env["DAILY_MOBILITY_START_T"] = args.start_t
    env["DAILY_MOBILITY_RUN_DIR"] = str(args.run_dir.resolve())
    env["DAILY_MOBILITY_DURATION_HOURS"] = str(args.duration_hours)
    env["DAILY_MOBILITY_TICK_SEC"] = str(args.tick_sec)
    env["DAILY_MOBILITY_SLOT_MINUTES"] = str(args.slot_minutes)
    if args.map_path:
        env["DAILY_MOBILITY_MAP_PATH"] = str(args.map_path.resolve())
    if args.profiles_path:
        env["DAILY_MOBILITY_PROFILES_PATH"] = str(args.profiles_path.resolve())
    return env


def generate_config(args: argparse.Namespace) -> tuple[Path, Path]:
    _run([sys.executable, str(INIT_SCRIPT)], env=_stage_env(args))
    config_path = args.config or (DEFAULT_INIT_DIR / "init_config.json")
    steps_path = args.steps or (DEFAULT_INIT_DIR / "steps.yaml")
    return config_path.resolve(), steps_path.resolve()


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _dry_run_world_description(router: Any) -> str:
    tools_info = router._collect_tools_info()
    lines = [
        "You are operating in a simulated daily mobility environment.",
        "Use ask_env with clear natural-language instructions to observe or act.",
        "Inspect and activate environment-module skills when module-specific behavior rules are needed.",
        "",
        "Environment modules:",
    ]
    for module in router.env_modules:
        module_info = tools_info.get(module.name)
        tool_count = len(module_info.tools) if module_info is not None else 0
        skill_count = 0
        try:
            for skills_dir in module.skill_dirs():
                base = Path(skills_dir)
                if base.is_dir():
                    skill_count += sum(
                        1
                        for child in base.iterdir()
                        if child.is_dir() and (child / "SKILL.md").is_file()
                    )
        except Exception:
            skill_count = 0
        lines.append(
            f"- {module.name}: {module.description()} "
            f"(tools={tool_count}, env_skills={skill_count})"
        )
    return "\n".join(lines)


async def generate_world_description(
    config_path: Path,
    steps_path: Path,
    run_dir: Path,
    *,
    max_retries: int = 10,
    timeout: float | None = None,
    dry_run: bool = False,
    output_path: Path | None = None,
) -> str:
    from agentsociety2.env import CodeGenRouter
    from agentsociety2.registry import (
        get_registered_env_modules,
        scan_and_register_custom_modules,
    )
    from agentsociety2.society.models import InitConfig, StepsConfig

    config = InitConfig.model_validate(_load_json(config_path))
    import yaml

    steps_config = StepsConfig.model_validate(
        yaml.safe_load(steps_path.read_text(encoding="utf-8"))
    )
    start_t = datetime.fromisoformat(steps_config.start_t)

    custom_root = run_dir.resolve()
    while custom_root.parent != custom_root:
        if (custom_root / "custom").is_dir():
            scan_and_register_custom_modules(custom_root)
            break
        custom_root = custom_root.parent

    env_type_map = {
        module_type: env_class
        for module_type, env_class in get_registered_env_modules()
    }
    env_modules = []
    for module_config in config.env_modules:
        env_class = env_type_map.get(module_config.module_type)
        if env_class is None:
            raise ValueError(
                f"Unknown env module {module_config.module_type!r}; "
                f"available={sorted(env_type_map)}"
            )
        env_modules.append(env_class(**module_config.kwargs))

    router = CodeGenRouter(
        env_modules=env_modules,
        final_summary_enabled=config.codegen_router.final_summary_enabled,
    )
    router.run_dir = run_dir.resolve()
    try:
        if dry_run:
            router.t = start_t
            for env_module in router.env_modules:
                await env_module.init(start_t)
        else:
            await router.init(start_t)

        if dry_run:
            description = _dry_run_world_description(router)
        else:
            description_task = router.generate_world_description_from_tools(
                max_retries=max(1, max_retries),
            )
            if timeout is None:
                description = await description_task
            else:
                description = await asyncio.wait_for(description_task, timeout=timeout)
    finally:
        await router.close()

    out = output_path or (run_dir / "world_description.txt")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(description, encoding="utf-8")
    print(f"World description written to {out}")
    print(description)
    return description


async def run_simulation(
    args: argparse.Namespace, config_path: Path, steps_path: Path
) -> None:
    """Run simulation by directly invoking AgentSociety (no subprocess)."""
    from agentsociety2.society.cli import ExperimentRunner

    args.run_dir.mkdir(parents=True, exist_ok=True)
    runner = ExperimentRunner(args.run_dir)
    await runner.run(config_path, steps_path)


def compute_metrics(args: argparse.Namespace) -> None:
    gt_dir = args.gt_dir or (EXP_DIR / "data" / "groundtruth")
    _run(
        [
            sys.executable,
            str(EVAL_SCRIPT),
            "--run-dir",
            str(args.run_dir),
            "--gt-dir",
            str(gt_dir),
            "--config",
            str((args.config or (DEFAULT_INIT_DIR / "init_config.json")).resolve()),
        ]
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--stage",
        choices=["all", "config", "world-description", "simulate", "metrics"],
        default="all",
        help="Pipeline stage to run.",
    )
    parser.add_argument("--preset", choices=["smoke", "benchmark"], default="smoke")
    parser.add_argument("--num-agents", type=int, default=2)
    parser.add_argument("--start-t", default="2018-06-13T00:00:00")
    parser.add_argument("--duration-hours", type=int, default=24)
    parser.add_argument("--tick-sec", type=int, default=900)
    parser.add_argument("--slot-minutes", type=int, default=30)
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--steps", type=Path, default=None)
    parser.add_argument("--run-dir", type=Path, default=DEFAULT_RUN_DIR)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--gt-dir", type=Path, default=None)
    parser.add_argument("--map-path", type=Path, default=None)
    parser.add_argument("--profiles-path", type=Path, default=None)
    parser.add_argument("--experiment-id", default="daily_mobility")
    parser.add_argument("--log-level", default="INFO")
    parser.add_argument(
        "--skip-world-description",
        action="store_true",
        help="Deprecated no-op: --stage all no longer runs the world-description smoke check.",
    )
    parser.add_argument(
        "--world-description-max-retries",
        type=int,
        default=10,
        help="LLM retry count for the world-description stage.",
    )
    parser.add_argument(
        "--world-description-timeout",
        type=float,
        default=None,
        help="Optional timeout in seconds for the world-description LLM call.",
    )
    parser.add_argument(
        "--world-description-dry-run",
        action="store_true",
        help="Validate env module setup and write a deterministic description without calling LLM.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = args.config or (DEFAULT_INIT_DIR / "init_config.json")
    steps_path = args.steps or (DEFAULT_INIT_DIR / "steps.yaml")

    if args.stage in {"all", "config"}:
        config_path, steps_path = generate_config(args)

    if args.stage == "world-description":
        asyncio.run(
            generate_world_description(
                config_path,
                steps_path,
                args.run_dir,
                max_retries=args.world_description_max_retries,
                timeout=args.world_description_timeout,
                dry_run=args.world_description_dry_run,
            )
        )

    if args.stage in {"all", "simulate"}:
        asyncio.run(run_simulation(args, config_path, steps_path))

    if args.stage in {"all", "metrics"}:
        compute_metrics(args)


if __name__ == "__main__":
    main()
