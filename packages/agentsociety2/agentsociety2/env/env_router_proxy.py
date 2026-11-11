"""env router 的 Ray-only proxy。

society、agent 与 helper 和本 proxy 交互的方式与进程内 ``CodeGenRouter``
完全相同(同名方法:``ask`` 、``init`` 、``step`` 、``close`` 、
``to_workspaces`` 、``from_workspaces`` 、``set_current_time`` 、
``set_replay_writer``)。proxy 把每次调用转发给在独立进程中持有真正
router 的 Ray actor,因此 env 代码生成执行(及其原先的 ``_execute_lock``
串行化)不再阻塞 agent 事件循环。

进程内 ``CodeGenRouter`` 实例 **不可** Ray 序列化。示例与脚本必须使用
:func:`create_env_router_proxy`(或 CLI 的 actor 路径),``ServiceProxy``
才能跨越 Ray Task 边界。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any


class EnvRouterProxy:
    """面向 agent/society 的句柄,委托给持有 env router 的 Ray actor。

    与进程内 router 不同,本 proxy 不持有具体的 env 模块实例(它们位于
    actor 进程中),因此无法暴露 ``env_modules`` 。为了让 agent 侧仍能发现
    env 提供的 skill,proxy 携带 ``env_skill_dirs``——构造时从 registry
    解析出的全部已配置 env 模块 ``skill_dirs()`` 的并集,每项配对模块类名
    (用作 ``env:{ClassName}`` 命名空间)。``AgentBase.discover_skill_sources``
    在 ``env_modules`` 之外还会读取该属性,因此无论 agent 看到的是真实
    router 还是本 proxy,env skill 都可见。该属性是纯 JSON 可序列化数据
    (``list[(str, str)]``),proxy 仍能干净地跨越 Ray 边界。
    """

    def __init__(
        self,
        actor_handle: Any,
        *,
        run_dir: Any = None,
        env_module_types: list[str] | None = None,
    ) -> None:
        self._actor = actor_handle
        self.run_dir = run_dir
        self.env_skill_dirs: list[tuple[str, str]] = _resolve_env_skill_dirs(
            env_module_types or []
        )

    def set_current_time(self, t: datetime) -> None:
        """把 society 时钟转发给 actor(fire-and-forget)。

        参见 :meth:`RouterBase.set_current_time`——推送 society 当前时间,
        使 env 模块在 agent 阶段能观察到它。
        """
        self._actor.set_current_time.remote(t)

    def set_replay_writer(self, writer: Any) -> None:
        """把回放 writer/proxy 转发给 actor(fire-and-forget)。

        env actor 通常在构造时即获得其回放 proxy(使 env 模块与 agent 共享
        同一回放目录)。本方法允许调用方在构造之后额外/另行注入 writer;经
        ``set_replay_writer`` 转发给 actor。``ReplayProxy`` 可序列化,能干净
        地跨越 Ray 边界。
        """
        self._actor.set_replay_writer.remote(writer)

    async def ask(
        self,
        ctx: dict,
        instruction: str,
        readonly: bool = False,
        template_mode: bool = False,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ):
        """把 env ask 转发给 actor 并等待 ``(ctx, answer)`` 结果。"""
        return await self._actor.ask.remote(
            ctx, instruction, readonly, template_mode, trace_id, parent_span_id
        )

    async def get_world_description(self) -> str:
        return await self._actor.get_world_description.remote()

    async def init(self, start_datetime: datetime) -> bool:
        return await self._actor.init.remote(start_datetime)

    async def step(self, tick: int, t: datetime) -> None:
        return await self._actor.step.remote(tick, t)

    async def to_workspaces(self) -> None:
        """转发每步 env 状态持久化到 actor。"""
        return await self._actor.to_workspaces.remote()

    async def from_workspaces(self) -> bool:
        """转发 env 状态恢复（resume）到 actor。"""
        return await self._actor.from_workspaces.remote()

    async def close(self) -> None:
        return await self._actor.close.remote()

    def get_token_usages(self) -> dict[str, Any]:
        """返回 env router(coder/summary)token 用量快照。"""
        return ray_get_token_usages(self._actor)


def ray_get_token_usages(actor_handle: Any) -> dict[str, Any]:
    """阻塞式从 env actor 拉取 token 用量(仅 driver 侧)。"""
    import ray

    return ray.get(actor_handle.get_token_usages.remote())


async def create_env_router_proxy(
    env_module_types: list[str],
    env_kwargs: dict[str, dict[str, Any]] | None = None,
    *,
    run_dir: str | Path | None = None,
    max_concurrency: int | None = None,
    final_summary_enabled: bool = False,
) -> EnvRouterProxy:
    """为示例 / 脚本创建 Ray ``EnvRouterProxy``(与 CLI 兼容)。

    按需初始化 Ray 与 LLM dispatcher,以与 ``society.cli`` 相同的注入模式
    构建 env actor,并返回可序列化的 proxy。

    :param env_module_types: registry 键(通常是 env 类名)。
    :param env_kwargs: 各类型的构造 kwargs;默认每类型为 ``{}`` 。
    :param run_dir: 实验 run 目录(env workspace 位于 ``run_dir/env`` 下)。
    :param max_concurrency: Ray actor 并发度。``None`` 表示当每个模块都声明
        ``is_concurrency_safe()`` 时取 ``Config.ENV_ACTOR_MAX_CONCURRENCY``,
        否则取 ``1`` 。
    :param final_summary_enabled: 转发给 ``CodeGenRouter`` 。
    :returns: 可供 ``AgentSociety`` 使用的可序列化 :class:`EnvRouterProxy` 。
    """
    from agentsociety2.config import Config
    from agentsociety2.config.llm_dispatcher import (
        build_client_for_role,
        init_dispatchers,
    )
    from agentsociety2.env.env_router_actor import get_env_router_actor_class
    from agentsociety2.registry import get_registered_env_modules

    await init_dispatchers()

    types = list(env_module_types)
    kwargs = dict(env_kwargs or {})
    for t in types:
        kwargs.setdefault(t, {})

    run_dir_path = Path(run_dir).resolve() if run_dir is not None else None
    if run_dir_path is not None and (run_dir_path / "custom").is_dir():
        from agentsociety2.registry import get_registry

        get_registry().set_workspace(run_dir_path)

    type_map = dict(get_registered_env_modules())
    missing = [t for t in types if t not in type_map]
    if missing:
        raise ValueError(
            f"Unknown env module type(s): {missing}. "
            "Register custom classes before calling create_env_router_proxy."
        )

    if max_concurrency is None:
        all_safe = all(type_map[t].is_concurrency_safe() for t in types)
        max_concurrency = Config.ENV_ACTOR_MAX_CONCURRENCY if all_safe else 1
    llm_clients_spec = {
        "coder": build_client_for_role("coder"),
        "default": build_client_for_role("default"),
    }
    actor_cls = get_env_router_actor_class(max_concurrency=max_concurrency)
    actor = actor_cls.remote(
        types,
        kwargs,
        str(run_dir_path) if run_dir_path is not None else None,
        {"final_summary_enabled": final_summary_enabled},
        llm_clients_spec,
        None,
        None,
    )
    return EnvRouterProxy(
        actor,
        run_dir=run_dir_path,
        env_module_types=types,
    )


def _resolve_env_skill_dirs(
    env_module_types: list[str],
) -> list[tuple[str, str]]:
    """为给定 env 模块类型收集 ``(module_class_name, skill_dir)`` 。

    从全局 registry 解析各类型的类并读取其 ``skill_dirs()`` 。无法解析类型
    或读取目录时记录日志并跳过——发现过程绝不能因缺失 skill 源而让 agent
    构建崩溃。重复的 ``(name, dir)`` 对会被去除。

    :param env_module_types: registry 的 env 模块类型键。
    :returns: 有序、去重后的 ``(module_class_name, skill_dir_str)`` 对。
    """
    if not env_module_types:
        return []
    try:
        from agentsociety2.registry import get_registered_env_modules
    except Exception:  # pragma: no cover - defensive
        return []
    type_map = dict(get_registered_env_modules())
    seen: set[tuple[str, str]] = set()
    result: list[tuple[str, str]] = []
    for module_type in env_module_types:
        env_class = type_map.get(module_type)
        if env_class is None:
            continue
        try:
            skill_dirs = env_class.skill_dirs()
        except Exception:
            continue
        # ``skill_dirs()`` is a classmethod declared on the ``EnvBase``
        # metaclass, so ``type(env_class)`` would yield the metaclass name
        # (``EnvMeta``) — use ``env_class.__name__`` to match the concrete
        # module class name the in-process path produces via
        # ``type(module).__name__`` on instances.
        class_name = env_class.__name__
        for skills_dir in skill_dirs or []:
            pair = (class_name, str(skills_dir))
            if pair[1] and pair not in seen:
                seen.add(pair)
                result.append(pair)
    return result
