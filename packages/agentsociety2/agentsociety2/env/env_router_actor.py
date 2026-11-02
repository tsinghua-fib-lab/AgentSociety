"""持有 ``CodeGenRouter`` 的 Ray actor(env router)。

把 env router 移入专用 Ray actor,可使 env 代码生成执行(及其原先的
``_execute_lock`` 串行化)离开 agent 的事件循环。单个 Ray actor 一次只处理
一个方法(FIFO),与原锁提供相同的互斥,但在独立进程/事件循环中。

actor 由可序列化 spec(env 模块类型 + kwargs + codegen kwargs)构建。LLM 以
携带连接参数的可序列化 :class:`LLMClient` 句柄(coder + default)形式
**注入**;每个 actor 进程在首次使用时自建 litellm Router。回放以可序列化
:class:`ReplayProxy` 注入。actor 从不自行创建中心运行时服务,因此没有
Ray-in-Ray(D8)。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

# Module-level cache for the Ray actor class, keyed by max_concurrency. ``import
# ray`` is deferred so importing this module never requires Ray.
_cached_env_actor_classes: dict[int, Any] = {}


def get_env_router_actor_class(max_concurrency: int = 1) -> Any:
    """返回 Ray env-router actor 类(每个 max_concurrency 只创建一次)。

    :param max_concurrency: Ray actor 并发度。``1`` 串行化 ask 调用(任一
        env 模块非并发安全时的默认值);``>1`` 仅当所有 env 模块声明
        ``is_concurrency_safe()`` 时才允许并行 async ask 调用。
    :returns: 一个 Ray actor 类(``@ray.remote(max_concurrency=...)``)。
    """
    if max_concurrency in _cached_env_actor_classes:
        return _cached_env_actor_classes[max_concurrency]

    import ray  # deferred import

    class EnvRouterActor:
        """持有一个 ``CodeGenRouter``;生命周期与 ask 方法运行在其自身的事件循环上。"""

        def __init__(
            self,
            env_module_types: list[str],
            env_kwargs: dict[str, dict[str, Any]],
            run_dir: str | None,
            codegen_kwargs: dict[str, Any] | None,
            llm_clients_spec: dict[str, Any] | None = None,
            replay_proxy: Any = None,
            trace_proxy: Any = None,
        ) -> None:
            """在 actor 进程内创建 env router。

            :param env_module_types: 可序列化的 env 模块类型键。
            :param env_kwargs: 各类型的构造 kwargs。
            :param run_dir: run 目录(赋给 ``router.run_dir``)。
            :param codegen_kwargs: CodeGenRouter kwargs(如
                ``final_summary_enabled``)。
            :param llm_clients_spec: 可选。含 ``coder`` / ``default`` 键的
                dict,每个值为序列化的 :class:`LLMClient`。为 ``None`` 时
                router 回退到每进程 dispatcher 的 client 工厂。
            :param replay_proxy: 可选。用于共享 sharded JSONL 回放的
                :class:`ReplayProxy`。为 ``None`` / 未启用时,env 回放关闭。
            :param trace_proxy: 可选。用于 env 侧 ``llm.completion`` span 的
                :class:`TraceProxy`。为 ``None`` 时,env LLM 调用不被追踪。
            """
            from agentsociety2.env.router_codegen import CodeGenRouter
            from agentsociety2.registry import get_registered_env_modules, get_registry

            if run_dir is not None:
                custom_root = Path(run_dir)
                if (custom_root / "custom").is_dir():
                    get_registry().set_workspace(custom_root)

            env_type_map = dict(get_registered_env_modules())
            env_modules = []
            for module_type in env_module_types:
                env_class = env_type_map[module_type]
                env_modules.append(env_class(**env_kwargs.get(module_type, {})))

            self._router = CodeGenRouter(
                env_modules=env_modules,
                replay_writer=None,
                llm_clients_spec=llm_clients_spec,
                **(codegen_kwargs or {}),
            )
            if run_dir is not None:
                self._router.run_dir = run_dir
                # 模块状态只存在于本 actor 进程，故在此绑定各模块到
                # ``<run_dir>/env/<module_type>``，供 RouterBase.init 恢复、
                # society 每步 to_workspace。
                self._router.bind_env_workspaces(
                    Path(run_dir) / "env", env_module_types
                )
            # Shared replay proxy: when set, env modules and agents append to
            # the same replay directory through process-local ReplaySink objects.
            self._replay_proxy = replay_proxy
            # Trace proxy: when set, env-side LLM calls emit spans via this
            # actor's own local ShardedAppendSink (same trace store as agents,
            # distributed — no central actor).
            self._trace_proxy = trace_proxy
            if trace_proxy is not None:
                from agentsociety2.trace import build_local_sink

                sink = build_local_sink(trace_proxy)
                if sink is not None:
                    self._router.set_trace_sink(sink)

        async def init(self, start_datetime: datetime) -> bool:
            if self._replay_proxy is not None:
                self._router.set_replay_writer(self._replay_proxy)
            # RouterBase.init 会先跑各模块 init() 再恢复 checkpoint（resume）。
            return await self._router.init(start_datetime)

        async def to_workspaces(self) -> None:
            """把各 env 模块状态写入 workspace（每步）。"""
            await self._router.to_workspaces()

        async def from_workspaces(self) -> bool:
            """从 workspace 恢复 env 模块状态（resume）。"""
            return await self._router.from_workspaces()

        def set_current_time(self, t: datetime) -> None:
            self._router.set_current_time(t)

        def set_replay_writer(self, writer: Any) -> None:
            """向 router(及其模块)注入回放 writer/proxy。

            ``writer`` 通常是可序列化的 :class:`ReplayProxy`。同时存到
            ``self._replay_proxy``,以便 :meth:`init` 把 env 回放路由到共享
            回放目录。
            """
            self._replay_proxy = writer
            self._router.set_replay_writer(writer)

        async def ask(
            self,
            ctx: dict,
            instruction: str,
            readonly: bool = False,
            template_mode: bool = False,
            trace_id: str | None = None,
            parent_span_id: str | None = None,
        ):
            return await self._router.ask(
                ctx,
                instruction,
                readonly=readonly,
                template_mode=template_mode,
                trace_id=trace_id,
                parent_span_id=parent_span_id,
            )

        async def get_world_description(self) -> str:
            return await self._router.get_world_description()

        def get_token_usages(self) -> dict[str, Any]:
            getter = getattr(self._router, "get_token_usages", None)
            if getter is None:
                return {}
            return getter()

        async def step(self, tick: int, t: datetime) -> None:
            await self._router.step(tick, t)

        async def close(self) -> None:
            await self._router.close()

    # Apply Ray with max_concurrency (>1 allows parallel async ask calls; only
    # safe when all env modules declare is_concurrency_safe()).
    actor_cls = ray.remote(max_concurrency=max_concurrency)(EnvRouterActor)
    _cached_env_actor_classes[max_concurrency] = actor_cls
    return actor_cls
