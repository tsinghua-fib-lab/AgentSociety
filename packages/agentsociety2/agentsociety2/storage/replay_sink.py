"""Distributed append-only JSONL replay sink.

Replaces the former central SQLite/Ray actor write path. Each writer process
holds its own :class:`ReplaySink` and appends directly via ``os.open(O_APPEND)``
+ ``os.write`` — no central actor and no Ray round-trip on the hot path.

Layout under ``replay_dir``:

- ``{table}.{shard:02x}.jsonl`` — one JSONL line per row. Sharded by
  ``zlib.crc32(line) % 256`` so the (at most 256 × #tables) files are touched
  by a bounded set of concurrent writers regardless of agent count (scales to
  1M+ agents run as batches of Ray tasks).
- ``_schema.json`` — schema sidecar catalog (tables + datasets + per-column
  metadata), merged idempotently across writers.

Atomicity: replay rows can exceed ``PIPE_BUF`` (agent_profile JSON, dialog
content), so each shard write is guarded by ``fcntl.flock(LOCK_EX)`` —
multi-chunk writes never interleave across the concurrent writer processes.
``flock`` is ~µs and replay write volume per tick is tiny vs the LLM seconds
that dominate each step, so the serialization cost is negligible.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import zlib
from collections.abc import Iterable
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any

from agentsociety2.storage.replay_metadata import ReplayDatasetSpec
from agentsociety2.storage.table_schema import ColumnDef, TableSchema

_NUM_SHARDS = 256
_SCHEMA_FILENAME = "_schema.json"


@contextmanager
def _file_lock(fd: int):
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            os.lseek(fd, 0, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        return
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_EX)
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)


def _normalize(value: Any) -> Any:
    """Coerce a row value to JSON-serializable form (mirrors the old SQLite
    writer): datetime → ISO 8601, dict/list → JSON sub-string."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: _normalize(v) for k, v in row.items()}


def _column_to_dict(col: ColumnDef) -> dict[str, Any]:
    return asdict(col)


def _schema_to_dict(schema: TableSchema) -> dict[str, Any]:
    return {
        "columns": [_column_to_dict(c) for c in schema.columns],
        "primary_key": list(schema.primary_key),
        "indexes": [list(idx) for idx in schema.indexes],
    }


def _dataset_to_dict(
    spec: ReplayDatasetSpec, columns: Iterable[ColumnDef]
) -> dict[str, Any]:
    d = asdict(spec)
    d["columns"] = [_column_to_dict(c) for c in columns]
    return d


class ReplaySink:
    """Per-process, distributed, append-only JSONL replay writer.

    One instance per writer process (driver / env router actor / each agent Ray
    task). Holds its own open shard fds; per-shard lock files make concurrent
    appends to the same shard file safe for rows of any size.
    """

    def __init__(self, replay_dir: str | Path, *, enabled: bool = True) -> None:
        self._dir = Path(replay_dir)
        self._enabled = bool(enabled)
        self._fds: dict[tuple[str, int], int] = {}
        self._lock_fds: dict[tuple[str, int], int] = {}
        self._lock = threading.Lock()
        self._schema_path = self._dir / _SCHEMA_FILENAME
        if self._enabled:
            self._dir.mkdir(parents=True, exist_ok=True)

    # ---- back-compat: the old SQLite writer had an async init() ----
    async def init(self) -> None:
        """No-op (kept for API compatibility with the legacy writer)."""
        return

    # ------------------------------------------------------------------
    # Row writes
    # ------------------------------------------------------------------

    def _ensure_fd(self, table: str, shard: int) -> None:
        key = (table, shard)
        if key in self._fds:
            return
        with self._lock:
            if key not in self._fds:
                path = self._dir / f"{table}.{shard:02x}.jsonl"
                # Cached descriptor is owned by this sink and released by close().
                # codeql[py/file-not-closed]
                fd = os.open(
                    str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600
                )
                self._fds[key] = fd

    def _ensure_lock_fd(self, table: str, shard: int) -> None:
        key = (table, shard)
        if key in self._lock_fds:
            return
        with self._lock:
            if key not in self._lock_fds:
                path = self._dir / f".{table}.{shard:02x}.lock"
                # Cached descriptor is owned by this sink and released by close().
                # codeql[py/file-not-closed]
                fd = os.open(
                    str(path), os.O_RDWR | os.O_CREAT, 0o600
                )
                self._lock_fds[key] = fd

    @contextmanager
    def _shard_lock(self, table: str, shard: int):
        self._ensure_lock_fd(table, shard)
        fd = self._lock_fds[(table, shard)]
        with _file_lock(fd):
            yield

    def _append_lines(self, table: str, lines: list[bytes]) -> None:
        """Append pre-serialized lines, sharded, each shard write lock-guarded."""
        if not lines:
            return
        by_shard: dict[int, bytearray] = {}
        for line in lines:
            shard = zlib.crc32(line) % _NUM_SHARDS
            by_shard.setdefault(shard, bytearray()).extend(line)
        for shard, buf in by_shard.items():
            self._ensure_fd(table, shard)
            fd = self._fds[(table, shard)]
            with self._shard_lock(table, shard):
                mv = memoryview(buf)
                while mv:
                    n = os.write(fd, mv)
                    mv = mv[n:]

    async def write(self, table: str, data: dict[str, Any]) -> None:
        """Append one row to ``table``."""
        if not self._enabled:
            return
        line = (
            json.dumps(_normalize_row(data), ensure_ascii=False, default=str) + "\n"
        ).encode("utf-8")
        self._append_lines(table, [line])

    async def write_batch(self, table: str, rows: list[dict[str, Any]]) -> None:
        """Append multiple rows to ``table`` (one flock per shard)."""
        if not self._enabled or not rows:
            return
        lines = [
            (
                json.dumps(_normalize_row(r), ensure_ascii=False, default=str) + "\n"
            ).encode("utf-8")
            for r in rows
        ]
        self._append_lines(table, lines)

    # ------------------------------------------------------------------
    # Schema catalog sidecar
    # ------------------------------------------------------------------

    async def register_table(self, schema: TableSchema) -> None:
        """Record a table's schema in ``_schema.json`` (idempotent)."""
        if not self._enabled:
            return
        self._merge_schema({"tables": {schema.name: _schema_to_dict(schema)}})

    async def register_dataset(
        self, spec: ReplayDatasetSpec, columns: list[ColumnDef]
    ) -> None:
        """Record a dataset + its columns in ``_schema.json`` (idempotent)."""
        if not self._enabled:
            return
        self._merge_schema(
            {"datasets": {spec.dataset_id: _dataset_to_dict(spec, columns)}}
        )

    def _merge_schema(self, patch: dict[str, Any]) -> None:
        """Read-merge-write ``_schema.json`` under an flock on the sidecar fd."""
        self._dir.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self._schema_path), os.O_RDWR | os.O_CREAT, 0o600)
        try:
            with _file_lock(fd):
                os.lseek(fd, 0, os.SEEK_SET)
                existing = b""
                while True:
                    chunk = os.read(fd, 65536)
                    if not chunk:
                        break
                    existing += chunk
                data: dict[str, Any] = {}
                if existing.strip():
                    try:
                        data = json.loads(existing.decode("utf-8"))
                    except json.JSONDecodeError:
                        data = {}
                for section, entries in patch.items():
                    bucket = data.setdefault(section, {})
                    bucket.update(entries)
                payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
                os.lseek(fd, 0, os.SEEK_SET)
                os.ftruncate(fd, 0)
                mv = memoryview(payload)
                while mv:
                    n = os.write(fd, mv)
                    mv = mv[n:]
                os.fsync(fd)
        finally:
            os.close(fd)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close all open shard fds."""
        for fd in list(self._fds.values()) + list(self._lock_fds.values()):
            try:
                os.close(fd)
            except OSError:
                import logging

                logging.getLogger(__name__).debug(
                    "Failed to close replay sink fd", exc_info=True
                )
        self._fds.clear()
        self._lock_fds.clear()


class ReplayWriter(ReplaySink):
    """Back-compat alias over :class:`ReplaySink`.

    The legacy public API (:mod:`agentsociety2.storage`, examples) constructed a
    SQLite writer with a ``.db`` file path and called ``await init()`` before
    use. That writer is gone; this alias keeps the symbol importable and writes
    the same JSONL format, mapping the legacy ``db_path`` to a replay directory
    (a trailing ``.db`` is stripped) so old call sites keep working without
    SQLite.
    """

    def __init__(self, db_path: str | Path, *, enabled: bool = True) -> None:
        path = str(db_path)
        path = path.removesuffix(".db")
        super().__init__(path, enabled=enabled)


def build_replay_sink(replay_proxy: Any) -> ReplaySink | None:
    """Build a per-process :class:`ReplaySink` from a :class:`ReplayProxy`.

    Returns ``None`` when the proxy is disabled or carries no ``replay_dir``.
    """
    if not getattr(replay_proxy, "enabled", True):
        return None
    replay_dir = getattr(replay_proxy, "replay_dir", None)
    if not replay_dir:
        return None
    return ReplaySink(replay_dir)


__all__ = ["ReplaySink", "ReplayWriter", "build_replay_sink"]
