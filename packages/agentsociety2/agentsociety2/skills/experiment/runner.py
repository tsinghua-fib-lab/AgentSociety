"""实验运行器模块

提供实验的停止与状态监控功能。真正的仿真启动由
``agentsociety2.society.cli`` 或扩展脚本负责；本模块不伪造启动行为。
"""

from __future__ import annotations

import json
from itertools import pairwise
from pathlib import Path
from typing import Any

import psutil

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
    """校验启动输入并返回运行路径，供调用方启动实验。

    :param workspace_path: 工作区目录路径
    :param hypothesis_id: 假设 ID（如 '1'、'2'）
    :param experiment_id: 实验 ID（如 '1'、'2'）
    :param run_id: 运行 ID（默认 'run'）
    :param init_config_path: ``init_config.json`` 的可选路径（默认 ``init/init_config.json``）
    :param steps_path: steps.yaml 的可选路径（默认 init/steps.yaml）

    :returns: 包含状态与信息的结果字典
    """
    from agentsociety2.skills.experiment.config import get_experiment_paths

    exp_paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id, run_id)

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
    """停止正在运行的实验

    :param workspace_path: 工作区目录路径
    :param hypothesis_id: 假设 ID
    :param experiment_id: 实验 ID
    :param run_id: 运行 ID（默认 'run'）

    :returns: 包含状态的结果字典
    """
    from agentsociety2.skills.experiment.config import get_experiment_paths

    exp_paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id, run_id)

    # Check for PID file and attempt to stop the process
    pid_file = exp_paths["pid_file"]
    stopped = False
    failure: str | None = None
    if pid_file.exists():
        try:
            pid_data = json.loads(pid_file.read_text())
            pid = pid_data.get("pid")
            if pid and pid_data.get("status") not in _TERMINAL_STATUSES:
                process = _experiment_process(
                    int(pid), exp_paths["run"].resolve(), pid_data
                )
                if process is None:
                    failure = "pid.json does not belong to this experiment; refusing to signal"
                else:
                    process.terminate()
                    stopped = True
        except (TypeError, ValueError, OSError, psutil.Error) as exc:
            failure = f"failed to read pid file: {exc}"
            logger.debug("Failed to read pid file", exc_info=True)

    if failure:
        return {
            "success": False,
            "error": failure,
            "content": f"Experiment {experiment_id} was not stopped: {failure}",
            "hypothesis_id": hypothesis_id,
            "experiment_id": experiment_id,
            "run_id": run_id,
        }
    return {
        "success": True,
        "content": f"Experiment {experiment_id} stopped (PID terminated)"
        if stopped
        else f"No running process recorded for experiment {experiment_id}",
        "hypothesis_id": hypothesis_id,
        "experiment_id": experiment_id,
        "run_id": run_id,
    }


_TERMINAL_STATUSES = {"completed", "completed_with_errors", "failed", "terminated"}


def _experiment_process(
    pid: int, run_dir: Path, pid_data: dict[str, Any]
) -> psutil.Process | None:
    """Find the simulator process whose arguments select this exact run directory."""
    try:
        if pid <= 0 or (
            pid_data.get("run_dir") and Path(pid_data["run_dir"]).resolve() != run_dir
        ):
            return None
        process = psutil.Process(pid)
        argv = process.cmdline()
        module = any(
            pair == ("-m", "agentsociety2.society.cli") for pair in pairwise(argv)
        )
        entrypoint = any(
            Path(arg).stem in {"agentsociety", "agentsociety-script"}
            for arg in argv[:2]
        )
        if not (module or entrypoint):
            return None
        selected = "."  # CLI default
        for index, arg in enumerate(argv):
            if arg == "--run-dir" and index + 1 < len(argv):
                selected = argv[index + 1]
            elif arg.startswith("--run-dir="):
                selected = arg.split("=", 1)[1]
        if selected and (Path(process.cwd()) / selected).resolve() == run_dir:
            return process
    except (OSError, TypeError, ValueError, psutil.Error):
        pass
    return None


async def get_experiment_status(
    workspace_path: Path,
    hypothesis_id: str,
    experiment_id: str,
    run_id: str = "run",
) -> ExperimentStatus:
    """获取实验状态

    :param workspace_path: 工作区目录路径
    :param hypothesis_id: 假设 ID
    :param experiment_id: 实验 ID
    :param run_id: 运行 ID（默认 'run'）

    :returns: ExperimentStatus 对象
    """
    from agentsociety2.skills.experiment.config import get_experiment_paths

    exp_paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id, run_id)

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
                pid_data = json.loads(pid_content)
                pid = pid_data.get("pid")
                pid_status = str(pid_data.get("status") or "").strip().lower()
                start_time = pid_data.get("start_time") or pid_data.get("started_at")
                end_time = pid_data.get("end_time")

                if pid_status:
                    status = pid_status
                if pid and pid_status not in _TERMINAL_STATUSES:
                    is_running = (
                        _experiment_process(
                            int(pid), exp_paths["run"].resolve(), pid_data
                        )
                        is not None
                    )
                    if is_running:
                        status = "running"
                    elif pid_status == "running":
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
    """列出实验

    :param workspace_path: 工作区目录路径
    :param hypothesis_id: 可选的过滤用假设 ID
    :returns: ExperimentInfo 对象列表

    Note:
        使用简化 init 结构：``init/init_config.json``、init/steps.yaml
    """
    experiments: list[ExperimentInfo] = []

    def _check_experiment_status(
        exp_dir: Path,
    ) -> tuple[bool, bool, bool, int | None, bool, str | None]:
        """检查实验状态的辅助函数。

        :returns: ``(has_init, has_run, is_completed, pid, is_running, terminal_status)``
        六元组。

        Note:
            - ``has_init``: 检查 ``init/init_config.json``（简化结构）
            - ``has_run``: 检查 run/ 目录是否存在
            - ``is_completed``: 检查 ``run/replay/_schema.json`` 是否存在
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
                pid_content = pid_file.read_text().strip()
                if pid_content:
                    pid_data = json.loads(pid_content)
                    pid = pid_data.get("pid")
                    pid_status = str(pid_data.get("status") or "").strip().lower()
                    if pid_status in _TERMINAL_STATUSES:
                        terminal_status = pid_status
                    elif pid:
                        is_running = (
                            _experiment_process(
                                int(pid), pid_file.parent.resolve(), pid_data
                            )
                            is not None
                        )
                        if pid_status == "running" and not is_running:
                            terminal_status = "failed"
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
