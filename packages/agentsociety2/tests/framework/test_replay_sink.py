"""Tests for the distributed append-only replay sink.

Replay writes go to sharded JSONL files (``<table>.<shard>.jsonl``) via
``os.write(O_APPEND)`` with an ``flock`` guard per shard so rows of any size
survive concurrent writers. Schema/dataset metadata is merged into a
``_schema.json`` sidecar.
"""

import json
import multiprocessing as mp
import shutil
from datetime import datetime
from pathlib import Path

import pytest

from agentsociety2.storage.replay_metadata import ReplayDatasetSpec
from agentsociety2.storage.replay_proxy import ReplayProxy
from agentsociety2.storage.replay_sink import _NUM_SHARDS, ReplaySink, build_replay_sink
from agentsociety2.storage.table_schema import ColumnDef, TableSchema


def _read_table(replay_dir: Path, table: str) -> list[dict]:
    rows = []
    for path in sorted(replay_dir.glob(f"{table}.*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
    return rows


def test_write_appends_and_normalizes(tmp_path):
    sink = ReplaySink(tmp_path)
    sink_sync = sink  # write is async but body is sync; drive via asyncio
    import asyncio

    asyncio.run(
        sink_sync.write(
            "t",
            {"id": 1, "when": datetime(2020, 1, 1, 12, 0, 0), "blob": {"a": 1}},
        )
    )
    asyncio.run(sink_sync.write("t", {"id": 2, "when": datetime(2021, 1, 1)}))
    asyncio.run(sink_sync.close())

    rows = sorted(_read_table(tmp_path, "t"), key=lambda r: r["id"])
    assert [r["id"] for r in rows] == [1, 2]
    assert rows[0]["when"] == "2020-01-01T12:00:00"  # datetime -> ISO
    assert json.loads(rows[0]["blob"]) == {"a": 1}  # dict -> JSON string


def test_write_batch(tmp_path):
    import asyncio

    sink = ReplaySink(tmp_path)
    asyncio.run(sink.write_batch("t", [{"id": i} for i in range(50)]))
    asyncio.run(sink.close())
    rows = _read_table(tmp_path, "t")
    assert sorted(r["id"] for r in rows) == list(range(50))


def test_disabled_is_noop(tmp_path):
    import asyncio

    sink = ReplaySink(tmp_path, enabled=False)
    asyncio.run(sink.write("t", {"id": 1}))
    asyncio.run(sink.close())
    assert list(tmp_path.glob("*.jsonl")) == []


def test_schema_sidecar_registers_table_and_dataset(tmp_path):
    import asyncio

    sink = ReplaySink(tmp_path)
    schema = TableSchema(
        name="core_agent_profile",
        columns=[
            ColumnDef("id", "INTEGER", nullable=False),
            ColumnDef("name", "TEXT"),
        ],
        primary_key=["id"],
    )
    spec = ReplayDatasetSpec(
        dataset_id="core.agent_profile",
        table_name="core_agent_profile",
        module_name="AgentSociety",
        kind="entity_static",
        entity_key="id",
        default_order=["id"],
        capabilities=["agent_profile"],
    )
    asyncio.run(sink.register_table(schema))
    asyncio.run(sink.register_dataset(spec, schema.columns))
    asyncio.run(sink.close())

    catalog = json.loads((tmp_path / "_schema.json").read_text())
    assert catalog["tables"]["core_agent_profile"]["primary_key"] == ["id"]
    ds = catalog["datasets"]["core.agent_profile"]
    assert ds["entity_key"] == "id"
    assert ds["capabilities"] == ["agent_profile"]
    assert [c["name"] for c in ds["columns"]] == ["id", "name"]


def test_schema_merge_is_idempotent(tmp_path):
    import asyncio

    sink_a = ReplaySink(tmp_path)
    asyncio.run(
        sink_a.register_dataset(
            ReplayDatasetSpec(
                dataset_id="d1",
                table_name="t1",
                module_name="m",
                kind="entity_static",
            ),
            [ColumnDef("id", "INTEGER")],
        )
    )
    asyncio.run(sink_a.close())

    sink_b = ReplaySink(tmp_path)  # new process/instance -> re-reads sidecar
    asyncio.run(
        sink_b.register_dataset(
            ReplayDatasetSpec(
                dataset_id="d2",
                table_name="t2",
                module_name="m",
                kind="event_stream",
            ),
            [ColumnDef("id", "INTEGER")],
        )
    )
    asyncio.run(sink_b.close())

    catalog = json.loads((tmp_path / "_schema.json").read_text())
    assert set(catalog["datasets"]) == {"d1", "d2"}


def test_proxy_disabled_and_no_dir(tmp_path):
    import asyncio

    assert build_replay_sink(ReplayProxy(replay_dir=None)) is None
    assert build_replay_sink(ReplayProxy(replay_dir=str(tmp_path), enabled=False)) is None
    proxy = ReplayProxy(replay_dir=str(tmp_path), enabled=False)
    asyncio.run(proxy.write("t", {"id": 1}))  # no-op, no files
    assert list(tmp_path.glob("*.jsonl")) == []


def _worker_write(replay_dir: str, table: str, n: int, big: bool):
    import asyncio

    sink = ReplaySink(replay_dir)
    for i in range(n):
        row = {"id": i, "payload": ("X" * 60000) if (big and i % 10 == 0) else "ok"}
        asyncio.run(sink.write(table, row))
    asyncio.run(sink.close())


def test_concurrent_multi_process_large_rows_no_corruption(tmp_path):
    """N processes append to the same table (incl. 60KB rows) — flock keeps
    every line intact, no interleaving."""
    shutil.rmtree(tmp_path, ignore_errors=True)
    tmp_path.mkdir()
    NW, N = 8, 300
    procs = [mp.Process(target=_worker_write, args=(str(tmp_path), "t", N, True)) for _ in range(NW)]
    for p in procs:
        p.start()
    for p in procs:
        p.join()

    rows = _read_table(tmp_path, "t")
    expected = NW * N
    assert len(rows) == expected  # no lost/corrupted lines
    # every row parses and the big payloads survived at full length
    big_rows = [r for r in rows if len(r.get("payload", "")) > 10]
    assert big_rows and all(r["payload"] == "X" * 60000 for r in big_rows)
    # sharding is bounded
    assert len(list(tmp_path.glob("t.*.jsonl"))) <= _NUM_SHARDS


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
