"""可序列化的回放代理与每进程 sink 构建器。

回放写入过去经由单个封装 SQLite 的 Ray actor 汇聚；该中心化写入路径已被移除。

:class:`ReplayProxy` 现在是一个可序列化的配置 dataclass，仅携带输出目录
（外加启用标志）。每个消费方——env router actor、society、每个 agent Ray
task——都从 ``replay_dir`` 自行构建进程本地的
:class:`~agentsociety2.storage.replay_sink.ReplaySink` 并直接追加写入。没有
中心 actor，写入路径上没有 Ray 往返，也就没有死锁。``enabled=False`` 直接
短路为 no-op（超大规模下的逃生通道，可整体跳过回放）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agentsociety2.storage.replay_sink import ReplaySink, build_replay_sink


@dataclass
class ReplayProxy:
    """分布式回放写入的可序列化配置。

    仅携带回放输出目录与启用标志——不含 Ray actor 句柄。各方法在首次使用时
    懒构建并缓存进程本地的 :class:`ReplaySink` （由 ``replay_dir`` 构建）并委托
    其执行，因此每个收到反序列化副本的 agent Ray task / env actor 都获得自己
    的 sink 与自己的文件描述符。``enabled=False`` 使所有方法成为 no-op。
    """

    replay_dir: str | None = None
    enabled: bool = True

    # Process-local sink, built lazily on first write. NOT serialized across
    # Ray task boundaries — ReplaySink holds open fds + a threading.Lock (both
    # unpicklable) and is per-process. Each Ray task that receives a
    # deserialized copy rebuilds its own sink from replay_dir.
    _sink: Any = None

    def _get_sink(self) -> ReplaySink | None:
        sink = self._sink
        if sink is None:
            sink = build_replay_sink(self)
            self._sink = sink
        return sink

    # --- pickle/cloudpickle: drop the process-local sink so the proxy can
    # cross Ray task boundaries. Each side rebuilds its own sink. ---
    def __getstate__(self) -> dict[str, Any]:
        return {"replay_dir": self.replay_dir, "enabled": self.enabled}

    def __setstate__(self, state: dict[str, Any]) -> None:
        self.replay_dir = state.get("replay_dir")
        self.enabled = state.get("enabled", True)
        self._sink = None

    async def write(self, table: str, data: dict[str, Any]) -> None:
        if not self.enabled:
            return
        sink = self._get_sink()
        if sink is None:
            return
        await sink.write(table, data)

    async def write_batch(self, table: str, rows: list[dict[str, Any]]) -> None:
        if not self.enabled:
            return
        sink = self._get_sink()
        if sink is None:
            return
        await sink.write_batch(table, rows)

    async def register_table(self, schema: Any) -> None:
        if not self.enabled:
            return
        sink = self._get_sink()
        if sink is None:
            return
        await sink.register_table(schema)

    async def register_dataset(self, spec: Any, columns: Any) -> None:
        if not self.enabled:
            return
        sink = self._get_sink()
        if sink is None:
            return
        await sink.register_dataset(spec, columns)

    async def close(self) -> None:
        sink = self._sink
        if sink is not None:
            await sink.close()
            self._sink = None


__all__ = ["ReplayProxy", "build_replay_sink"]
