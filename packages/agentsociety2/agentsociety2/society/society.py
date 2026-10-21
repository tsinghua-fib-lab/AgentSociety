"""仿真社会编排模块（record-based，无 agent 对象常驻）。

:class:`AgentSociety` 不再持有 agent 对象——agent 是磁盘上的记录，每 tick 通过
Ray Task（:mod:`agentsociety2.agent.runner`）流式处理。这使得内存占用与总 agent 数 N
解耦：driver 只持有 specs（元数据）+ ids + 句柄（env / service_proxy），并行度来自
"大量 Ray Task"而非"主进程内的 N 个对象"。

主要功能：

- **仿真初始化**: 初始化 Ray / LLM dispatcher、service_proxy（已注入则复用）、批式创建 agent
  workspaces（不在主进程实例化 agent）、初始化环境路由器、可选回放写入 agent profile。
- **时间推进**: 通过 ``step()``/``run()`` 每 tick 切批提交 ``step_agent_batch`` Ray Task，
  ``await`` 全部后再推进 env、前进时钟。
- **交互接口**: ``ask()``/``intervene()``/``run_questionnaire()`` 为低频外部查询，在主进程
  内按需 ``from_workspace`` 重建目标 agent（workspace 在本地磁盘，无需 Ray Task）。
- **状态持久化**: ``to_workspace()`` 每 step 写 ``run_dir/SOCIETY.json``（society
  时间 / 步数 / env 模块配置）并让 env router 落盘各模块动态状态；``from_workspace()``
  从 ``run_dir`` 重建 society（agent 状态已落盘，env 由 actor 在 ``init`` 中恢复），
  支持中断后 CLI ``--resume`` 续跑。
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from importlib import import_module
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentsociety2.agent.runner import (
    create_agents_batch,
    questionnaire_agent_batch,
    step_agent_batch,
)
from agentsociety2.env import RouterBase
from agentsociety2.logger import get_logger
from agentsociety2.society.questionnaire import (
    AgentQuestionnaireResult,
    Questionnaire,
    QuestionnaireResponse,
)
from agentsociety2.storage import (
    ColumnDef,
    ReplayDatasetSpec,
    TableSchema,
)
from agentsociety2.storage.replay_metadata import (
    AGENT_PROFILE_DATASET_CAPABILITY,
    AGENT_PROFILE_DATASET_ID,
    AGENT_PROFILE_TABLE_NAME,
    SIMULATION_TIMELINE_CAPABILITY,
    SIMULATION_TIMELINE_DATASET_ID,
    SIMULATION_TIMELINE_TABLE_NAME,
)
from agentsociety2.storage.workspace_state import atomic_write_text

if TYPE_CHECKING:
    from agentsociety2.agent.base import AgentBase
    from agentsociety2.agent.service_proxy import ServiceProxy
    from agentsociety2.society.helper import AgentSocietyHelper

__all__ = ["AgentSociety"]

logger = get_logger()

# checkpoint 布局：SOCIETY.json 只在 init 写一次（含不可变的 agent_specs 等，
# 避免每步重序列化大列表）；SOCIETY_STEP.json 每步写少量标量。两文件均原子写入。
SOCIETY_JSON = "SOCIETY.json"
SOCIETY_STEP_JSON = "SOCIETY_STEP.json"
# LLM token 用量汇总（含 prompt 缓存命中）。收尾写一次；resume 时被忽略。
LLM_STATS_JSON = "LLM_STATS.json"
SOCIETY_SCHEMA_VERSION = 1


def _json_safe_profile(profile: Any) -> dict[str, Any]:
    """Convert an arbitrary profile payload into a JSON-safe dict."""
    if not isinstance(profile, dict):
        profile = {"raw": str(profile)}
    try:
        return json.loads(json.dumps(profile, ensure_ascii=False, default=str))
    except Exception:
        return {"raw": str(profile)}


def _chunked(lst: list, n: int):
    """Yield successive chunks of size ``n`` from ``lst``."""
    if n <= 0:
        n = 1
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _agent_name_from_spec(spec: dict) -> str:
    """Derive a display name from an agent spec (no reconstruction needed)."""
    profile = spec.get("profile") or {}
    if isinstance(profile, dict):
        name = profile.get("name")
        if isinstance(name, str) and name:
            return name
    return f"Agent_{spec.get('id')}"


class AgentSociety:
    """Record-based 仿真编排器（不持有 agent 对象）。

    AgentSociety 是框架的核心类，负责管理仿真生命周期：

    - 持有 **agent_specs** （元数据含 id / profile / config）与 **agent_ids**，
      绝不在主进程常驻 agent 对象。
    - ``step`` 每 tick 切批提交 ``step_agent_batch`` Ray Task，跨 worker 并行；批内顺序执行
      （每个 agent 是 LLM-bound，顺序无妨）。
    - ``ask`` / ``intervene`` / ``run_questionnaire`` 为低频外部查询，按需在主进程
      ``from_workspace`` 重建目标 agent （workspace 在本地磁盘）。
      状态落盘使用 ``to_workspace`` / ``from_workspace`` （society 级 checkpoint）。

    Example::

        from datetime import datetime
        from pathlib import Path
        from agentsociety2.society import AgentSociety

        society = AgentSociety(
            agent_specs=[{"id":1,"profile":{...},"config":{...}}, ...],
            agent_class_name="PersonAgent",
            env_router=env_proxy,
            service_proxy=proxy,
            start_t=datetime.now(),
            run_dir=Path("./run"),
        )

        async with society:
            await society.run(num_steps=100, tick=3600)
    """

    def __init__(
        self,
        agent_specs: list[dict],
        agent_class_name: str,
        env_router: RouterBase,
        start_t: datetime,
        run_dir: Path | None = None,
        *,
        service_proxy: ServiceProxy | None = None,
        batch_size: int | None = None,
        enable_replay: bool = True,
        env_module_types: list[str] | None = None,
        env_kwargs: dict[str, dict] | None = None,
    ):
        """创建 record-based 仿真编排器。

        :param agent_specs: agent 元数据列表，每个形如
            ``{"id": int, "profile": dict, "config": dict}``。仅元数据，不在构造时实例化。
        :param agent_class_name: agent 类名（经 registry 解析，如 ``"PersonAgent"``）。
        :param env_router: 环境路由器（in-process 或 ``EnvRouterProxy``）。
        :param start_t: 仿真开始时间。
        :param run_dir: 运行目录（``run_dir/agents`` 为 agent workspaces 根）。
        :param service_proxy: 共享服务句柄（env / llm / trace / replay）。流式任务
            处理必需——runner 任务通过它访问 LLM clients / env actor。提供时 :meth:`init`
            直接复用；``close`` 关闭其中 trace/replay actor。
        :param batch_size: 每 ``step_agent_batch`` Ray Task 处理的 agent 数；
            ``None`` 时回落到 ``Config.BATCH_SIZE``（环境变量
            ``AGENTSOCIETY_BATCH_SIZE``，缺省 256）。
        :param enable_replay: 是否启用回放记录。
        """
        self._agent_specs: list[dict] = list(agent_specs)
        self._agent_class_name: str = agent_class_name
        self._agent_ids: list[int] = [int(s["id"]) for s in self._agent_specs]

        self._env_router = env_router
        self._t = start_t
        self._should_terminate: bool = False
        self._step_count: int = 0

        # Resolve to ABSOLUTE paths. Ray worker processes may run with a cwd
        # inside an uploaded runtime-env package (/tmp/ray/.../_ray_pkg_.../),
        # not the driver's cwd — so a relative run_dir would resolve to a
        # phantom path inside the package and agent workspaces would never land
        # where the driver (and replay/trace) expect them.
        self._run_dir = Path(run_dir).resolve() if run_dir is not None else None
        self._workspace_root: Path = (
            (self._run_dir / "agents").resolve()
            if self._run_dir is not None
            else Path("./agents").resolve()
        )
        from agentsociety2.config import Config

        resolved_batch_size = (
            batch_size if batch_size is not None else Config.BATCH_SIZE
        )
        self._batch_size = max(1, int(resolved_batch_size))
        self._enable_replay = enable_replay

        # env 模块类型 + init kwargs：写入 SOCIETY.json，resume 时据此重建 env 模块。
        self._env_module_types: list[str] = list(env_module_types or [])
        self._env_kwargs: dict[str, dict] = {
            k: dict(v) for k, v in (env_kwargs or {}).items()
        }
        # resume 游标：已完成的前置 step 数（含 Ask/Intervene/Questionnaire），
        # 由 CLI 在每个顶层 step 开始前推进；resume 时据此跳过已执行的前置步。
        self._completed_step_count: int = 0
        # steps.yaml 的 hash（CLI 在 init 前设置），用于 resume 时检测 steps 漂移。
        self._steps_hash: str | None = None

        self._service_proxy: ServiceProxy | None = service_proxy
        self._owns_service_proxy = service_proxy is not None

        self._replay_writer: Any = None
        self._agent_profiles_persisted = False
        self._simulation_timeline_ready = False
        self._agents_created = False
        # SOCIETY.json（不可变全量）只在 init 写一次；resume 时由 from_workspace
        # 置 True 跳过，避免覆盖原 checkpoint。
        self._society_json_written = False
        # Aggregate LLM token usage across all Ray Task batches (instance-level,
        # not module-global). Each batch returns a per-task delta.
        self._token_stats: dict[str, dict[str, int]] = {}

        # Helper is built lazily on first ask/intervene (it reconstructs agents on demand).
        self._helper: AgentSocietyHelper | None = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def current_time(self) -> datetime:
        """返回当前仿真时间。"""
        return self._t

    @property
    def step_count(self) -> int:
        """返回已执行的仿真步数。"""
        return self._step_count

    @property
    def agent_ids(self) -> list[int]:
        """返回所有 agent id（不暴露 agent 对象）。"""
        return list(self._agent_ids)

    @property
    def agent_specs(self) -> list[dict]:
        """返回 agent specs（元数据快照）。"""
        return list(self._agent_specs)

    @property
    def token_stats(self) -> dict[str, dict[str, int]]:
        """按模型聚合的 LLM token 用量（agent 侧，快照）。

        每项含 ``calls`` / ``input`` / ``output`` / ``cached_input``。
        ``cached_input`` 是 ``input`` 中命中 provider prompt 前缀缓存的部分。
        仅统计 agent 侧调用；env router（coder 角色）的用量见
        :meth:`router_token_stats`。
        """
        return {model: dict(s) for model, s in self._token_stats.items()}

    @property
    def router_token_stats(self) -> dict[str, dict[str, int]]:
        """env router（coder/summary 角色）的 token 用量快照。

        :meth:`RouterBase.get_token_usages` 返回的是**快照而非增量**，所以这里
        取一次合并即可，不要按步累加，否则会重复计数。
        """
        env_router = getattr(self, "_env_router", None)
        getter = getattr(env_router, "get_token_usages", None)
        if getter is None:
            return {}
        usages = getter()
        stats = {
            model: {
                "calls": int(getattr(u, "call_count", 0) or 0),
                "input": int(getattr(u, "input_tokens", 0) or 0),
                "output": int(getattr(u, "output_tokens", 0) or 0),
                "cached_input": int(getattr(u, "cached_input_tokens", 0) or 0),
            }
            for model, u in (usages or {}).items()
        }
        return {model: s for model, s in stats.items() if s["calls"] or s["input"]}

    def all_token_stats(self) -> dict[str, dict[str, int]]:
        """agent 侧 + env router 侧的 token 用量合并快照。"""
        from agentsociety2.config.llm_dispatcher import merge_token_stats

        return merge_token_stats(self.token_stats, self.router_token_stats)

    def cache_hit_rate(self) -> float:
        """Prompt 前缀缓存命中率（``cached_input / input``，全部调用合计）。

        .. note::
           分母包含 ask 轮与一次性工具调用（world description、memory
           consolidation），这些结构上不可能命中前缀缓存、恒为 0%，因此该聚合值
           会**低估** ReAct 循环自身的命中率。要看后者请用 ``llm.completion``
           trace span 上的 ``llm.cache_hit_rate``。
        """
        from agentsociety2.config.llm_dispatcher import cache_hit_rate

        return cache_hit_rate(self.all_token_stats())

    # ------------------------------------------------------------------
    # Replay: agent profile persistence (record-based)
    # ------------------------------------------------------------------
    async def _persist_agent_profiles_once(self) -> None:
        if self._replay_writer is None or self._agent_profiles_persisted:
            return

        columns = [
            ColumnDef(
                "id",
                "INTEGER",
                nullable=False,
                logical_type="entity_id",
                description="Unique agent identifier.",
            ),
            ColumnDef(
                "name",
                "TEXT",
                nullable=False,
                logical_type="label",
                description="Agent display name.",
            ),
            ColumnDef(
                "profile",
                "JSON",
                nullable=False,
                logical_type="json",
                description="Static agent profile payload captured at simulation init.",
            ),
            ColumnDef(
                "created_at",
                "TIMESTAMP",
                nullable=False,
                logical_type="timestamp",
                description="When the agent profile snapshot was persisted.",
            ),
        ]
        await self._replay_writer.register_table(
            TableSchema(
                name=AGENT_PROFILE_TABLE_NAME,
                columns=columns,
                primary_key=["id"],
                indexes=[["name"]],
            )
        )
        await self._replay_writer.register_dataset(
            ReplayDatasetSpec(
                dataset_id=AGENT_PROFILE_DATASET_ID,
                table_name=AGENT_PROFILE_TABLE_NAME,
                module_name="AgentSociety",
                kind="entity_static",
                title="Agent Profiles",
                description="Static agent profiles persisted once when the simulation initializes.",
                entity_key="id",
                default_order=["id"],
                capabilities=[AGENT_PROFILE_DATASET_CAPABILITY, "entity_static"],
            ),
            columns,
        )

        rows = [
            {
                "id": int(spec["id"]),
                "name": _agent_name_from_spec(spec),
                "profile": _json_safe_profile(spec.get("profile", {})),
                "created_at": self._t,
            }
            for spec in self._agent_specs
        ]
        if rows:
            await self._replay_writer.write_batch(AGENT_PROFILE_TABLE_NAME, rows)
        self._agent_profiles_persisted = True

    async def _ensure_simulation_timeline_dataset(self) -> None:
        """Register the society-owned simulation timeline dataset once."""
        if self._replay_writer is None or self._simulation_timeline_ready:
            return
        columns = [
            ColumnDef(
                "step",
                "INTEGER",
                nullable=False,
                logical_type="step",
                analysis_role="timestamp",
                description="Simulation step index for this timeline marker.",
            ),
            ColumnDef(
                "t",
                "TIMESTAMP",
                nullable=False,
                logical_type="timestamp",
                analysis_role="timestamp",
                description="Simulation timestamp for this timeline marker.",
            ),
        ]
        await self._replay_writer.register_table(
            TableSchema(
                name=SIMULATION_TIMELINE_TABLE_NAME,
                columns=columns,
                primary_key=["step"],
                indexes=[["t"]],
            )
        )
        await self._replay_writer.register_dataset(
            ReplayDatasetSpec(
                dataset_id=SIMULATION_TIMELINE_DATASET_ID,
                table_name=SIMULATION_TIMELINE_TABLE_NAME,
                module_name="AgentSociety",
                kind="env_snapshot",
                title="Simulation Timeline",
                description=(
                    "Society-owned step markers so replay has a timeline even "
                    "while a long tick is still running."
                ),
                step_key="step",
                time_key="t",
                default_order=["step"],
                capabilities=[
                    SIMULATION_TIMELINE_CAPABILITY,
                    "env_snapshot",
                    "timeseries",
                ],
            ),
            columns,
        )
        self._simulation_timeline_ready = True

    async def _write_simulation_timeline_point(self, step: int, t: datetime) -> None:
        """Append one timeline marker used by the replay UI."""
        if self._replay_writer is None:
            return
        await self._ensure_simulation_timeline_dataset()
        await self._replay_writer.write(
            SIMULATION_TIMELINE_TABLE_NAME,
            {"step": int(step), "t": t},
        )

    # ------------------------------------------------------------------
    # Workspace helpers
    # ------------------------------------------------------------------
    def _workspace_for(self, agent_id: int) -> Path:
        """Return ``<workspace_root>/agent_<id:04d>``."""
        return self._workspace_root / f"agent_{int(agent_id):04d}"

    async def _create_agent_workspaces(self) -> None:
        """Batch-create agent workspaces via ``create_agents_batch`` Ray Tasks.

        Agents are NOT instantiated in the society process — each task writes
        ``config.json`` + initial ``AGENT.json`` for its chunk of specs.
        """
        if self._agents_created or not self._agent_specs:
            self._agents_created = True
            return

        refs = []
        for chunk in _chunked(self._agent_specs, self._batch_size):
            refs.append(
                create_agents_batch.remote(
                    chunk,
                    str(self._workspace_root),
                    self._agent_class_name,
                )
            )
        if refs:
            await asyncio.gather(*[self._await_ref(r) for r in refs])
        self._agents_created = True

    async def _resolve_service_proxy(self) -> ServiceProxy:
        """Return the bound service proxy, building one if none injected."""
        if self._service_proxy is not None:
            return self._service_proxy
        from agentsociety2.agent.service_proxy import build_service_proxy

        proxy = build_service_proxy(
            self._env_router,
            run_dir=self._run_dir,
            trace=False,
            replay=bool(self._enable_replay and self._run_dir is not None),
        )
        self._service_proxy = proxy
        self._owns_service_proxy = True
        return proxy

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def init(self):
        """初始化：Ray / LLM dispatcher → service_proxy → replay → 批式创建 workspaces → env init。"""
        # Initializes Ray and per-process LLM dispatch support (idempotent).
        from agentsociety2.config.llm_dispatcher import init_dispatchers

        await init_dispatchers()

        proxy = await self._resolve_service_proxy()

        # Replay: the single proxy.replay handle (a the distributed ReplayProxy proxy).
        self._replay_writer = getattr(proxy, "replay", None)
        if self._replay_writer is not None:
            await self._persist_agent_profiles_once()
            try:
                self._env_router.set_replay_writer(self._replay_writer)
            except Exception:
                logger.debug("Failed to set replay writer on env router", exc_info=True)

        # Ensure workspace_root exists before tasks write into it.
        self._workspace_root.mkdir(parents=True, exist_ok=True)

        # Batch-create agent workspaces (no agent objects in this process).
        await self._create_agent_workspaces()

        await self._env_router.init(self._t)

        # Step-0 timeline marker: replay UI can open immediately after init,
        # even if the first agent tick has not finished writing env snapshots.
        if self._replay_writer is not None:
            await self._write_simulation_timeline_point(0, self._t)

        # 写一次不可变全量 checkpoint（含 agent_specs / env 配置 / steps_hash）。
        # resume 时（from_workspace 已置 _society_json_written=True）跳过，避免覆盖。
        if self._run_dir is not None and not self._society_json_written:
            self._write_society_json()
            self._society_json_written = True

    async def close(self):
        """关闭：env router + service_proxy 的 trace/replay 句柄 + LLM dispatcher。"""
        try:
            await self._env_router.close()
        except Exception:
            logger.debug("Error closing env router", exc_info=True)

        # Close the proxy's replay actor (if we own the proxy). Trace needs no
        # central close: it is distributed — each writer process appends
        # directly and its fds are reclaimed on process exit.
        if self._owns_service_proxy and self._service_proxy is not None:
            replay = getattr(self._service_proxy, "replay", None)
            if replay is not None and hasattr(replay, "close"):
                try:
                    await replay.close()
                except Exception:
                    logger.debug("Error closing replay writer", exc_info=True)

        # LLM shutdown is currently a no-op; local Routers die with the process.
        from agentsociety2.config.llm_dispatcher import shutdown_dispatchers

        await shutdown_dispatchers()

    # ------------------------------------------------------------------
    # 状态持久化 / resume（无状态 checkpoint）
    # ------------------------------------------------------------------
    async def to_workspace(self, *, tick: int | None = None) -> None:
        """持久化 society + env 状态（每步调用，无状态 resume）。

        让 env router 落盘各模块状态，并写 ``run_dir/SOCIETY_STEP.json``（仅少量
        标量：当前时间 / 步数 / 已完成前置步数 / terminated）。不可变的大字段
        （agent_specs 等）只在 :meth:`init` 写一次到 ``SOCIETY.json``，避免每步
        重序列化。``run_dir`` 为空时 no-op；env 落盘失败只告警，不中断 step。

        :param tick: 保留以兼容旧调用签名（不再单独持久化）。
        """
        if self._run_dir is None:
            return
        try:
            await self._env_router.to_workspaces()
        except Exception as exc:
            logger.warning("env to_workspaces failed: %s", exc)
        self._write_society_step_json()

    def _write_society_json(self) -> None:
        """写不可变全量 checkpoint 到 ``run_dir/SOCIETY.json``（init 时写一次）。

        含 schema_version、agent_specs、env 模块类型+kwargs、batch_size、steps_hash。
        原子写入。
        """
        assert self._run_dir is not None
        payload = {
            "schema_version": SOCIETY_SCHEMA_VERSION,
            "agent_class_name": self._agent_class_name,
            "agent_specs": list(self._agent_specs),
            "env_module_types": list(self._env_module_types),
            "env_kwargs": dict(self._env_kwargs),
            "batch_size": self._batch_size,
            "steps_hash": self._steps_hash,
        }
        atomic_write_text(
            self._run_dir / SOCIETY_JSON,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )

    def _write_society_step_json(self) -> None:
        """写每步标量 checkpoint 到 ``run_dir/SOCIETY_STEP.json``（原子写入）。"""
        assert self._run_dir is not None
        payload = {
            "current_time": self._t.isoformat(),
            "step_count": self._step_count,
            "completed_step_count": self._completed_step_count,
            "terminated": self._should_terminate,
        }
        atomic_write_text(
            self._run_dir / SOCIETY_STEP_JSON,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )

    def write_llm_stats_json(self) -> dict[str, Any] | None:
        """把 LLM token 用量与缓存命中率写到 ``run_dir/LLM_STATS.json``。

        含 agent 侧与 env router（coder）侧的合并快照、逐模型明细、以及聚合命中率。
        原始计数器一并保留——不同网关对 ``input`` 是否含 cache read 的口径不同，
        保留原值便于自行换算。

        :returns: 写入的 payload；无 run_dir 时返回 ``None``。
        """
        if self._run_dir is None:
            return None

        from agentsociety2.config.llm_dispatcher import (
            cache_hit_rate,
            merge_token_stats,
        )

        # Snapshot each side once: ``router_token_stats`` hits the env router.
        agent_stats = self.token_stats
        router_stats = self.router_token_stats
        combined = merge_token_stats(agent_stats, router_stats)

        def _totals(stats: dict[str, dict[str, int]]) -> dict[str, int]:
            return {
                "calls": sum(int(s.get("calls", 0)) for s in stats.values()),
                "input": sum(int(s.get("input", 0)) for s in stats.values()),
                "output": sum(int(s.get("output", 0)) for s in stats.values()),
                "cached_input": sum(
                    int(s.get("cached_input", 0)) for s in stats.values()
                ),
            }

        payload = {
            "schema_version": 1,
            "step_count": self._step_count,
            "current_time": self._t.isoformat(),
            "models": combined,
            "totals": _totals(combined),
            "cache_hit_rate": cache_hit_rate(combined),
            "agent_side": {
                "models": agent_stats,
                "totals": _totals(agent_stats),
                "cache_hit_rate": cache_hit_rate(agent_stats),
            },
            "router_side": {
                "models": router_stats,
                "totals": _totals(router_stats),
                "cache_hit_rate": cache_hit_rate(router_stats),
            },
        }
        atomic_write_text(
            self._run_dir / LLM_STATS_JSON,
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
        )
        return payload

    def mark_step_completed(self, step_idx: int) -> None:
        """标记第 ``step_idx`` 个顶层 step 已完成并立即持久化进度。

        由 CLI 在每个顶层 step（含 Ask/Intervene/Questionnaire）成功后调用——
        否则连续的非 RunStep 完成后若崩溃，resume 会把它们当作未执行而重跑。
        """
        if self._run_dir is None:
            return
        self._completed_step_count = step_idx + 1
        self._write_society_step_json()

    @staticmethod
    def _read_checkpoint(run_dir: Path) -> tuple[dict, dict]:
        """读取并校验 society checkpoint，返回 (society_meta, step_meta)。

        :raises FileNotFoundError: SOCIETY.json 不存在。
        :raises ValueError: schema_version 缺失/不支持，或字段残缺。
        """
        run_dir = Path(run_dir)
        meta_path = run_dir / SOCIETY_JSON
        if not meta_path.is_file():
            raise FileNotFoundError(
                f"Cannot resume: {meta_path} not found (not a checkpoint run_dir)"
            )
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Cannot resume: {meta_path} is corrupt or was truncated "
                f"(non-atomic write of a prior crash?): {exc}"
            ) from exc
        schema_version = meta.get("schema_version")
        if schema_version != SOCIETY_SCHEMA_VERSION:
            raise ValueError(
                f"Cannot resume: {meta_path} schema_version={schema_version!r}, "
                f"expected {SOCIETY_SCHEMA_VERSION}. The checkpoint was written by "
                "an incompatible build."
            )
        if "agent_class_name" not in meta:
            raise ValueError(f"Cannot resume: {meta_path} missing agent_class_name")
        step_path = run_dir / SOCIETY_STEP_JSON
        step_meta: dict = {}
        if step_path.is_file():
            try:
                step_meta = json.loads(step_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"Cannot resume: {step_path} is corrupt or was truncated: {exc}"
                ) from exc
        return meta, step_meta

    @classmethod
    async def from_workspace(
        cls,
        run_dir: Path,
        *,
        env_router: RouterBase,
        service_proxy: ServiceProxy | None = None,
    ) -> AgentSociety:
        """从 ``run_dir`` 重建 society（resume）。

        读 ``SOCIETY.json``（不可变：agent specs、env 模块类型+kwargs）+
        ``SOCIETY_STEP.json``（每步标量：当前时间、步数、已完成前置步数）。
        ``env_router`` 必须由调用方（CLI）预先构造（actor 不可在此重建）；
        env 模块状态由 actor 在自身 ``init()`` 中恢复。

        返回的 society 的 :meth:`init` 会跳过 agent workspace 创建与 profile 重写
        （原 run 已存在），也不会覆盖已有的 ``SOCIETY.json``。

        :raises FileNotFoundError: ``run_dir/SOCIETY.json`` 不存在。
        :raises ValueError: schema 不兼容或 checkpoint 损坏。
        """
        run_dir = Path(run_dir).resolve()
        meta, step_meta = cls._read_checkpoint(run_dir)
        if step_meta.get("current_time"):
            current_time = datetime.fromisoformat(str(step_meta["current_time"]))
        else:
            # 旧布局（仅有 SOCIETY.json，无 SOCIETY_STEP.json）——回退到 SOCIETY.json。
            current_time = datetime.fromisoformat(str(meta["current_time"]))
        society = cls(
            agent_specs=list(meta.get("agent_specs", [])),
            agent_class_name=str(meta["agent_class_name"]),
            env_router=env_router,
            start_t=current_time,
            run_dir=run_dir,
            service_proxy=service_proxy,
            batch_size=meta.get("batch_size"),
            enable_replay=True,
            env_module_types=list(meta.get("env_module_types", [])),
            env_kwargs=dict(meta.get("env_kwargs", {})),
        )
        society._steps_hash = meta.get("steps_hash")
        society._step_count = int(
            step_meta.get("step_count", meta.get("step_count", 0))
        )
        society._completed_step_count = int(step_meta.get("completed_step_count", 0))
        # init() 时跳过 agent workspace 创建、profile 重写，以及 SOCIETY.json 覆盖。
        society._agents_created = True
        society._agent_profiles_persisted = True
        society._simulation_timeline_ready = True
        society._society_json_written = True
        return society

    async def __aenter__(self):
        await self.init()
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    # ------------------------------------------------------------------
    # Step / Run — the hot path (no agent objects held)
    # ------------------------------------------------------------------
    async def step(self, tick: int):
        """推进一次仿真步：sync clock → 切批 step_agent_batch → env.step → 前进时钟。

        :param tick: 本步时间跨度（秒）。
        """
        if not self._agent_ids:
            # 仍推进 env + 时钟。
            self._env_router.set_current_time(self._t)
            if self._replay_writer is not None:
                await self._write_simulation_timeline_point(self._step_count, self._t)
            await self._env_router.step(tick, self._t)
            self._t += timedelta(seconds=tick)
            self._step_count += 1
            # 自增后再落盘，checkpoint 反映已完成步数。
            await self.to_workspace(tick=tick)
            return

        proxy = await self._resolve_service_proxy()

        # Push the clock to env BEFORE fan-out so all batches share the same
        # time context (env modules read it during agent tool calls).
        self._env_router.set_current_time(self._t)

        # Publish the upcoming step marker before the long agent fan-out so
        # replay stays usable while a tick is still running.
        if self._replay_writer is not None:
            await self._write_simulation_timeline_point(self._step_count, self._t)

        # Chunk ids and submit one Ray Task per chunk.
        refs = []
        for ids in _chunked(self._agent_ids, self._batch_size):
            refs.append(
                step_agent_batch.remote(
                    ids,
                    str(self._workspace_root),
                    self._agent_class_name,
                    tick,
                    self._t,
                    proxy,
                )
            )
        # Await all batches. Each batch returns {"results", "token_stats"};
        # fold the per-task token-usage deltas into this society's instance
        # aggregate (no module-global state).
        if refs:
            from agentsociety2.config.llm_dispatcher import merge_token_stats

            batch_returns = await asyncio.gather(*[self._await_ref(r) for r in refs])
            failures: list[str] = []
            for br in batch_returns:
                if not isinstance(br, dict):
                    continue
                if br.get("token_stats"):
                    self._token_stats = merge_token_stats(
                        self._token_stats, br["token_stats"]
                    )
                for item in br.get("results") or []:
                    if isinstance(item, dict) and not item.get("ok", True):
                        failures.append(f"agent {item.get('id')}: {item.get('error')}")
            if failures:
                preview = "; ".join(failures[:5])
                more = "" if len(failures) <= 5 else f" (+{len(failures) - 5} more)"
                raise RuntimeError(
                    f"Agent step failures ({len(failures)}): {preview}{more}"
                )

        # Env advances AFTER agents.
        await self._env_router.step(tick, self._t)
        self._t += timedelta(seconds=tick)
        self._step_count += 1
        # 自增后再落盘，checkpoint 反映已完成步数。
        await self.to_workspace(tick=tick)

    async def run(self, num_steps: int, tick: int):
        """运行多步仿真。

        :param num_steps: 运行步数上限。
        :param tick: 每步时间跨度（秒）。
        """
        for _ in range(num_steps):
            if self._should_terminate:
                break
            await self.step(tick)

    @staticmethod
    async def _await_ref(ref: Any) -> Any:
        """Await a Ray ObjectRef (Ray >=2 supports ``await ref`` in an asyncio loop)."""
        return await ref

    # ------------------------------------------------------------------
    # Queries — low-volume, reconstruct target agents locally
    # ------------------------------------------------------------------
    async def _reconstruct_agent(self, agent_id: int) -> AgentBase:
        """Reconstruct a single agent in the society process via from_workspace.

        Used by ask/intervene/questionnaire (low-volume external queries). The
        workspace lives on local disk, so no Ray Task is needed.
        """
        from agentsociety2.registry import get_agent_module_class

        cls = get_agent_module_class(self._agent_class_name)
        if cls is None:
            try:
                from agentsociety2 import agent as _agent_mod

                cls = getattr(_agent_mod, self._agent_class_name, None)
            except Exception:
                cls = None
        if cls is None:
            raise ValueError(
                f"Agent class '{self._agent_class_name}' not found in registry."
            )
        proxy = await self._resolve_service_proxy()
        ws = self._workspace_for(int(agent_id))
        return await cls.from_workspace(ws, proxy)

    async def _reconstruct_agents(self, agent_ids: list[int]) -> list[AgentBase]:
        """Reconstruct a subset of agents (parallel from_workspace calls)."""
        coros = [self._reconstruct_agent(int(aid)) for aid in agent_ids]
        return list(await asyncio.gather(*coros))

    def _get_helper(self) -> AgentSocietyHelper:
        """Lazily build the plan-and-execute helper bound to this society.

        The helper receives the society handle (specs/ids + reconstruction
        callbacks) instead of a pre-built agent list, so it can reconstruct
        only the agents a specific plan needs.
        """
        if self._helper is None:
            helper_module = import_module("agentsociety2.society.helper")
            self._helper = helper_module.AgentSocietyHelper(
                env_router=self._env_router,
                society=self,
            )
        return self._helper

    async def ask(self, question: str) -> str:
        """向仿真系统提问（由 helper 协调 agents/env 作答）。

        :param question: 问题文本。
        :returns: 答案文本。
        """
        return await self._get_helper().ask(question)

    async def intervene(self, instruction: str) -> str:
        """对仿真进行干预（由 helper 协调执行）。

        :param instruction: 干预指令文本。
        :returns: 执行结果/反馈文本。
        """
        return await self._get_helper().intervene(instruction)

    async def run_questionnaire(
        self,
        questionnaire: Questionnaire,
        target_agent_ids: list[int] | None = None,
    ) -> QuestionnaireResponse:
        """向目标 agents 发放问卷并返回结构化结果。

        目标 agent 按 id 切批，每批提交一个 ``questionnaire_agent_batch`` Ray Task
        （与 ``step`` 同款分布式批处理）：worker 进程内 ``from_workspace`` 重建本批
        agents、并发跑完整个问卷、``to_workspace`` 落盘，再返回结构化结果。失败的单个
        agent 被隔离（不中断整批），与 ``step_agent_batch`` 的容错语义一致。

        :param questionnaire: 问卷定义。
        :param target_agent_ids: 目标 agent id（默认全部）。
        :returns: 汇总后的问卷响应。
        """
        ids = (
            list(target_agent_ids)
            if target_agent_ids is not None
            else list(self._agent_ids)
        )
        # Validate ids against known specs.
        known = set(self._agent_ids)
        missing = [i for i in ids if int(i) not in known]
        if missing:
            raise ValueError(f"Unknown target_agent_ids: {missing}")

        ordered_ids = [int(i) for i in ids]

        if not ordered_ids:
            return QuestionnaireResponse(
                questionnaire_id=questionnaire.questionnaire_id,
                title=questionnaire.title,
                description=questionnaire.description,
                simulation_time=self._t.isoformat(),
                step_count=self._step_count,
                target_agent_ids=ordered_ids,
                questions=questionnaire.questions,
                responses=[],
            )

        proxy = await self._resolve_service_proxy()

        # Chunk ids and submit one Ray Task per chunk — same fan-out as step().
        refs = []
        for chunk in _chunked(ordered_ids, self._batch_size):
            refs.append(
                questionnaire_agent_batch.remote(
                    chunk,
                    str(self._workspace_root),
                    self._agent_class_name,
                    questionnaire,
                    self._t,
                    self._step_count,
                    proxy,
                )
            )

        from agentsociety2.config.llm_dispatcher import merge_token_stats

        batch_returns = await asyncio.gather(*[self._await_ref(r) for r in refs])

        # Merge per-agent results across batches; aggregate token deltas.
        results_by_id: dict[int, dict] = {}
        failed: list[tuple[int, str]] = []
        for br in batch_returns:
            if isinstance(br, dict) and br.get("token_stats"):
                self._token_stats = merge_token_stats(
                    self._token_stats, br["token_stats"]
                )
            for r in br.get("results", []):
                results_by_id[int(r["id"])] = r
                if not r.get("ok"):
                    failed.append((int(r["id"]), str(r.get("error"))))

        responses: list[AgentQuestionnaireResult] = []
        for aid in ordered_ids:
            r = results_by_id.get(aid)
            if r is not None and r.get("ok") and r.get("result") is not None:
                responses.append(AgentQuestionnaireResult.model_validate(r["result"]))

        if failed:
            logger.warning(
                "Questionnaire %s: %d/%d agents failed (skipped): %s",
                questionnaire.questionnaire_id,
                len(failed),
                len(ordered_ids),
                failed[:5],
            )

        return QuestionnaireResponse(
            questionnaire_id=questionnaire.questionnaire_id,
            title=questionnaire.title,
            description=questionnaire.description,
            simulation_time=self._t.isoformat(),
            step_count=self._step_count,
            target_agent_ids=ordered_ids,
            questions=questionnaire.questions,
            responses=responses,
        )
