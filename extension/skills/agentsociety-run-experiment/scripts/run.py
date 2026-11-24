#!/usr/bin/env python3
"""Run experiment CLI script

This script manages experiment execution by:
1. Reading experiment configuration from init/init_config.json
2. Reading execution steps from init/steps.yaml
3. Running the experiment and storing all output in run/

The simplified structure means config files are directly in init/:
- init/config_params.py - Parameter generation script
- init/init_config.json - Experiment configuration
- init/steps.yaml - Execution steps

All experiment output (logs, replay data, etc.) is stored in run/:
- run/replay/ - Replay datasets (_schema.json + sharded JSONL)
- run/stdout.log - Standard output
- run/stderr.log - Standard error
- run/pid.json - Process ID file
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from dotenv import load_dotenv


def _load_workspace_env(workspace_path: Path) -> None:
    """从工作区 ``.env`` 加载环境变量（覆盖已有 shell 值）。"""
    env_file = workspace_path / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)


async def main():
    parser = argparse.ArgumentParser(
        description="Run experiment commands",
        epilog="""
Examples:
  # List all experiments
  $PYTHON_PATH .agentsociety/bin/ags.py run-experiment list

  # Start an experiment (uses default init/ paths)
  $PYTHON_PATH .agentsociety/bin/ags.py run-experiment start --hypothesis-id 1 --experiment-id 1

  # Start with custom config paths
  $PYTHON_PATH .agentsociety/bin/ags.py run-experiment start --hypothesis-id 1 --experiment-id 1 \\
      --init-config /path/to/init_config.json \\
      --steps /path/to/steps.yaml

  # Check status
  $PYTHON_PATH .agentsociety/bin/ags.py run-experiment status --hypothesis-id 1 --experiment-id 1

  # Stop a running experiment
  $PYTHON_PATH .agentsociety/bin/ags.py run-experiment stop --hypothesis-id 1 --experiment-id 1
        """,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "action", choices=["start", "stop", "status", "list"], help="Action to perform"
    )
    parser.add_argument("--hypothesis-id", help="Hypothesis ID")
    parser.add_argument("--experiment-id", help="Experiment ID")
    parser.add_argument("--run-id", default="run", help="Run ID (default: run)")
    parser.add_argument("--workspace", default=".", help="Workspace path")
    parser.add_argument("--json", action="store_true", help="Output JSON")
    parser.add_argument(
        "--foreground",
        action="store_true",
        help="Run in foreground instead of the default background mode",
    )
    parser.add_argument(
        "--init-config",
        type=Path,
        help="Path to init_config.json (default: init/init_config.json)",
    )
    parser.add_argument(
        "--steps",
        type=Path,
        help="Path to steps.yaml (default: init/steps.yaml)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume an interrupted run from run_dir/SOCIETY.json + SOCIETY_STEP.json",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Fresh start: delete previous run artifacts in run_dir",
    )
    parser.add_argument("--seed", type=int, help="Global random seed")
    parser.add_argument(
        "--batch-size", type=int, help="Agents per step_agent_batch Ray task"
    )
    parser.add_argument(
        "--replay-disable",
        action="store_true",
        help="Disable replay JSONL writing",
    )
    parser.add_argument(
        "--log-file",
        help="Write CLI logs to this file (background runs also capture stdout/stderr)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="CLI log level (default: INFO)",
    )

    args = parser.parse_args()

    workspace_path = Path(args.workspace).resolve()
    _load_workspace_env(workspace_path)

    from agentsociety2.logger import get_logger
    from agentsociety2.skills.experiment import (
        get_experiment_status,
        list_experiments,
        stop_experiment,
    )
    from agentsociety2.society.cli import ExperimentRunner

    logger = get_logger()

    if args.action == "list":
        experiments = await list_experiments(workspace_path)

        if args.json:
            output = [exp.model_dump() for exp in experiments]
            print(json.dumps(output, indent=2))
        else:
            print(f"Found {len(experiments)} experiment(s):")
            for exp in experiments:
                status_marker = (
                    "🏃"
                    if exp.is_running
                    else ("✅" if exp.status == "completed" else "❓")
                )
                print(
                    f"{status_marker} hypothesis_{exp.hypothesis_id}/experiment_{exp.experiment_id}"
                )
                print(
                    f"   init: {'✓' if exp.has_init else '✗'}  run: {'✓' if exp.has_run else '✗'}"
                )
                if exp.pid:
                    print(f"   PID: {exp.pid}")
        return 0

    # Other actions require hypothesis_id and experiment_id
    if not args.hypothesis_id or not args.experiment_id:
        message = "Error: --hypothesis-id and --experiment-id are required"
        if args.json:
            print(json.dumps({"success": False, "error": message}))
        else:
            print(message, file=sys.stderr)
        return 1

    from agentsociety2.skills.experiment.config import get_experiment_paths

    try:
        exp_paths = get_experiment_paths(
            workspace_path, args.hypothesis_id, args.experiment_id, args.run_id
        )
    except ValueError as exc:
        if args.json:
            print(json.dumps({"success": False, "error": str(exc)}))
        else:
            print(f"Error: {exc}", file=sys.stderr)
        return 1
    experiment_key = f"{args.hypothesis_id}_{args.experiment_id}"

    # Use provided paths or defaults
    init_config_path = args.init_config or exp_paths["init_config"]
    steps_path = args.steps or exp_paths["steps"]

    if args.action == "start":
        import yaml
        from pydantic import ValidationError

        from agentsociety2.society.models import InitConfig, StepsConfig

        try:
            InitConfig.model_validate_json(init_config_path.read_text(encoding="utf-8"))
            StepsConfig.model_validate(
                yaml.safe_load(steps_path.read_text(encoding="utf-8"))
            )
        except (OSError, UnicodeError, ValidationError, yaml.YAMLError) as exc:
            print(f"Invalid experiment configuration: {exc}", file=sys.stderr)
            return 1

        current = await get_experiment_status(
            workspace_path, args.hypothesis_id, args.experiment_id, args.run_id
        )
        if current.is_running:
            print(f"Experiment is already running (PID: {current.pid})", file=sys.stderr)
            return 1

        # Ensure run directory exists
        run_dir = exp_paths["run"]
        run_dir.mkdir(parents=True, exist_ok=True)
        stdout_log = run_dir / "stdout.log"
        stderr_log = run_dir / "stderr.log"

        print(
            f"Starting experiment hypothesis_{args.hypothesis_id}/experiment_{args.experiment_id}..."
        )
        print(f"  Config: {init_config_path}")
        print(f"  Steps: {steps_path}")
        print(f"  Output: {run_dir}")
        print(f"  Stdout Log: {stdout_log}")
        print(f"  Stderr Log: {stderr_log}")
        print(f"  Mode: {'foreground' if args.foreground else 'background'}")
        print()

        cli_command = [
            sys.executable,
            "-m",
            "agentsociety2.society.cli",
            "--config",
            str(init_config_path),
            "--steps",
            str(steps_path),
            "--run-dir",
            str(run_dir),
            "--experiment-id",
            experiment_key,
            "--log-level",
            args.log_level,
        ]
        if args.resume:
            cli_command.append("--resume")
        if args.overwrite:
            cli_command.append("--overwrite")
        if args.seed is not None:
            cli_command.extend(["--seed", str(args.seed)])
        if args.batch_size is not None:
            cli_command.extend(["--batch-size", str(args.batch_size)])
        if args.replay_disable:
            cli_command.append("--replay-disable")
        if args.log_file:
            cli_command.extend(["--log-file", args.log_file])

        if args.foreground:
            try:
                runner = ExperimentRunner(run_dir=run_dir)
                await runner.run(
                    config_path=init_config_path,
                    steps_path=steps_path,
                    experiment_id=experiment_key,
                    resume=args.resume,
                    seed=args.seed,
                    batch_size=args.batch_size,
                    replay_disable=args.replay_disable,
                    overwrite=args.overwrite,
                )

                print("\n✓ Experiment completed successfully!")
                return 0
            except KeyboardInterrupt:
                print("\n⚠ Experiment interrupted by user")
                return 130
            except Exception as e:
                print(f"\n✗ Experiment failed: {e}")
                logger.error(f"Experiment error: {e}", exc_info=True)
                return 1

        try:
            with open(stdout_log, "a", encoding="utf-8") as stdout_handle, open(
                stderr_log, "a", encoding="utf-8"
            ) as stderr_handle:
                process = subprocess.Popen(
                    cli_command,
                    cwd=workspace_path,
                    env=os.environ.copy(),
                    stdout=stdout_handle,
                    stderr=stderr_handle,
                    start_new_session=True,
                    close_fds=True,
                )

            # The simulation CLI owns pid.json and publishes it atomically.
            deadline = time.monotonic() + 10
            while process.poll() is None and time.monotonic() < deadline:
                try:
                    status = json.loads(exp_paths["pid_file"].read_text(encoding="utf-8"))
                    if status.get("pid") == process.pid:
                        break
                except (OSError, ValueError):
                    pass
                await asyncio.sleep(0.1)
            exit_code = process.poll()
            if exit_code == 0:
                print("Experiment completed successfully.")
                return 0
            if exit_code is not None:
                try:
                    stderr_tail = stderr_log.read_text(
                        encoding="utf-8", errors="replace"
                    )[-2000:]
                except OSError:
                    stderr_tail = ""
                print(
                    f"\n✗ Experiment exited immediately (code {exit_code}).\n{stderr_tail}"
                )
                return 1

            print(f"✓ Experiment started in background (PID: {process.pid})")
            return 0
        except Exception as e:
            print(f"\n✗ Failed to start experiment in background: {e}")
            logger.error(f"Experiment start error: {e}", exc_info=True)
            return 1

    elif args.action == "stop":
        result = await stop_experiment(
            workspace_path=workspace_path,
            hypothesis_id=args.hypothesis_id,
            experiment_id=args.experiment_id,
            run_id=args.run_id,
        )
        print(result.get("content", result.get("error", "Done")))
        return 0 if result.get("success") else 1

    elif args.action == "status":
        status = await get_experiment_status(
            workspace_path=workspace_path,
            hypothesis_id=args.hypothesis_id,
            experiment_id=args.experiment_id,
            run_id=args.run_id,
        )

        if args.json:
            print(json.dumps(status.model_dump(), indent=2))
        else:
            print(f"Experiment: hypothesis_{status.hypothesis_id}/experiment_{status.experiment_id}")
            print(f"Status: {status.status}")
            if status.is_running:
                print(f"Running: Yes (PID: {status.pid})")
            else:
                print(f"Running: No")
            if status.start_time:
                print(f"Start Time: {status.start_time}")
            print(f"\nConfig files:")
            print(f"  init_config.json: {exp_paths['init_config']}")
            print(f"  steps.yaml: {exp_paths['steps']}")
            print(f"  run_dir: {exp_paths['run']}")

            # Check file existence
            init_config_exists = exp_paths["init_config"].exists()
            steps_exists = exp_paths["steps"].exists()
            replay_schema_exists = (
                exp_paths["run"] / "replay" / "_schema.json"
            ).exists()

            print(f"\nFiles:")
            print(f"  init/init_config.json: {'✓' if init_config_exists else '✗'}")
            print(f"  init/steps.yaml: {'✓' if steps_exists else '✗'}")
            print(f"  run/replay/_schema.json: {'✓' if replay_schema_exists else '✗'}")

        return 0

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
