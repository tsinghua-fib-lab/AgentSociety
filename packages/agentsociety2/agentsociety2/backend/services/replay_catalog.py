"""为 HTTP 回放接口读取数据集目录、执行查询并转换响应。"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder

from agentsociety2.storage.replay_metadata import SIMULATION_TIMELINE_DATASET_ID
from agentsociety2.storage.replay_reader import ReplayReader


def open_http_replay_reader(replay_dir: Path) -> ReplayReader:
    """创建请求专用读取器，限制并发短查询各自占用的线程数。"""
    return ReplayReader(replay_dir, threads=2)


def iter_timeline_datasets(datasets: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    """先返回仿真时间线，再返回旧回放使用的智能体或环境快照。"""
    fallback = []
    for dataset in datasets:
        if not (dataset.get("step_key") and dataset.get("time_key")):
            continue
        if dataset["dataset_id"] == SIMULATION_TIMELINE_DATASET_ID:
            yield dataset
            continue
        capabilities = dataset.get("capabilities", [])
        if (
            dataset.get("kind") == "entity_snapshot"
            and dataset.get("entity_key")
            and "agent_snapshot" in capabilities
        ):
            priority = 1 if "geo_point" in capabilities else 0
        elif dataset.get("kind") == "env_snapshot" and "env_snapshot" in capabilities:
            priority = 2
        else:
            continue
        fallback.append((priority, dataset["dataset_id"], dataset))
    if fallback:
        yield min(fallback, key=lambda item: (item[0], item[1]))[2]


def _loads_json(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default
    return default


def _get_column_map(dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {column["column_name"]: column for column in dataset.get("columns", [])}


def _normalize_dataset_value(column: dict[str, Any] | None, value: Any) -> Any:
    if value is None:
        return None
    sqlite_type = str((column or {}).get("sqlite_type") or "").upper()
    if sqlite_type == "JSON":
        return jsonable_encoder(_loads_json(value, value))
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", errors="ignore")
    return jsonable_encoder(value)


def normalize_dataset_row(
    dataset: dict[str, Any], row: dict[str, Any]
) -> dict[str, Any]:
    """按列定义将一行记录转换为可编码的 JSON 字典。"""

    column_map = _get_column_map(dataset)
    return {
        key: _normalize_dataset_value(column_map.get(key), value)
        for key, value in row.items()
    }


def _translate_reader_error(error: Exception) -> HTTPException:
    if isinstance(error, KeyError):
        return HTTPException(
            status_code=404, detail=f"Dataset '{error.args[0]}' not found"
        )
    if isinstance(error, ValueError):
        return HTTPException(status_code=400, detail=str(error))
    return HTTPException(status_code=500, detail=str(error))


async def _to_thread_http(func, *args, **kwargs):
    try:
        return await asyncio.to_thread(func, *args, **kwargs)
    except HTTPException:
        raise
    except (KeyError, ValueError) as e:
        raise _translate_reader_error(e) from e


async def load_dataset_catalog(reader: ReplayReader) -> list[dict[str, Any]]:
    """读取数据集目录及列定义。"""

    return await _to_thread_http(reader.load_dataset_catalog)


async def get_dataset_by_id(reader: ReplayReader, dataset_id: str) -> dict[str, Any]:
    """按标识查找数据集，未注册时返回 HTTP 404。"""
    try:
        return await asyncio.to_thread(reader.get_dataset_by_id, dataset_id)
    except KeyError as e:
        raise HTTPException(
            status_code=404, detail=f"Dataset '{dataset_id}' not found"
        ) from e


async def find_dataset_by_capability(
    reader: ReplayReader,
    capability: str,
    *,
    kind: str | None = None,
) -> dict[str, Any]:
    """查找支持指定能力的数据集，可进一步限定数据集类型。"""
    try:
        return await asyncio.to_thread(
            reader.find_dataset_by_capability, capability, kind=kind
        )
    except KeyError as e:
        raise HTTPException(
            status_code=404,
            detail=f"No replay dataset found for capability '{capability}'",
        ) from e


async def fetch_dataset_rows(
    reader: ReplayReader,
    dataset: dict[str, Any],
    *,
    order_by: str | None = None,
    desc: bool = False,
    step: int | None = None,
    entity_id: int | None = None,
    start_step: int | None = None,
    end_step: int | None = None,
    max_step: int | None = None,
    columns: list[str] | None = None,
    latest_per_entity: bool = False,
    limit: int | None = None,
    offset: int = 0,
) -> dict[str, Any]:
    """根据筛选条件读取数据行并转换为 JSON 可编码的值。"""

    return await _to_thread_http(
        reader.fetch_dataset_rows,
        dataset,
        order_by=order_by,
        desc=desc,
        step=step,
        entity_id=entity_id,
        start_step=start_step,
        end_step=end_step,
        max_step=max_step,
        columns=columns,
        latest_per_entity=latest_per_entity,
        limit=limit,
        offset=offset,
    )


async def count_dataset_rows(
    reader: ReplayReader,
    dataset: dict[str, Any],
    *,
    step: int | None = None,
    entity_id: int | None = None,
    start_step: int | None = None,
    end_step: int | None = None,
    max_step: int | None = None,
    latest_per_entity: bool = False,
) -> int:
    """按与行查询相同的筛选条件统计记录数。"""

    return await _to_thread_http(
        reader.count_dataset_rows,
        dataset,
        step=step,
        entity_id=entity_id,
        start_step=start_step,
        end_step=end_step,
        max_step=max_step,
        latest_per_entity=latest_per_entity,
    )


async def query_dataset_rows(
    reader: ReplayReader,
    dataset: dict[str, Any],
    *,
    page: int,
    page_size: int,
    order_by: str | None = None,
    desc: bool = False,
    step: int | None = None,
    entity_id: int | None = None,
    start_step: int | None = None,
    end_step: int | None = None,
    max_step: int | None = None,
    columns: list[str] | None = None,
    latest_per_entity: bool = False,
) -> dict[str, Any]:
    """读取一页记录，并返回筛选后的总行数。"""

    return await _to_thread_http(
        reader.query_dataset_rows,
        dataset,
        page=page,
        page_size=page_size,
        order_by=order_by,
        desc=desc,
        step=step,
        entity_id=entity_id,
        start_step=start_step,
        end_step=end_step,
        max_step=max_step,
        columns=columns,
        latest_per_entity=latest_per_entity,
    )


async def distinct_dataset_values(
    reader: ReplayReader,
    dataset: dict[str, Any],
    column: str,
    *,
    order: bool = True,
) -> list[Any]:
    """列出去重后的非空列值，可选择是否排序。"""
    return await _to_thread_http(reader.distinct_values, dataset, column, order=order)


async def count_dataset_distinct(
    reader: ReplayReader, dataset: dict[str, Any], column: str
) -> int:
    """统计该列不同非空值的数量。"""
    return await _to_thread_http(reader.count_distinct, dataset, column)


async def min_dataset_value(
    reader: ReplayReader, dataset: dict[str, Any], column: str
) -> Any:
    """读取列最小值；没有非空值时返回空值。"""
    return await _to_thread_http(reader.min_value, dataset, column)


async def max_dataset_value(
    reader: ReplayReader, dataset: dict[str, Any], column: str
) -> Any:
    """读取列最大值；没有非空值时返回空值。"""
    return await _to_thread_http(reader.max_value, dataset, column)


async def dataset_timeline_summary(
    reader: ReplayReader, dataset: dict[str, Any]
) -> tuple[int, Any, Any]:
    """在线程池中读取步数与时间范围，沿用回放查询的 HTTP 错误处理。"""
    return await _to_thread_http(reader.timeline_summary, dataset)
