"""
实验数据 API。

提供实验基本信息与产出文件查询。新 replay 写入格式为
``run/replay/_schema.json`` + sharded JSONL；实验统计通过
``agentsociety2.storage.ReplayReader`` 读取，不再访问 ``sqlite.db`` 。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from agentsociety2.backend.path_security import (
    require_safe_segment,
    resolve_artifact_path,
    resolve_experiment_dir,
    resolve_under_root,
)
from agentsociety2.logger import get_logger
from agentsociety2.storage.replay_metadata import AGENT_PROFILE_DATASET_CAPABILITY
from agentsociety2.storage.replay_reader import ReplayReader

logger = get_logger()

router = APIRouter(prefix="/experiments", tags=["experiments"])

_LOG_CANDIDATES = ("output.log", "stderr.log")
_DEFAULT_LOG_TAIL_LINES = 2000
_MAX_LOG_TAIL_LINES = 100_000
_LOG_READ_CHUNK = 64 * 1024


def _resolve_experiment_log_path(run_dir: Path, source: str) -> Path:
    """按请求的 source 选择 ``run/`` 下的日志文件。

    :param run_dir: 已信任的实验运行目录。
    :param source: 请求的日志来源名：``auto`` 、``output.log`` 或
        ``stderr.log`` 。
    :returns: 解析出的 ``run_dir`` 下已存在的日志文件路径。
    :raises HTTPException: ``source`` 不受支持或找不到匹配的日志文件时
        抛出。
    """
    # Select trusted literal filenames, never join the request value into a path.
    if source == "auto":
        names = _LOG_CANDIDATES
    elif source == "output.log":
        names = ("output.log",)
    elif source == "stderr.log":
        names = ("stderr.log",)
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported log source: {source}")
    for name in names:
        candidate = resolve_under_root(run_dir, name)
        if candidate.is_file():
            return candidate
    raise HTTPException(status_code=404, detail="Experiment log not found")


def read_log_tail(path: Path, *, tail: int) -> str:
    """返回 ``path`` 的最后 ``tail`` 行，无需加载整个文件。

    从 EOF 起按固定大小的块向前读取，直到找到足够的换行符（或到达文件
    开头）。适用于数 MB 的 ``output.log`` 文件。

    :param path: 日志文件路径。
    :param tail: 保留的尾部行数（必须 ``>= 1`` ）。
    :returns: 尾部文本；源文件以换行符结尾时保留最后的换行符。
    :raises ValueError: 当 ``tail < 1`` 时抛出。
    """
    if tail < 1:
        raise ValueError("tail must be >= 1")
    size = path.stat().st_size
    if size == 0:
        return ""

    newline_target = max(tail - 1, 0)
    chunks: list[bytes] = []
    newlines = 0
    with path.open("rb") as fh:
        pos = size
        while pos > 0 and newlines <= newline_target:
            read_size = min(_LOG_READ_CHUNK, pos)
            pos -= read_size
            fh.seek(pos)
            block = fh.read(read_size)
            chunks.append(block)
            newlines += block.count(b"\n")
            if pos == 0:
                break

    data = b"".join(reversed(chunks))
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if len(lines) > tail:
        lines = lines[-tail:]
    return "\n".join(lines) + ("\n" if text.endswith("\n") and lines else "")


class ExperimentInfo(BaseModel):
    """实验信息。"""

    experiment_id: str
    hypothesis_id: str
    status: str
    start_time: str | None = None
    end_time: str | None = None
    agent_count: int
    step_count: int


def _get_experiment_path(
    workspace_path: str,
    hypothesis_id: str,
    experiment_id: str,
) -> Path:
    """解析配置工作区下的实验目录。

    :param workspace_path: API 调用方提供的工作区根目录。
    :param hypothesis_id: 已校验的假设标识符。
    :param experiment_id: 已校验的实验标识符。
    :returns: 解析出的实验目录路径。
    :raises HTTPException: 任一路径组成部分逃逸出工作区根目录时抛出。
    """
    return resolve_experiment_dir(workspace_path, hypothesis_id, experiment_id)


def _list_agent_state_datasets(datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """从 replay 目录中返回确定性的 agent 快照候选数据集。

    :param datasets: replay 数据集目录条目。
    :returns: 按 capability 与 dataset_id 排序后的兼容条目。
    """
    items = [
        dataset
        for dataset in datasets
        if dataset.get("kind") == "entity_snapshot"
        and "agent_snapshot" in dataset.get("capabilities", [])
        and dataset.get("entity_key")
        and dataset.get("step_key")
    ]
    items.sort(
        key=lambda item: (
            0 if "geo_point" not in item.get("capabilities", []) else 1,
            item["dataset_id"],
        )
    )
    return items


def _get_agent_profile_dataset(
    datasets: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """选择首选的 agent profile 数据集。

    :param datasets: replay 数据集目录条目。
    :returns: 第一个兼容的 profile 数据集，无则返回 ``None`` 。
    """
    candidates = [
        dataset
        for dataset in datasets
        if AGENT_PROFILE_DATASET_CAPABILITY in dataset.get("capabilities", [])
        and dataset.get("entity_key")
    ]
    candidates.sort(key=lambda item: item["dataset_id"])
    return candidates[0] if candidates else None


def _get_timeline_dataset(datasets: list[dict[str, Any]]) -> dict[str, Any] | None:
    """选择用于计算 replay 步数的首选数据集。

    :param datasets: replay 数据集目录条目。
    :returns: 兼容的 agent 或环境快照数据集，无则返回 ``None`` 。
    """
    agent_datasets = [
        dataset
        for dataset in _list_agent_state_datasets(datasets)
        if dataset.get("step_key") and dataset.get("time_key")
    ]
    if agent_datasets:
        return agent_datasets[0]

    env_datasets = [
        dataset
        for dataset in datasets
        if dataset.get("kind") == "env_snapshot"
        and "env_snapshot" in dataset.get("capabilities", [])
        and dataset.get("step_key")
        and dataset.get("time_key")
    ]
    env_datasets.sort(key=lambda item: item["dataset_id"])
    return env_datasets[0] if env_datasets else None


def _read_replay_summary(replay_dir: Path) -> tuple[int, int]:
    """从当前 replay JSONL 数据返回 agent 数与步数。

    :param replay_dir: 包含 replay schema 与分片文件的目录。
    :returns: ``(agent_count, step_count)`` 。
    """

    reader = ReplayReader(replay_dir)
    try:
        datasets = reader.load_dataset_catalog()
        agent_count = 0
        profile_dataset = _get_agent_profile_dataset(datasets)
        if profile_dataset is not None and profile_dataset.get("entity_key"):
            agent_count = reader.count_distinct(
                profile_dataset, str(profile_dataset["entity_key"])
            )
        else:
            agent_state = _list_agent_state_datasets(datasets)
            if agent_state and agent_state[0].get("entity_key"):
                agent_count = reader.count_distinct(
                    agent_state[0], str(agent_state[0]["entity_key"])
                )

        step_count = 0
        timeline_dataset = _get_timeline_dataset(datasets)
        if timeline_dataset is not None and timeline_dataset.get("step_key"):
            step_count = reader.count_distinct(
                timeline_dataset, str(timeline_dataset["step_key"])
            )

        return agent_count, step_count
    finally:
        reader.close()


@router.get("/{hypothesis_id}/{experiment_id}/info")
async def get_experiment_info(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace directory path"),
) -> ExperimentInfo:
    """获取实验基本信息。

    返回指定实验的状态、开始/结束时间、Agent 数量和已执行 step 数。

    :param hypothesis_id: 假设标识符。
    :param experiment_id: 实验标识符。
    :param workspace_path: 包含实验数据的工作区根目录。
    :returns: 实验状态与 replay 摘要。
    :raises HTTPException: 标识符不安全或实验不存在时抛出。
    """
    # Validate path parameters at the API boundary
    require_safe_segment(hypothesis_id, field="hypothesis_id")
    require_safe_segment(experiment_id, field="experiment_id")
    exp_path = _get_experiment_path(workspace_path, hypothesis_id, experiment_id)

    if not exp_path.exists():
        raise HTTPException(status_code=404, detail="Experiment not found")

    run_dir = resolve_under_root(exp_path, "run")
    pid_file = run_dir / "pid.json"
    replay_dir = run_dir / "replay"

    status = "not_started"
    start_time = None
    end_time = None

    if pid_file.exists():
        try:
            pid_data = json.loads(pid_file.read_text(encoding="utf-8"))
            status = pid_data.get("status", "unknown")
            start_time = pid_data.get("start_time")
            end_time = pid_data.get("end_time")
        except Exception as e:
            logger.warning(f"Failed to read pid.json: {e}")

    agent_count = 0
    step_count = 0
    if replay_dir.is_dir() and (replay_dir / "_schema.json").is_file():
        try:
            agent_count, step_count = await asyncio.to_thread(
                _read_replay_summary, replay_dir
            )
        except Exception as e:
            logger.warning(f"Failed to query replay data: {e}")

    return ExperimentInfo(
        experiment_id=experiment_id,
        hypothesis_id=hypothesis_id,
        status=status,
        start_time=start_time,
        end_time=end_time,
        agent_count=agent_count,
        step_count=step_count,
    )


@router.get("/{hypothesis_id}/{experiment_id}/artifacts")
async def list_artifacts(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace directory path"),
) -> list[dict[str, str]]:
    """列出实验运行过程中生成的 Markdown 产出文件。

    :param hypothesis_id: 假设标识符。
    :param experiment_id: 实验标识符。
    :param workspace_path: 包含实验数据的工作区根目录。
    :returns: 生成的 Markdown 产出文件的元数据。
    :raises HTTPException: 标识符或解析出的路径不安全时抛出。
    """

    # Validate path parameters at the API boundary
    require_safe_segment(hypothesis_id, field="hypothesis_id")
    require_safe_segment(experiment_id, field="experiment_id")
    exp_path = _get_experiment_path(workspace_path, hypothesis_id, experiment_id)
    artifacts_dir = resolve_under_root(exp_path, "run", "artifacts")

    if not artifacts_dir.is_dir():
        return []

    artifacts = []
    for file_path in sorted(artifacts_dir.glob("*.md")):
        artifacts.append(
            {
                "name": file_path.name,
                "path": str(file_path),
                "type": "ask" if file_path.name.startswith("ask_") else "intervene",
            }
        )

    return artifacts


@router.get("/{hypothesis_id}/{experiment_id}/artifacts/{artifact_name}")
async def get_artifact(
    hypothesis_id: str,
    experiment_id: str,
    artifact_name: str,
    workspace_path: str = Query(..., description="Workspace directory path"),
) -> dict[str, str]:
    """获取指定 Markdown 产出文件内容。

    :param hypothesis_id: 假设标识符。
    :param experiment_id: 实验标识符。
    :param artifact_name: Markdown 产出文件名。
    :param workspace_path: 包含实验数据的工作区根目录。
    :returns: 产出文件名与 UTF-8 内容。
    :raises HTTPException: 产出文件路径不安全或不存在时抛出。
    """

    artifact_path = resolve_artifact_path(
        workspace_path, hypothesis_id, experiment_id, artifact_name
    )
    return {
        "name": artifact_name,
        "content": artifact_path.read_text(encoding="utf-8"),
    }


@router.get(
    "/{hypothesis_id}/{experiment_id}/log",
    response_class=PlainTextResponse,
)
async def get_experiment_log(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace directory path"),
    tail: int = Query(
        _DEFAULT_LOG_TAIL_LINES,
        ge=1,
        le=_MAX_LOG_TAIL_LINES,
        description="Return only the last N lines of the log",
    ),
    source: str = Query(
        "auto",
        description="Log file: auto | output.log | stderr.log",
    ),
) -> PlainTextResponse:
    """返回实验运行日志的尾部内容。

    :param hypothesis_id: 假设标识符。
    :param experiment_id: 实验标识符。
    :param workspace_path: 包含实验数据的工作区根目录。
    :param tail: 返回的尾部最大行数。
    :param source: 日志来源：``auto`` 、``output.log`` 或 ``stderr.log`` 。
    :returns: 包含所选日志尾部内容的纯文本响应。
    :raises HTTPException: 标识符、路径或来源无效，或运行目录/日志文件
        不存在时抛出。
    """

    require_safe_segment(hypothesis_id, field="hypothesis_id")
    require_safe_segment(experiment_id, field="experiment_id")
    exp_path = _get_experiment_path(workspace_path, hypothesis_id, experiment_id)
    run_dir = resolve_under_root(exp_path, "run")
    if not run_dir.is_dir():
        raise HTTPException(
            status_code=404, detail="Experiment run directory not found"
        )

    log_path = _resolve_experiment_log_path(run_dir, source)
    content = await asyncio.to_thread(read_log_tail, log_path, tail=tail)
    return PlainTextResponse(content)
