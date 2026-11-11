"""OTel-compatible tracing for AgentSociety2.

Two pieces:

* :class:`JsonlTraceWriter` — the span API (one instance per agent / per env
  router). Builds OTel spans (start / end / nested context) and forwards each
  finished span as one JSONL record to a sharded backend.
* :class:`ShardedAppendSink` — the distributed, lock-free backend. Each writer
  process holds its own instance and appends directly via
  ``os.open(O_APPEND)`` + ``os.write`` into the (at most 256) shard files keyed
  by ``trace_id[:2]``. No central Ray actor, so it cannot deadlock; the file
  count is constant regardless of agent count.

Each span is emitted as one JSON line with ``resource``, ``scope``,
``trace_id``, ``span_id``, ``parent_span_id``, timing, status, and attributes.
"""

from __future__ import annotations

import json
import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentsociety2.trace.span import TraceSpan


def new_trace_id() -> str:
    """Generate a 32-character lowercase hex UUID for use as ``trace_id``."""
    return uuid.uuid4().hex


def _new_span_id() -> str:
    """Generate a 16-character lowercase hex span ID."""
    return uuid.uuid4().hex[:16]


# ---------------------------------------------------------------------------
# Distributed append-only sink (replaces the central TraceActor)
# ---------------------------------------------------------------------------

# Truncation limits individual string values in lightweight trace records;
# full experiment data lives in replay datasets. PIPE_BUF is only a historical
# sizing heuristic here: it does not bound an entire serialized JSON record or
# establish atomic-write guarantees for regular files and shared filesystems.
# pathconf is POSIX-only; Windows has neither os.pathconf nor pathconf_names.
try:
    _PIPE_BUF = os.pathconf("/", os.pathconf_names["PC_PIPE_BUF"])
except (AttributeError, OSError, ValueError, KeyError):
    _PIPE_BUF = 4096
# Leave headroom for the JSON envelope (keys/timing/attrs dict) around the
# largest capped value.
_TRACE_VALUE_CAP = max(256, _PIPE_BUF // 2 - 256)


def _cap_large(value: Any, limit: int = _TRACE_VALUE_CAP) -> Any:
    """Recursively truncate oversized strings, without bounding total JSON size."""
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return value[:limit] + f"…<+{len(value) - limit}B>"
    if isinstance(value, dict):
        return {k: _cap_large(v, limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_cap_large(v, limit) for v in value]
    return value


@dataclass
class TraceProxy:
    """分布式追踪的可序列化配置。

    仅保存输出目录 ``trace_dir``，不携带 Ray actor 句柄。智能体、环境路由和驱动进程分别创建本地 :class:`ShardedAppendSink` 并直接写入；``trace_dir`` 为 ``None`` 时不记录追踪数据。
    """

    trace_dir: str | None = None


class ShardedAppendSink:
    """按 ``trace_id[:2]`` 分片的 JSONL 追踪写入器，最多生成 256 个分片文件。

    每个进程维护自己的实例，通过 ``os.open(O_APPEND)`` 和 ``os.write`` 追加记录，不需要集中式 actor。分片数量不随智能体数量增加；并发追加的行为取决于底层文件系统，管道的 ``PIPE_BUF`` 原子写入保证不适用于普通文件。

    ``_cap_large`` 会截断过长字符串，以减少追踪数据量。它限制单个值的长度，不限制整条记录编码后的总大小。
    """

    def __init__(
        self, trace_dir: str | Path, *, value_cap: int = _TRACE_VALUE_CAP
    ) -> None:
        self._base = Path(trace_dir)
        self._base.mkdir(parents=True, exist_ok=True)
        self._cap = value_cap
        self._fds: dict[str, int] = {}
        self._lock = threading.Lock()

    def _ensure_fd(self, key: str) -> None:
        if key in self._fds:
            return
        with self._lock:
            if key not in self._fds:
                path = self._base / f"trace_{key}.jsonl"
                # Cached descriptor is owned by this writer and released by close().
                # codeql[py/file-not-closed]
                fd = os.open(str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
                self._fds[key] = fd

    def append_record(self, record: dict[str, Any]) -> None:
        """Append one JSONL record to the shard keyed by ``trace_id[:2]``.

        Writes go straight to the kernel page cache via ``os.write`` (no
        userspace buffer), so there is nothing to flush. String values are
        capped before encoding; partial writes are retried below.
        """
        rec = _cap_large(record, self._cap) if self._cap else record
        key = str(rec.get("trace_id", ""))[:2].lower() or "00"
        data = (json.dumps(rec, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        self._ensure_fd(key)
        fd = self._fds[key]
        mv = memoryview(data)
        # Retry partial writes; a whole record may require multiple writes.
        while mv:
            n = os.write(fd, mv)
            mv = mv[n:]

    def flush(self) -> None:
        """No-op: writes are unbuffered (raw ``os.write`` to the page cache)."""
        return

    def close(self) -> None:
        """Close all open shard file descriptors."""
        for fd in self._fds.values():
            try:
                os.close(fd)
            except OSError:
                import logging

                logging.getLogger(__name__).debug(
                    "Failed to close shard fd", exc_info=True
                )
        self._fds.clear()


def build_local_sink(trace_proxy: Any) -> ShardedAppendSink | None:
    """根据 :class:`TraceProxy` 创建当前进程的 :class:`ShardedAppendSink`。

    未设置 ``trace_dir`` 时返回 ``None``，表示追踪功能已关闭。
    """
    trace_dir = getattr(trace_proxy, "trace_dir", None)
    if not trace_dir:
        return None
    return ShardedAppendSink(trace_dir)


# ---------------------------------------------------------------------------
# Span API (JsonlTraceWriter)
# ---------------------------------------------------------------------------


class JsonlTraceWriter:
    """通过分片写入器记录 OpenTelemetry 兼容的 JSONL 追踪片段。

    完成的片段发送到 ``sharded_writer``；生产环境通常使用 :class:`ShardedAppendSink`。当写入器为 ``None`` 时仍可创建片段，但不会保存记录。

    Parameters
    ----------
    agent_id : int
        所属智能体的 ID。
    service_name : str
        OpenTelemetry 的 ``resource.service.name`` 字段。
    scope_name : str
        OpenTelemetry 的 ``scope.name`` 字段。
    scope_version : str
        OpenTelemetry 的 ``scope.version`` 字段。
    sharded_writer : ShardedAppendSink | None
        底层写入器；为 ``None`` 时不保存记录。
    """

    def __init__(
        self,
        *,
        agent_id: int,
        service_name: str = "agentsociety2.person_agent",
        scope_name: str = "agentsociety2.agent.runtime",
        scope_version: str = "1",
        sharded_writer: ShardedAppendSink | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.service_name = service_name
        self.scope_name = scope_name
        self.scope_version = scope_version
        self._sharded: ShardedAppendSink | None = sharded_writer
        self._sequence = 0
        self._span_stack: ContextVar[tuple[TraceSpan, ...]] = ContextVar(
            f"agentsociety2_trace_stack_{agent_id}_{id(self)}",
            default=(),
        )

    def start_span(
        self,
        name: str,
        *,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> TraceSpan:
        """Create a new :class:`TraceSpan`.

        If ``trace_id`` is not provided it is inherited from the current parent
        span, or auto-generated as a UUID hex string.
        """
        parent = self.current_span
        self._sequence += 1
        return TraceSpan(
            trace_id=trace_id or (parent.trace_id if parent else new_trace_id()),
            span_id=_new_span_id(),
            parent_span_id=(
                parent_span_id
                if parent_span_id is not None
                else (parent.span_id if parent else None)
            ),
            name=name,
            start_time_unix_nano=time.time_ns(),
            attributes=attributes or {},
        )

    @contextmanager
    def trace_span(
        self,
        name: str,
        *,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
        attributes: dict[str, Any] | None = None,
        end_attributes: dict[str, Any] | None = None,
    ) -> Iterator[TraceSpan]:
        """Context manager: create a span, yield it, then end & write it."""
        span = self.start_span(
            name,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            attributes=attributes,
        )
        stack = self._span_stack.get()
        token = self._span_stack.set((*stack, span))
        try:
            yield span
        except Exception as exc:
            self.end_span(
                span,
                status="error",
                message=str(exc),
                attributes=end_attributes,
            )
            raise
        else:
            self.end_span(span, attributes=end_attributes)
        finally:
            self._span_stack.reset(token)

    def record_event(
        self,
        name: str,
        attributes: dict[str, Any] | None = None,
        *,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> None:
        """Write a single-point event (zero-duration span)."""
        span = self.start_span(
            name,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            attributes=attributes,
        )
        self.end_span(span)

    def end_span(
        self,
        span: TraceSpan,
        *,
        status: str = "ok",
        message: str = "",
        attributes: dict[str, Any] | None = None,
    ) -> None:
        """End *span* and write the OTel JSONL record."""
        merged = dict(span.attributes)
        if attributes:
            merged.update(attributes)
        self.append_record(
            {
                "resource": {
                    "service.name": self.service_name,
                    "agent.id": self.agent_id,
                },
                "scope": {
                    "name": self.scope_name,
                    "version": self.scope_version,
                },
                "trace_id": span.trace_id,
                "span_id": span.span_id,
                "parent_span_id": span.parent_span_id,
                "name": span.name,
                "kind": "internal",
                "start_time_unix_nano": span.start_time_unix_nano,
                "end_time_unix_nano": time.time_ns(),
                "status": {"code": status, "message": message},
                "attributes": merged,
                "events": span.events,
            }
        )

    def append_record(self, record: dict[str, Any]) -> None:
        """Append a raw JSONL record to the sharded writer."""
        if "attributes" not in record or not isinstance(record["attributes"], dict):
            record["attributes"] = {}
        self._sequence += 1
        record["attributes"].setdefault("event.sequence", self._sequence)
        if self._sharded is not None:
            self._sharded.append_record(record)

    def flush(self) -> None:
        """Flush buffered records to disk (no-op for the append sink)."""
        if self._sharded is not None:
            self._sharded.flush()

    def close(self) -> None:
        """Close the sharded writer (closes shard fds)."""
        if self._sharded is not None:
            self._sharded.close()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def sequence(self) -> int:
        """Return the current sequence counter."""
        return self._sequence

    @property
    def current_span(self) -> TraceSpan | None:
        """Return the innermost active span, or ``None``."""
        stack = self._span_stack.get()
        return stack[-1] if stack else None
