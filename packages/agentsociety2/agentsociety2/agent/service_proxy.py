"""共享服务句柄容器 :class:`ServiceProxy` 。

Agent 不持有运行时对象(LLM dispatcher、env router、trace/replay
writer)。这些共享服务改为以可序列化句柄的形式,经由单个
:class:`ServiceProxy` 在 :meth:`from_workspace` 中注入。该 proxy 只持有
句柄/数据(不含锁、连接或线程),因此能干净地跨越 Ray Task 边界。

proxy、协议与工厂位于本模块,具体的 proxy 类位于各自的运行时模块
(:class:`~agentsociety2.trace.TraceProxy` 、
:class:`~agentsociety2.storage.replay_proxy.ReplayProxy`)。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# ═══════════════════════════════════════════════════════════
# Service interface protocols (agents depend on these, not concretes)
# ═══════════════════════════════════════════════════════════


@runtime_checkable
class EnvLike(Protocol):
    """环境路由协议(进程内 ``RouterBase`` 或远程 ``EnvRouterProxy``)。"""

    async def ask(
        self,
        ctx: dict,
        instruction: str,
        readonly: bool = False,
        template_mode: bool = False,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> tuple[dict, str]:
        raise NotImplementedError

    def set_current_time(self, t: Any) -> None:
        raise NotImplementedError

    async def step(self, tick: int, t: Any) -> None:
        raise NotImplementedError

    async def get_world_description(self) -> str:
        raise NotImplementedError


@runtime_checkable
class LLMClientLike(Protocol):
    """LLM client 协议:单次补全请求。"""

    async def call(
        self,
        model: str,
        messages: list[dict[str, Any]],
        stream: bool = False,
        thinking: str = "inherit",
        **kwargs: Any,
    ) -> Any:
        raise NotImplementedError


@runtime_checkable
class TraceLike(Protocol):
    """Trace writer 协议。"""

    def append_record(self, record: dict[str, Any]) -> None:
        raise NotImplementedError

    def flush(self) -> None:
        raise NotImplementedError


@runtime_checkable
class ReplayLike(Protocol):
    """Replay writer 协议。"""

    async def write_batch(self, table: str, rows: list[dict[str, Any]]) -> None:
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════
# Containers
# ═══════════════════════════════════════════════════════════


@dataclass
class LLMClients:
    """按角色组织的 LLM client 集合。

    Agent 使用 ``default``,env router 使用 ``coder`` / ``default`` 。
    """

    coder: Any
    default: Any
    embedding: Any | None = None


@dataclass
class ServiceProxy:
    """所有共享服务句柄的一站式容器。

    ``from_workspace(path, service_proxy)`` 只接收本对象。所有字段都是
    可序列化句柄(LLM client、env router、可选的 trace 与 replay proxy),
    因此该容器可跨 Ray Task 边界传输。

    ``llm`` client 只携带连接参数(不含活跃的 Router/semaphore),每个接收
    反序列化副本的 Ray Task / actor 会在首次 ``call()`` 时重建自己的按事件
    循环的运行时。:meth:`take_token_stats` 排空按任务的 token 使用增量,
    使 Ray Task 能把它带回返回值中(无 actor,无模块级全局聚合)。
    """

    env: Any  # EnvLike
    llm: LLMClients
    trace: Any  # TraceLike | None
    replay: Any  # ReplayLike | None
    run_dir: Path | None = None

    def take_token_stats(self) -> dict[str, dict[str, int]]:
        """排空并返回本 proxy 各 LLM client 的 token 用量(增量)。

        在 Ray Task 结束时调用,以便把增量并入其返回值。每个 ``LLMClient``
        自行清零统计,因此复用的 worker 进程不会跨任务重复计数。
        """
        from agentsociety2.config.llm_dispatcher import merge_token_stats

        deltas: list[dict] = []
        for client in (self.llm.default, self.llm.coder, self.llm.embedding):
            if client is not None and hasattr(client, "take_token_stats"):
                deltas.append(client.take_token_stats())
        return merge_token_stats(*deltas) if deltas else {}


# ═══════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════


def _role_configured(role: str) -> bool:
    """某个角色是否已配置(避免为未配置的 embedding 强建 dispatcher)。"""
    try:
        from agentsociety2.config import get_model_name

        return bool(get_model_name(role))
    except Exception:
        return False


def build_service_proxy(
    env: Any,
    *,
    run_dir: Path | None = None,
    trace: bool | Any = True,
    trace_dir: Path | str | None = None,
    replay: bool | Any = True,
    replay_db_path: Path | str | None = None,
    replay_sample_rate: float = 1.0,
) -> ServiceProxy:
    """由本地 LLM client 与可选 actor 组装一个 :class:`ServiceProxy` 。

    构建可序列化的 LLM client(其 Router 在每个进程/事件循环首次使用时
    创建),以及指向 append-only replay/trace 目录的可选
    :class:`~agentsociety2.trace.TraceProxy` 和
    :class:`~agentsociety2.storage.replay_proxy.ReplayProxy` 。所有字段都是
    可序列化句柄,因此组装出的 proxy 可传入 agent Ray task /
    ``from_workspace`` 。

    :param env: 进程内 router(``RouterBase``)或 ``EnvRouterProxy``,两者都
        满足 :class:`EnvLike` 。这是唯一的可变项,其余接线完全一致。
    :param run_dir: 运行目录(同时也是 trace / replay 路径的默认基目录)。
    :param trace: trace 接线,接受:

        * 预构建的 :class:`~agentsociety2.trace.TraceProxy`(原样使用),
          让驱动端在 agent 的 ``ServiceProxy`` 与 env router actor 之间
          共享同一个 trace 目录;
        * ``True``,构建一个指向 ``trace_dir``(或 ``run_dir / "trace"``)
          的 :class:`~agentsociety2.trace.TraceProxy`;
        * ``False`` / ``None``,proxy 上的 ``trace`` 为 ``None``(no-op)。

        trace 是分布式且无锁的:proxy 只携带输出目录,每个消费者各自构建
        append-only 的 :class:`~agentsociety2.trace.ShardedAppendSink` 。
    :param trace_dir: trace 基目录的覆盖值(默认 ``run_dir / "trace"``)。
        当 ``trace`` 是 :class:`~agentsociety2.trace.TraceProxy` 时被忽略。
    :param replay: replay 接线,接受:

        * 预构建的 :class:`~agentsociety2.storage.replay_proxy.ReplayProxy`
          (原样使用),让驱动端把同一 replay 目录交给 agent 的
          ``ServiceProxy`` 与 env router actor;
        * ``True``,在此创建新的 ``ReplayProxy``;
        * ``False`` / ``None``,禁用的 ``ReplayProxy``(no-op)。

    :param replay_db_path: 旧参数名,现在覆盖 replay 输出目录(默认
        ``run_dir / "replay"``)。当 ``replay`` 是
        :class:`~agentsociety2.storage.replay_proxy.ReplayProxy` 时被忽略。
    :param replay_sample_rate: replay 写入的采样率(1.0 = 全量)。当
        ``replay`` 是 :class:`~agentsociety2.storage.replay_proxy.ReplayProxy`
        时被忽略。
    :returns: 接线完备的 :class:`ServiceProxy` 。
    """
    from agentsociety2.config.llm_dispatcher import build_client_for_role
    from agentsociety2.storage.replay_proxy import ReplayProxy
    from agentsociety2.trace import TraceProxy

    llm = LLMClients(
        coder=build_client_for_role("coder"),
        default=build_client_for_role("default"),
        embedding=build_client_for_role("embedding")
        if _role_configured("embedding")
        else None,
    )

    # Trace wiring: a pre-built TraceProxy wins; otherwise build one. Trace is
    # distributed & lock-free now — TraceProxy just carries the output dir; each
    # consumer builds its own local ShardedAppendSink. No central actor.
    trace_proxy: TraceProxy | None
    if isinstance(trace, TraceProxy):
        trace_proxy = trace
    elif trace:
        base = (
            Path(trace_dir)
            if trace_dir is not None
            else ((Path(run_dir) / "trace") if run_dir is not None else Path("./trace"))
        )
        trace_proxy = TraceProxy(trace_dir=str(base))
    else:
        trace_proxy = None

    # Replay wiring: a pre-built ReplayProxy wins; otherwise build one. Replay
    # is distributed & lock-free now — ReplayProxy just carries the output dir;
    # each consumer builds its own local ReplaySink. No central actor.
    replay_proxy: ReplayProxy | None
    if isinstance(replay, ReplayProxy):
        replay_proxy = replay
    elif replay:
        replay_dir = (
            Path(replay_db_path)
            if replay_db_path is not None
            else ((Path(run_dir) / "replay") if run_dir is not None else None)
        )
        if replay_dir is not None:
            replay_proxy = ReplayProxy(replay_dir=str(replay_dir), enabled=True)
        else:
            replay_proxy = None
    else:
        replay_proxy = None

    return ServiceProxy(
        env=env,
        llm=llm,
        trace=trace_proxy,
        replay=replay_proxy,
        run_dir=run_dir,
    )


__all__ = [
    "EnvLike",
    "LLMClientLike",
    "LLMClients",
    "ReplayLike",
    "ServiceProxy",
    "TraceLike",
    "build_service_proxy",
]
