"""Replay-backed analysis summaries must expose real aggregates."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

import pytest

from agentsociety2.backend.services.replay_catalog import iter_timeline_datasets
from agentsociety2.skills.analysis.data import DataReader
from agentsociety2.society.society import AgentSociety
from agentsociety2.storage.replay_metadata import SIMULATION_TIMELINE_DATASET_ID
from agentsociety2.storage.replay_reader import ReplayReader


def _write_replay(
    root: Path,
    *,
    values: tuple[float | None, ...] = (1.0, 3.0, 2.0),
) -> Path:
    replay = root / "replay"
    replay.mkdir()
    dataset = {
        "dataset_id": "demo.metric",
        "table_name": "demo_metric",
        "kind": "event_stream",
        "default_order": ["step", "agent_id"],
        "columns": [
            {"name": "step", "type": "INTEGER"},
            {"name": "agent_id", "type": "INTEGER"},
            {"name": "condition", "type": "TEXT"},
            {"name": "value", "type": "REAL"},
        ],
    }
    (replay / "_schema.json").write_text(
        json.dumps({"datasets": {"demo.metric": dataset}}),
        encoding="utf-8",
    )
    rows = [
        {"step": 1, "agent_id": i, "condition": "a" if i < 3 else "b", "value": value}
        for i, value in enumerate(values, start=1)
    ]
    (replay / "demo_metric.aa.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )
    return replay


def test_replay_summary_reports_avg_and_top_value_counts(tmp_path: Path) -> None:
    summary = DataReader(_write_replay(tmp_path)).read_full_summary()

    value_stats = summary.numeric_stats["demo_metric"]["value"]
    assert value_stats["avg"] == 2.0
    condition_stats = summary.categorical_stats["demo_metric"]["condition"]
    assert condition_stats["top_values"] == [("a", 2), ("b", 1)]
    assert "avg=2.0" in summary.quick_stats
    assert "'a'(2)" in summary.quick_stats


def test_replay_summary_handles_all_null_numeric_column(tmp_path: Path) -> None:
    replay = _write_replay(tmp_path, values=(None, None, None))

    summary = DataReader(replay).read_full_summary()

    assert summary.numeric_stats["demo_metric"]["value"] == {
        "min": None,
        "max": None,
        "avg": None,
        "count": 3,
    }


def test_timeline_summary_matches_distinct_and_range_with_empty_or_repeated_steps(
    tmp_path,
):
    """一次聚合须与分别统计步数、最小值和最大值的结果一致。"""
    replay = _write_replay(tmp_path)
    reader = ReplayReader(replay, threads=2)
    try:
        dataset = reader.get_dataset_by_id("demo.metric")
        dataset.update(step_key="step", time_key="value")
        assert reader.timeline_summary(dataset) == (1, 1.0, 3.0)
    finally:
        reader.close()
    (replay / "demo_metric.aa.jsonl").unlink()
    reader = ReplayReader(replay)
    try:
        assert reader.timeline_summary(dataset) == (0, None, None)
    finally:
        reader.close()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile_ids, expected_count", [(["01", "1", "2"], 2), ([], 3)]
)
async def test_replay_overview_counts_profiles_or_falls_back_to_state(
    tmp_path, profile_ids, expected_count
):
    """兼容旧回放的字符串标识，并在画像数据为空时按状态计算。"""
    from agentsociety2.backend.routers.replay import _get_experiment_summary

    datasets = {}
    for name, ids, capability in (
        ("profiles", profile_ids, "agent_profile"),
        ("states", [2, 3, 4], "agent_snapshot"),
    ):
        datasets[name] = {
            "dataset_id": name,
            "table_name": name,
            "kind": "entity_snapshot",
            "entity_key": "agent_id",
            "step_key": "step",
            "capabilities": [capability],
            "columns": [
                {"name": "agent_id", "type": "TEXT"},
                {"name": "step", "type": "INTEGER"},
            ],
        }
        (tmp_path / f"{name}.aa.jsonl").write_text(
            "".join(json.dumps({"agent_id": i, "step": 1}) + "\n" for i in ids),
            encoding="utf-8",
        )
    (tmp_path / "_schema.json").write_text(
        json.dumps({"datasets": datasets}), encoding="utf-8"
    )
    reader = ReplayReader(tmp_path, threads=2)
    try:
        *_, count = await _get_experiment_summary(reader, reader.load_dataset_catalog())
    finally:
        reader.close()
    assert count == expected_count


def test_replay_catalog_invalidates_on_schema_change(tmp_path: Path) -> None:
    replay = tmp_path / "replay"
    replay.mkdir()
    schema = replay / "_schema.json"
    schema.write_text(
        json.dumps({"datasets": {"a": {"dataset_id": "a", "table_name": "a"}}}),
        encoding="utf-8",
    )
    reader = ReplayReader(replay)
    try:
        assert len(reader.load_dataset_catalog()) == 1
        previous = schema.stat()
        schema.write_text(
            json.dumps(
                {
                    "datasets": {
                        "a": {"dataset_id": "a", "table_name": "a"},
                        "b": {"dataset_id": "b", "table_name": "b"},
                    }
                }
            ),
            encoding="utf-8",
        )
        os.utime(schema, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        assert len(reader.load_dataset_catalog()) == 2
    finally:
        reader.close()


def test_live_replay_reader_sees_first_shard_and_reopens(tmp_path):
    (tmp_path / "_schema.json").write_text(
        json.dumps(
            {"datasets": {"events": {"columns": [{"name": "step", "type": "INTEGER"}]}}}
        )
    )
    reader = ReplayReader(tmp_path)
    try:
        (dataset,) = reader.load_dataset_catalog()
        assert reader.count_dataset_rows(dataset) == 0
        (tmp_path / "events.0.jsonl").write_text('{"step": 1}\n')
        assert reader.count_dataset_rows(dataset) == 1
        reader.close()
        assert reader.count_dataset_rows(dataset) == 1
    finally:
        reader.close()


def test_select_timeline_prefers_simulation_timeline() -> None:
    datasets = [
        {
            "dataset_id": "media.agent_state",
            "kind": "entity_snapshot",
            "capabilities": ["agent_snapshot", "timeseries"],
            "entity_key": "agent_id",
            "step_key": "step",
            "time_key": "t",
        },
        {
            "dataset_id": SIMULATION_TIMELINE_DATASET_ID,
            "kind": "env_snapshot",
            "capabilities": ["simulation_timeline", "env_snapshot", "timeseries"],
            "entity_key": None,
            "step_key": "step",
            "time_key": "t",
        },
    ]
    primary, legacy = iter_timeline_datasets(datasets)
    assert primary["dataset_id"] == SIMULATION_TIMELINE_DATASET_ID
    assert legacy["dataset_id"] == "media.agent_state"


def test_timeline_marker_is_idempotent_for_first_step() -> None:
    class _Writer:
        def __init__(self) -> None:
            self.rows: list[tuple[str, dict]] = []

        async def write(self, table: str, row: dict) -> None:
            self.rows.append((table, row))

    writer = _Writer()
    society = object.__new__(AgentSociety)
    society._replay_writer = writer
    society._simulation_timeline_ready = True
    society._last_timeline_step = None

    async def run() -> None:
        t = datetime(2026, 11, 21, 10, 0)
        await society._write_simulation_timeline_point(0, t)
        await society._write_simulation_timeline_point(0, t)
        await society._write_simulation_timeline_point(1, t)

    asyncio.run(run())

    assert [row["step"] for _, row in writer.rows] == [0, 1]


def test_pagination_counts_matches_before_projection_and_limit(tmp_path):
    reader = ReplayReader(_write_replay(tmp_path))
    try:
        dataset = reader.get_dataset_by_id("demo.metric")
        dataset.update(entity_key="agent_id", step_key="step")
        args = {"page_size": 2, "columns": ["value"], "latest_per_entity": True}
        first = reader.query_dataset_rows(dataset, page=1, **args)
        assert first == {
            "columns": ["value"],
            "rows": [{"value": 1.0}, {"value": 3.0}],
            "total": 3,
        }
        assert reader.query_dataset_rows(dataset, page=2, **args)["rows"] == [
            {"value": 2.0}
        ]
        assert reader.query_dataset_rows(dataset, page=3, **args) == {
            "columns": ["value"],
            "rows": [],
            "total": 3,
        }
        assert (
            reader.query_dataset_rows(dataset, page=1, step=100, **args)["total"] == 0
        )
    finally:
        reader.close()


def test_experiment_counts_authoritative_timeline_or_legacy_snapshots(tmp_path):
    from agentsociety2.backend.routers.experiments import _read_replay_summary

    replay = _write_replay(tmp_path)
    schema = replay / "_schema.json"
    datasets = json.loads(schema.read_text())["datasets"]
    snapshot = datasets["demo.metric"]
    snapshot.update(
        kind="entity_snapshot",
        capabilities=["agent_snapshot"],
        entity_key="agent_id",
        step_key="step",
        time_key="value",
    )
    core = dict(
        snapshot,
        dataset_id=SIMULATION_TIMELINE_DATASET_ID,
        table_name="timeline",
        kind="env_snapshot",
        capabilities=["env_snapshot"],
    )
    datasets[SIMULATION_TIMELINE_DATASET_ID] = core
    schema.write_text(json.dumps({"datasets": datasets}))
    assert _read_replay_summary(replay) == (3, 1)
    (replay / "timeline.00.jsonl").write_text(
        '{"step":1,"value":1}\n{"step":2,"value":2}\n'
    )
    assert _read_replay_summary(replay) == (3, 2)
