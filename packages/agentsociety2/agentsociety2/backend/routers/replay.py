"""查询实验回放数据。

为回放界面提供实验元信息、数据集目录与记录查询。底层读取接口见 :class:`agentsociety2.storage.ReplayReader`，数据布局见 :doc:`/storage`。"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from ...backend.path_security import resolve_experiment_replay_dir
from ...backend.services.replay_catalog import (
    count_dataset_distinct,
    fetch_dataset_rows,
    get_dataset_by_id,
    load_dataset_catalog,
    max_dataset_value,
    min_dataset_value,
    query_dataset_rows,
)
from ...storage.replay_metadata import AGENT_PROFILE_DATASET_CAPABILITY
from ...storage.replay_reader import ReplayReader

router = APIRouter(prefix="/replay", tags=["replay"])


class ExperimentInfo(BaseModel):
    hypothesis_id: str
    experiment_id: str
    total_steps: int
    start_time: datetime | None
    end_time: datetime | None
    agent_count: int
    run_status: str | None = None
    pid_step_count: int | None = None
    simulation_time: str | None = None
    registered_datasets: int = 0
    nonempty_snapshot_tables: int = 0


class TimelinePoint(BaseModel):
    step: int
    t: datetime


class AgentProfile(BaseModel):
    id: int
    name: str
    profile: dict[str, Any] = Field(default_factory=dict)


class ReplayDatasetColumn(BaseModel):
    column_name: str
    sqlite_type: str
    logical_type: str | None = None
    analysis_role: str | None = None
    title: str | None = None
    description: str | None = None
    unit: str | None = None
    nullable: bool
    enum_values: Any | None = None
    example: Any | None = None
    tags: list[str] = Field(default_factory=list)


class ReplayDatasetInfo(BaseModel):
    dataset_id: str
    table_name: str
    module_name: str
    kind: str
    title: str = ""
    description: str = ""
    entity_key: str | None = None
    step_key: str | None = None
    time_key: str | None = None
    default_order: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    version: int
    created_at: datetime
    columns: list[ReplayDatasetColumn] = Field(default_factory=list)


class ReplayDatasetList(BaseModel):
    datasets: list[ReplayDatasetInfo]


class ReplayDatasetRows(BaseModel):
    dataset_id: str
    columns: list[str]
    rows: list[dict[str, Any]]
    total: int


class ReplayPanelSchema(BaseModel):
    agent_profile_dataset: ReplayDatasetInfo | None = None
    agent_state_datasets: list[ReplayDatasetInfo] = Field(default_factory=list)
    env_state_datasets: list[ReplayDatasetInfo] = Field(default_factory=list)
    geo_dataset: ReplayDatasetInfo | None = None
    primary_agent_state_dataset_id: str | None = None
    layout_hint: Literal["map", "random"] = "random"
    supports_map: bool = False


class ReplayDatasetPanelRef(BaseModel):
    dataset_id: str
    module_name: str
    title: str = ""


class ReplayPosition(BaseModel):
    agent_id: int
    lng: float | None = None
    lat: float | None = None


class ReplayAgentStateAtStep(BaseModel):
    dataset: ReplayDatasetPanelRef
    rows_by_agent_id: dict[str, dict[str, Any]] = Field(default_factory=dict)


class ReplayEnvStateAtStep(BaseModel):
    dataset: ReplayDatasetPanelRef
    row: dict[str, Any] | None = None


class ReplayStepBundle(BaseModel):
    step: int
    t: datetime | None = None
    layout_hint: Literal["map", "random"] = "random"
    positions: list[ReplayPosition] = Field(default_factory=list)
    agent_state_rows: dict[str, ReplayAgentStateAtStep] = Field(default_factory=dict)
    env_state_rows: dict[str, ReplayEnvStateAtStep] = Field(default_factory=dict)


def get_replay_dir(workspace_path: str, hypothesis_id: str, experiment_id: str) -> Path:
    return resolve_experiment_replay_dir(workspace_path, hypothesis_id, experiment_id)


@asynccontextmanager
async def get_replay_reader(replay_dir: Path):
    reader = ReplayReader(replay_dir)
    try:
        yield reader
    finally:
        await asyncio.to_thread(reader.close)


def _dataset_to_response(dataset: dict[str, Any]) -> ReplayDatasetInfo:
    return ReplayDatasetInfo.model_validate(dataset)


def _dataset_ref(dataset: dict[str, Any]) -> ReplayDatasetPanelRef:
    return ReplayDatasetPanelRef(
        dataset_id=dataset["dataset_id"],
        module_name=dataset.get("module_name") or "",
        title=dataset.get("title") or "",
    )


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _dataset_has_columns(dataset: dict[str, Any], *column_names: str) -> bool:
    available = {column["column_name"] for column in dataset.get("columns", [])}
    return all(column_name in available for column_name in column_names)


def _split_columns_param(raw_columns: str | None) -> list[str] | None:
    if raw_columns is None:
        return None
    columns = [column.strip() for column in raw_columns.split(",") if column.strip()]
    return columns or None


def _list_agent_state_datasets(datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = [
        dataset
        for dataset in datasets
        if dataset.get("kind") == "entity_snapshot"
        and "agent_snapshot" in dataset.get("capabilities", [])
        and dataset.get("entity_key")
        and dataset.get("step_key")
    ]
    items.sort(key=lambda item: item["dataset_id"])
    return items


def _list_env_state_datasets(datasets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = [
        dataset
        for dataset in datasets
        if dataset.get("kind") == "env_snapshot"
        and "env_snapshot" in dataset.get("capabilities", [])
        and dataset.get("step_key")
    ]
    items.sort(key=lambda item: item["dataset_id"])
    return items


def _select_geo_dataset(datasets: list[dict[str, Any]]) -> dict[str, Any] | None:
    candidates = [
        dataset
        for dataset in _list_agent_state_datasets(datasets)
        if "geo_point" in dataset.get("capabilities", [])
        and _dataset_has_columns(dataset, "lng", "lat")
    ]
    candidates.sort(key=lambda item: item["dataset_id"])
    return candidates[0] if candidates else None


def _select_primary_agent_state_dataset(
    datasets: list[dict[str, Any]],
) -> dict[str, Any] | None:
    agent_state_datasets = _list_agent_state_datasets(datasets)
    if not agent_state_datasets:
        return None

    non_geo_candidates = [
        dataset
        for dataset in agent_state_datasets
        if "geo_point" not in dataset.get("capabilities", [])
    ]
    candidates = non_geo_candidates or agent_state_datasets
    candidates.sort(key=lambda item: item["dataset_id"])
    return candidates[0]


def _select_timeline_dataset(
    datasets: list[dict[str, Any]],
) -> dict[str, Any] | None:
    from ...storage.replay_metadata import SIMULATION_TIMELINE_DATASET_ID

    for dataset in datasets:
        if dataset.get("dataset_id") == SIMULATION_TIMELINE_DATASET_ID:
            if dataset.get("step_key") and dataset.get("time_key"):
                return dataset

    primary_agent_state = _select_primary_agent_state_dataset(datasets)
    if (
        primary_agent_state is not None
        and primary_agent_state.get("step_key")
        and primary_agent_state.get("time_key")
    ):
        return primary_agent_state

    agent_candidates = [
        dataset
        for dataset in _list_agent_state_datasets(datasets)
        if dataset.get("step_key") and dataset.get("time_key")
    ]
    agent_candidates.sort(
        key=lambda item: (
            0 if "geo_point" not in item.get("capabilities", []) else 1,
            item["dataset_id"],
        )
    )
    if agent_candidates:
        return agent_candidates[0]

    env_candidates = [
        dataset
        for dataset in _list_env_state_datasets(datasets)
        if dataset.get("step_key") and dataset.get("time_key")
    ]
    env_candidates.sort(key=lambda item: item["dataset_id"])
    return env_candidates[0] if env_candidates else None


def _find_time_value(
    rows: list[dict[str, Any]],
    time_key: str | None,
) -> datetime | None:
    if not time_key:
        return None
    for row in rows:
        timestamp = _coerce_datetime(row.get(time_key))
        if timestamp is not None:
            return timestamp
    return None


def _build_positions_from_step_rows(
    geo_dataset: dict[str, Any] | None,
    agent_state_groups: dict[str, ReplayAgentStateAtStep],
) -> list[ReplayPosition]:
    agent_ids: set[int] = set()
    for group in agent_state_groups.values():
        for raw_agent_id in group.rows_by_agent_id:
            try:
                agent_ids.add(int(raw_agent_id))
            except (TypeError, ValueError):
                continue

    positions_by_agent_id: dict[int, ReplayPosition] = {
        agent_id: ReplayPosition(agent_id=agent_id, lng=None, lat=None)
        for agent_id in sorted(agent_ids)
    }
    if geo_dataset is None:
        return list(positions_by_agent_id.values())

    geo_group = agent_state_groups.get(geo_dataset["dataset_id"])
    if geo_group is None:
        return list(positions_by_agent_id.values())

    for raw_agent_id, row in geo_group.rows_by_agent_id.items():
        try:
            agent_id = int(raw_agent_id)
        except (TypeError, ValueError):
            continue
        positions_by_agent_id[agent_id] = ReplayPosition(
            agent_id=agent_id,
            lng=row.get("lng"),
            lat=row.get("lat"),
        )
    return list(positions_by_agent_id.values())


async def _get_agent_profile_dataset(
    reader: ReplayReader,
    datasets: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    catalog = datasets or await load_dataset_catalog(reader)
    candidates = [
        dataset
        for dataset in catalog
        if AGENT_PROFILE_DATASET_CAPABILITY in dataset.get("capabilities", [])
        and dataset.get("entity_key")
    ]
    candidates.sort(key=lambda item: item["dataset_id"])
    return candidates[0] if candidates else None


def _parse_profile_payload(raw_profile: Any) -> dict[str, Any]:
    if isinstance(raw_profile, dict):
        return raw_profile
    if isinstance(raw_profile, str):
        try:
            decoded = json.loads(raw_profile)
        except json.JSONDecodeError:
            return {"raw": raw_profile}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _resolve_agent_name(
    agent_id: int, row: dict[str, Any], profile: dict[str, Any]
) -> str:
    name = row.get("name")
    if isinstance(name, str) and name.strip():
        return name
    profile_name = profile.get("name")
    if isinstance(profile_name, str) and profile_name.strip():
        return profile_name
    return f"Agent_{agent_id}"


async def _load_agent_profiles(
    reader: ReplayReader,
    datasets: list[dict[str, Any]] | None = None,
) -> dict[int, AgentProfile]:
    catalog = datasets or await load_dataset_catalog(reader)
    profile_dataset = await _get_agent_profile_dataset(reader, catalog)
    if profile_dataset is not None:
        entity_key = profile_dataset["entity_key"]
        rows_result = await fetch_dataset_rows(reader, profile_dataset)
        profiles: dict[int, AgentProfile] = {}
        for row in rows_result["rows"]:
            raw_id = row.get(entity_key)
            if raw_id is None:
                continue
            agent_id = int(raw_id)
            profile_payload = _parse_profile_payload(row.get("profile"))
            profiles[agent_id] = AgentProfile(
                id=agent_id,
                name=_resolve_agent_name(agent_id, dict(row), profile_payload),
                profile=profile_payload,
            )
        if profiles:
            return profiles

    identity_dataset = _select_primary_agent_state_dataset(catalog)
    if identity_dataset is None:
        return {}

    entity_key = identity_dataset["entity_key"]
    agent_ids = await asyncio.to_thread(
        reader.distinct_values, identity_dataset, entity_key, order=True
    )
    return {
        int(agent_id): AgentProfile(
            id=int(agent_id),
            name=f"Agent_{int(agent_id)}",
            profile={},
        )
        for agent_id in agent_ids
        if agent_id is not None
    }


async def _get_experiment_summary(
    reader: ReplayReader,
    datasets: list[dict[str, Any]],
) -> tuple[int, datetime | None, datetime | None, int]:
    timeline_dataset = _select_timeline_dataset(datasets)
    total_steps = 0
    start_time: datetime | None = None
    end_time: datetime | None = None

    if timeline_dataset is not None:
        step_key = timeline_dataset["step_key"]
        time_key = timeline_dataset["time_key"]
        total_steps = await count_dataset_distinct(reader, timeline_dataset, step_key)
        start_time = _coerce_datetime(
            await min_dataset_value(reader, timeline_dataset, time_key)
        )
        end_time = _coerce_datetime(
            await max_dataset_value(reader, timeline_dataset, time_key)
        )

    profiles = await _load_agent_profiles(reader, datasets)
    return int(total_steps), start_time, end_time, len(profiles)


@router.get("/{hypothesis_id}/{experiment_id}/info", response_model=ExperimentInfo)
async def get_experiment_info(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> ExperimentInfo:
    replay_dir = get_replay_dir(workspace_path, hypothesis_id, experiment_id)
    run_dir = replay_dir.parent
    pid_path = run_dir / "pid.json"

    run_status: str | None = None
    pid_step_count: int | None = None
    simulation_time: str | None = None
    if pid_path.is_file():
        try:
            pid_data = json.loads(pid_path.read_text(encoding="utf-8"))
            run_status = pid_data.get("status")
            raw_step = pid_data.get("step_count")
            pid_step_count = int(raw_step) if raw_step is not None else None
            simulation_time = pid_data.get("simulation_time")
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            run_status = None

    async with get_replay_reader(replay_dir) as reader:
        datasets = await load_dataset_catalog(reader)
        total_steps, start_time, end_time, agent_count = await _get_experiment_summary(
            reader, datasets
        )
        nonempty_snapshot_tables = 0
        for dataset in datasets:
            table = dataset.get("table_name")
            if not table:
                continue
            shard_glob = list(replay_dir.glob(f"{table}.*.jsonl"))
            if any(path.stat().st_size > 0 for path in shard_glob):
                nonempty_snapshot_tables += 1
        return ExperimentInfo(
            hypothesis_id=hypothesis_id,
            experiment_id=experiment_id,
            total_steps=total_steps,
            start_time=start_time,
            end_time=end_time,
            agent_count=agent_count,
            run_status=run_status,
            pid_step_count=pid_step_count,
            simulation_time=simulation_time,
            registered_datasets=len(datasets),
            nonempty_snapshot_tables=nonempty_snapshot_tables,
        )


@router.get(
    "/{hypothesis_id}/{experiment_id}/datasets", response_model=ReplayDatasetList
)
async def get_replay_datasets(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> ReplayDatasetList:
    replay_dir = get_replay_dir(workspace_path, hypothesis_id, experiment_id)

    async with get_replay_reader(replay_dir) as reader:
        datasets = await load_dataset_catalog(reader)
        return ReplayDatasetList(
            datasets=[_dataset_to_response(dataset) for dataset in datasets]
        )


@router.get(
    "/{hypothesis_id}/{experiment_id}/datasets/{dataset_id}",
    response_model=ReplayDatasetInfo,
)
async def get_replay_dataset(
    hypothesis_id: str,
    experiment_id: str,
    dataset_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> ReplayDatasetInfo:
    replay_dir = get_replay_dir(workspace_path, hypothesis_id, experiment_id)

    async with get_replay_reader(replay_dir) as reader:
        dataset = await get_dataset_by_id(reader, dataset_id)
        return _dataset_to_response(dataset)


@router.get(
    "/{hypothesis_id}/{experiment_id}/datasets/{dataset_id}/rows",
    response_model=ReplayDatasetRows,
)
async def get_replay_dataset_rows(
    hypothesis_id: str,
    experiment_id: str,
    dataset_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    order_by: str | None = Query(None),
    desc_order: bool = Query(False),
    step: int | None = Query(None, description="Exact step filter"),
    entity_id: int | None = Query(None, description="Exact entity filter"),
    start_step: int | None = Query(None, description="Start step (inclusive)"),
    end_step: int | None = Query(None, description="End step (inclusive)"),
    max_step: int | None = Query(None, description="Maximum step (inclusive)"),
    columns: str | None = Query(None, description="Comma-separated column whitelist"),
    latest_per_entity: bool = Query(
        False,
        description="Return only the latest row per entity",
    ),
) -> ReplayDatasetRows:
    replay_dir = get_replay_dir(workspace_path, hypothesis_id, experiment_id)

    async with get_replay_reader(replay_dir) as reader:
        dataset = await get_dataset_by_id(reader, dataset_id)
        rows = await query_dataset_rows(
            reader,
            dataset,
            page=page,
            page_size=page_size,
            order_by=order_by,
            desc=desc_order,
            step=step,
            entity_id=entity_id,
            start_step=start_step,
            end_step=end_step,
            max_step=max_step,
            columns=_split_columns_param(columns),
            latest_per_entity=latest_per_entity,
        )
        return ReplayDatasetRows(
            dataset_id=dataset_id,
            columns=rows["columns"],
            rows=rows["rows"],
            total=rows["total"],
        )


@router.get(
    "/{hypothesis_id}/{experiment_id}/panel-schema",
    response_model=ReplayPanelSchema,
)
async def get_replay_panel_schema(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> ReplayPanelSchema:
    replay_dir = get_replay_dir(workspace_path, hypothesis_id, experiment_id)

    async with get_replay_reader(replay_dir) as reader:
        datasets = await load_dataset_catalog(reader)
        agent_profile_dataset = await _get_agent_profile_dataset(reader, datasets)
        agent_state_datasets = _list_agent_state_datasets(datasets)
        env_state_datasets = _list_env_state_datasets(datasets)
        geo_dataset = _select_geo_dataset(datasets)
        primary_agent_state_dataset = _select_primary_agent_state_dataset(datasets)
        return ReplayPanelSchema(
            agent_profile_dataset=(
                _dataset_to_response(agent_profile_dataset)
                if agent_profile_dataset is not None
                else None
            ),
            agent_state_datasets=[
                _dataset_to_response(dataset) for dataset in agent_state_datasets
            ],
            env_state_datasets=[
                _dataset_to_response(dataset) for dataset in env_state_datasets
            ],
            geo_dataset=(
                _dataset_to_response(geo_dataset) if geo_dataset is not None else None
            ),
            primary_agent_state_dataset_id=(
                primary_agent_state_dataset["dataset_id"]
                if primary_agent_state_dataset is not None
                else None
            ),
            layout_hint="map" if geo_dataset is not None else "random",
            supports_map=geo_dataset is not None,
        )


@router.get(
    "/{hypothesis_id}/{experiment_id}/steps/{step}/bundle",
    response_model=ReplayStepBundle,
)
async def get_replay_step_bundle(
    hypothesis_id: str,
    experiment_id: str,
    step: int,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> ReplayStepBundle:
    replay_dir = get_replay_dir(workspace_path, hypothesis_id, experiment_id)

    async with get_replay_reader(replay_dir) as reader:
        datasets = await load_dataset_catalog(reader)
        agent_state_datasets = _list_agent_state_datasets(datasets)
        env_state_datasets = _list_env_state_datasets(datasets)
        geo_dataset = _select_geo_dataset(datasets)
        layout_hint: Literal["map", "random"] = (
            "map" if geo_dataset is not None else "random"
        )

        step_timestamp: datetime | None = None
        agent_state_rows: dict[str, ReplayAgentStateAtStep] = {}
        for dataset in agent_state_datasets:
            rows_result = await fetch_dataset_rows(reader, dataset, step=step)
            entity_key = dataset.get("entity_key")
            if not entity_key:
                continue
            rows_by_agent_id: dict[str, dict[str, Any]] = {}
            for row in rows_result["rows"]:
                raw_agent_id = row.get(entity_key)
                if raw_agent_id is None:
                    continue
                rows_by_agent_id[str(raw_agent_id)] = row
            agent_state_rows[dataset["dataset_id"]] = ReplayAgentStateAtStep(
                dataset=_dataset_ref(dataset),
                rows_by_agent_id=rows_by_agent_id,
            )
            if step_timestamp is None:
                step_timestamp = _find_time_value(
                    rows_result["rows"], dataset.get("time_key")
                )

        env_state_rows: dict[str, ReplayEnvStateAtStep] = {}
        for dataset in env_state_datasets:
            rows_result = await fetch_dataset_rows(reader, dataset, step=step, limit=1)
            row = rows_result["rows"][0] if rows_result["rows"] else None
            env_state_rows[dataset["dataset_id"]] = ReplayEnvStateAtStep(
                dataset=_dataset_ref(dataset),
                row=row,
            )
            if step_timestamp is None:
                step_timestamp = _find_time_value(
                    rows_result["rows"], dataset.get("time_key")
                )

        positions = _build_positions_from_step_rows(geo_dataset, agent_state_rows)
        return ReplayStepBundle(
            step=step,
            t=step_timestamp,
            layout_hint=layout_hint,
            positions=positions,
            agent_state_rows=agent_state_rows,
            env_state_rows=env_state_rows,
        )


@router.get(
    "/{hypothesis_id}/{experiment_id}/timeline", response_model=list[TimelinePoint]
)
async def get_timeline(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> list[TimelinePoint]:
    replay_dir = get_replay_dir(workspace_path, hypothesis_id, experiment_id)

    async with get_replay_reader(replay_dir) as reader:
        datasets = await load_dataset_catalog(reader)
        timeline_dataset = _select_timeline_dataset(datasets)
        if timeline_dataset is None:
            return []

        step_key = timeline_dataset["step_key"]
        time_key = timeline_dataset["time_key"]
        rows_result = await fetch_dataset_rows(
            reader,
            timeline_dataset,
            columns=[step_key, time_key],
            order_by=step_key,
        )
        by_step: dict[int, datetime] = {}
        for row in rows_result["rows"]:
            raw_step = row.get(step_key)
            timestamp = _coerce_datetime(row.get(time_key))
            if raw_step is None or timestamp is None:
                continue
            step_value = int(raw_step)
            current = by_step.get(step_value)
            if current is None or timestamp < current:
                by_step[step_value] = timestamp
        timeline: list[TimelinePoint] = []
        for step_value, timestamp in sorted(by_step.items()):
            timeline.append(TimelinePoint(step=int(step_value), t=timestamp))
        return timeline


@router.get(
    "/{hypothesis_id}/{experiment_id}/agents/profiles",
    response_model=list[AgentProfile],
)
async def get_agent_profiles(
    hypothesis_id: str,
    experiment_id: str,
    workspace_path: str = Query(..., description="Workspace root path"),
) -> list[AgentProfile]:
    replay_dir = get_replay_dir(workspace_path, hypothesis_id, experiment_id)

    async with get_replay_reader(replay_dir) as reader:
        datasets = await load_dataset_catalog(reader)
        profiles = await _load_agent_profiles(reader, datasets)
        return sorted(profiles.values(), key=lambda profile: profile.id)
