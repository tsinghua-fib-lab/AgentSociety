"""用于批量执行 agent 的无状态 Ray Tasks。

驱动端(``AgentSociety``)只持有 agent 记录(spec/ids),从不持有 agent
对象。每个 tick 它把 id 列表分块,并为每个分块提交一个
:func:`step_agent_batch` Ray Task。每个任务:

- 从本地磁盘读取 agent 工作区(``<workspace_root>/agent_<id:04d>``),
- 通过 ``cls.from_workspace(ws, service_proxy)`` 重建 agent,
- 运行 ``agent.step(tick, t)``,经 ``agent.to_workspace(ws)`` 持久化,
- 返回轻量摘要列表(agent 对象不跨进程边界,从而保持 Ray object store
  健康)。

并行来自两层:(1) 大量任务被调度到多个 Ray worker(驱动端把 ids 分块,
每块提交一个任务),(2) 单个任务内的 agent 通过 ``asyncio.gather`` 并发
运行,每个 agent 都受 LLM 限制(一串被 await 的 LLM/工具调用),重叠
执行可让共享的 AdaptiveSemaphore 将 LLM 请求扇出到 API。全局 LLM 并发
由 dispatcher 的信号量控制,因此按批扇出是安全的。关键在于,任务从不
直接调用 ``ray.init`` / ``get_dispatcher``,而是消费注入的
``service_proxy`` 句柄以避免 Ray-in-Ray。

``create_agents_batch`` 为一批 spec 写入初始工作区,且不在驱动进程中
实例化 agent。

低频外部查询(ask/intervene/questionnaire/dump)完全不经 Ray:驱动端
在本地重建目标 agent(更简单,工作区在同一磁盘上)。

实现说明:Ray(2.x)不允许在普通 ``async def`` 任务上直接使用
``@ray.remote``。因此每个公开任务都是一个薄的同步包装,通过
``asyncio.run`` 驱动内部异步协程。异步核心保持 agent 契约
(``from_workspace`` / ``step`` / ``to_workspace`` 均为协程)不变。
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from agentsociety2.agent.service_proxy import ServiceProxy

_F = TypeVar("_F", bound=Callable[..., Any])


def _ray_remote(fn: _F) -> _F:
    try:
        import ray
    except ImportError:
        return fn
    return ray.remote(fn)  # type: ignore[return-value]


__all__ = [
    "create_agents_batch",
    "questionnaire_agent_batch",
    "step_agent_batch",
]


def _resolve_agent_class(
    agent_class_name: str, workspace_root: str | None = None
) -> Any:
    """通过模块注册表按名字解析 agent 类。

    在每个任务内完成(而非驱动端),使类对象不跨越 Ray 边界。

    :param agent_class_name: 已注册的 agent 类名(如 ``"PersonAgent"``)。
    :param workspace_root: agent 工作区根(``run_dir/agents``)。当父
        ``run_dir`` 包含 ``custom/`` 时会扫描该工作区,使自定义 agent
        类在本 worker 上可见。
    :returns: agent 类。
    :raises ValueError: 类未注册时抛出。
    """
    if workspace_root:
        run_dir = Path(workspace_root).resolve().parent
        if (run_dir / "custom").is_dir():
            from agentsociety2.registry import get_registry

            get_registry().set_workspace(run_dir)

    from agentsociety2.registry import get_agent_module_class

    cls = get_agent_module_class(agent_class_name)
    if cls is None:
        # Fall back to a direct attribute lookup on the agent package in case
        # the class is registered under a different type id than its __name__.
        try:
            from agentsociety2 import agent as _agent_mod

            cls = getattr(_agent_mod, agent_class_name, None)
        except Exception:
            cls = None
    if cls is None:
        raise ValueError(
            f"Agent class '{agent_class_name}' not found in registry; "
            "ensure the module is discovered before submitting tasks."
        )
    return cls


def _workspace_for(workspace_root: str, agent_id: int) -> Path:
    """返回每个 agent 的规范工作区路径。

    与 ``AgentSociety`` 和 ``PersonAgent`` 使用的方案一致:
    ``<workspace_root>/agent_<id:04d>``。
    """
    return Path(workspace_root) / f"agent_{int(agent_id):04d}"


# ---------------------------------------------------------------------------
# Async cores (testable in-process, driven by the sync Ray wrappers below)
# ---------------------------------------------------------------------------
async def _step_agent_batch_async(
    agent_ids: list[int],
    workspace_root: str,
    agent_class_name: str,
    tick: int,
    t: datetime,
    service_proxy: ServiceProxy,
) -> list[dict]:
    cls = _resolve_agent_class(agent_class_name, workspace_root)

    async def _step_one(aid: int) -> dict:
        ws = _workspace_for(workspace_root, aid)
        agent = None
        try:
            agent = await cls.from_workspace(ws, service_proxy)
            summary = await agent.step(tick, t)
        except Exception as e:
            # The step died mid-way, but whatever state the agent DID
            # advance (memory episodes, skill activation, step counter,
            # partial thread) is worth persisting — without this the
            # workspace silently stays a full tick behind the rest of
            # society with no marker of what happened. Save best-effort,
            # then report the failure.
            if agent is not None:
                persisted = False
                try:
                    await agent.to_workspace(ws)
                    persisted = True
                except Exception:
                    logging.getLogger(__name__).debug(
                        "Best-effort to_workspace after failed step also failed for agent %s",
                        aid,
                        exc_info=True,
                    )
            else:
                persisted = False
            try:
                if agent is not None:
                    await agent.close()
            except Exception:
                logging.getLogger(__name__).debug(
                    "Error closing agent %s after failed step", aid, exc_info=True
                )
            return {
                "id": aid,
                "ok": False,
                "error": repr(e),
                "state_persisted": persisted,
            }
        await agent.to_workspace(ws)
        try:
            await agent.close()
        except Exception:
            logging.getLogger(__name__).debug(
                "Error closing agent %s", aid, exc_info=True
            )
        return {"id": aid, "ok": True, "summary": summary}

    # Run all agents in the batch CONCURRENTLY. Each agent is LLM-bound — its
    # step() is a sequence of `await`-ed LLM/tool calls — so overlapping them
    # lets the shared AdaptiveSemaphore fan LLM requests out to the API rather
    # than serializing the whole batch behind one agent. Global LLM concurrency
    # is still gated by the dispatcher's semaphore; per-agent workspaces and the
    # injected service_proxy are concurrency-safe, so there is no shared mutable
    # state to protect. gather() preserves input order in the returned list.
    return await asyncio.gather(*[_step_one(aid) for aid in agent_ids])


async def _create_agents_batch_async(
    items: list[dict],
    workspace_root: str,
    agent_class_name: str,
) -> int:
    cls = _resolve_agent_class(agent_class_name, workspace_root)
    for it in items:
        ws = _workspace_for(workspace_root, int(it["id"]))
        cls.create(ws, it["profile"], it["config"])
    return len(items)


async def _questionnaire_agent_batch_async(
    agent_ids: list[int],
    workspace_root: str,
    agent_class_name: str,
    questionnaire: Any,
    t: datetime,
    step_count: int,
    service_proxy: ServiceProxy,
) -> list[dict]:
    """为批内每个 agent 运行完整问卷(并发)。

    与 ``_step_agent_batch_async`` 对称:每个 agent 从其工作区重建,运行
    完整问卷(所有问题),再经 ``to_workspace`` 持久化。agent 通过
    ``asyncio.gather`` 并发运行,每个 ``agent.ask`` 受 LLM 限制,重叠执行
    可让共享的 AdaptiveSemaphore 扇出请求。失败按 agent 隔离(一个坏
    agent 不会中止整个批次),与 ``step_agent_batch`` 一致。

    :returns: 每个 agent 一个 dict::

        {"id": int, "ok": True, "result": <AgentQuestionnaireResult dump>}
        {"id": int, "ok": False, "error": str}
    """
    from agentsociety2.society.questionnaire import QuestionnaireRunner

    cls = _resolve_agent_class(agent_class_name, workspace_root)
    runner = QuestionnaireRunner()

    async def _run_one(aid: int) -> dict:
        ws = _workspace_for(workspace_root, aid)
        try:
            agent = await cls.from_workspace(ws, service_proxy)
            try:
                # 单 agent 问卷整体超时(2026-10-20 修复):此前 gather 无
                # deadline,一个卡死的 LLM 调用能把整轮问卷挂 14 小时
                # (T2 clean 实锤:step 50 在 23:39→13:32 间挂死)。
                resp = await asyncio.wait_for(
                    runner.run(
                        questionnaire,
                        [agent],
                        t=t,
                        step_count=step_count,
                        target_agent_ids=[aid],
                    ),
                    float(os.getenv("AGENTSOCIETY_QUESTIONNAIRE_TIMEOUT", "600")),
                )
            finally:
                # Persist any agent state mutations back to the workspace
                # (the driver no longer holds the agent object).
                try:
                    await agent.to_workspace(ws)
                except Exception:
                    logging.getLogger(__name__).debug(
                        "Error persisting agent %s to workspace", aid, exc_info=True
                    )
            try:
                await agent.close()
            except Exception:
                logging.getLogger(__name__).debug(
                    "Error closing agent %s after query", aid, exc_info=True
                )
            per_agent = resp.responses[0] if resp.responses else None
            return {
                "id": aid,
                "ok": True,
                "result": per_agent.model_dump(mode="json") if per_agent else None,
            }
        except Exception as e:
            return {"id": aid, "ok": False, "error": repr(e)}

    return await asyncio.gather(*[_run_one(aid) for aid in agent_ids])


@_ray_remote
def step_agent_batch(
    agent_ids: list[int],
    workspace_root: str,
    agent_class_name: str,
    tick: int,
    t: datetime,
    service_proxy: ServiceProxy,
) -> list[dict]:
    """为批内每个 agent id 运行一次 ``step``。

    对每个 id:``from_workspace`` → ``step`` → ``to_workspace``。批内 agent
    通过 ``asyncio.gather`` 并发运行,每个都受 LLM 限制(一串被 await 的
    LLM/工具调用),重叠执行可让共享的 AdaptiveSemaphore 将 LLM 请求扇出
    到 API。全局 LLM 并发由 dispatcher 的信号量控制。跨群体的额外并行来自
    驱动端提交多个此类任务。

    :param agent_ids: 本批次内的 agent id 列表。
    :param workspace_root: 存放 ``agent_<id:04d>`` 工作区的目录。
    :param agent_class_name: 已注册的 agent 类名。
    :param tick: 本次 step 的 tick 跨度(秒)。
    :param t: 当前仿真时间。
    :param service_proxy: 共享服务句柄(env / llm / trace / replay),
        注入式提供,任务内从不重建。
    :returns: 每个 agent 的结果 dict 列表::

        {"id": int, "ok": True, "summary": str}
        {"id": int, "ok": False, "error": str}

        只有轻量摘要跨回驱动端,没有 agent 对象。同时携带本任务进程的
        token 使用增量(``token_stats``)回驱动端,以便跨所有批次聚合。
    """
    results = asyncio.run(
        _step_agent_batch_async(
            agent_ids, workspace_root, agent_class_name, tick, t, service_proxy
        )
    )
    # Drain this task's LLM clients' token stats (a delta since the last drain)
    # and return them alongside the per-agent results — no actor, no extra RPC.
    return {"results": results, "token_stats": service_proxy.take_token_stats()}


@_ray_remote
def create_agents_batch(
    items: list[dict],
    workspace_root: str,
    agent_class_name: str,
) -> int:
    """为一批 agent spec 创建初始工作区。

    对每个 spec ``{"id", "profile", "config"}`` 调用 ``cls.create(ws,
    profile, config)``。驱动端从不实例化 agent 对象,工作区在此写入,
    agent 按需重建。

    :param items: ``{"id": int, "profile": dict, "config": dict}`` 列表。
    :param workspace_root: 在其下创建 ``agent_<id:04d>`` 的目录。
    :param agent_class_name: 已注册的 agent 类名。
    :returns: 创建的 agent 工作区数量。
    """
    return asyncio.run(
        _create_agents_batch_async(items, workspace_root, agent_class_name)
    )


@_ray_remote
def questionnaire_agent_batch(
    agent_ids: list[int],
    workspace_root: str,
    agent_class_name: str,
    questionnaire: Any,
    t: datetime,
    step_count: int,
    service_proxy: ServiceProxy,
) -> dict:
    """为批内每个 agent 运行完整问卷。

    与 ``step_agent_batch`` 平行,但服务于外部问卷而非仿真 tick。对每个
    id:``from_workspace`` → 运行整个问卷(所有问题、readonly asks)→
    ``to_workspace``。批内 agent 通过 ``asyncio.gather`` 并发运行(每个
    ``ask`` 受 LLM 限制)。跨群体的并行来自驱动端提交多个此类任务,与
    ``step`` 完全一致。

    :param agent_ids: 本批次内的 agent id 列表。
    :param workspace_root: 存放 ``agent_<id:04d>`` 工作区的目录。
    :param agent_class_name: 已注册的 agent 类名。
    :param questionnaire: ``Questionnaire`` 模型(可跨 Ray 序列化)。
    :param t: 当前仿真时间(对 agent 推理具有权威性)。
    :param step_count: 当前仿真步数。
    :param service_proxy: 共享服务句柄(env / llm / trace / replay),
        注入式提供,任务内从不重建。
    :returns: ``{"results": [...], "token_stats": <delta>}``,其中每个 result 为::

        {"id": int, "ok": True, "result": <AgentQuestionnaireResult dump>}
        {"id": int, "ok": False, "error": str}

        ``token_stats`` 携带本进程的 token 使用增量回驱动端做聚合
        (无 actor,无额外 RPC)。
    """
    results = asyncio.run(
        _questionnaire_agent_batch_async(
            agent_ids,
            workspace_root,
            agent_class_name,
            questionnaire,
            t,
            step_count,
            service_proxy,
        )
    )
    return {"results": results, "token_stats": service_proxy.take_token_stats()}
