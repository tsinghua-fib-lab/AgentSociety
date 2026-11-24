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

import asyncio
import math
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

from agentsociety2.logger import get_logger

if TYPE_CHECKING:
    from ray import ObjectRef

logger = get_logger()
_T = TypeVar("_T")


def _env_call_timeout(name: str, default: float) -> float:
    """读取 actor 调用超时（秒）。

    :param name: 环境变量名。
    :param default: 未设置时的默认超时。
    :returns: 有限的正数超时秒数。
    """
    try:
        value = float(os.getenv(name, ""))
    except ValueError:
        return default
    return value if math.isfinite(value) and value > 0 else default


def _cancel_actor_call(ref: ObjectRef[Any]) -> None:
    """尽力取消远端调用；不等待 actor 响应，也不回滚已发生的副作用。"""
    import ray

    try:
        ray.cancel(ref, force=False)
    except Exception:
        logger.debug("Failed to cancel env router RPC", exc_info=True)


async def _await_actor_call(
    ref: ObjectRef[_T], *, operation: str, timeout: float
) -> _T:
    """为本地等待设置期限，并在放弃等待时显式取消 Ray 任务。"""
    deadline = asyncio.timeout(timeout)
    try:
        async with deadline:
            return await ref
    except asyncio.CancelledError:
        _cancel_actor_call(ref)
        raise
    except TimeoutError as exc:
        if not deadline.expired():
            raise  # 远端自己抛出的超时不是本地等待期限到期。
        _cancel_actor_call(ref)
        raise TimeoutError(
            f"Env router RPC {operation} timed out after {timeout:g}s"
        ) from exc


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
    worker 借用句柄发起请求；只有拥有本轮运行的调用方才应调用 ``close`` 。
    """

    def __init__(
        self,
        actor_handle: Any,
        *,
        run_dir: Any = None,
        env_module_types: list[str] | None = None,
    ) -> None:
        self._actor = actor_handle
        self._closed = False
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
    ) -> tuple[dict, str]:
        """把 env ask 转发给 actor 并等待 ``(ctx, answer)`` 结果。"""
        return await _await_actor_call(
            self._actor.ask.remote(
                ctx, instruction, readonly, template_mode, trace_id, parent_span_id
            ),
            operation="ask",
            timeout=_env_call_timeout("AGENTSOCIETY_ENV_ASK_TIMEOUT", 900),
        )

    async def get_world_description(self) -> str:
        return await _await_actor_call(
            self._actor.get_world_description.remote(),
            operation="get_world_description",
            timeout=_env_call_timeout("AGENTSOCIETY_ENV_ASK_TIMEOUT", 900),
        )

    async def init(self, start_datetime: datetime) -> bool:
        return await _await_actor_call(
            self._actor.init.remote(start_datetime),
            operation="init",
            timeout=_env_call_timeout("AGENTSOCIETY_ENV_INIT_TIMEOUT", 300),
        )

    async def step(self, tick: int, t: datetime) -> None:
        await _await_actor_call(
            self._actor.step.remote(tick, t),
            operation="step",
            timeout=_env_call_timeout("AGENTSOCIETY_ENV_STEP_TIMEOUT", 900),
        )

    async def to_workspaces(self) -> None:
        """转发每步 env 状态持久化到 actor。"""
        await _await_actor_call(
            self._actor.to_workspaces.remote(),
            operation="to_workspaces",
            timeout=_env_call_timeout("AGENTSOCIETY_ENV_STATE_TIMEOUT", 300),
        )

    async def from_workspaces(self) -> bool:
        """转发 env 状态恢复（resume）到 actor。"""
        return await _await_actor_call(
            self._actor.from_workspaces.remote(),
            operation="from_workspaces",
            timeout=_env_call_timeout("AGENTSOCIETY_ENV_STATE_TIMEOUT", 300),
        )

    async def close(self) -> None:
        """由运行所有者限时执行模块清理，随后终止 actor 且不重启。"""
        if self._closed:
            return

        import ray

        try:
            await _await_actor_call(
                self._actor.close.remote(),
                operation="close",
                timeout=_env_call_timeout("AGENTSOCIETY_ENV_CLOSE_TIMEOUT", 60),
            )
        finally:
            ray.kill(self._actor, no_restart=True)
            self._closed = True

    def get_token_usages(self) -> dict[str, Any]:
        """Fetch diagnostic statistics without blocking experiment teardown."""
        import ray

        ref = self._actor.get_token_usages.remote()
        try:
            return ray.get(ref, timeout=2)
        except ray.exceptions.GetTimeoutError:
            _cancel_actor_call(ref)
            raise


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
