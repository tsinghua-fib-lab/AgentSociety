"""分布式只追加 JSONL 回放写入端。

取代原先的中央 SQLite/Ray actor 写入路径。每个写入进程各自持有
:class:`ReplaySink` ，直接通过 ``os.open(O_APPEND)`` + ``os.write`` 追加——
热路径上没有中央 actor，也没有 Ray 往返。

``replay_dir`` 下的布局：

- ``{table}.{shard:02x}.jsonl`` — 每行一条 JSONL 记录。按
  ``zlib.crc32(line) % 256`` 分片，无论 agent 数量多少，（至多
  256 × 表数）个文件都只被一组有界的并发写入者触碰（可扩展到以
  Ray task 批次运行的 1M+ agents）。
- ``_schema.json`` — schema 旁路目录（表 + 数据集 + 逐列元数据），
  各写入者之间幂等合并。

原子性：replay 行可能超过 ``PIPE_BUF`` （agent_profile JSON、dialog 内容），
因此每个分片写入都由 ``fcntl.flock(LOCK_EX)`` 保护——多块写入在并发写入
进程之间绝不会交错。``flock`` 约为 µs 量级，且每个 tick 的回放写入量相对
主导每步耗时的 LLM 秒数而言极小，串行化开销可忽略。
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
    """把行值转换为可 JSON 序列化的形式（与旧 SQLite 写入器一致）：
    datetime → ISO 8601，dict/list → JSON 子字符串。"""
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
    """每进程的分布式只追加 JSONL 回放写入器。

    每个写入进程（driver / env router actor / 每个 agent Ray task）各持
    一个实例。各自持有打开的分片 fd；逐分片的锁文件保证并发追加同一分片
    文件对任意大小的行都是安全的。
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
        """空操作（仅为兼容旧写入器的 API 而保留）。"""
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
                fd = os.open(str(path), os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
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
                fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
                self._lock_fds[key] = fd

    @contextmanager
    def _shard_lock(self, table: str, shard: int):
        self._ensure_lock_fd(table, shard)
        fd = self._lock_fds[(table, shard)]
        with _file_lock(fd):
            yield

    def _append_lines(self, table: str, lines: list[bytes]) -> None:
        """追加已序列化的行，按分片写入，每个分片写入由锁保护。"""
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
        """向 ``table`` 追加一行。"""
        if not self._enabled:
            return
        line = (
            json.dumps(_normalize_row(data), ensure_ascii=False, default=str) + "\n"
        ).encode("utf-8")
        self._append_lines(table, [line])

    async def write_batch(self, table: str, rows: list[dict[str, Any]]) -> None:
        """向 ``table`` 追加多行（每个分片一次 flock）。"""
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
        """把表 schema 记录到 ``_schema.json`` （幂等）。"""
        if not self._enabled:
            return
        self._merge_schema({"tables": {schema.name: _schema_to_dict(schema)}})

    async def register_dataset(
        self, spec: ReplayDatasetSpec, columns: list[ColumnDef]
    ) -> None:
        """把数据集及其列记录到 ``_schema.json`` （幂等）。"""
        if not self._enabled:
            return
        self._merge_schema(
            {"datasets": {spec.dataset_id: _dataset_to_dict(spec, columns)}}
        )

    def _merge_schema(self, patch: dict[str, Any]) -> None:
        """在旁路 fd 的 flock 保护下对 ``_schema.json`` 做读-合并-写。"""
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
        """关闭所有打开的分片 fd。"""
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
    """:class:`ReplaySink` 的向后兼容别名。

    旧的公开 API（:mod:`agentsociety2.storage` 、examples）用 ``.db`` 文件路径
    构造 SQLite 写入器，并在使用前调用 ``await init()`` 。该写入器已被移除；
    此别名保持符号可导入，并写入相同的 JSONL 格式，把旧的 ``db_path`` 映射为
    replay 目录（去掉末尾的 ``.db`` ），使旧调用点无需 SQLite 即可继续工作。
    """

    def __init__(self, db_path: str | Path, *, enabled: bool = True) -> None:
        path = str(db_path)
        path = path.removesuffix(".db")
        super().__init__(path, enabled=enabled)


def build_replay_sink(replay_proxy: Any) -> ReplaySink | None:
    """从 :class:`ReplayProxy` 构建每进程的 :class:`ReplaySink` 。

    proxy 被禁用或未携带 ``replay_dir`` 时返回 ``None`` 。
    """
    if not getattr(replay_proxy, "enabled", True):
        return None
    replay_dir = getattr(replay_proxy, "replay_dir", None)
    if not replay_dir:
        return None
    return ReplaySink(replay_dir)


__all__ = ["ReplaySink", "ReplayWriter", "build_replay_sink"]
