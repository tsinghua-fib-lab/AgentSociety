"""Tests for the distributed trace sink and the JsonlTraceWriter span API.

Trace is now distributed and lock-free: each writer holds its own
``ShardedAppendSink`` and appends directly via ``os.write(O_APPEND)`` into the
256 shard files keyed by ``trace_id[:2]`` (no central Ray actor). Oversized
string values are capped so every record fits below ``PIPE_BUF`` and a single
``write`` is atomic across concurrent writers.
"""

import json
from pathlib import Path

import pytest

from agentsociety2.trace import (
    JsonlTraceWriter,
    ShardedAppendSink,
    TraceProxy,
    build_local_sink,
)
from agentsociety2.trace.sharded_writer import _PIPE_BUF, _TRACE_VALUE_CAP


def _read_all_records(trace_dir: Path) -> list[dict]:
    records = []
    for path in sorted(trace_dir.glob("trace_*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
    return records


def test_sharded_append_sink_shards_by_trace_prefix(tmp_path):
    sink = ShardedAppendSink(tmp_path)
    sink.append_record({"trace_id": "ab" + "0" * 30, "i": 1})
    sink.append_record({"trace_id": "ff" + "0" * 30, "i": 2})
    sink.append_record({"trace_id": "ab" + "1" * 30, "i": 3})
    sink.close()

    assert sorted(p.name for p in tmp_path.glob("trace_*.jsonl")) == [
        "trace_ab.jsonl",
        "trace_ff.jsonl",
    ]
    ab = [
        json.loads(line)
        for line in (tmp_path / "trace_ab.jsonl").read_text().splitlines()
        if line.strip()
    ]
    assert [r["i"] for r in ab] == [1, 3]


def test_sharded_append_sink_caps_large_values_below_pipe_buf(tmp_path):
    pipe_buf = _PIPE_BUF
    value_cap = _TRACE_VALUE_CAP
    sink = ShardedAppendSink(tmp_path)
    original_len = 60000
    sink.append_record(
        {"trace_id": "00" + "0" * 30, "attr": {"msg": "Z" * original_len}}
    )
    sink.close()

    line = (tmp_path / "trace_00.jsonl").read_text()
    assert len(line) < pipe_buf, len(line)
    rec = json.loads(line)
    capped = rec["attr"]["msg"]
    assert capped.startswith("Z")
    expected_truncated = original_len - value_cap
    assert f"+{expected_truncated}B" in capped  # truncation marker kept


def test_trace_proxy_and_build_local_sink(tmp_path):
    assert build_local_sink(TraceProxy(trace_dir=None)) is None
    sink = build_local_sink(TraceProxy(trace_dir=str(tmp_path)))
    assert isinstance(sink, ShardedAppendSink)
    sink.append_record({"trace_id": "11" + "0" * 30, "x": 1})
    sink.close()
    assert _read_all_records(tmp_path)[0]["x"] == 1


def test_jsonl_trace_writer_span_context_and_parent_linking(tmp_path):
    writer = JsonlTraceWriter(agent_id=7, sharded_writer=ShardedAppendSink(tmp_path))

    with writer.trace_span("agent.step", trace_id="trace-ctx") as parent:
        assert writer.current_span is parent
        with writer.trace_span("react.loop") as react:
            assert writer.current_span is react
            assert react.trace_id == parent.trace_id
            assert react.parent_span_id == parent.span_id
            with writer.trace_span("workspace.read_text") as tool:
                assert tool.parent_span_id == react.span_id
            assert writer.current_span is react
        assert writer.current_span is parent
    assert writer.current_span is None

    writer.flush()
    writer.close()

    records = _read_all_records(tmp_path)
    # spans end innermost-first
    assert [r["name"] for r in records] == [
        "workspace.read_text",
        "react.loop",
        "agent.step",
    ]
    by_name = {r["name"]: r for r in records}
    assert by_name["workspace.read_text"]["parent_span_id"] == react.span_id
    assert by_name["react.loop"]["parent_span_id"] == parent.span_id
    assert by_name["agent.step"]["parent_span_id"] is None
    # sequence is monotonic across records
    seqs = [r["attributes"]["event.sequence"] for r in records]
    assert seqs == sorted(seqs)


def test_jsonl_trace_writer_otel_envelope(tmp_path):
    writer = JsonlTraceWriter(agent_id=31, sharded_writer=ShardedAppendSink(tmp_path))
    span = writer.start_span(
        "agent.step", trace_id="trace-1", attributes={"agent.tick": 1}
    )
    child = writer.start_span(
        "workspace.read_text",
        trace_id=span.trace_id,
        parent_span_id=span.span_id,
        attributes={"workspace.path": "x.txt"},
    )
    writer.end_span(child)
    writer.end_span(span)
    writer.close()

    records = _read_all_records(tmp_path)
    rec = records[0]
    assert rec["trace_id"] == span.trace_id
    assert rec["resource"]["service.name"] == "agentsociety2.person_agent"
    assert rec["scope"]["name"] == "agentsociety2.agent.runtime"
    assert rec["status"]["code"] == "ok"
    assert (
        rec["attributes"]["event.sequence"] < records[1]["attributes"]["event.sequence"]
    )


def test_sharded_append_sink_writes_through_jsonl_writer(tmp_path):
    """JsonlTraceWriter forwards finished spans to its ShardedAppendSink."""
    writer = JsonlTraceWriter(agent_id=40, sharded_writer=ShardedAppendSink(tmp_path))
    for i in range(10):
        span = writer.start_span(f"span.{i}", trace_id="trace-batch")
        writer.end_span(span)
    writer.flush()
    writer.close()

    records = _read_all_records(tmp_path)
    assert [r["name"] for r in records] == [f"span.{i}" for i in range(10)]


def test_trace_sink_caps_open_descriptors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENTSOCIETY_TRACE_MAX_FDS_PER_SINK", "8")
    sink = ShardedAppendSink(tmp_path)
    for index in range(40):
        sink.append_record(
            {"trace_id": f"{index:02x}" + "0" * 30, "name": f"span-{index}"}
        )
    try:
        assert len(sink._fds) <= 8
        assert len(list(tmp_path.glob("trace_*.jsonl"))) >= 40
    finally:
        sink.close()
    assert not sink._fds
