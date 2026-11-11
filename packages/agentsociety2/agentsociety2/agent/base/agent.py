"""``AgentBase`` —— 通用 agent 运行时基类。

中文：``AgentBase`` 是所有 agent 的基类，直接拥有 workspace 绑定、skill
runtime、ReAct 工具调度、identity、service slots、抽象契约和构造模型。
English: ``AgentBase`` is the base class for all agents. It directly owns
workspace binding, the skill runtime, ReAct tool dispatch, identity, service
slots, the abstract contract, and the construction model.

构造模型(``__init__`` 无实际意义):

- ``AgentBase.__init__(self)`` —— 无参。仅初始化空槽位。
- ``AgentBase.create(workspace_path, profile, config)`` —— 写入初始
  workspace(``config.json`` + ``AGENT.json`` + 目录)。不返回实例。
- ``AgentBase.from_workspace(workspace_path, service_proxy)`` ——
  ``agent = cls()``;``await agent.restore(ws, proxy)``;返回。
- ``AgentBase.restore(workspace_path, service_proxy)`` —— 真正的初始化:
  读取 config.json + AGENT.json;设置 ``_id``/``_profile``/``_name``/
  ``_config``;调用 ``_bind_services`` + ``_bind_workspace``;恢复
  visible/activated skills 与计数器。
"""

from __future__ import annotations

import asyncio
import json
import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentsociety2.agent.base.react import (
    ReactDecision,
    ReactToolResult,
    ReactTurn,
)
from agentsociety2.agent.base.skill_registry import get_skill_registry
from agentsociety2.agent.base.skill_runtime import AgentSkillRuntime
from agentsociety2.agent.base.todo import TodoStateStore
from agentsociety2.agent.base.tool_schema import react_tool_schemas
from agentsociety2.agent.base.workspace_fs import WorkspaceFS
from agentsociety2.agent.person_prompt import (
    json_block as _json_block,
)
from agentsociety2.agent.person_prompt import (
    short_text as _short_text,
)
from agentsociety2.agent.person_prompt import (
    xml_block as _xml_block,
)
from agentsociety2.config.llm_dispatcher import reasoning_fields
from agentsociety2.env.router_base import RouterBase
from agentsociety2.logger import get_logger
from agentsociety2.trace import (
    JsonlTraceWriter,
    TraceSpan,
)

if TYPE_CHECKING:
    from agentsociety2.agent.service_proxy import ServiceProxy

__all__ = [
    "AgentBase",
]

logger = get_logger()

# agent workspace 布局常量（agent 专属）。
AGENT_JSON_PATH = "AGENT.json"
STANDARD_WORKSPACE_DIRS = ("state", "memory")

# Short clock shorthand (HH:MM) used to normalize TODO ``due`` values.
_SHORT_CLOCK_RE = re.compile(r"^(?P<hour>[01]?\d|2[0-3]):(?P<minute>[0-5]\d)$")


def _brief_memories_summary(memories: Any) -> str:
    """由内联 finish memories 推导一行 step 结果。

    step 模式的 ``finish`` 只携带 ``memories``(无 ``final`` 文本);本函数从首个记录的 episode 生成简短摘要,使 step 结果/trace 保持可读。无可摘要内容时返回 ``""`` 。

    :param memories: finish 工具调用的 ``memories`` 列表(或 None)。
    :returns: 简短摘要字符串(无可用 memory 文本时为空)。
    """
    if not isinstance(memories, list) or not memories:
        return ""
    first = memories[0]
    text = ""
    if isinstance(first, dict):
        text = str(first.get("text") or "").strip()
    elif isinstance(first, str):
        text = first.strip()
    return text[:160]


#: Cap on the assistant text echoed back into the thread alongside native tool
#: calls. Reasoning models can put a lot of prose there; the echo exists for
#: conversational fidelity, not to re-read it.
_ASSISTANT_ECHO_MAX_CHARS = 4000


def _tool_call_payload(call_id: str, name: str, arguments: str) -> dict[str, Any]:
    """构建一条 OpenAI ``tool_calls`` 条目。"""
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _raw_assistant_message(content: str, tool_calls: Any) -> dict[str, Any]:
    """原样回显一条原生 assistant 轮次(id 与 ``arguments`` 不作改动)。

    用于解析错误路径:循环会用错误文本应答**每一个**原始 id,因此 id 与
    ``arguments`` 必须与 provider 发来的完全一致。
    """
    return {
        "role": "assistant",
        "content": _short_text(content, limit=_ASSISTANT_ECHO_MAX_CHARS) or None,
        "tool_calls": [
            _tool_call_payload(
                str(getattr(tool_call, "id", "") or f"call_{index}"),
                str(getattr(getattr(tool_call, "function", None), "name", "") or ""),
                str(
                    getattr(getattr(tool_call, "function", None), "arguments", "")
                    or "{}"
                ),
            )
            for index, tool_call in enumerate(tool_calls)
        ],
    }


def _decisions_assistant_message(
    content: str, decisions: list[ReactDecision]
) -> dict[str, Any]:
    """由实际将要执行的 decisions 构建 assistant 轮次。

    必须重建而非回显原始响应:当响应包含 ``finish`` 调用时,
    ``_build_react_decisions`` 会丢弃其余调用,回显出的 id 无人应答会让下一个请求失效。
    """
    return {
        "role": "assistant",
        "content": _short_text(content, limit=_ASSISTANT_ECHO_MAX_CHARS) or None,
        "tool_calls": [
            _tool_call_payload(
                decision.call_id,
                decision.action,
                json.dumps(decision.args, ensure_ascii=False, default=str),
            )
            for decision in decisions
            if decision.call_id
        ],
    }


def _react_tool_replies(
    decisions: list[ReactDecision],
    entries: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """构建应答一个轮次工具调用的消息。

    两种编码,与轮次的解析方式对应:

    - **native**(每个 decision 都携带 ``call_id``)——每个调用一条
      ``role: "tool"`` 消息,以 id 为键。失败的调用带 ``ERROR: `` 前缀:
      native 编码没有 ``ok`` 字段,文本是模型得知调用失败的唯一途径。
    - **text-parsed**(无 id)——单条 user 消息,携带与旧的重渲染布局下模型所见相同的 ``<recent_observations>`` JSON 块,文本回退模型因此不损失信息。
    """
    if decisions and all(decision.call_id for decision in decisions):
        return [
            {
                "role": "tool",
                "tool_call_id": decision.call_id,
                "content": (
                    entry["observation"]
                    if entry.get("ok")
                    else f"ERROR: {entry['observation']}"
                ),
            }
            for decision, entry in zip(decisions, entries)
        ]
    return [{"role": "user", "content": _json_block("recent_observations", entries)}]


def _synthesize_step_fallback_episode(
    *,
    step_count: int,
    t: datetime,
    observations: list[dict[str, Any]],
) -> dict[str, Any]:
    """在模型始终未记录 memory episode 时,按规则构建一条。

    用于 ``run_react_loop``(step 模式)结束时未产生有效
    ``finish(memories=...)`` 的情形,使 agent 仍携带一条由本 step 的
    observations 推导出的跨步 memory。该 episode 打上
    ``source=step_result_fallback`` 标记,以便与 LLM 生成的 memories 区分。

    :param step_count: 当前 agent 的 step 计数。
    :param t: 当前仿真时间。
    :param observations: 本 step 收集的 ReAct observations。
    :returns: 一条通过校验的 episode dict。
    """
    parts: list[str] = []
    for obs in observations:
        action = str(obs.get("action") or "").strip()
        text = str(obs.get("observation") or "").strip()
        if not text:
            continue
        prefix = f"{action}: " if action and action != "(invalid)" else ""
        parts.append(prefix + text[:200])
    summary = " | ".join(parts[:5]) if parts else "no notable events recorded"
    text = f"Step {step_count} ({t.isoformat()}): {summary}"[:1000]
    return {
        "type": "observation",
        "importance": 0.4,
        "keywords": [],
        "text": text,
        "source": "step_result_fallback",
        "refs": [],
    }


#: config.json 的白名单 schema(2.5 配置自改通道正式化,2026-10-19)。
#: 键名 → (校验器, 说明)。未列出的键:update_config 拒绝写入,通用
#: workspace 工具因 config.json 进入核心保护路径而不可直写——自我
#: 修改从此只有这一条受校验的通道。校验器返回错误消息或 None(合法)。
_CONFIG_SCHEMA: dict[str, tuple] = {
    "max_react_turns": (
        lambda v: None if isinstance(v, int) and 1 <= v <= 20 else "1..20 的整数",
        "每步 ReAct 循环轮数上限。",
    ),
    "enable_todo_list": (
        lambda v: None if isinstance(v, bool) else "布尔值",
        "是否启用 TODO 上下文与工具。",
    ),
    "enable_memory": (
        lambda v: None if isinstance(v, bool) else "布尔值",
        "是否启用核心记忆(person)。",
    ),
    "memory_context_max_chars": (
        lambda v: (
            None if isinstance(v, int) and 500 <= v <= 100_000 else "500..100000 的整数"
        ),
        "MEMORY.md 提示词字符预算。",
    ),
    "recent_memory_limit": (
        lambda v: None if isinstance(v, int) and 0 <= v <= 64 else "0..64 的整数",
        "提示词内最近 episode 条数。",
    ),
    "memory_consolidation_pending_threshold": (
        lambda v: None if isinstance(v, int) and 1 <= v <= 1000 else "1..1000 的整数",
        "合并触发的待合并 episode 阈值。",
    ),
    "memory_consolidation_interval_steps": (
        lambda v: None if isinstance(v, int) and 1 <= v <= 1000 else "1..1000 的整数",
        "合并触发的最小步间隔。",
    ),
    "memory_high_importance_threshold": (
        lambda v: (
            None if isinstance(v, (int, float)) and 0.0 <= v <= 1.0 else "0.0..1.0"
        ),
        "高重要性 episode 判定阈值。",
    ),
    "idle_skip_enabled": (
        lambda v: None if isinstance(v, bool) else "布尔值",
        "睡眠段确定性快路径开关(person)。",
    ),
    "default_activated_skill_ids": (
        lambda v: (
            None
            if isinstance(v, list) and all(isinstance(x, str) for x in v)
            else "字符串列表"
        ),
        "默认激活的技能 id 列表。",
    ),
    "disabled_skill_ids": (
        lambda v: (
            None
            if isinstance(v, list) and all(isinstance(x, str) for x in v)
            else "字符串列表"
        ),
        "禁用的技能 id 列表。",
    ),
    "extra_skill_paths": (
        lambda v: (
            None
            if isinstance(v, list) and all(isinstance(x, str) for x in v)
            else "字符串列表"
        ),
        "额外技能目录列表。",
    ),
}


class AgentBase(ABC):
    """所有 agent 的抽象基类。

    直接持有通用 agent 运行时(workspace 绑定、skill runtime、ReAct 工具分发),外加 identity、service 槽位与抽象契约。构造经由
    ``create`` / ``from_workspace``;``__init__`` 无参。

    子类必须实现(强制抽象方法):

    - :meth:`create`
    - :meth:`from_workspace`
    - :meth:`to_workspace`
    - :meth:`ask`
    - :meth:`step`
    """

    def __init__(self) -> None:
        """初始化一个未绑定的 agent(无参)。

        只设置空槽位;不解析 profile,也不要求 id。真正的初始化发生在
        :meth:`restore` 中（由 :meth:`from_workspace` 调用）。
        """
        # Identity slots — populated by restore.
        self._id: int | None = None
        self._profile: Any = None
        self._name: str | None = None
        self._config: dict[str, Any] = {}

        # Runtime service slots — injected by _bind_services.
        self._service_proxy: ServiceProxy | None = None
        self._dispatcher = None
        self._model_name: str | None = None
        self._env: RouterBase | None = None
        # Shared logger slot for subclasses (contrib agents log through
        # ``self._logger``); the base class itself uses the module logger.
        self._logger = get_logger()

        # Memories the model recorded inline in the step-mode `finish` tool call
        # (avoids a separate extraction LLM pass). Set by run_react_loop on
        # finish; consumed by step() -> memory_runtime.after_step. None when the
        # loop finished without a finish tool call or in ask mode.
        self._last_finish_memories: list[dict[str, Any]] | None = None
        # Ask-mode scratch: the most recent free-text answer the model emitted
        # without wrapping it in a finish(answer=...) tool call. Used as the
        # end-of-loop fallback answer when the model never self-corrects.
        self._last_raw_answer_text: str = ""
        # Most recent ReAct parse/validation error surfaced from the LLM call;
        # read by run_react_loop to push corrective feedback on a no-decision
        # turn so the model can retry instead of silently ending as "done".
        self._last_react_error: str = ""

        # Workspace / trace placeholders.
        self._workspace_root: Path | None = None
        self._workspace_fs: WorkspaceFS | None = None
        self._jsonl_trace_writer: JsonlTraceWriter | None = None

        # Skill placeholders.  _setup_skill_runtime needs an agent id, so it
        # runs inside restore once _id is known.
        self._skill_registry = None
        self.skill_runtime = None
        self._disabled_skill_ids: set[str] = set()
        self._default_activated_skill_ids: set[str] = set()
        self._default_activated_skills_applied: bool = False
        # Extra skill scan roots beyond the default <root>/custom/skills
        # locations. Populated from config["extra_skill_paths"] in restore;
        # relative paths resolve against the workspace root.
        self._extra_skill_paths: list[Path] = []

        # Generic counters / state — set by restore / subclass restore.
        self._step_count: int = 0
        self._initialized_at: str | None = None
        self._current_time: datetime | None = None

        # Generic ReAct / tool-loop config flags — populated by restore from
        # self._config.  Subclasses (e.g. PersonAgent) may additionally set
        # feature-specific flags (such as _enable_memory) in their own config
        # helper, but these base flags are owned here so the generic react
        # loop and tool dispatcher work for any AgentBase subclass.
        self._max_react_turns: int = 10
        self._enable_todo_list: bool = True
        self._enable_memory: bool = False

    # ------------------------------------------------------------------
    # Service binding
    # ------------------------------------------------------------------

    def _bind_services(self, service_proxy: ServiceProxy) -> None:
        """注入运行时共享服务(由 ``from_workspace`` 调用)。

        将 ``service_proxy`` 及其 env 与 default-LLM dispatcher 绑定到
        ``self._env`` / ``self._dispatcher`` / ``self._model_name`` 。

        :param service_proxy: 共享服务容器(env / llm / trace / replay)。
        """
        self._service_proxy = service_proxy
        self._env = service_proxy.env
        default = service_proxy.llm.default
        self._dispatcher = default
        self._model_name = getattr(default, "model_name", None)

    # ------------------------------------------------------------------
    # Construction model
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        """创建初始 agent workspace(静态、一次写定的 config)。

        写入 ``config.json``(静态、永不重写)+ 初始 ``AGENT.json`` + 标准空目录。不返回 agent 实例;重建请使用 :meth:`from_workspace` 。

        :param workspace_path: agent workspace 根目录(缺失时创建)。
        :param profile: agent profile dict(必须含 ``id``)。
        :param config: 原样写入 ``config.json`` 的静态 config dict。
        """
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)
        for rel in STANDARD_WORKSPACE_DIRS:
            (workspace_path / rel).mkdir(parents=True, exist_ok=True)
        (workspace_path / "config.json").write_text(
            json.dumps(dict(config or {}), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        agent_id = int(profile.get("id", 0))
        name = AgentBase._derive_name(profile, agent_id)
        initial_agent = {
            "schema_version": 1,
            "agent_class": cls.__name__,
            "agent_id": agent_id,
            "id": agent_id,
            "name": name,
            "profile": profile,
            "step_count": 0,
            "current_time": None,
            "tick": None,
            "skills": {
                "visible": [],
                "activated": [],
                "disabled": sorted(
                    str(s)
                    for s in (config or {}).get("disabled_skill_ids", [])
                    if str(s).strip()
                ),
                "default_activated": sorted(
                    str(s)
                    for s in (config or {}).get("default_activated_skill_ids", [])
                    if str(s).strip()
                ),
            },
            "initialized_at": None,
        }
        (workspace_path / AGENT_JSON_PATH).write_text(
            json.dumps(initial_agent, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    @classmethod
    async def from_workspace(
        cls, workspace_path: Path, service_proxy: ServiceProxy
    ) -> AgentBase:
        """由 workspace 重建一个就绪的 agent。

        ``agent = cls()``(无参);``await agent.restore(ws, proxy)``;返回该 agent。

        :param workspace_path: agent workspace 根目录。
        :param service_proxy: 共享服务容器(env / llm / trace / replay)。
        :returns: 就绪的 agent 实例。
        """
        agent = cls()
        await agent.restore(workspace_path, service_proxy)
        return agent

    async def restore(
        self,
        workspace_path: Path,
        service_proxy: ServiceProxy,
    ) -> None:
        """真正的初始化(由 ``from_workspace`` 调用)。

        读取 ``config.json`` + ``AGENT.json``;设置 ``_id``/``_profile``/
        ``_name``/``_config``;调用 ``_bind_services`` + ``_bind_workspace``;
        恢复 visible/activated skills 与计数器。

        子类可覆写本方法,在 ``await super().restore(...)`` 之后**同时**恢复
        person 专属状态。

        :param workspace_path: agent workspace 根目录。
        :param service_proxy: 共享服务容器。
        """
        workspace_path = Path(workspace_path)
        config = json.loads(
            (workspace_path / "config.json").read_text(encoding="utf-8")
        )
        meta = json.loads(
            (workspace_path / AGENT_JSON_PATH).read_text(encoding="utf-8")
        )
        self._config = dict(config or {})
        self._id = int(meta.get("agent_id", meta.get("id", 0)))
        self._profile = meta.get("profile", {})
        self._name = meta.get("name") or self._derive_name(self._profile, self._id)

        # Generic config-derived skill sets.
        self._disabled_skill_ids = set(self._config.get("disabled_skill_ids") or [])
        self._default_activated_skill_ids = {
            str(sid)
            for sid in (self._config.get("default_activated_skill_ids") or [])
            if str(sid).strip()
        } - self._disabled_skill_ids

        # Services + workspace.
        self._bind_services(service_proxy)
        self._setup_skill_runtime(agent_id=self._id)
        self._bind_workspace(workspace_path)

        # Generic react-loop / tool config flags (own read; subclasses extend).
        self._max_react_turns = max(
            1, int(self._config.get("max_react_turns", 10) or 10)
        )
        self._enable_todo_list = bool(self._config.get("enable_todo_list", True))
        # _enable_memory defaults to False at the base level; PersonAgent
        # overrides it in _apply_person_config.

        # Restore visible/activated skill subset from AGENT.json.
        skills = meta.get("skills", {})
        visible = {str(s) for s in skills.get("visible", []) if str(s).strip()}
        activated = {str(s) for s in skills.get("activated", []) if str(s).strip()}
        self.skill_runtime.set_visible_skills(visible)
        self.skill_runtime.set_activated_skills(activated)

        # Restore counters and time.
        self._step_count = int(meta.get("step_count", 0))
        current_time = meta.get("current_time")
        if current_time:
            try:
                self._current_time = datetime.fromisoformat(str(current_time))
            except ValueError:
                self._current_time = None
        else:
            self._current_time = None
        initialized_at = meta.get("initialized_at")
        self._initialized_at = str(initialized_at) if initialized_at else None
        # ``_default_activated_skills_applied`` tracks whether
        # ``add_default_activated_skills`` has actually been invoked inside
        # ``discover_skill_sources``. It must NOT be set just because
        # ``default_activated_skill_ids`` is configured — for a freshly-created
        # agent ``activated`` is still empty at this point, and setting the flag
        # here would make ``discover_skill_sources`` skip the default-activation
        # step entirely, so the configured defaults would never activate. We
        # only treat it as already-applied when persisted ``activated`` skills
        # were restored (resume path); the fresh path leaves it False so the
        # first ``discover_skill_sources`` applies the defaults once.
        self._default_activated_skills_applied = bool(activated)

        # Extra skill scan roots from config (declarative; no code change
        # needed to add skill sources). Relative paths resolve against the
        # workspace root. Discovery merges these with the default
        # <root>/custom/skills locations.
        self._extra_skill_paths = self._resolve_skill_paths(
            self._config.get("extra_skill_paths")
        )

        # Re-scan skill sources into the process-global registry on every
        # restore. Agents are workspace-bound records reconstructed per step
        # via Ray ``from_workspace``; ``SkillRegistry`` is process-global and
        # starts empty on a fresh worker (only builtins are pre-scanned). A
        # reconstructed agent whose AGENT.json was persisted in another process
        # would otherwise see an incomplete registry: ``set_visible_skills``
        # (above) resolves persisted tokens against the registry and silently
        # drops the missing ones, and ``step``'s ``_refresh_visible_skills``
        # then recomputes from the same incomplete registry — so env/custom
        # skills (and their lifecycle hooks / activations) are lost until first
        # use. ``discover_skill_sources`` is idempotent (scans dedupe; default
        # activation is guarded by ``_default_activated_skills_applied``), so
        # running it here is cheap after the first scan in a process and keeps
        # the visible/activated sets consistent with the live registry.
        if self._env is not None:
            try:
                self.discover_skill_sources(self._env)
                # Environment/custom IDs become resolvable only after discovery
                # on a cold worker. Restore the saved activation set at that point.
                self.skill_runtime.add_default_activated_skills(activated)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "Agent %s: skill re-discovery on restore failed: %s",
                    self.id,
                    exc,
                )

    # ------------------------------------------------------------------
    # Abstract methods (subclasses must implement these three;
    # create / from_workspace have concrete base implementations above)
    # ------------------------------------------------------------------

    @abstractmethod
    async def to_workspace(self, workspace_path: Path) -> None:
        """将当前动态状态写回 workspace。"""
        raise NotImplementedError

    @abstractmethod
    async def ask(
        self,
        message: str,
        readonly: bool = True,
        *,
        t: datetime | None = None,
    ) -> str:
        """经由 agent 的推理流程回答一个外部问题。"""
        raise NotImplementedError

    @abstractmethod
    async def step(self, tick: int, t: datetime) -> str:
        """运行一个仿真 step。"""
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Identity + properties
    # ------------------------------------------------------------------

    @property
    def id(self) -> int:
        """Agent 唯一标识符。"""
        return self._id

    @property
    def name(self) -> str:
        """Agent 显示名。"""
        return self._name

    async def ask_env(
        self,
        ctx: dict,
        message: str,
        readonly: bool,
        template_mode: bool = False,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ):
        """向环境 router 发送一个请求。

        封装与仿真环境的交互,支持 template 模式与上下文变量替换。

        :param ctx: 上下文 dict(template 模式下可含 ``variables`` 键)。
        :param message: 请求消息。
        :param readonly: 是否为只读请求。
        :param template_mode: 是否启用 template 模式。
        :param trace_id: 用于跨 agent/env 关联的 OTel trace ID。
        :param parent_span_id: 父追踪片段的 ID。
        :returns: 元组 ``(ctx, answer)`` 。
        """
        assert self._env is not None, "Environment is not initialized"
        # Framework-provided identity keys, independent of any skill.
        i = self.id
        merged_ctx = {**ctx, "id": i, "agent_id": i, "person_id": i}
        ctx, answer = await self._env.ask(
            merged_ctx,
            message,
            readonly=readonly,
            template_mode=template_mode,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
        )
        return ctx, answer

    @staticmethod
    def _extract_json_list_from_text(text: str) -> list[Any]:
        """扫描 ``text`` 中的首个 JSON 数组并返回。

        :param text: 可能内嵌 JSON 数组的自由文本。
        :returns: 首个解码出的 list;未找到时为 ``[]`` 。
        """
        decoder = json.JSONDecoder()
        for idx, ch in enumerate(text):
            if ch != "[":
                continue
            try:
                value, _ = decoder.raw_decode(text[idx:])
            except json.JSONDecodeError:
                continue
            if isinstance(value, list):
                return value
        return []

    def _extract_env_list_result(
        self,
        env_result: Any,
        answer: str,
        key: str,
    ) -> list[Any]:
        """从 ``ask_env`` 返回值中抽取 list 载荷。

        优先取直接的 list,其次 ``env_result[key]``,最后取 ``answer`` 中内嵌的首个 JSON 数组。

        :param env_result: ``ask_env`` 的第一个元素(通常是 ``results``)。
        :param answer: ``ask_env`` 的第二个元素(打印的摘要文本)。
        :param key: ``env_result`` 为 mapping 时读取的 dict 键。
        :returns: 一个 list(可能为空)。
        """
        if isinstance(env_result, list):
            return env_result
        if isinstance(env_result, dict):
            value = env_result.get(key)
            if isinstance(value, list):
                return value
        return self._extract_json_list_from_text(answer)

    def _ensure_env_ask_ok(
        self,
        env_result: Any,
        answer: str,
        *,
        op: str,
    ) -> None:
        """当 ``ask_env`` 调用未报告成功状态时抛出异常。

        :param env_result: ``ask_env`` 的第一个元素(通常是 ``results``)。
        :param answer: ``ask_env`` 的第二个元素(打印的摘要文本)。
        :param op: 操作的短标签(用于错误消息)。
        :raises RuntimeError: status 缺失或非成功形态时抛出。
        """
        if not isinstance(env_result, dict):
            raise RuntimeError(
                f"{op} returned non-dict results: {type(env_result).__name__}"
            )
        status = str(env_result.get("status", "")).lower()
        if status not in {"success", "submitted"}:
            reason = env_result.get("reason") or answer.strip()[:200] or "no reason"
            raise RuntimeError(f"{op} failed (status={status or 'missing'}): {reason}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def acompletion(
        self,
        messages: list[dict[str, Any]],
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        """经由绑定的 default 角色调度器执行一次 LLM 补全。

        供需要一次性 LLM 调用的子类使用的便捷入口(完整的多轮工具循环见
        :meth:`run_react_loop`)。使用 agent 绑定的 dispatcher + model。

        截断兜底:思考型模型的推理偶尔远超网关默认输出上限——思考链耗尽全部预算,``finish_reason`` 返回 ``"length"`` 且 ``content`` 为空。恰好命中该签名时,以宽裕的显式 ``max_tokens`` 重试一次(保留思考——故障在上限而非推理本身);其余空内容形态留给调用方处理。

        :param messages: 聊天消息列表。
        :param stream: 流式开关(恒为 False;本地调度器不支持流式)。
        :param kwargs: 透传给 litellm 的附加参数(timeout、tools 等)。
        :returns: litellm ``ModelResponse`` 响应对象。
        """
        assert self._dispatcher is not None, "Agent LLM dispatcher is not bound"
        response = await self._dispatcher.call(
            model=self._model_name,
            messages=messages,
            stream=stream,
            **kwargs,
        )

        def _empty_by_truncation(resp: Any) -> bool:
            choices = getattr(resp, "choices", None)
            if not choices:
                return False
            choice = choices[0]
            message = getattr(choice, "message", None)
            content = str(getattr(message, "content", "") or "")
            return (
                not content.strip()
                and str(getattr(choice, "finish_reason", "")) == "length"
            )

        if not _empty_by_truncation(response):
            return response
        retry_kwargs = dict(kwargs)
        caller_cap = int(kwargs.get("max_tokens") or 0)
        retry_kwargs["max_tokens"] = max(caller_cap, 16384)
        logger.warning(
            "Agent %s: model '%s' hit the output cap before emitting content "
            "(finish_reason=length); retrying once with max_tokens=%s",
            self.id,
            self._model_name,
            retry_kwargs["max_tokens"],
        )
        return await self._dispatcher.call(
            model=self._model_name,
            messages=messages,
            stream=stream,
            **retry_kwargs,
        )

    async def _completion_text(
        self,
        messages: list[dict[str, Any]],
        *,
        empty_attempts: int = 3,
        **kwargs: Any,
    ) -> str:
        """Return nonempty completion text with bounded empty-response retries.

        中文:返回非空补全文文本,空响应按 ``empty_attempts`` 有界重试。与 :meth:`acompletion` 的截断兜底叠加:``finish_reason=length``
        的空内容在 ``acompletion`` 层已加大 ``max_tokens`` 重试,其余空形态在本层重试,连续 ``empty_attempts`` 次为空则抛
        ``RuntimeError`` 交调用方处置。

        :param messages: 聊天消息列表。
        :param empty_attempts: 空响应重试上限(含首发)。
        :param kwargs: 透传给 :meth:`acompletion` 的附加参数。
        :returns: 非空补全文文本。
        :raises ValueError: ``empty_attempts`` 非正。
        :raises RuntimeError: 连续 ``empty_attempts`` 次空响应。
        """
        if empty_attempts < 1:
            raise ValueError("empty_attempts must be positive")
        for attempt in range(1, empty_attempts + 1):
            response = await self.acompletion(messages, stream=False, **kwargs)
            choices = getattr(response, "choices", None)
            message = getattr(choices[0], "message", None) if choices else None
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return content
            if attempt < empty_attempts:
                self._logger.warning(
                    "[%s] Empty LLM response (%d/%d); retrying",
                    self.name,
                    attempt,
                    empty_attempts,
                )
        raise RuntimeError(
            f"LLM returned empty responses after {empty_attempts} attempts"
        )

    async def close(self):
        """关闭 agent 并释放资源。子类可覆写。"""

    def get_profile(self) -> dict[str, Any]:
        """以 dict 形式返回 agent profile。

        :returns: profile dict(原始 dict、``model_dump`` 或 ``{"raw": str}``)。
        """
        if isinstance(self._profile, dict):
            return self._profile
        elif hasattr(self._profile, "model_dump"):
            return self._profile.model_dump()
        else:
            return {"raw": str(self._profile)}

    # ------------------------------------------------------------------
    # Descriptions
    # ------------------------------------------------------------------

    @classmethod
    def description(cls) -> str:
        """返回用于模块清单的 agent 简短描述。"""
        if cls is AgentBase:
            return "Abstract base class for agents."
        doc = (cls.__doc__ or "").strip().splitlines()
        return doc[0].strip() if doc else f"{cls.__name__}: Agent class."

    @classmethod
    def init_description(cls) -> str:
        """返回本 agent 类的可供 AI 阅读的初始化指引。"""
        if cls is AgentBase:
            description = f"""{cls.__name__}: Abstract base class for agents.

**Description:** {cls.__doc__ or "No description available"}

**Construction:** Agents are created via ``AgentBase.create(workspace_path, profile, config)``
and reconstructed via ``await AgentBase.from_workspace(workspace_path, service_proxy)``.
The constructor ``__init__`` is arg-less.

**Note:** This is an abstract base class. Do not use it directly.

**Example initialization config:**
```json
{{
  "id": 1,
  "profile": {{
    "name": "Alice",
    "gender": "female",
    "age": 30,
    "education": "University",
    "occupation": "Engineer",
    "marriage_status": "single",
    "persona": "helpful",
    "background_story": "A software engineer who loves coding."
  }},
  "config": {{}}
}}
```
"""
        else:
            description = f"""{cls.__name__}: Agent class.

**Description:** {cls.__doc__ or "No description available"}

**Construction:** Agents are created via ``{cls.__name__}.create(workspace_path, profile, config)``
and reconstructed via ``await {cls.__name__}.from_workspace(workspace_path, service_proxy)``.
The constructor ``__init__`` is arg-less.

**Note:** This subclass has not provided a detailed description. Please refer to the class documentation or source code.
"""
        return description

    # ==================================================================
    # Workspace binding
    # ==================================================================

    def _bind_workspace(self, workspace_path: Path) -> None:
        """将运行时对象绑定到一个已存在的 workspace(不创建目录)。

        假定 workspace 已存在(由 :meth:`create` 创建)。设置 WorkspaceFS +
        trace writer,并绑定 skill runtime。

        trace 写入经由本地的 :class:`ShardedAppendSink`
        (``service_proxy.trace`` 只携带输出目录)——没有 per-workspace 的
        event 文件,没有中央 trace actor。未绑定 proxy trace 时,span 仍会创建(span API 可用)但不记录(no-op)。

        :param workspace_path: 已存在的 agent workspace 根目录。
        """
        workspace = Path(workspace_path).resolve()
        self._workspace_root = workspace
        self._workspace_fs = WorkspaceFS(workspace)
        sharded = self._maybe_proxy_sharded_writer()
        self._jsonl_trace_writer = JsonlTraceWriter(
            agent_id=self.id,
            sharded_writer=sharded,
        )
        # Bind the skill runtime if present.
        skill_runtime = getattr(self, "skill_runtime", None)
        if skill_runtime is not None:
            skill_runtime.bind_workspace(
                workspace_root=workspace,
                fs=self._workspace_fs,
                trace_writer=self._jsonl_trace_writer,
            )

    def _maybe_proxy_sharded_writer(self):
        """当绑定的 proxy 启用了 trace 时,返回一个本地 sharded sink。

        查看 ``self._service_proxy.trace``;若其携带 ``trace_dir``,则构建本 agent 自己的 :class:`ShardedAppendSink`(分布式、append-only、无中央 actor)。否则返回 ``None``(no-op)。
        """
        proxy = getattr(self, "_service_proxy", None)
        if proxy is None:
            return None
        trace = getattr(proxy, "trace", None)
        if trace is None:
            return None
        from agentsociety2.trace import build_local_sink

        return build_local_sink(trace)

    @staticmethod
    def _derive_name(profile: Any, agent_id: int) -> str:
        """由 profile/id 推导显示名。

        :param profile: agent profile(dict 或对象)。
        :param agent_id: agent id 兜底值。
        :returns: 显示名字符串。
        """
        if isinstance(profile, dict) and profile.get("name"):
            return str(profile["name"])
        if hasattr(profile, "name") and getattr(profile, "name", None):
            return str(profile.name)
        return f"Agent_{agent_id}"

    def workspace_root_path(self) -> Path:
        """返回 agent 持有的 workspace 根目录。

        :raises RuntimeError: workspace 未初始化时抛出。
        """
        if self._workspace_root is None:
            raise RuntimeError("Agent workspace is not initialized")
        return self._workspace_root

    @property
    def _workspace(self) -> WorkspaceFS:
        """返回 agent 持有的 workspace 文件系统。"""
        if self._workspace_fs is None:
            raise RuntimeError("Agent workspace is not initialized")
        return self._workspace_fs

    @property
    def _trace(self) -> JsonlTraceWriter:
        """返回 agent 持有的 trace writer。"""
        if self._jsonl_trace_writer is None:
            raise RuntimeError("Agent trace writer is not initialized")
        return self._jsonl_trace_writer

    # ------------------------------------------------------------------
    # Trace span helpers
    # ------------------------------------------------------------------

    @property
    def _current_trace_span(self) -> TraceSpan | None:
        """返回当前活跃的 trace span,无则为 None。"""
        return (
            self._jsonl_trace_writer.current_span if self._jsonl_trace_writer else None
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
        """创建一个 agent 持有的 trace span 上下文。"""
        with self._trace.trace_span(
            name,
            trace_id=trace_id,
            parent_span_id=parent_span_id,
            attributes=attributes,
            end_attributes=end_attributes,
        ) as span:
            yield span

    # ------------------------------------------------------------------
    # AGENT.json persistence
    # ------------------------------------------------------------------

    def build_agent_json(
        self,
        *,
        tick: int | None,
        t: Any | None,
    ) -> dict[str, Any]:
        """构建 agent 的整合式自描述文件。

        子类可覆写以追加额外字段(如 memory 摘要)。

        :param tick: 当前仿真 tick(若可用)。
        :param t: 当前仿真时间(若可用)。
        :returns: 可序列化的 AGENT.json dict。
        """
        skill_runtime = getattr(self, "skill_runtime", None)
        visible = sorted(skill_runtime.visible_skill_ids()) if skill_runtime else []
        activated = sorted(skill_runtime.activated_skill_ids()) if skill_runtime else []
        return {
            "schema_version": 1,
            "agent_class": type(self).__name__,
            "agent_id": self.id,
            "name": self.name,
            "current_time": t.isoformat() if t is not None else None,
            "tick": tick,
            "step_count": getattr(self, "_step_count", 0),
            "profile": self.get_profile(),
            "workspace": {
                "root": str(self.workspace_root_path()),
                "agent_json_path": AGENT_JSON_PATH,
            },
            "skills": {
                "visible": visible,
                "activated": activated,
            },
            "initialized_at": getattr(self, "_initialized_at", None),
        }

    def build_prompt_agent_view(
        self,
        *,
        tick: int | None,
        t: Any | None,
    ) -> dict[str, Any]:
        """把 AGENT.json 投影为其运行稳定、prompt 安全的子集。

        :meth:`build_agent_json` 是持久化的 AGENT.json 载荷——由 resume 路径读回,且被文档化为子类扩展点,因此保持原样。本投影剔除不应进入
        prompt 的部分:

        - ``initialized_at`` —— 挂钟时间,逐 agent、逐运行地不同。
        - ``current_time`` / ``tick`` / ``step_count`` —— 每个 step 都变化,
          因此改由独立的 ``<turn_state>`` 块输出,置于运行稳定块之后。
        - ``workspace.root`` —— 宿主机绝对路径,对模型无用(所有
          workspace 工具接收 workspace 相对路径)。

        :meth:`build_agent_json` 覆写追加的子类额外字段会保留。

        :param tick: 当前仿真 tick(若可用)。
        :param t: 当前仿真时间(若可用)。
        :returns: agent 自描述的 prompt 安全视图。
        """
        data = dict(self.build_agent_json(tick=tick, t=t))
        for volatile in ("initialized_at", "current_time", "tick", "step_count"):
            data.pop(volatile, None)
        workspace = dict(data.get("workspace") or {})
        workspace.pop("root", None)
        data["workspace"] = workspace
        return data

    def build_prompt_turn_state(
        self,
        *,
        tick: int | None,
        t: Any | None,
    ) -> dict[str, Any]:
        """构建逐 step 的 ``<turn_state>`` 块载荷。

        在一个仿真 step 内的所有 ReAct 轮次间保持恒定,因而渲染在
        ``<recent_observations>`` 之前。

        :param tick: 当前仿真 tick(若可用)。
        :param t: 当前仿真时间(若可用)。
        :returns: 逐 step 的状态 dict。
        """
        return {
            "current_time": t.isoformat() if t is not None else None,
            "tick": tick,
            "step_count": getattr(self, "_step_count", 0),
        }

    def persist_agent_json(
        self,
        *,
        tick: int | None = None,
        t: Any | None = None,
    ) -> dict[str, Any]:
        """将整合的 agent 自描述持久化到 AGENT.json。

        :param tick: 当前仿真 tick(若可用)。
        :param t: 当前仿真时间(若可用)。
        :returns: 写入 AGENT.json 的数据。
        """
        data = self.build_agent_json(tick=tick, t=t)
        self._workspace.write_text(
            AGENT_JSON_PATH,
            json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str),
        )
        return data

    # ==================================================================
    # Skill runtime
    # ==================================================================

    def _setup_skill_runtime(self, *, agent_id: int) -> None:
        """初始化共享 skill registry 与本 agent 的 runtime。

        :param agent_id: 数值型 agent id。
        """
        self._skill_registry = get_skill_registry()
        self.skill_runtime = AgentSkillRuntime(
            registry=self._skill_registry,
        )

    # ------------------------------------------------------------------
    # Discovery + visibility
    # ------------------------------------------------------------------

    def _refresh_visible_skills(self) -> None:
        """registry 变更后刷新 visible skills。"""
        visible_skill_ids = {
            info.skill_id
            for info in self._skill_registry.list_all()
            if info.skill_id not in self._disabled_skill_ids
        }
        self.skill_runtime.set_visible_skills(visible_skill_ids)

    def _resolve_skill_paths(self, items: Iterable[Any]) -> list[Path]:
        """把一组技能目录路径解析为去重的绝对路径。

        接受 ``str`` / ``Path`` 条目。相对路径以 workspace 根目录解析;
        绝对路径原样使用。空值/falsy 条目被跳过,非法输入绝不抛异常
        (只是产出更少条目)。

        :param items: 技能目录路径候选的可迭代对象。
        :returns: 去重后的绝对路径,保持插入顺序。
        """
        workspace = self._workspace_root
        resolved: list[Path] = []
        seen: set[Path] = set()
        if items is None:
            return resolved
        # A bare str/Path is one path, not an iterable of characters.
        if isinstance(items, (str, Path)):
            items = [items]
        if not isinstance(items, Iterable):
            return resolved
        for item in items:
            text = str(item or "").strip()
            if not text:
                continue
            path = Path(text).expanduser()
            if not path.is_absolute() and workspace is not None:
                path = workspace / path
            path = path.resolve()
            if path not in seen:
                seen.add(path)
                resolved.append(path)
        return resolved

    def discover_skill_sources(
        self,
        env: RouterBase,
        *,
        extra_skill_paths: Iterable[Path | str] | None = None,
    ) -> dict[str, list[str]]:
        """发现 custom 与环境提供的技能来源。

        先扫描默认的 ``<root>/custom/skills`` 位置(``env.run_dir`` 与本
        agent 的 workspace 根目录),再扫描由两个来源合并出的额外技能目录:

        - 声明式:``config.json`` 中的 ``extra_skill_paths`` (在
          :meth:`restore` 中解析);
        - 程序式:此处的 ``extra_skill_paths`` 参数。

        每个额外条目都是一个包含技能子目录的目录(与 ``custom/skills``
        布局相同)。相对条目以 workspace 根目录解析。两者都未给出时默认扫描不变,agent 可经任一入口加载存放在任意位置的 custom skills。

        :param env: 用于定位 run 目录与模块的环境 router。
        :param extra_skill_paths: 现在即要扫描的额外技能目录(每个都是
            技能子目录的根)。
        :returns: 从发现来源标签到新增 skill ID 的映射。
        """
        discovered: dict[str, list[str]] = {}

        roots: list[Path] = []
        run_dir = getattr(env, "run_dir", None)
        if run_dir:
            roots.append(Path(run_dir))
        roots.append(self.workspace_root_path())

        seen: set[Path] = set()
        for root in roots:
            root_abs = root.resolve()
            if root_abs in seen:
                continue
            seen.add(root_abs)
            try:
                added = self._skill_registry.scan_custom(root_abs / "custom" / "skills")
            except Exception as exc:
                logger.warning(
                    "Agent %s: custom skill scan failed at %s: %s",
                    self.id,
                    root_abs,
                    exc,
                )
                added = []
            if added:
                discovered[f"custom:{root_abs}"] = added

        # Extra skill paths (config-driven + programmatic), scanned directly.
        # Lets an agent load custom skills stored at any location.
        for path in self._resolve_skill_paths(
            [*self._extra_skill_paths, *(extra_skill_paths or [])]
        ):
            if path in seen:
                continue
            seen.add(path)
            try:
                added = self._skill_registry.scan_custom(path)
            except Exception as exc:
                logger.warning(
                    "Agent %s: extra skill scan failed at %s: %s",
                    self.id,
                    path,
                    exc,
                )
                added = []
            if added:
                discovered[f"custom:{path}"] = added

        # Env-provided skills come from two shapes of ``env``:
        # - in-process router (``RouterBase``): exposes concrete ``env_modules``
        #   instances, each with a ``skill_dirs()`` method;
        # - Ray ``EnvRouterProxy``: carries no module instances (they live in the
        #   actor's process) but exposes ``env_skill_dirs`` —
        #   ``(module_class_name, skill_dir)`` pairs resolved from the registry
        #   at proxy construction. Scan both so env skills are discoverable in
        #   the distributed path too.
        env_skill_pairs: list[tuple[str, str]] = []
        for module in getattr(env, "env_modules", []) or []:
            class_name = type(module).__name__
            for skills_dir in module.skill_dirs() or []:
                env_skill_pairs.append((class_name, str(skills_dir)))
        for class_name, skills_dir_str in getattr(env, "env_skill_dirs", []) or []:
            env_skill_pairs.append((class_name, str(skills_dir_str)))

        seen_env: set[tuple[str, str]] = set()
        for class_name, skills_dir_str in env_skill_pairs:
            if not skills_dir_str or (class_name, skills_dir_str) in seen_env:
                continue
            seen_env.add((class_name, skills_dir_str))
            skills_dir = Path(skills_dir_str)
            try:
                added = self._skill_registry.scan_env(skills_dir, class_name)
            except Exception as exc:
                logger.warning(
                    "Agent %s: env skill scan failed at %s: %s",
                    self.id,
                    skills_dir,
                    exc,
                )
                added = []
            if added:
                discovered[f"env:{class_name}:{skills_dir}"] = added

        self._refresh_visible_skills()
        if not self._default_activated_skills_applied:
            self.skill_runtime.add_default_activated_skills(
                self._default_activated_skill_ids
            )
            self._default_activated_skills_applied = True
        return discovered

    def _resolve_skill_id_from_args(self, args: Mapping[str, Any]) -> str:
        """把以 ``skill_name`` 优先的工具参数解析为 技能注册表中的技能 ID。

        :param args: 含 ``skill_name`` 的工具参数 mapping。
        :returns: 匹配到的 visible skill ID;否则为空字符串。
        """
        skill_id = self.skill_runtime.resolve_skill_id(
            str(args.get("skill_name") or "")
        )
        if skill_id:
            return skill_id
        return self.skill_runtime.infer_single_script_skill_id()

    # ------------------------------------------------------------------
    # Lifecycle hooks
    # ------------------------------------------------------------------

    async def run_lifecycle_hooks(
        self,
        hook_type: str,
        *,
        tick: int,
        t: Any,
    ) -> list[dict[str, Any]]:
        """为当前已激活的技能运行生命周期 hook。

        :param hook_type: 生命周期 hook 名,如 ``pre_step`` 或 ``post_step`` 。
        :param tick: 当前仿真 tick。
        :param t: 当前仿真时间。
        :returns: hook 执行摘要。
        """
        payload = {
            "hook_type": hook_type,
            "tick": tick,
            "time": t.isoformat(),
            "agent_id": self.id,
            "step_count": getattr(self, "_step_count", 0),
        }
        summaries: list[dict[str, Any]] = []
        argv = ["--args-json", json.dumps(payload, ensure_ascii=False, default=str)]
        with self.trace_span(
            f"skill.lifecycle_hooks.{hook_type}",
            attributes={
                "operation.type": "skill",
                "hook.type": hook_type,
                "agent.tick": tick,
            },
        ) as span:
            for info in self.skill_runtime.active_hook_skills(hook_type):
                result = await self.skill_runtime.run_skill_hook(
                    info.skill_id,
                    hook_type,
                    argv,
                    timeout_sec=30,
                )
                summary = {
                    "skill_id": info.skill_id,
                    "hook_type": hook_type,
                    "ok": result.ok,
                    "exit_code": result.exit_code,
                    "stdout": _short_text(result.stdout, limit=1000),
                    "stderr": _short_text(result.stderr, limit=1000),
                }
                summaries.append(summary)
                if not result.ok:
                    logger.warning(
                        "Agent %s: lifecycle hook failed: %s %s",
                        self.id,
                        info.skill_id,
                        hook_type,
                    )
            span.attributes.update(
                {
                    "hook.executed_count": len(summaries),
                    "hook.failed_count": sum(1 for item in summaries if not item["ok"]),
                }
            )
        return summaries

    # ==================================================================
    # ReAct tool dispatch
    # ==================================================================

    # ------------------------------------------------------------------
    # Tool execution (trace-span wrapper)
    # ------------------------------------------------------------------

    # Read-only tools that are safe to run concurrently within one assistant
    # turn. Mutation / env tools stay serial to preserve side-effect order.
    _REACT_PARALLEL_SAFE_ACTIONS = frozenset(
        {
            "read",
            "list",
            "grep",
            "read_skill_file",
            "todo_list",
        }
    )

    async def _update_config_tool(
        self, changes_json: str, readonly: bool
    ) -> ReactToolResult:
        """受校验的配置自改工具(2.5 正式化通道)。

        流程:白名单校验 → 写前快照备份 → 应用变更 → 变更日志
        (``config_changes.jsonl`` 追加旧值/新值/step/时间)→ 提示下次
        restore 生效。坏 JSON、未知键或非法值被逐键拒绝,原配置不动。

        :param changes_json: 待应用的 ``{键: 值}`` JSON 字符串。
        :param readonly: ask(只读)模式下拒绝写入。
        :returns: 工具执行结果(拒绝原因或应用明细)。
        """
        if readonly:
            return ReactToolResult(
                False,
                "update_config is disabled in readonly mode",
                {"error": "readonly", "readonly": True},
            )
        from agentsociety2.agent.json_utils import jr_or_json

        try:
            changes = jr_or_json(changes_json)
        except Exception as exc:
            return ReactToolResult(
                False,
                f"invalid JSON for update_config: {exc}",
                {"error": "invalid_json"},
            )
        if not isinstance(changes, dict) or not changes:
            return ReactToolResult(
                False,
                "update_config requires a non-empty object of {key: value}",
                {"error": "invalid_shape"},
            )
        errors: dict[str, str] = {}
        accepted: dict[str, Any] = {}
        for key, value in changes.items():
            if key not in _CONFIG_SCHEMA:
                errors[key] = "未知配置键(不在白名单)"
                continue
            check, _doc = _CONFIG_SCHEMA[key]
            problem = check(value)
            if problem is not None:
                errors[key] = f"非法值:{problem}"
                continue
            accepted[key] = value
        if errors:
            return ReactToolResult(
                False,
                "config update rejected: "
                + "; ".join(f"{k}: {v}" for k, v in errors.items()),
                {"error": "validation_failed", "details": errors},
            )
        import time as _time

        config_path = self._workspace.resolve("config.json")
        backup_path = self._workspace.resolve(
            f"config_backup_{self._step_count:06d}_{int(_time.time())}.json"
        )
        backup_path.write_text(
            config_path.read_text(encoding="utf-8"), encoding="utf-8"
        )
        merged = dict(self._config)
        merged.update(accepted)
        config_path.write_text(
            json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        log_path = self._workspace.resolve("config_changes.jsonl")
        entry = {
            "step": self._step_count,
            "time": str(self._current_time),
            "changes": {
                k: {"old": self._config.get(k), "new": v} for k, v in accepted.items()
            },
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        self._config = merged
        return ReactToolResult(
            True,
            "config updated: "
            + ", ".join(sorted(accepted))
            + " (takes effect on next restore; rollback via backup file)",
            {"applied": sorted(accepted), "backup": backup_path.name},
        )

    def _cap_read_observation(self, content: str) -> tuple[str, bool]:
        """给 ``read`` 观察结果设上限,防止单个大文件撑爆 react 线程。

        观察文本会进入 react 线程,并在后续每一轮以未缓存尾部 token 重发,
        无上限的读入会膨胀整个 step 的上下文与成本。超限时保留前
        ``Config.WORKSPACE_READ_MAX_BYTES`` 字节并附标记提示模型改用
        ``grep`` 定向提取;磁盘上的原文件不受影响。

        :param content: read 工具读到的原始文本。
        :returns: ``(截断后的内容, 是否发生截断)`` 二元组。
        """
        from agentsociety2.config import Config

        cap = max(int(Config.WORKSPACE_READ_MAX_BYTES), 1024)
        data = content.encode("utf-8", errors="replace")
        if len(data) <= cap:
            return content, False
        kept = data[:cap].decode("utf-8", errors="ignore")
        marker = (
            f"\n... [truncated: file is {len(data)} bytes, showing first "
            f"{cap}; use grep to extract the rest]"
        )
        return kept + marker, True

    async def _execute_react_tools(
        self,
        decisions: list[ReactDecision],
        *,
        readonly: bool = False,
    ) -> list[ReactToolResult]:
        """执行一个 assistant 轮次的工具,只读动作并行化。

        :param decisions: 按 assistant 顺序解析出的 ReAct decisions。
        :param readonly: 是否阻止变更类工具。
        :returns: 与 ``decisions`` 顺序对齐的结果。
        """

        async def _one(decision: ReactDecision) -> ReactToolResult:
            try:
                return await self._execute_react_tool(decision, readonly=readonly)
            except Exception as exc:
                # Every id in the assistant turn must be answered before the
                # next assistant/user message, so a throwing tool becomes a
                # failed result rather than a stranded tool_call id.
                return ReactToolResult(
                    False,
                    f"tool execution failed: {exc}",
                    {"error": str(exc)},
                )

        if len(decisions) > 1 and all(
            decision.action in self._REACT_PARALLEL_SAFE_ACTIONS
            for decision in decisions
        ):
            return list(
                await asyncio.gather(*[_one(decision) for decision in decisions])
            )
        results: list[ReactToolResult] = []
        for decision in decisions:
            results.append(await _one(decision))
        return results

    async def _execute_react_tool(
        self,
        decision: ReactDecision,
        *,
        readonly: bool = False,
    ) -> ReactToolResult:
        """在 trace span 下执行一个 ReAct 工具。

        :param decision: 待执行的解析后 ReAct decision。
        :param readonly: 是否阻止变更类工具。
        :returns: 工具执行结果。
        """
        action = decision.action
        args = decision.args
        with self.trace_span(
            "react.tool",
            attributes={
                "operation.type": "react",
                "react.action": action,
            },
        ) as span:
            result = await self.dispatch_react_tool(action, args, readonly=readonly)
            update: dict[str, Any] = {
                "result.ok": result.ok,
                "output.summary": {
                    "observation": result.observation,
                },
            }
            if result.data:
                update["tool.data"] = result.data
            span.attributes.update(update)
            return result

    # ------------------------------------------------------------------
    # Core dispatch
    # ------------------------------------------------------------------

    async def dispatch_react_tool(
        self,
        action: str,
        args: dict[str, Any],
        *,
        readonly: bool = False,
    ) -> ReactToolResult:
        """分发一个 ReAct 工具调用。

        处理 workspace 文件工具、skill 工具与 ``ask_env``。person 专属工具
        (``memory_*``、``todo_*``)在到达本方法之前由子类处理(或经子类覆写)。

        :param action: 工具名。
        :param args: 工具参数 dict。
        :param readonly: 是否阻止变更类工具。
        :returns: 工具执行结果。
        """
        try:
            if readonly and action in {"write", "append"}:
                return ReactToolResult(
                    False,
                    f"{action} is disabled in readonly mode",
                    {"action": action, "readonly": True},
                )
            if action == "read":
                path = str(args.get("path") or "")
                requested_path = path
                path = self._normalize_workspace_read_path(path)
                with self.trace_span(
                    "workspace.read_text",
                    attributes={
                        "operation.type": "workspace",
                        "workspace.path": requested_path,
                        "workspace.normalized_path": path,
                    },
                ) as workspace_span:
                    try:
                        content = self._workspace.read_text(path)
                    except ValueError:
                        # The path escapes the agent workspace. If it points at
                        # a file bundled inside a visible skill (a common
                        # mistake — e.g. trying to ``read`` a skill's
                        # ``references/*.md``), serve it via read_skill_file
                        # instead of surfacing an opaque escape error.
                        resolved = self._try_read_skill_path(requested_path or path)
                        if resolved is not None:
                            skill_id, rel_path, content = resolved
                            workspace_span.attributes["skill_redirect"] = skill_id
                            workspace_span.attributes["result.size"] = len(content)
                            content, truncated = self._cap_read_observation(content)
                            if truncated:
                                workspace_span.attributes["result.truncated"] = True
                            return ReactToolResult(
                                True,
                                content,
                                {
                                    "skill_id": skill_id,
                                    "path": rel_path,
                                    "redirected_from": requested_path,
                                    "truncated": truncated,
                                },
                            )
                        raise
                    workspace_span.attributes["result.size"] = len(content)
                    content, truncated = self._cap_read_observation(content)
                    if truncated:
                        workspace_span.attributes["result.truncated"] = True
                return ReactToolResult(
                    True, content, {"path": path, "truncated": truncated}
                )
            if action == "write":
                path = str(args.get("path") or "")
                if self._is_core_owned_workspace_path(
                    self._workspace.resolve(path)
                    .relative_to(self._workspace.root)
                    .as_posix()
                ):
                    return ReactToolResult(
                        True,
                        (
                            f"{path} is managed by the agent runtime and cannot "
                            "be written directly; no workspace write was performed"
                        ),
                        {"path": path, "core_owned": True, "noop": True},
                    )
                content = str(args.get("content") or "")
                with self.trace_span(
                    "workspace.write_text",
                    attributes={
                        "operation.type": "workspace",
                        "workspace.path": path,
                    },
                ) as workspace_span:
                    result = self._workspace.write_text(path, content)
                    workspace_span.attributes["result.bytes"] = result.bytes_written
                # Workspace-relative, like ``read``/``grep``: an absolute host
                # path is noise to the model and varies per agent, so it would
                # break prompt-prefix reuse for no benefit.
                return ReactToolResult(
                    result.ok,
                    f"written: {path}" if result.ok else result.error,
                    result.__dict__,
                )
            if action == "append":
                path = str(args.get("path") or "")
                if self._is_core_owned_workspace_path(
                    self._workspace.resolve(path)
                    .relative_to(self._workspace.root)
                    .as_posix()
                ):
                    return ReactToolResult(
                        True,
                        (
                            f"{path} is managed by the agent runtime and cannot "
                            "be appended directly; no workspace append was performed"
                        ),
                        {"path": path, "core_owned": True, "noop": True},
                    )
                content = str(args.get("content") or "")
                with self.trace_span(
                    "workspace.append_text",
                    attributes={
                        "operation.type": "workspace",
                        "workspace.path": path,
                    },
                ) as workspace_span:
                    result = self._workspace.append_text(path, content)
                    workspace_span.attributes["result.bytes"] = result.bytes_written
                return ReactToolResult(result.ok, f"appended: {path}", result.__dict__)
            if action == "list":
                path = str(args.get("path") or ".")
                files = [
                    item.path
                    for item in self._workspace.list(path, limit=10_000)
                    if not item.is_dir
                ]
                return ReactToolResult(
                    True,
                    json.dumps(files, ensure_ascii=False, default=str),
                    {"files": files},
                )
            if action == "grep":
                pattern = str(args.get("pattern") or "")
                path = str(args.get("path") or ".")
                limit = int(args.get("limit") or 100)
                with self.trace_span(
                    "workspace.grep",
                    attributes={
                        "operation.type": "workspace",
                        "workspace.path": path,
                        "grep.pattern": pattern,
                    },
                ) as workspace_span:
                    matches = await self._workspace.grep(pattern, path, limit=limit)
                    workspace_span.attributes["result.count"] = len(matches)
                data = {"matches": [item.__dict__ for item in matches]}
                return ReactToolResult(
                    True, json.dumps(data, ensure_ascii=False, default=str), data
                )
            if action == "activate_skill":
                requested_skill_name = str(args.get("skill_name") or "")
                activated, skill_id, doc = self.skill_runtime.activate_skill(
                    requested_skill_name
                )
                if not activated:
                    if skill_id:
                        observation = (
                            "activate_skill failed: "
                            f"skill_name={requested_skill_name!r} resolved to "
                            f"skill_id={skill_id!r}, but its SKILL.md is missing or empty"
                        )
                        error = "skill_doc_unavailable"
                    else:
                        observation = (
                            "activate_skill failed: "
                            f"skill_name={requested_skill_name!r} is not visible, "
                            "does not exist, or is ambiguous; use a skill name from "
                            "the visible skill catalog"
                        )
                        error = "skill_not_resolved"
                    return ReactToolResult(
                        False,
                        observation,
                        {
                            "skill_id": skill_id,
                            "skill_name": requested_skill_name,
                            "activated": False,
                            "error": error,
                        },
                    )
                return ReactToolResult(
                    True,
                    doc,
                    {
                        "skill_id": skill_id,
                        "skill_name": requested_skill_name,
                        "activated": True,
                    },
                )
            if action == "deactivate_skill":
                removed, skill_id = self.skill_runtime.deactivate_skill(
                    str(args.get("skill_name") or "")
                )
                return ReactToolResult(
                    True,
                    f"deactivated: {skill_id}"
                    if removed
                    else f"not active: {skill_id}",
                    {"skill_id": skill_id, "removed": removed},
                )
            if action == "read_skill_file":
                skill_id = self._resolve_skill_id_from_args(args)
                path = str(args.get("path") or "")
                content = self.skill_runtime.read_skill_file(skill_id, path)
                return ReactToolResult(
                    bool(content),
                    content,
                    {
                        "skill_id": skill_id,
                        "path": path,
                        "content_len": len(content or ""),
                    },
                )
            if action == "execute_skill_script":
                skill_id = self._resolve_skill_id_from_args(args)
                script_path = str(args.get("script_path") or "")
                argv = args.get("argv")
                argv_list = (
                    [str(item) for item in argv] if isinstance(argv, list) else []
                )
                if skill_id.startswith("env:"):
                    instruction = self._build_env_skill_instruction(args, argv_list)
                    env_readonly = bool(args.get("readonly", False))
                    if readonly and not env_readonly:
                        return ReactToolResult(
                            False,
                            "environment skill mutation is disabled in readonly mode",
                            {
                                "skill_id": skill_id,
                                "argv": argv_list,
                                "readonly": True,
                            },
                        )
                    _span = self._current_trace_span
                    _, answer = await self.ask_env(
                        self._build_env_tool_context(args),
                        instruction,
                        readonly=env_readonly,
                        template_mode=True,
                        trace_id=_span.trace_id if _span else None,
                        parent_span_id=_span.span_id if _span else None,
                    )
                    return ReactToolResult(
                        True,
                        str(answer or ""),
                        {
                            "skill_id": skill_id,
                            "argv": argv_list,
                            "instruction": instruction,
                            "redirected_to": "ask_env",
                            "readonly": env_readonly,
                        },
                    )
                result = await self.skill_runtime.run_skill_script(
                    skill_id,
                    script_path,
                    argv_list,
                    timeout_sec=int(args.get("timeout_sec") or 30),
                )
                return ReactToolResult(
                    result.ok,
                    json.dumps(result.as_dict(), ensure_ascii=False, default=str),
                    {
                        "skill_id": skill_id,
                        "script_path": script_path,
                        "argv": argv_list,
                        "exit_code": result.exit_code,
                        "stdout_len": len(result.stdout or ""),
                        "stderr_len": len(result.stderr or ""),
                        **({"stdout": result.stdout} if result.stdout else {}),
                        **({"stderr": result.stderr} if result.stderr else {}),
                    },
                )
            if action == "ask_env":
                ctx = self._build_env_tool_context(args)
                instruction = str(args.get("instruction") or "")
                if not instruction:
                    return ReactToolResult(
                        False,
                        "ask_env requires instruction",
                        {"error": "missing instruction"},
                    )
                # Template/cache mode is always forced on for ask_env so the
                # router reuses cached code for similar instructions instead of
                # regenerating (and paying an LLM round-trip) on every call.
                env_readonly = bool(args.get("readonly", False))
                if readonly and not env_readonly:
                    return ReactToolResult(
                        False,
                        "ask_env mutation is disabled in readonly mode",
                        {"instruction": instruction, "readonly": True},
                    )
                _span = self._current_trace_span
                _, answer = await self.ask_env(
                    ctx,
                    instruction,
                    readonly=env_readonly,
                    template_mode=True,
                    trace_id=_span.trace_id if _span else None,
                    parent_span_id=_span.span_id if _span else None,
                )
                return ReactToolResult(
                    True,
                    str(answer or ""),
                    {"instruction": instruction, "template_mode": True},
                )
            if action == "update_config":
                return await self._update_config_tool(
                    str(args.get("changes") or ""), bool(readonly)
                )
            return ReactToolResult(
                False,
                f"unknown action: {action}",
                {"action": action},
            )
        except Exception as exc:
            return ReactToolResult(False, str(exc), {"error": str(exc)})

    # ------------------------------------------------------------------
    # Path helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_core_owned_workspace_path(path: str) -> bool:
        """判断某个 workspace 路径是否由 agent 核心运行时持有。

        :param path: LLM 工具循环请求的 workspace 相对路径。
        :returns: 通用 workspace 变更工具不得编辑该路径时为 True。

        归一化与 ``WorkspaceFS.resolve`` 对齐(2026-11-06 审计修复):
        ``posixpath.normpath`` 消掉 ``..`` 段(``subdir/../AGENT.json``
        此前绕过清单;大小写用 ``casefold`` 兜住大小写不敏感文件系统
        (macOS APFS 上 ``agent.json`` 此前可命中 AGENT.json)。
        """
        import posixpath

        normalized = str(path or "").replace("\\", "/").strip()
        normalized = posixpath.normpath(normalized)
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized or normalized == ".":
            return False
        lowered = normalized.casefold()
        return (
            # 大小写不敏感文件系统(macOS APFS)下 casefold 兜住变体;
            # TODO 真实路径是根目录 TODO.json 与 state/todos_archive.jsonl
            # (todo.py:TODO_STATE_PATH/TODO_ARCHIVE_PATH)。
            lowered == "agent.json"
            or lowered == "config.json"
            or lowered == "memory.md"
            or lowered == "todo.json"
            or lowered.startswith(("memory/", "state/daily_guidance/"))
            or lowered == "state/todos_archive.jsonl"
        )

    def _normalize_workspace_read_path(self, path: str) -> str:
        """把已知的 agent workspace 绝对路径映射到本 workspace。

        :param path: 模型提供的 read 路径。
        :returns: 原相对路径,或相对本 agent workspace 的路径。
        """
        raw = str(path or "").strip()
        if not raw:
            return raw
        candidate = Path(raw)
        if not candidate.is_absolute():
            return raw
        parts = candidate.parts
        agent_dir = self.workspace_root_path().name
        for idx, part in enumerate(parts):
            if part == agent_dir:
                rel_parts = parts[idx + 1 :]
                if rel_parts:
                    return Path(*rel_parts).as_posix()
        return raw

    def _try_read_skill_path(self, path: str) -> tuple[str, str, str] | None:
        """把越界的 read 路径解析为某个 visible skill 文件的内容。

        :param path: 模型尝试读取的路径(绝对或相对)。
        :returns: 路径命中 visible skill 根内文件时返回
            ``(skill_id, relative_path, content)``,否则为 ``None`` 。
        """
        resolved = self.skill_runtime.resolve_skill_path(path)
        if resolved is None:
            return None
        skill_id, rel_path = resolved
        content = self.skill_runtime.read_skill_file(skill_id, rel_path)
        if not content:
            return None
        return skill_id, rel_path, content

    def _build_env_tool_context(self, args: dict[str, Any]) -> dict[str, Any]:
        """由工具参数构建 ``ask_env`` 上下文。

        :param args: ``ask_env`` 工具参数。
        :returns: 传给 RouterBase.ask 的上下文 dict。
        """
        raw_ctx = args.get("ctx")
        ctx = dict(raw_ctx) if isinstance(raw_ctx, Mapping) else {}
        raw_variables = args.get("variables")
        if isinstance(raw_variables, Mapping):
            current = ctx.get("variables")
            variables = dict(current) if isinstance(current, Mapping) else {}
            variables.update(dict(raw_variables))
            ctx["variables"] = variables
        return ctx

    def _build_env_skill_instruction(
        self,
        args: Mapping[str, Any],
        argv: list[str],
    ) -> str:
        """为送往脚本执行的 env skill 调用构建 ``ask_env`` instruction。

        :param args: 原始工具参数。
        :param argv: 模型提供的类命令行参数。
        :returns: 给环境 router 的自然语言 instruction。
        """
        skill_name = str(args.get("skill_name") or "environment").strip()
        if argv:
            return (
                f"Use the {skill_name} environment skill to perform: {' '.join(argv)}"
            )
        return f"Use the {skill_name} environment skill for the current state."

    # ==================================================================
    # ReAct loop (generic orchestration)
    # ==================================================================
    #
    # The loop is generic: it builds messages via ``self.build_react_messages``
    # (a subclass-provided prompt hook), dispatches the LLM via
    # ``self._dispatcher.call``, executes tools via ``self._execute_react_tool``
    # (which calls ``self.dispatch_react_tool`` polymorphically), and respects
    # ``self._max_react_turns``.  Nothing person-specific is inlined here.

    async def run_react_loop(
        self,
        *,
        tick: int,
        t: datetime,
        observations: list[dict[str, Any]] | None = None,
        question: str | None = None,
        readonly: bool = False,
        skill_hooks: list[dict[str, Any]] | None = None,
    ) -> str:
        """运行 ReAct 循环直至 finish 或轮次上限。

        :param tick: 当前仿真 tick。
        :param t: 当前仿真时间。
        :param observations: 初始 observation 列表(就地追加)。
        :param question: 可选的外部问题(ask 模式)。
        :param readonly: 是否阻止变更类工具。
        :param skill_hooks: 可选的供 prompt 使用的 ``pre_step`` hook 输出。
        :returns: 循环的最终结果字符串。
        """
        if observations is None:
            observations = []
        # Reset inline finish memories for this loop invocation; set below when
        # a step-mode `finish` carrying `memories` is observed.
        self._last_finish_memories = None
        self._last_raw_answer_text = ""
        self._last_react_error = ""
        # ONE thread per loop invocation, built once and thereafter only
        # appended to. That is what makes every request a strict
        # prefix-extension of the previous one, so the provider's prompt-prefix
        # cache grows across turns instead of resetting each turn (measured
        # ~52% -> ~82% aggregate hit rate over a 6-turn conversation).
        #
        # Do NOT rebuild this per turn, and do NOT truncate it from the front:
        # both destroy the cached prefix and give back the entire win.
        messages: list[dict[str, Any]] = list(
            self.build_react_messages(
                tick=tick,
                t=t,
                observations=observations,
                question=question,
                readonly=readonly,
                skill_hooks=skill_hooks,
            )
        )
        with self.trace_span(
            "react.loop",
            attributes={
                "agent.tick": tick,
                "operation.type": "react",
                "react.max_turns": self._max_react_turns,
                "react.readonly": readonly,
                "input.message_chars": len(question or ""),
            },
        ) as loop_span:
            for turn in range(1, self._max_react_turns + 1):
                with self.trace_span(
                    "react.turn",
                    attributes={
                        "agent.tick": tick,
                        "operation.type": "react",
                        "react.turn": turn,
                    },
                ) as turn_span:
                    # Clear the per-turn parse error so a stale message from an
                    # earlier turn never surfaces as corrective feedback if the
                    # current turn yields empty decisions for a different reason
                    # (e.g. an empty-content response that carries no error).
                    self._last_react_error = ""
                    react_turn = await self._call_react_llm_with_messages(
                        messages, readonly=readonly
                    )
                    decisions = react_turn.decisions
                    turn_span.attributes.update(
                        {
                            "react.action": ", ".join(d.action for d in decisions)
                            if decisions
                            else "(none)",
                            "react.tool_count": len(decisions),
                            "llm.message_count": len(messages),
                            # Which encoding served this turn — lets a production
                            # run be sliced by it, so the append-only change can
                            # be A/B-ed from logs without a permanent switch.
                            "react.history_encoding": (
                                "tool"
                                if (react_turn.assistant_message or {}).get(
                                    "tool_calls"
                                )
                                else "user"
                            ),
                        }
                    )

                    finish_d = next(
                        (d for d in decisions if d.action == "finish"), None
                    )
                    if finish_d is not None:
                        # Capture memories the model recorded inline in the
                        # step-mode finish tool, so step() can ingest them
                        # without a separate extraction pass. Absent in ask mode
                        # (finish carries only `answer`) — stays None there.
                        self._last_finish_memories = finish_d.args.get("memories")
                        # Step-mode finish has no `final` text; derive a brief
                        # step result from the recorded memories so the trace /
                        # step summary stays meaningful (ask mode keeps its
                        # explicit `answer`).
                        final = (
                            finish_d.final
                            or _brief_memories_summary(self._last_finish_memories)
                            or "done"
                        )
                        loop_span.attributes.update(
                            {
                                "react.end_reason": "finish",
                                "output.summary": {"final": final},
                            }
                        )
                        return final

                    if not decisions:
                        # No valid tool call this turn (parse/validation failed
                        # even after the within-turn retry). Instead of silently
                        # ending as "done" — which drops the ask answer / step
                        # memory — record the failure so the model can
                        # self-correct on a later turn. The corrective feedback
                        # is already in `messages`; `observations` stays the
                        # side-channel that react.tool_ok and the end-of-loop
                        # fallbacks read. The loop is still bounded by
                        # _max_react_turns; if the model never recovers we
                        # synthesize a fallback below.
                        feedback = (
                            self._last_react_error or "No valid tool call was produced."
                        )
                        observations.append(
                            {
                                "turn": turn,
                                "action": "(invalid)",
                                "ok": False,
                                "observation": feedback,
                                "data": {"error": feedback},
                            }
                        )
                        continue

                    if react_turn.assistant_message is not None:
                        messages.append(react_turn.assistant_message)
                    entries: list[dict[str, Any]] = []
                    results = await self._execute_react_tools(
                        decisions,
                        readonly=readonly,
                    )
                    for decision, result in zip(decisions, results):
                        if not result.ok:
                            logger.warning(
                                "Agent %s: ReAct tool failed: action=%s observation=%s",
                                self.id,
                                decision.action,
                                _short_text(result.observation, limit=300),
                            )
                        entries.append(
                            {
                                "turn": turn,
                                "action": decision.action,
                                "ok": result.ok,
                                "observation": result.observation,
                                "data": result.data,
                            }
                        )
                    observations.extend(entries)
                    messages.extend(_react_tool_replies(decisions, entries))
                    self._append_context_refresh(
                        messages, decisions, entries, tick=tick, t=t
                    )
                    turn_span.attributes["react.tool_ok"] = all(
                        obs["ok"] for obs in observations if obs.get("turn") == turn
                    )

            # Loop exhausted without a valid finish. Fall back to a rule-based
            # result so the agent always carries forward *something*: a step
            # memory synthesized from the turn observations (step mode), or the
            # last free-text answer the model emitted (ask mode).
            if readonly:
                final = self._synthesize_ask_fallback()
                loop_span.attributes.update(
                    {
                        "react.end_reason": "ask_fallback",
                        "output.summary": {"final": final},
                    }
                )
                return final
            self._last_finish_memories = self._synthesize_step_fallback_memory(
                tick=tick, t=t, observations=observations
            )
            final = _brief_memories_summary(self._last_finish_memories) or "done"
            loop_span.attributes.update(
                {
                    "react.end_reason": "step_memory_fallback",
                    "output.summary": {"final": final},
                }
            )
            return final

    async def _call_react_llm_with_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        readonly: bool = False,
    ) -> ReactTurn:
        """调用 LLM,工具参数非法时重试一次。

        ``messages`` 会**就地**追加本轮的 assistant 消息,出错时还会追加纠错回复——因此下一个请求是本请求的前缀扩展,prompt-prefix 缓存得以持续增长。

        :param messages: OpenAI 风格聊天消息(就地修改)。
        :param readonly: 是否阻止变更类工具。
        :returns: 最终一次尝试解析出的 :class:`ReactTurn` 。
        """
        with self.trace_span(
            "llm.completion",
            attributes={
                "operation.type": "llm",
                "llm.model": self._model_name or "",
                "input.message_count": len(messages),
            },
        ) as span:
            turn, appended = await self._append_react_turn(
                messages, readonly=readonly, span=span
            )
            if turn.error:
                self._last_react_error = turn.error
                span.attributes["llm.retry"] = True
                span.attributes["input.message_count"] = len(messages)
                turn, appended = await self._append_react_turn(
                    messages, readonly=readonly, span=span
                )
            if turn.error:
                self._last_react_error = turn.error
                span.attributes["schema.error"] = turn.error
                logger.warning(
                    "Agent %s: invalid ReAct decision: %s", self.id, turn.error
                )
            if not turn.decisions and not appended:
                # Guarantee the next request differs from this one. The thread
                # is no longer rebuilt per turn, so an un-appended empty turn
                # would re-send a byte-identical prompt — and with a prefix
                # cache in play the model could spin on it until the turn limit.
                messages.append(
                    {
                        "role": "user",
                        "content": _xml_block(
                            "react_error",
                            (
                                self._last_react_error
                                or "No valid tool call was produced."
                            )
                            + "\nRespond with a single valid tool call.",
                        ),
                    }
                )
        return turn

    async def _append_react_turn(
        self,
        messages: list[dict[str, Any]],
        *,
        readonly: bool,
        span: Any,
    ) -> tuple[ReactTurn, bool]:
        """运行一次补全,必要时追加纠错回复。

        成功时这里刻意**不**追加 assistant 消息;由 :meth:`run_react_loop`
        将其与工具回复一并追加,这样即使某个工具抛异常也能产出回复,不会留下无人应答的 tool-call id。

        :param messages: 聊天消息(就地修改)。
        :param readonly: 是否阻止变更类工具。
        :param span: 打开中的 ``llm.completion`` span,用于用量记账。
        :returns: ``(turn, appended)``——``appended`` 表示 ``messages``
            是否增长。
        """
        response = await self._complete_react_once(messages, readonly=readonly)
        self._record_llm_usage(span, response)
        turn = self._parse_react_turn(response, readonly=readonly)
        if not turn.error:
            return turn, False

        error_block = _xml_block(
            "schema_error",
            turn.error + "\nCall valid tool(s) with valid arguments.",
        )
        if turn.assistant_message is not None:
            messages.append(turn.assistant_message)
            tool_calls = turn.assistant_message.get("tool_calls") or []
            # An assistant turn that carries tool_calls must have every id
            # answered before any later assistant/user message, so answer them
            # with the error text rather than following up with a bare user turn.
            for tool_call in tool_calls:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call["id"],
                        "content": error_block,
                    }
                )
            if not tool_calls:
                messages.append({"role": "user", "content": error_block})
        else:
            messages.append({"role": "user", "content": error_block})
        return turn, True

    def _record_llm_usage(self, span: Any, response: Any) -> None:
        """把一次响应的 token 用量复制到 ``llm.completion`` span 上。

        在 trace JSONL 中暴露逐轮次、逐 agent 的 prompt-cache 命中。据此可把低命中率定位到三种情形之一——共享 system 前缀未命中、逐轮窗口被失效、或该轮为 ask 模式轮次;run 汇总中的聚合计数器无法区分这些。

        span 属性会跨轮内重试累加,因此重试过的轮次报告两次补全的总和。

        :param span: 打开中的 ``llm.completion`` trace span。
        :param response: dispatcher 返回的原始 LLM 响应。
        :returns: 无。
        """
        from agentsociety2.config.llm_dispatcher import extract_cached_tokens

        usage = getattr(response, "usage", None)
        if usage is None:
            return
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        cached = extract_cached_tokens(response)
        attributes = span.attributes
        attributes["llm.input_tokens"] = (
            int(attributes.get("llm.input_tokens", 0)) + input_tokens
        )
        attributes["llm.cached_input_tokens"] = (
            int(attributes.get("llm.cached_input_tokens", 0)) + cached
        )
        total_input = int(attributes["llm.input_tokens"])
        attributes["llm.cache_hit_rate"] = (
            max(0.0, min(1.0, int(attributes["llm.cached_input_tokens"]) / total_input))
            if total_input > 0
            else 0.0
        )

    async def _complete_react_once(
        self,
        messages: list[dict[str, str]],
        *,
        readonly: bool = False,
    ) -> Any:
        """执行一次 ReAct LLM 补全。

        :param messages: OpenAI 风格聊天消息。
        :param readonly: 是否阻止变更类工具。
        :returns: 原始 LLM 响应对象。
        """
        assert self._model_name is not None, "LLM is not initialized"
        enable_skill_tools = self.skill_runtime.visible_skill_count() > 0
        response = await self._dispatcher.call(
            model=self._model_name,
            messages=messages,
            stream=False,
            tools=react_tool_schemas(
                enable_todo_list=self._enable_todo_list,
                enable_memory=self._enable_memory,
                disable_skills=not enable_skill_tools,
                readonly=readonly,
                overrides=self._react_tool_overrides(readonly=readonly),
            ),
            tool_choice="auto",
        )
        return response

    def _react_tool_overrides(self, *, readonly: bool) -> dict[str, dict[str, Any]]:
        """按工具名索引的逐 agent ReAct 工具 schema 覆写。

        子类 hook(默认无覆写)。由 :meth:`_complete_react_once` 在
        readonly 过滤之前应用,子类可按模式替换工具——例如 PersonAgent 在
        ask 模式把 ``finish`` 换成仅含 answer 的变体,step 模式换成
        result+memories 变体(后者内联记录 memories,省去单独的抽取
        LLM 调用)。

        :param readonly: 循环是否处于 readonly(ask)模式。
        :returns: ``{tool_name: full_tool_schema_dict}``(默认为空)。
        """
        return {}

    def _synthesize_step_fallback_memory(
        self,
        *,
        tick: int,
        t: datetime,
        observations: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """未产生有效 finish 时合成一个单元素 memory 列表。

        封装 :func:`_synthesize_step_fallback_episode`,使 ``run_react_loop``
        在模型始终未给出可接受的 ``finish(memories=...)`` 时也能填充
        ``self._last_finish_memories``(由
        ``step() -> memory_runtime.after_step`` 消费)。

        :param tick: 当前仿真 tick(未使用,为保持对称而保留)。
        :param t: 当前仿真时间。
        :param observations: 本 step 收集的 ReAct observations。
        :returns: 仅含兜底 episode 的单元素列表。
        """
        del tick  # step_count is the meaningful counter here.
        return [
            _synthesize_step_fallback_episode(
                step_count=self._step_count,
                t=t,
                observations=observations,
            )
        ]

    def _synthesize_ask_fallback(self) -> str:
        """未发生有效 finish 时,返回 ask 模式的最后兜底答案。

        优先取模型最近发出的自由文本答案(响应解析期间暂存于
        ``self._last_raw_answer_text``);仅当模型完全没有产出可用文本时才回退为 ``"done"`` 。

        :returns: 兜底答案字符串。
        """
        text = (self._last_raw_answer_text or "").strip()
        return text or "done"

    def _parse_react_turn(self, response: Any, *, readonly: bool = False) -> ReactTurn:
        """把一次 LLM 响应解析为 decisions 及待追加的 assistant 轮次。

        一些 OpenAI 兼容端点从不发出原生 ``tool_calls``,而是把每个工具调用渲染为 ``message.content`` 中的文本(如
        ``ask_env(instruction="...", readonly=false)``)。为使 agent 在此类模型下仍可用,当没有原生工具调用时,回退到
        :meth:`_parse_text_tool_calls`;它理解常见的文本编码(Python-kwarg
        调用、``name({...})`` JSON 调用、Hermes/Qwen ``<tool_call>``/``<tool_input>``
        块、裸 JSON 对象,以及 ``<invoke>`` XML)。

        ask 模式(``readonly=True``)下,当模型返回的自由文本答案不含可识别的工具调用时,先做一次保守的答案抽取(带类 ``answer`` 键的
        JSON 对象,或裸 JSON 标量)并合成一个 ``finish(answer=...)``;
        无法确信匹配的一切都以错误拒绝,使循环把失败反馈给模型并重试
        (主要的纠正机制)。原始自由文本会被暂存,供循环结束时的兜底使用。

        除 decisions 外,本方法还返回循环追加进线程的规范化
        ``assistant_message``,使每个请求都是前一个的扩展。产出两种形态,
        同一轮内不得混用:

        - **native**(响应携带了 ``tool_calls``)——消息携带从*存活的*
          decisions 重建的 ``tool_calls``,而非从原始响应回显。
          ``_build_react_decisions`` 在存在 ``finish`` 决策时只保留它,
          回显原始调用列表会留下无人应答的 tool-call id,下一个请求会被拒绝。
        - **text**(无原生调用)——纯 assistant 文本消息;结果由循环以
          ``<recent_observations>`` user 块追加,与模型已见过的形态完全一致。

        出错且带原生调用时,消息回显*原始*调用(id 与 ``arguments``
        原样),使循环能用错误文本应答每个 id。

        :param response: 原始 LLM 响应对象。
        :param readonly: 循环是否处于 readonly(ask)模式。
        :returns: 含 decisions、error 与待追加消息的 :class:`ReactTurn`
            (响应无可追加内容时,消息为 ``None``)。
        """
        if not getattr(response, "choices", None):
            return ReactTurn([], "missing response choices", None)
        message = getattr(response.choices[0], "message", None)
        if message is None:
            return ReactTurn([], "missing response message", None)

        content = str(getattr(message, "content", "") or "").strip()
        reasoning = reasoning_fields(response)
        tool_calls = getattr(message, "tool_calls", None) or []
        if tool_calls:
            calls: list[tuple[str, dict[str, Any]]] = []
            call_ids: list[str] = []
            for index, tool_call in enumerate(tool_calls):
                function = getattr(tool_call, "function", None)
                name = str(getattr(function, "name", "") or "").strip()
                raw_args = str(getattr(function, "arguments", "") or "{}")
                try:
                    from agentsociety2.agent.json_utils import jr_or_json

                    parsed_args = jr_or_json(raw_args)
                except Exception as exc:
                    return ReactTurn(
                        [],
                        f"invalid tool arguments for {name}: {exc}",
                        {**_raw_assistant_message(content, tool_calls), **reasoning},
                    )
                if not isinstance(parsed_args, Mapping):
                    return ReactTurn(
                        [],
                        f"tool arguments for {name} must be an object",
                        {**_raw_assistant_message(content, tool_calls), **reasoning},
                    )
                calls.append((name, dict(parsed_args)))
                # Providers normally supply an id; synthesize one when they do
                # not, so every native turn can still be answered 1:1.
                call_ids.append(str(getattr(tool_call, "id", "") or f"call_{index}"))

            decisions, error = self._build_react_decisions(
                calls, readonly=readonly, call_ids=call_ids
            )
            if error:
                return ReactTurn(
                    decisions,
                    error,
                    {**_raw_assistant_message(content, tool_calls), **reasoning},
                )
            return ReactTurn(
                decisions,
                "",
                {**_decisions_assistant_message(content, decisions), **reasoning},
            )

        # No native tool calls: try parsing tool invocations from the text
        # content before rejecting the response. Many OpenAI-compatible models
        # emit calls only as text.
        if not content:
            return ReactTurn([], "", None)
        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": content,
            **reasoning,
        }
        if readonly:
            # Stash the raw free text so run_react_loop can fall back to it if
            # the model never produces a valid finish(answer=...) tool call.
            self._last_raw_answer_text = content
        text_calls = self._parse_text_tool_calls(content)
        if text_calls:
            decisions, error = self._build_react_decisions(
                text_calls, readonly=readonly
            )
            return ReactTurn(decisions, error, assistant_message)
        # Ask mode: attempt a conservative answer extraction from free text
        # before giving up. This recovers obvious cases (e.g. {"answer": ...});
        # everything else falls through to an error so the loop corrects the
        # model via feedback.
        if readonly:
            answer = self._extract_free_text_answer(content)
            if answer:
                decisions, error = self._build_react_decisions(
                    [("finish", {"answer": answer})], readonly=readonly
                )
                return ReactTurn(decisions, error, assistant_message)
            return ReactTurn(
                [],
                "In ask mode you must deliver your answer through the `finish` "
                "tool with a non-empty `answer` argument. Free-text answers are "
                "not accepted. Re-issue your complete answer as a single "
                "finish(answer=...) tool call.",
                assistant_message,
            )
        return ReactTurn(
            [],
            "Respond with tool calls only. Free text is not accepted.",
            assistant_message,
        )

    # Keys whose JSON value may carry a direct answer in ask-mode free text.
    _FREE_TEXT_ANSWER_KEYS = ("answer", "final", "result", "response", "value")

    def _extract_free_text_answer(self, content: str) -> str:
        """从自由文本中保守地抽取 ask 模式答案。

        只匹配形态确定无疑的载荷,使一切有歧义的内容都走错误反馈路径:

        - 带类 ``answer`` 键的 JSON 对象(如 ``{"answer": "left"}``)。
        - 裸 JSON 标量(string / number / boolean)。

        自然语言答案(如 "The answer is left")刻意**不**在此匹配——
        那些经由重试反馈纠正。

        :param content: 原始 ``message.content`` 文本。
        :returns: 抽取出的答案字符串;无可确信匹配时为 ``""`` 。
        """
        from agentsociety2.agent.json_utils import jr_or_json

        text = content.strip().strip("`")
        # Strip a leading "json" code-fence marker if present.
        if text.lower().startswith("json"):
            text = text[4:].lstrip()
        parsed: Any = None
        try:
            parsed = jr_or_json(text)
        except Exception:
            parsed = None
        if isinstance(parsed, Mapping):
            for key in self._FREE_TEXT_ANSWER_KEYS:
                if key in parsed:
                    raw = parsed.get(key)
                    # Skip null/None payloads — str(None) would yield the
                    # literal "None", which is never a real answer. Let these
                    # fall through to the error-feedback path instead.
                    if raw is None:
                        continue
                    value = str(raw).strip()
                    if value:
                        return value
            return ""
        if parsed is None:
            return ""
        if isinstance(parsed, (str, int, float, bool)):
            return str(parsed).strip()
        return ""

    def _build_react_decisions(
        self,
        calls: list[tuple[str, dict[str, Any]]],
        *,
        readonly: bool = False,
        call_ids: list[str] | None = None,
    ) -> tuple[list[ReactDecision], str]:
        """由 (name, args) 工具调用列表构建 ReAct decisions。

        由原生 tool-call 路径与文本解析回退共享,使 ``finish`` 语义保持
        一致:``finish`` 胜出,至多返回一条。``finish`` 载荷按模式校验,
        被拒绝的 ``finish`` 返回错误以便调用方重试:

        - ask / readonly 模式:``finish`` 必须携带非空 ``answer``;
        - step 模式:``finish`` 必须携带至少含一项的 ``memories`` 列表
          (空列表非法——memory 生成发生在这一步)。

        :param calls: 有序的 ``(tool_name, args)`` 对。
        :param readonly: 循环是否处于 readonly(ask)模式。
        :param call_ids: 可选的 provider tool-call id,与 ``calls`` 位置
            对应。文本解析回退没有 id,会省略;所得 decisions 因此携带
            ``call_id=""`` 。
        :returns: (decisions, error) 元组。
        """
        decisions: list[ReactDecision] = []
        for index, (name, args) in enumerate(calls):
            call_id = call_ids[index] if call_ids and index < len(call_ids) else ""
            if name == "finish":
                if readonly:
                    answer = str(args.get("answer") or "").strip()
                    if not answer:
                        return (
                            [],
                            (
                                "In ask mode `finish` requires a non-empty `answer` "
                                "with your complete answer to the question. Re-issue "
                                "your answer as a single finish(answer=...) tool call."
                            ),
                        )
                    decisions.append(ReactDecision(name, args, answer, call_id))
                else:
                    memories = args.get("memories")
                    if not isinstance(memories, list) or not memories:
                        return (
                            [],
                            (
                                "`finish` requires `memories` with at least one "
                                "memory item from this step (an empty list is not "
                                "accepted). Record at least one episode (key "
                                "decision/event/observation/intention) and call "
                                "finish again."
                            ),
                        )
                    decisions.append(ReactDecision(name, args, "", call_id))
            else:
                decisions.append(ReactDecision(name, args, "", call_id))
        finish_decisions = [d for d in decisions if d.action == "finish"]
        if finish_decisions:
            return finish_decisions[:1], ""
        return decisions, ""

    # Keys that may carry the tool name across textual encodings.
    _TEXT_TOOL_NAME_KEYS = ("name", "function", "tool", "tool_name", "action")
    # Keys that may carry the tool arguments across textual encodings.
    _TEXT_TOOL_ARG_KEYS = (
        "arguments",
        "parameters",
        "args",
        "params",
        "tool_input",
        "input",
        "inputs",
    )

    def _parse_text_tool_calls(self, content: str) -> list[tuple[str, dict[str, Any]]]:
        """解析内嵌在自由 LLM 文本中的工具调用。

        支持不返回原生 ``tool_calls`` 的 OpenAI 兼容模型发出的编码:

        - Python-kwarg 风格:``ask_env(instruction="...", readonly=false)``
          (此类模型最常见的形态)。
        - JSON 函数调用:``finish({"answer": "..."})`` 或 ``name({...})`` 。
        - Hermes / Qwen 块:``<tool_call>name</tool_call><tool_input>{...}
          </tool_input>``(以及 JSON 装在 ``<tool_call>`` 里的变体)。
        - 裸 JSON 对象:``{"name"/"tool": ..., "arguments"/...: {...}}`` 。
        - XML invoke:``<invoke name="...">...</invoke>``(带
          ``<parameters>`` JSON 体)。

        未找到可识别的工具调用时返回空列表(调用方随后把内容当作自由文本处理)。解析尽力而为:畸形片段被跳过而非抛出。

        :param content: 原始 ``message.content`` 文本。
        :returns: 有序的 ``(tool_name, args)`` 对(可能为空)。
        """
        results: list[tuple[str, dict[str, Any]]] = []
        # Guard against pathological input dominating the regex passes.
        if len(content) > 200_000:
            content = content[:200_000]

        def _clean_name(raw: str) -> str:
            # Strip XML tags, quotes, backticks and surrounding whitespace.
            cleaned = re.sub(r"<[^>]+>", "", raw)
            cleaned = cleaned.strip().strip("`\"' \t\r\n")
            # Take the leading identifier token (drop trailing junk like "()").
            m = re.match(r"^([A-Za-z_][\w\-\.]*)", cleaned)
            return m.group(1) if m else cleaned

        def _coerce_args(value: Any) -> dict[str, Any]:
            if isinstance(value, Mapping):
                return dict(value)
            if isinstance(value, str):
                parsed = _json_loads_lenient(value)
                return dict(parsed) if isinstance(parsed, Mapping) else {}
            return {}

        def _record(name: str, args: Any) -> None:
            name = _clean_name(name)
            if name:
                results.append((name, _coerce_args(args)))

        def _json_loads_lenient(text: str) -> Any:
            text = text.strip()
            if not text:
                return None
            from agentsociety2.agent.json_utils import jr_or_json

            try:
                return jr_or_json(text)
            except Exception:
                return None

        def _extract_name_args(obj: Any) -> tuple[str, Any]:
            """按已知键集从 JSON 对象中取出 (name, args)。"""
            if not isinstance(obj, Mapping):
                return "", {}
            name = ""
            for key in self._TEXT_TOOL_NAME_KEYS:
                val = obj.get(key)
                if isinstance(val, str) and val.strip():
                    name = val.strip()
                    break
            args: Any = {}
            for key in self._TEXT_TOOL_ARG_KEYS:
                if key in obj:
                    args = obj[key]
                    break
            return name, args

        def _parse_call_body(body: str) -> dict[str, Any]:
            """解析 ``NAME(...)`` 的参数体。

            处理两种形态:
            - Python-kwarg 风格:``instruction="...", readonly=false, n=3``;
            - JSON 对象:``{"answer": "..."}``(可能带杂散代码围栏/尾逗号)。
            """
            body = body.strip()
            if not body:
                return {}
            # JSON object form first.
            if body.startswith("{"):
                parsed = _json_loads_lenient(body)
                return dict(parsed) if isinstance(parsed, Mapping) else {}
            # Python-kwarg form: key=value pairs separated by commas (values may
            # contain commas inside quotes, so we walk char-by-char).
            kwargs: dict[str, Any] = {}
            for key, raw_val in _split_kwargs(body):
                kwargs[key] = _parse_python_literal(raw_val)
            return kwargs

        def _split_kwargs(body: str) -> list[tuple[str, str]]:
            """切分 ``k=v, k2=v2``,尊重引号/花括号(不做 eval)。"""
            pairs: list[tuple[str, str]] = []
            i, n = 0, len(body)
            while i < n:
                # Skip whitespace and stray commas.
                while i < n and body[i] in " \t\r\n,":
                    i += 1
                # Read key.
                km = re.match(r"([A-Za-z_][\w\-\.]*)\s*=\s*", body[i:])
                if not km:
                    break
                key = km.group(1)
                i += km.end()
                # Read value up to the next top-level comma.
                start = i
                quote: str | None = None
                bracket = 0
                while i < n:
                    ch = body[i]
                    if quote:
                        if ch == "\\":
                            i += 2
                            continue
                        if ch == quote:
                            quote = None
                    elif ch in "\"'":
                        quote = ch
                    elif ch in "[{(":
                        bracket += 1
                    elif ch in "]})":
                        bracket -= 1
                    elif ch == "," and bracket <= 0:
                        break
                    i += 1
                pairs.append((key, body[start:i].strip()))
            return pairs

        def _parse_python_literal(raw: str) -> Any:
            """把 Python-kwarg 值 token 转成 JSON 友好的值。"""
            raw = raw.strip()
            if not raw:
                return ""
            if raw.lower() in ("true", "false"):
                return raw.lower() == "true"
            if raw.lower() in ("none", "null"):
                return None
            if (raw[0] in "\"'" and raw[-1] == raw[0]) or (
                len(raw) >= 6 and raw[:3] in ('"""', "'''") and raw[-3:] == raw[:3]
            ):
                # Quoted string: use ast.literal_eval for escape fidelity if
                # available, else strip quotes.
                try:
                    import ast

                    return ast.literal_eval(raw)
                except Exception:
                    return raw[1:-1]
            # JSON-ish (dict/list/number/string) — try strict then lenient.
            parsed = _json_loads_lenient(raw)
            if parsed is not None:
                return parsed
            return raw

        # 1. <tool_call>NAME</tool_call><tool_input>{...}</tool_input>  (Hermes/Qwen)
        for m in re.finditer(
            r"<tool_call>\s*(.*?)\s*</tool_call>.*?"
            r"<tool_input>\s*(.*?)\s*</tool_input>",
            content,
            re.DOTALL,
        ):
            _record(m.group(1), m.group(2))

        # 2. <tool_call>{...json with name + arguments...}</tool_call> (Qwen JSON variant)
        if not results:
            for m in re.finditer(
                r"<tool_call>\s*(\{.*?\})\s*</tool_call>", content, re.DOTALL
            ):
                obj = _json_loads_lenient(m.group(1))
                if obj:
                    name, args = _extract_name_args(obj)
                    if name:
                        _record(name, args)

        # 3. Function-call style: NAME(...) — covers both kwarg and JSON arg forms.
        #    Matches the outermost parenthesized group (non-greedy, balanced-ish via
        #    [^()]* fallback for simple bodies; complex nested JSON is handled by
        #    greedy matching up to the last ')' on the same logical call).
        if not results:
            for m in re.finditer(
                r"([A-Za-z_][\w\-\.]*)\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)",
                content,
            ):
                body = m.group(2).strip()
                _record(m.group(1), _parse_call_body(body))

        # 4. Bare JSON object: {"name"/"tool": ..., "arguments"/...: {...}}
        if not results:
            for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", content):
                obj = _json_loads_lenient(m.group(0))
                if obj:
                    name, args = _extract_name_args(obj)
                    if name:
                        _record(name, args)

        # 5. XML invoke: <invoke name="..."> ... <parameters>{...}</parameters> ...
        if not results:
            for m in re.finditer(
                r'<invoke\s+name="([^"]+)">.*?</invoke>',
                content,
                re.DOTALL,
            ):
                inner = m.group(0)
                pm = re.search(
                    r"<parameters>\s*(.*?)\s*</parameters>", inner, re.DOTALL
                )
                _record(m.group(1), pm.group(1) if pm else {})

        return results

    def build_react_messages(
        self,
        *,
        tick: int,
        t: datetime,
        observations: list[dict[str, Any]],
        question: str | None = None,
        readonly: bool = False,
        skill_hooks: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, str]]:
        """构建 ReAct prompt 消息(子类 prompt hook)。

        基类实现抛出 :class:`NotImplementedError` 。子类(如 PersonAgent)
        覆写本方法,组装各自的 agent 专属 prompt 并返回 OpenAI 风格聊天消息。

        :param tick: 当前仿真 tick。
        :param t: 当前仿真时间。
        :param observations: 近期 observation 列表。
        :param question: 可选的外部问题(ask 模式)。
        :param readonly: 是否阻止变更类工具。
        :param skill_hooks: 可选的供 prompt 使用的 ``pre_step`` hook 输出。
        :returns: OpenAI 风格聊天消息。
        :raises NotImplementedError: 基类中恒为如此。
        """
        raise NotImplementedError(
            "Subclasses must implement build_react_messages to use the "
            "generic ReAct loop."
        )

    def build_context_refresh_message(
        self,
        *,
        actions: list[str],
        tick: int,
        t: datetime,
    ) -> dict[str, Any] | None:
        """当某个工具使线程头部的块失效时,返回待追加的消息。

        线程在每次循环调用时只构建一次,因此位于首个 user 消息中的逐 agent 块(``<todo_context>`` 、``<skill_content>``)不再每轮重渲染。重渲染会重建 prompt、丢弃已缓存的 prefix;追加一个刷新块则保持 prefix 完整。子类 hook(默认:不刷新)。

        只传入**成功**的动作;即使多个动作触发,每轮至多追加一条消息。

        :param actions: 本轮成功的工具动作名。
        :param tick: 当前仿真 tick。
        :param t: 当前仿真时间。
        :returns: 待追加的聊天消息;无需刷新时为 ``None`` 。
        """
        return None

    def _append_context_refresh(
        self,
        messages: list[dict[str, Any]],
        decisions: list[ReactDecision],
        entries: list[dict[str, Any]],
        *,
        tick: int,
        t: datetime,
    ) -> None:
        """若子类返回了 context-refresh 消息,则将其追加。

        必须在工具回复**之后**执行:``role: "tool"`` 回复必须先跟随其
        assistant 轮次,其后才能有任何后续消息。

        :param messages: 聊天消息(就地修改)。
        :param decisions: 本轮执行的 decisions。
        :param entries: 与之位置对齐的 observation 条目。
        :param tick: 当前仿真 tick。
        :param t: 当前仿真时间。
        """
        actions = [
            decision.action
            for decision, entry in zip(decisions, entries)
            if entry.get("ok")
        ]
        if not actions:
            return
        refresh = self.build_context_refresh_message(actions=actions, tick=tick, t=t)
        if refresh is not None:
            messages.append(refresh)

    # ==================================================================
    # TODO handling (generic)
    # ==================================================================

    def _todo_store(self) -> TodoStateStore:
        """返回本 agent workspace 的 TODO store。

        :returns: 绑定到 agent workspace 根目录的 TodoStateStore。
        """
        return TodoStateStore(self.workspace_root_path())

    def _ensure_todo_state(self) -> None:
        """特性开关启用时初始化 TODO 状态。"""
        if self._enable_todo_list:
            self._todo_store().ensure()

    def _build_todo_context(self, t: datetime) -> dict[str, Any]:
        """构建 TODO 状态的紧凑 prompt 上下文。

        :param t: 当前仿真时间。
        :returns: TODO prompt 上下文 dict(特性禁用时为空)。
        """
        if not self._enable_todo_list:
            return {}
        return self._todo_store().build_prompt_context(t)

    def _current_simulation_time(self) -> datetime | None:
        """返回供工具规范化使用的最可信仿真时间。

        :returns: 当前仿真时间;不可用时为 ``None`` 。
        """
        if self._current_time is not None:
            return self._current_time
        if self._workspace_fs is None:
            return None
        try:
            data = json.loads(self._workspace.read_text(AGENT_JSON_PATH))
        except Exception:
            return None
        current_time = str(data.get("current_time") or "").strip()
        if not current_time:
            return None
        try:
            return datetime.fromisoformat(current_time)
        except ValueError:
            return None

    def _normalize_todo_due_value(self, value: Any) -> Any:
        """在 store 严格校验之前,归一化常见的 TODO due 简写。

        :param value: 模型给出的原始 ``due`` 值。
        :returns: 归一化后的值(``HH:MM`` 简写已按当前仿真时间解析为 ISO
            字符串;其余情况返回原值)。
        """
        if value in (None, ""):
            return value
        text = str(value).strip()
        match = _SHORT_CLOCK_RE.match(text)
        if not match:
            return value
        current = self._current_simulation_time()
        if current is None:
            return value
        hour = int(match.group("hour"))
        minute = int(match.group("minute"))
        return current.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        ).isoformat()

    def _normalize_todo_tool_args(
        self,
        action: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """在 agent 边界处归一化 TODO 工具参数。

        :param action: TODO 工具动作名。
        :param args: 工具参数 dict。
        :returns: 带归一化 ``due`` 值的新参数 dict。
        """
        normalized = dict(args)
        if action == "todo_add" and "due" in normalized:
            normalized["due"] = self._normalize_todo_due_value(normalized["due"])
        if action == "todo_update" and isinstance(normalized.get("patch"), Mapping):
            patch = dict(normalized["patch"])
            if "due" in patch:
                patch["due"] = self._normalize_todo_due_value(patch["due"])
            normalized["patch"] = patch
        if action == "todo_defer" and "new_due" in normalized:
            normalized["new_due"] = self._normalize_todo_due_value(
                normalized["new_due"]
            )
        return normalized

    def dispatch_todo_tool(
        self,
        action: str,
        args: dict[str, Any],
    ) -> ReactToolResult:
        """分发内置 TODO 工具。

        :param action: TODO 工具动作名。
        :param args: 工具参数 dict。
        :returns: 工具执行结果。
        """
        if not self._enable_todo_list:
            return ReactToolResult(
                False,
                "todo_list feature is disabled",
                {"error": "todo_list feature is disabled"},
            )
        args = self._normalize_todo_tool_args(action, args)
        store = self._todo_store()
        if action == "todo_list":
            limit_raw = args.get("limit")
            limit = int(limit_raw) if limit_raw is not None else None
            data = store.list(
                status=str(args.get("status") or "").strip() or None,
                limit=limit,
            )
            return ReactToolResult(
                True, json.dumps(data, ensure_ascii=False, indent=2, default=str), data
            )
        if action == "todo_add":
            data = store.add(dict(args))
            return ReactToolResult(
                True,
                json.dumps(data["todo"], ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "todo_update":
            patch = args.get("patch")
            data = store.update(
                str(args.get("todo_id") or ""),
                dict(patch) if isinstance(patch, Mapping) else {},
            )
            return ReactToolResult(
                True,
                json.dumps(data["todo"], ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "todo_start":
            data = store.start(str(args.get("todo_id") or ""))
            return ReactToolResult(
                True,
                json.dumps(data["todo"], ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "todo_complete":
            data = store.complete(
                str(args.get("todo_id") or ""),
                outcome=str(args.get("outcome") or ""),
            )
            return ReactToolResult(
                True,
                json.dumps(data["todo"], ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "todo_defer":
            data = store.defer(
                str(args.get("todo_id") or ""),
                new_due=str(args["new_due"])
                if args.get("new_due") not in (None, "")
                else None,
                reason=str(args.get("reason") or ""),
            )
            return ReactToolResult(
                True,
                json.dumps(data["todo"], ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "todo_clear_completed":
            keep_raw = args.get("keep_recent")
            keep_recent = int(keep_raw) if keep_raw is not None else 2
            data = store.clear_completed(keep_recent=keep_recent)
            summary = {
                "archived": data["archived"],
                "kept_terminal": data["kept_terminal"],
                "remaining": data["remaining"],
            }
            return ReactToolResult(
                True,
                json.dumps(summary, ensure_ascii=False, indent=2, default=str),
                data,
            )
        return ReactToolResult(False, f"unknown action: {action}", {"action": action})
