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

# Under O_APPEND the kernel makes a single write() of <= PIPE_BUF bytes atomic
# across concurrent writers. We cap every record below PIPE_BUF so no lock and
# no central actor is needed. Truncation targets attribute VALUES (e.g. large
# observation/summary blobs) — full data lives in the replay DB; trace only
# carries lightweight spans for timing/structure analysis.
# pathconf is POSIX-only; Windows has neither os.pathconf nor pathconf_names.
try:
    _PIPE_BUF = os.pathconf("/", os.pathconf_names["PC_PIPE_BUF"])
except (AttributeError, OSError, ValueError, KeyError):
    _PIPE_BUF = 4096
# Leave headroom for the JSON envelope (keys/timing/attrs dict) around the
# largest capped value.
_TRACE_VALUE_CAP = max(256, _PIPE_BUF // 2 - 256)


def _cap_large(value: Any, limit: int = _TRACE_VALUE_CAP) -> Any:
    """Recursively truncate oversized string values so a record serializes
    below PIPE_BUF, keeping O_APPEND writes atomic."""
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
    """Serializable config for distributed trace writing.

    Carries only the output directory (a path string) — no Ray actor handle.
    Each consumer (agent / env router / driver) builds its own
    :class:`ShardedAppendSink` pointed at ``trace_dir`` and appends directly,
    so there is no central trace actor to deadlock against. When ``trace_dir``
    is ``None`` the proxy is a no-op.
    """

    trace_dir: str | None = None


class ShardedAppendSink:
    """Append-only JSONL trace sink sharded by ``trace_id[:2]`` (256 files).

    Distributed and lock-free: every writer process holds its OWN instance and
    appends directly via ``os.open(O_APPEND)`` + ``os.write``. The kernel
    guarantees an ``O_APPEND`` ``write`` of at most ``PIPE_BUF`` bytes is
    atomic across concurrent writers, so the (at most 256) shard files stay
    consistent without any coordination, lock, or Ray actor. Oversized string
    values are truncated (:func:`_cap_large`) to keep every record under
    ``PIPE_BUF``.

    The shard/file count is constant (≤256) regardless of agent count, so this
    scales to 1M+ agents run as batches of Ray tasks — each task process is
    just another independent writer appending into the shared shard files.
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
                fd = os.open(
                    str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600
                )
                self._fds[key] = fd

    def append_record(self, record: dict[str, Any]) -> None:
        """Append one JSONL record to the shard keyed by ``trace_id[:2]``.

        Writes go straight to the kernel page cache via ``os.write`` (no
        userspace buffer), so there is nothing to flush. The record is
        value-capped first so the whole line fits in one atomic ``write``.
        """
        rec = _cap_large(record, self._cap) if self._cap else record
        key = str(rec.get("trace_id", ""))[:2].lower() or "00"
        data = (json.dumps(rec, ensure_ascii=False, default=str) + "\n").encode("utf-8")
        self._ensure_fd(key)
        fd = self._fds[key]
        mv = memoryview(data)
        # Under O_APPEND each os.write is atomic for <= PIPE_BUF; loop only to
        # handle the rare partial write of a (capped, small) buffer.
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
    """Build a per-process :class:`ShardedAppendSink` from a :class:`TraceProxy`.

    Returns ``None`` when the proxy carries no ``trace_dir`` (trace disabled).
    """
    trace_dir = getattr(trace_proxy, "trace_dir", None)
    if not trace_dir:
        return None
    return ShardedAppendSink(trace_dir)


# ---------------------------------------------------------------------------
# Span API (JsonlTraceWriter)
# ---------------------------------------------------------------------------


class JsonlTraceWriter:
    """Write OTel-compatible JSONL spans via a sharded backend.

    Each finished span is forwarded to ``sharded_writer`` (a
    :class:`ShardedAppendSink` in production). When ``sharded_writer`` is None,
    the span API still works but records are discarded (no-op).

    Parameters
    ----------
    agent_id : int
        The agent this writer belongs to.
    service_name : str
        OTel ``resource.service.name`` value.
    scope_name : str
        OTel ``scope.name`` value.
    scope_version : str
        OTel ``scope.version`` value.
    sharded_writer : ShardedAppendSink | None
        Backend sink; None = no-op.
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

        If *trace_id* is not provided it is inherited from the current parent
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
