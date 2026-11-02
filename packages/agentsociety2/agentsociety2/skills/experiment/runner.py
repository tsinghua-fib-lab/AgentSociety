"""Experiment runner module

Provides functionality for starting, stopping, and monitoring experiments.
This is a minimal implementation - actual experiment execution is handled
by the agent society framework and extension scripts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agentsociety2.logger import get_logger
from agentsociety2.skills.experiment.models import ExperimentInfo, ExperimentStatus

logger = get_logger()


async def start_experiment(
    workspace_path: Path,
    hypothesis_id: str,
    experiment_id: str,
    run_id: str = "run",
    init_config_path: Path | None = None,
    steps_path: Path | None = None,
) -> dict[str, Any]:
    """Start an experiment

    :param workspace_path: Path to workspace directory
    :param hypothesis_id: Hypothesis ID (e.g., '1', '2')
    :param experiment_id: Experiment ID (e.g., '1', '2')
    :param run_id: Run ID (default: 'run')
    :param init_config_path: Optional path to init_config.json (default: init/init_config.json)
    :param steps_path: Optional path to steps.yaml (default: init/steps.yaml)

    :returns: Result dictionary with status and info
    """
    from agentsociety2.skills.experiment.config import get_experiment_paths

    exp_paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id)

    if not exp_paths["experiment"].exists():
        return {
            "success": False,
            "error": "Experiment not found",
            "content": f"Experiment directory not found: {exp_paths['experiment']}",
        }

    # Use provided paths or fall back to default locations
    init_config_file = init_config_path or exp_paths["init_config"]
    steps_file = steps_path or exp_paths["steps"]

    # Validate init_config exists
    if not init_config_file.exists():
        return {
            "success": False,
            "error": "Experiment not initialized",
            "content": (
                f"Experiment configuration not found: {init_config_file}\n"
                f"Please run experiment-config prepare first."
            ),
        }

    # Validate steps.yaml exists
    if not steps_file.exists():
        return {
            "success": False,
            "error": "Steps configuration not found",
            "content": (
                f"Steps configuration not found: {steps_file}\n"
                f"Please run experiment-config prepare first."
            ),
        }

    # Ensure run directory exists for output
    run_dir = exp_paths["run"]
    run_dir.mkdir(parents=True, exist_ok=True)

    # Return the configuration for the caller to execute
    return {
        "success": True,
        "content": f"Experiment {experiment_id} ready to start",
        "hypothesis_id": hypothesis_id,
        "experiment_id": experiment_id,
        "run_id": run_id,
        "experiment_dir": str(exp_paths["experiment"]),
        "init_config_file": str(init_config_file),
        "steps_file": str(steps_file),
        "run_dir": str(run_dir),
    }


async def stop_experiment(
    workspace_path: Path,
    hypothesis_id: str,
    experiment_id: str,
    run_id: str = "run",
) -> dict[str, Any]:
    """Stop a running experiment

    :param workspace_path: Path to workspace directory
    :param hypothesis_id: Hypothesis ID
    :param experiment_id: Experiment ID
    :param run_id: Run ID (default: 'run')

    :returns: Result dictionary with status
    """
    from agentsociety2.skills.experiment.config import get_experiment_paths

    exp_paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id)

    # Check for PID file and attempt to stop the process
    pid_file = exp_paths["pid_file"]
    stopped = False
    if pid_file.exists():
        try:
            pid_content = pid_file.read_text().strip()
            if pid_content:
                import json
                import os
                import signal

                pid_data = json.loads(pid_content)
                pid = pid_data.get("pid")
                if pid:
                    try:
                        os.kill(pid, signal.SIGTERM)
                        stopped = True
                    except OSError:
                        logger.debug(
                            "Failed to send SIGTERM to pid %s", pid, exc_info=True
                        )
        except (ValueError, OSError, json.JSONDecodeError):
            logger.debug("Failed to read pid file", exc_info=True)

    # Experiment lifecycle is managed externally
    return {
        "success": True,
        "content": f"Stop signal sent for experiment {experiment_id}"
        if not stopped
        else f"Experiment {experiment_id} stopped (PID terminated)",
        "hypothesis_id": hypothesis_id,
        "experiment_id": experiment_id,
        "run_id": run_id,
    }


async def get_experiment_status(
    workspace_path: Path,
    hypothesis_id: str,
    experiment_id: str,
    run_id: str = "run",
) -> ExperimentStatus:
    """Get experiment status

    :param workspace_path: Path to workspace directory
    :param hypothesis_id: Hypothesis ID
    :param experiment_id: Experiment ID
    :param run_id: Run ID (default: 'run')

    :returns: ExperimentStatus object
    """
    from agentsociety2.skills.experiment.config import get_experiment_paths

    exp_paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id)

    # Determine status based on simplified init structure
    status = "not_initialized"
    if exp_paths["init_config"].exists():
        status = "configured"
    # Check for completion: replay schema in run/replay/ directory
    if (exp_paths["run"] / "replay" / "_schema.json").exists():
        status = "completed"

    # Check for PID file to determine if running
    pid = None
    is_running = False
    start_time = None
    end_time = None
    pid_file = exp_paths["pid_file"]
    if pid_file.exists():
        try:
            pid_content = pid_file.read_text().strip()
            if pid_content:
                import json

                pid_data = json.loads(pid_content)
                pid = pid_data.get("pid")
                pid_status = str(pid_data.get("status") or "").strip().lower()
                start_time = pid_data.get("start_time") or pid_data.get("started_at")
                end_time = pid_data.get("end_time")

                if pid_status == "completed":
                    status = "completed"
                elif pid_status == "failed":
                    status = "failed"
                elif pid_status:
                    status = pid_status

                if pid and pid_status not in {"completed", "failed"}:
                    # Check if process is still alive
                    import os

                    try:
                        os.kill(pid, 0)  # Check if process exists
                        is_running = True
                        status = "running"
                    except OSError:
                        if pid_status == "running" and status not in {
                            "completed",
                            "failed",
                        }:
                            if (exp_paths["run"] / "replay" / "_schema.json").exists():
                                status = "completed"
                            else:
                                status = "failed"
                        elif pid_status == "failed":
                            status = "failed"
        except (ValueError, OSError, json.JSONDecodeError):
            logger.debug("Failed to read pid file for status check", exc_info=True)

    # Check for log files
    stdout_log = None
    stderr_log = None
    if exp_paths["run"].exists():
        stdout_path = exp_paths["run"] / "stdout.log"
        stderr_path = exp_paths["run"] / "stderr.log"
        stdout_log = str(stdout_path) if stdout_path.exists() else None
        stderr_log = str(stderr_path) if stderr_path.exists() else None

    return ExperimentStatus(
        hypothesis_id=hypothesis_id,
        experiment_id=experiment_id,
        run_id=run_id,
        status=status,
        pid=pid,
        is_running=is_running,
        start_time=start_time,
        end_time=end_time,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
    )


async def list_experiments(
    workspace_path: Path,
    hypothesis_id: str | None = None,
) -> list[ExperimentInfo]:
    """List experiments

    :param workspace_path: Path to workspace directory
    :param hypothesis_id: Optional hypothesis ID to filter by
    :returns: List of ExperimentInfo objects

    Note:
        Uses simplified init structure: init/init_config.json, init/steps.yaml
    """
    experiments: list[ExperimentInfo] = []

    def _check_experiment_status(
        exp_dir: Path,
    ) -> tuple[bool, bool, bool, int | None, bool, str | None]:
        """检查实验状态的辅助函数。

        :returns: ``(has_init, has_run, is_completed, pid, is_running, terminal_status)``
        六元组。

        Note:
            - has_init: checks init/init_config.json (simplified structure)
            - has_run: checks run/ directory exists
            - is_completed: checks run/replay/_schema.json exists
        """
        # Check for init_config.json directly in init/ (simplified structure)
        has_init = (exp_dir / "init" / "init_config.json").exists()
        has_run = (exp_dir / "run").exists()
        is_completed = (exp_dir / "run" / "replay" / "_schema.json").exists()

        pid = None
        is_running = False
        terminal_status: str | None = None
        pid_file = exp_dir / "run" / "pid.json"
        if pid_file.exists():
            try:
                import json
                import os

                pid_content = pid_file.read_text().strip()
                if pid_content:
                    pid_data = json.loads(pid_content)
                    pid = pid_data.get("pid")
                    pid_status = str(pid_data.get("status") or "").strip().lower()
                    if pid_status == "completed":
                        is_completed = True
                        terminal_status = "completed"
                    elif pid_status == "failed":
                        terminal_status = "failed"
                    if pid_status not in {"completed", "failed"} and pid:
                        try:
                            os.kill(pid, 0)
                            is_running = True
                        except OSError:
                            if pid_status == "running" and not is_completed:
                                pid = None
            except (ValueError, OSError, json.JSONDecodeError):
                logger.debug("Failed to read pid file for running check", exc_info=True)

        return has_init, has_run, is_completed, pid, is_running, terminal_status

    if hypothesis_id:
        hyp_dir = workspace_path / f"hypothesis_{hypothesis_id}"
        if hyp_dir.exists():
            for item in hyp_dir.iterdir():
                if item.is_dir() and item.name.startswith("experiment_"):
                    exp_id = item.name.replace("experiment_", "")
                    (
                        has_init,
                        has_run,
                        is_completed,
                        pid,
                        is_running,
                        terminal_status,
                    ) = _check_experiment_status(item)
                    experiments.append(
                        ExperimentInfo(
                            hypothesis_id=hypothesis_id,
                            experiment_id=exp_id,
                            has_init=has_init,
                            has_run=has_run,
                            status=(
                                "running"
                                if is_running
                                else (
                                    terminal_status
                                    or (
                                        "completed"
                                        if is_completed
                                        else "configured"
                                        if has_init
                                        else "not_initialized"
                                    )
                                )
                            ),
                            pid=pid,
                            is_running=is_running,
                        )
                    )
    else:
        for hyp_item in workspace_path.iterdir():
            if hyp_item.is_dir() and hyp_item.name.startswith("hypothesis_"):
                hyp_id = hyp_item.name.replace("hypothesis_", "")
                for exp_item in hyp_item.iterdir():
                    if exp_item.is_dir() and exp_item.name.startswith("experiment_"):
                        exp_id = exp_item.name.replace("experiment_", "")
                        (
                            has_init,
                            has_run,
                            is_completed,
                            pid,
                            is_running,
                            terminal_status,
                        ) = _check_experiment_status(exp_item)
                        experiments.append(
                            ExperimentInfo(
                                hypothesis_id=hyp_id,
                                experiment_id=exp_id,
                                has_init=has_init,
                                has_run=has_run,
                                status=(
                                    "running"
                                    if is_running
                                    else (
                                        terminal_status
                                        or (
                                            "completed"
                                            if is_completed
                                            else "configured"
                                            if has_init
                                            else "not_initialized"
                                        )
                                    )
                                ),
                                pid=pid,
                                is_running=is_running,
                            )
                        )

    return experiments
