"""基于 workspace 的 PersonAgent(轻量封装)。

中文：``PersonAgent`` 现在只负责 person 专属逻辑（memory、todo、person prompt、
observe），通用的 agent 机器（workspace / skill / tool / react）已下沉到
``agent.base``。
English: ``PersonAgent`` now owns only person-specific logic (memory, todo,
person prompt, observe).  The generic agent machinery (workspace / skill /
tool / react) has been pushed down into ``agent.base``.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from agentsociety2.agent.base import AgentBase, ReactToolResult
from agentsociety2.agent.memory_runtime import (
    MemoryRuntimeConfig,
    PersonMemoryRuntime,
)
from agentsociety2.agent.person_prompt import (
    build_react_messages,
    json_block,
    load_prompt_overrides,
    xml_block,
)
from agentsociety2.logger import get_logger

if TYPE_CHECKING:
    from agentsociety2.agent.service_proxy import ServiceProxy

logger = get_logger()


def _str_override(overrides: Any, key: str) -> str | None:
    """取出 run 级 override 的 str 值。

    :param overrides: ``load_prompt_overrides`` 的返回(或 None)。
    :param key: override 键名。
    :returns: 非空字符串值;键缺失/非字符串/空串一律 ``None``
        (回退编译期默认,防畸形文件悄悄打空提示词)。
    """
    if not isinstance(overrides, dict):
        return None
    value = overrides.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


class PersonAgent(AgentBase):
    """基于 workspace 的模拟人类 agent。

    person 专属职责:

    - 记忆运行时(``PersonMemoryRuntime``): ``MEMORY.md`` + episodes,外加
      ``memory_*`` 工具分发。
    - ``todo_*`` 工具分发(通用 TODO 状态存储与辅助方法位于
      :class:`AgentBase`;PersonAgent 把 ``todo_*`` 前缀路由过去)。
    - person 提示词构建(``build_react_messages``),即通用 ReAct 循环调用的
      提示词 hook。
    - ``step`` / ``ask`` 编排(observe + react 循环 + 生命周期 hook)。

    通用 agent 机器(workspace 绑定、skill 发现、文件/skill/ask_env 工具分发、
    ReAct 循环、LLM 分发、响应解析、TODO 状态、trace span、AGENT.json 持久化、
    构造模型)全部继承自 :class:`AgentBase`。
    """

    # ==================== Workspace contract ====================
    # ``create`` / ``from_workspace`` are inherited verbatim from AgentBase
    # (they delegate to the concrete base implementations, which call
    # ``cls()`` + ``await agent.restore(...)``).  PersonAgent only overrides
    # ``restore`` to add person-specific state on top of the base restore.

    # ==================== Descriptions ====================

    @classmethod
    def description(cls) -> str:
        """返回简短的注册表描述。"""
        return (
            "PersonAgent: workspace-backed LLM-native person agent. Full ReAct "
            "tool loop, metadata-first skill activation, workspace-backed "
            "memory, and per-step behavior tracing."
        )

    @classmethod
    def init_description(cls) -> str:
        """返回供生成配置使用的初始化指引。"""
        return """PersonAgent initialization (workspace-based).

Agents are created via ``PersonAgent.create(workspace_path, profile, config)``
and reconstructed via ``await PersonAgent.from_workspace(workspace_path, service_proxy)``.
The constructor ``__init__`` is arg-less.

Required profile fields:
- id (int): unique agent id.
- name (str | None): optional display name.

Config dict keys (written to ``config.json``, round-tripped by ``from_workspace``):
- max_react_turns (int): max ReAct turns per step. Default 10.
- enable_todo_list (bool): default true.
- enable_memory (bool): default true.
- memory_context_max_chars (int): default 4000.
- recent_memory_limit (int): default 8.
- memory_consolidation_pending_threshold (int): default 10.
- memory_consolidation_interval_steps (int): default 8.
- memory_high_importance_threshold (float): default 0.75.
- disabled_skill_ids (list[str]): default [].
- default_activated_skill_ids (list[str]): default [].

Minimal config example:
```json
{
  "profile": {"id": 1, "name": "Alice", "occupation": "engineer"},
  "config": {"enable_memory": true, "max_react_turns": 6}
}
```
"""

    # ==================== Person-specific config helpers ====================

    def _apply_person_config(self) -> None:
        """从 ``self._config`` 解析 person 专属配置字段。

        在基类 restore 之后由 :meth:`restore` 调用。通用 react 循环 / 工具
        开关(``_max_react_turns``、``_enable_todo_list``)已改由
        :meth:`AgentBase.restore` 解析;本方法只解析 person 专属的记忆配置。
        """
        cfg = self._config
        self._enable_memory = bool(cfg.get("enable_memory", True))
        self._memory_context_max_chars = max(
            500, int(cfg.get("memory_context_max_chars", 4000) or 4000)
        )
        self._recent_memory_limit = max(0, int(cfg.get("recent_memory_limit", 8) or 0))
        # 闲置跳过(Reflex 快路径):默认关闭,经配置逐实验开启。
        # 开启后,pre_step hook 判定当前处于可确定性执行的静态活动段
        # (如夜间睡眠)时,run step 跳过 observe + react 循环,写一条
        # 合成记忆;问卷(ask 路径)不受影响。T1 实测:全部深夜 slot
        # 80/80 回答 sleep——每步都是花钱让模型说"我在睡觉"。
        self._idle_skip_enabled = bool(cfg.get("idle_skip_enabled", False))

    # ==================== restore override ====================

    async def restore(
        self,
        workspace_path: Path,
        service_proxy: ServiceProxy,
    ) -> None:
        """先恢复基类状态,再构建 person 专属运行时(记忆)。

        :param workspace_path: agent workspace 根目录。
        :param service_proxy: 共享服务容器。
        """
        await super().restore(workspace_path, service_proxy)
        self._apply_person_config()
        meta = json.loads(
            (Path(workspace_path) / "AGENT.json").read_text(encoding="utf-8")
        )
        self._world_description = str(meta.get("world_description") or "")
        # run 级提示词 override:workspace 布局为 run_dir/agents/agent_XXXX,
        # 上溯两级即 run_dir;布局不符/文件缺失时 load_prompt_overrides
        # 返回空 dict,提示词与默认逐字节一致(fail-safe)。Ray 下 agent
        # 每 tick restore,RSI 循环改 override 文件下一 tick 即生效。
        self._prompt_overrides = load_prompt_overrides(
            Path(workspace_path).parent.parent
        )
        self._build_memory_runtime()

    def _build_memory_runtime(self) -> None:
        """构建绑定到本 agent 的 ``PersonMemoryRuntime``。"""
        from agentsociety2.agent.memory import MemoryConsolidationConfig

        cfg = self._config
        self._memory_runtime = PersonMemoryRuntime(
            agent_id=self.id,
            consolidation_system_prompt=_str_override(
                self._prompt_overrides, "memory_consolidation"
            ),
            config=MemoryRuntimeConfig(
                enabled=self._enable_memory,
                context_max_chars=self._memory_context_max_chars,
                recent_limit=self._recent_memory_limit,
                consolidation=MemoryConsolidationConfig(
                    pending_threshold=max(
                        1,
                        int(
                            cfg.get("memory_consolidation_pending_threshold", 10) or 10
                        ),
                    ),
                    interval_steps=max(
                        1, int(cfg.get("memory_consolidation_interval_steps", 8) or 8)
                    ),
                    high_importance_threshold=max(
                        0.0,
                        min(
                            1.0,
                            float(
                                cfg.get("memory_high_importance_threshold", 0.75)
                                or 0.75
                            ),
                        ),
                    ),
                    max_memory_chars=self._memory_context_max_chars,
                ),
            ),
            get_model_name=lambda: self._model_name,
            dispatch_llm=lambda **kwargs: self._dispatcher.call(**kwargs),
            logger=logger,
            trace_span=self.trace_span,
        )

    # ==================== to_workspace ====================

    async def to_workspace(self, workspace_path: Path) -> None:
        """把当前动态状态写回 workspace。

        写入 ``AGENT.json``(profile / step_count / current_time / skills /
        initialized_at)。``config.json`` 不会被重写。记忆(``MEMORY.md`` +
        episodes)在 ``step()`` 期间经记忆运行时的 ``after_step`` 路径持久化。

        :param workspace_path: agent workspace 根目录。
        """
        workspace_path = Path(workspace_path)
        if self._workspace_root is None:
            self._bind_workspace(workspace_path)
        self.persist_agent_json(
            tick=None,
            t=self._current_time,
        )

    # ==================== AGENT.json override (memory fields) ====================

    def build_agent_json(
        self,
        *,
        tick: int | None,
        t: datetime | None,
    ) -> dict[str, Any]:
        """构建带 person 专属记忆 / skill 字段的 AGENT.json。"""
        data = super().build_agent_json(tick=tick, t=t)
        # Enrich with person-specific memory + skill-disabled/default fields.
        data["world_description"] = self._world_description
        data["skills"] = {
            "visible": sorted(self.skill_runtime.visible_skill_ids()),
            "activated": sorted(self.skill_runtime.activated_skill_ids()),
            "disabled": sorted(self._disabled_skill_ids),
            "default_activated": sorted(self._default_activated_skill_ids),
        }
        data["memory"] = {
            "enabled": self._enable_memory,
            "summary_path": "MEMORY.md" if self._enable_memory else None,
            "episodes_path": "memory/episodes.jsonl" if self._enable_memory else None,
        }
        return data

    def build_prompt_agent_view(
        self,
        *,
        tick: int | None,
        t: datetime | None,
    ) -> dict[str, Any]:
        """Prompt 的 ``<agent>`` 视图;世界文本留在单独的 ``<world>`` 块中。"""
        data = super().build_prompt_agent_view(tick=tick, t=t)
        data.pop("world_description", None)
        return data

    # ==================== TODO helpers ====================
    # The generic TODO helpers (_todo_store, _ensure_todo_state,
    # _build_todo_context, _current_simulation_time,
    # _normalize_todo_due_value, _normalize_todo_tool_args,
    # dispatch_todo_tool) are inherited from AgentBase.

    # ==================== Memory helpers ====================

    def _ensure_memory_store(self):
        """启用时返回已初始化的核心记忆存储。"""
        from agentsociety2.agent.memory import AgentMemoryStore

        store: AgentMemoryStore | None = self._memory_runtime.ensure_store(
            self.workspace_root_path()
        )
        return store

    def _build_memory_context(self) -> dict[str, Any]:
        """从 MEMORY.md 和近期 episodes 构建紧凑的 prompt 上下文。"""
        store = self._ensure_memory_store()
        if store is None:
            return {}
        return self._memory_runtime.build_context()

    # ==================== Person-specific react tool dispatch ====================

    async def dispatch_react_tool(
        self,
        action: str,
        args: dict[str, Any],
        *,
        readonly: bool = False,
    ) -> ReactToolResult:
        """分发 person 专属前缀,其余动作委托给基类。

        这里处理的 person 专属前缀:

        - ``memory_*`` → :meth:`_dispatch_memory_tool` (person 记忆运行时)。
        - ``todo_*`` → :meth:`dispatch_todo_tool` (继承自
          :class:`AgentBase`;通用 TODO 存储 + 参数归一化)。

        其余所有动作(workspace / skill / ask_env)委托给
        ``await super().dispatch_react_tool(action, args, readonly=readonly)``。
        """
        try:
            if readonly and action.startswith("todo_") and action != "todo_list":
                return ReactToolResult(
                    False,
                    f"{action} is disabled in readonly mode",
                    {"action": action, "readonly": True},
                )
            if action.startswith("memory_"):
                return self._dispatch_memory_tool(action, args)
            if action.startswith("todo_"):
                return self.dispatch_todo_tool(action, args)
        except Exception as exc:
            return ReactToolResult(False, str(exc), {"error": str(exc)})
        return await super().dispatch_react_tool(action, args, readonly=readonly)

    def _react_tool_overrides(self, *, readonly: bool) -> dict[str, Any]:
        """按模式替换 ``finish`` 工具。

        - ask / readonly 模式: 仅含答案的 ``finish``(外部问题)。
        - step 模式: ``finish`` 带简短 ``final`` 且内联 ``memories``,让模型
          在结束 step 的同一次调用里记录 step 记忆,从而省去单独的记忆抽取
          LLM 调用。``step()`` 把捕获到的记忆送入 ``memory_runtime.after_step``。
        """
        from agentsociety2.agent.person_tools import (
            finish_ask_tool_schema,
            finish_step_tool_schema,
        )

        return {
            "finish": finish_ask_tool_schema()
            if readonly
            else finish_step_tool_schema()
        }

    def _dispatch_memory_tool(
        self,
        action: str,
        args: dict[str, Any],
    ) -> ReactToolResult:
        """分发内置的只读记忆检索工具。"""
        ok, observation, data = self._memory_runtime.dispatch_tool(action, args)
        return ReactToolResult(ok, observation, data)

    # ==================== ReAct prompt hook ====================

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
        """构建 ReAct prompt 消息(person 专属)。

        把 AGENT.json 内容拆成布局所需的两个 prompt 块:运行期稳定的
        ``<agent>`` 身份视图(剥离易变与宿主路径字段)和逐 step 的
        ``<turn_state>``。两者来自同一源 dict,因此不会漂移失配。
        """
        return build_react_messages(
            base_rules_override=_str_override(self._prompt_overrides, "base_rules"),
            world_description=self._world_description,
            skill_catalog=self.skill_runtime.skill_catalog(),
            activated_skill_content=self.skill_runtime.activated_skill_content_xml(),
            observations=observations,
            agent_json=self.build_prompt_agent_view(tick=tick, t=t),
            turn_state=self.build_prompt_turn_state(tick=tick, t=t),
            memory_context=self._build_memory_context()
            if self._enable_memory
            else None,
            todo_context=self._build_todo_context(t)
            if self._enable_todo_list
            else None,
            question=question,
            readonly=readonly,
            enable_memory=self._enable_memory,
            enable_todo_list=self._enable_todo_list,
            disable_skills=self.skill_runtime.visible_skill_count() == 0,
            skill_hooks=skill_hooks,
        )

    # The generic ReAct loop, LLM call, and response parsing
    # (run_react_loop, _call_react_llm_with_messages, _complete_react_once,
    # _parse_react_turn, _parse_react_responses) are inherited from
    # AgentBase; they call this ``build_react_messages`` hook polymorphically.

    # ==================== Mid-step context refresh ====================

    # TODO actions that change the task list. ``todo_list`` is a read and needs
    # no refresh.
    _TODO_MUTATING_ACTIONS = frozenset(
        {
            "todo_add",
            "todo_update",
            "todo_start",
            "todo_complete",
            "todo_defer",
            "todo_clear_completed",
        }
    )
    # Skill actions that change which skills are active. The system prompt's
    # <skill_content> block is frozen for the step.
    _SKILL_MUTATING_ACTIONS = frozenset({"activate_skill", "deactivate_skill"})

    def build_context_refresh_message(
        self,
        *,
        actions: list[str],
        tick: int,
        t: datetime,
    ) -> dict[str, Any] | None:
        """为工具刚在 step 中途改变的状态追加刷新块。

        线程头每个 step 只构建一次(正是它保证了缓存前缀不被破坏),因此
        ``<todo_context>`` 与系统 ``<skill_content>`` 块若不刷新,就会在 step
        余下部分保持过期。

        - TODO 变更重发 ``<todo_context>``:它聚合单个工具 observation 不含的
          状态(``due_now``、``overdue_or_blocked``、``counts``)。
        - skill 变更只重发激活 skill 的**清单**,不重发其文档:
          ``activate_skill`` 已把完整 SKILL.md 作为工具 observation 返回,在此
          重复会使多 KB 块翻倍。清单才是 ``deactivate_skill`` 真正需要的;
          observation 无法撤回模型已读过的内容。

        :param actions: 本轮成功执行的工具动作名列表。
        :param tick: 当前模拟 tick。
        :param t: 当前模拟时间。
        :returns: 一条 ``role: "user"`` 刷新消息;没有相关变化时返回 ``None``。
        """
        blocks: list[str] = []
        if self._enable_todo_list and self._TODO_MUTATING_ACTIONS.intersection(actions):
            todo_context = self._build_todo_context(t)
            if todo_context:
                blocks.append(json_block("todo_context", todo_context))
        if self._SKILL_MUTATING_ACTIONS.intersection(actions):
            activated = sorted(self.skill_runtime.activated_skill_ids())
            blocks.append(
                xml_block(
                    "active_skills",
                    "\n".join(activated) if activated else "(none active)",
                )
            )
        if not blocks:
            return None
        # JSON dicts (not a fenced list) so the block stays valid JSON.
        return {"role": "user", "content": "\n\n".join(blocks)}

    async def _load_world_description(self) -> str:
        """从环境加载当前的世界描述。"""
        if self._env is None:
            return ""
        getter = getattr(self._env, "get_world_description", None)
        if getter is None:
            return ""
        try:
            value = await getter()
        except Exception as exc:
            logger.warning("Agent %s: get_world_description failed: %s", self.id, exc)
            return ""
        return str(value or "")

    async def _ensure_initialized(self) -> None:
        """惰性执行首次使用时的初始化(幂等)。"""
        if self._initialized_at is not None:
            return
        self._initialized_at = datetime.now().isoformat()
        with self.trace_span(
            "agent.init",
            attributes={
                "operation.type": "agent",
                "event.type": "agent_init",
                "agent.id": self.id,
            },
        ) as span:
            self._ensure_todo_state()
            self._ensure_memory_store()
            discovered = (
                self.discover_skill_sources(self._env) if self._env is not None else {}
            )
            self._world_description = await self._load_world_description()
            self.persist_agent_json(tick=None, t=None)
            span.attributes.update(
                {
                    "workspace": str(self.workspace_root_path()),
                    "profile.keys": sorted(self.get_profile().keys()),
                    "skill.visible_count": self.skill_runtime.visible_skill_count(),
                    "skill.discovery_sources": len(discovered),
                    "world.description_chars": len(self._world_description),
                }
            )

    # ==================== step / ask ====================

    # 闲置跳过适用(可确定性执行)的静态活动集合。刻意保守起步:夜间
    # 睡眠是唯一有 80/80 实测行为证据(全部深夜问卷回答 sleep)的
    # 无争议静态段;扩展该集合须先配 T2 JSD 行为保真对照。
    _IDLE_SKIP_ACTIVITIES = frozenset({"sleep"})

    def _idle_skip_segment(self, pre_hooks: list[dict[str, Any]] | None) -> dict | None:
        """从 pre_step hook 输出中判定当前是否处于可跳过的静态活动段。

        daily-guidance 的 pre_step hook 以 YAML 返回 ``active_segment``
        (含 activity/start/end 等);活动命中 ``_IDLE_SKIP_ACTIVITIES``
        即认为该 step 可按剧本确定性执行。任何缺失/解析失败/未开启
        都返回 ``None``,调用方回退完整 ReAct 路径(fail-open,绝不让
        优化吞掉判断)。

        :param pre_hooks: ``run_lifecycle_hooks`` 的原始返回项。
        :returns: 命中的活动段字典,无则 ``None``。
        """
        if not self._idle_skip_enabled or not pre_hooks:
            return None
        try:
            import yaml

            for item in pre_hooks:
                if not item.get("ok") or not item.get("output"):
                    continue
                data = yaml.safe_load(str(item["output"]))
                if not isinstance(data, dict):
                    continue
                seg = data.get("active_segment")
                if not isinstance(seg, dict):
                    continue
                activity = str(seg.get("activity") or "").strip().lower()
                if activity in self._IDLE_SKIP_ACTIVITIES:
                    return seg
        except Exception:
            logger.debug("idle-skip hook output parse failed", exc_info=True)
        return None

    async def step(self, tick: int, t: datetime) -> str:
        """运行一个模拟 step。"""
        await self._ensure_initialized()
        self._step_count += 1
        self._current_time = t

        with self.trace_span(
            "agent.step",
            attributes={
                "agent.tick": tick,
                "operation.type": "agent",
                "event.type": "step",
                "input.summary": {"time": t.isoformat(), "tick": tick},
            },
        ) as span:
            self._refresh_visible_skills()

            initial_obs: list[dict[str, Any]] = []
            pre_hooks = await self.run_lifecycle_hooks("pre_step", tick=tick, t=t)

            # 闲置跳过(Reflex 快路径):静态活动段(夜间睡眠等)按剧本
            # 确定性推进,不进 LLM 循环。任何解析失败/无段/未开启一律
            # 回退完整 ReAct 路径(fail-open)。
            idle_seg = self._idle_skip_segment(pre_hooks)
            if idle_seg is not None:
                result = (
                    f"[idle-skip] {idle_seg.get('activity')} "
                    f"({idle_seg.get('start', '?')}–{idle_seg.get('end', '?')}): "
                    "deterministic step, no reasoning performed"
                )
                span.attributes.update(
                    {
                        "idle_skip.skipped": True,
                        "idle_skip.activity": idle_seg.get("activity"),
                        "output.summary": {"result": result},
                    }
                )
                post_hooks = await self.run_lifecycle_hooks("post_step", tick=tick, t=t)
                memory_episodes = await self._memory_runtime.after_step(
                    tick=tick,
                    t=t,
                    step_count=self._step_count,
                    finish_memories=[
                        {
                            "type": "observation",
                            "importance": 0.2,
                            "keywords": [
                                str(idle_seg.get("activity") or "idle"),
                                "idle-skip",
                            ],
                            "text": (
                                f"Was {idle_seg.get('activity')} during "
                                f"{idle_seg.get('start', '?')}–"
                                f"{idle_seg.get('end', '?')} per the daily plan "
                                "(step executed deterministically)."
                            ),
                        }
                    ],
                )
                span.attributes.update(
                    {
                        "step.count": self._step_count,
                        "skill.pre_hook_count": len(pre_hooks),
                        "skill.post_hook_count": len(post_hooks),
                        "memory.episode_count": len(memory_episodes),
                    }
                )
                return result
            skill_hooks: list[dict[str, Any]] | None = None
            if pre_hooks:
                skill_hooks = [
                    {
                        "skill": item["skill_id"],
                        "hook": item["hook_type"],
                        "ok": item["ok"],
                        "output": item["stdout"],
                    }
                    for item in pre_hooks
                    if item.get("ok") and item.get("stdout")
                ] or None

            if self._env is not None:
                try:
                    with self.trace_span(
                        "react.tool",
                        attributes={
                            "operation.type": "react",
                            "react.action": "observe",
                        },
                    ) as obs_span:
                        _env_span = self._current_trace_span
                        _, observation = await self.ask_env(
                            {"id": self.id},
                            "<observe>",
                            readonly=True,
                            trace_id=_env_span.trace_id if _env_span else None,
                            parent_span_id=_env_span.span_id if _env_span else None,
                        )
                        obs_text = str(observation or "")
                        obs_span.attributes.update(
                            {
                                "result.ok": True,
                                "output.summary": {"observation": obs_text},
                            }
                        )
                        initial_obs.append(
                            {
                                "turn": 0,
                                "action": "observe",
                                "ok": True,
                                "observation": obs_text,
                            }
                        )
                except Exception:
                    logger.debug("Observation failed for agent", exc_info=True)

            result = await self.run_react_loop(
                tick=tick, t=t, observations=initial_obs, skill_hooks=skill_hooks
            )
            post_hooks = await self.run_lifecycle_hooks("post_step", tick=tick, t=t)
            memory_episodes = await self._memory_runtime.after_step(
                tick=tick,
                t=t,
                step_count=self._step_count,
                finish_memories=self._last_finish_memories,
            )
            span.attributes.update(
                {
                    "step.count": self._step_count,
                    "skill.visible_count": self.skill_runtime.visible_skill_count(),
                    "skill.pre_hook_count": len(pre_hooks),
                    "skill.post_hook_count": len(post_hooks),
                    "memory.episode_count": len(memory_episodes),
                    "output.summary": {"result": result},
                }
            )
        return result

    async def ask(
        self,
        message: str,
        readonly: bool = True,
        *,
        t: datetime | None = None,
    ) -> str:
        """通过 ReAct 循环回答外部问题。"""
        if self._env is None:
            raise RuntimeError("PersonAgent.ask requires an initialized environment")
        await self._ensure_initialized()

        with self.trace_span(
            "agent.ask",
            attributes={
                "operation.type": "agent",
                "event.type": "ask",
                "input.summary": {
                    "readonly": readonly,
                    "message_chars": len(message),
                },
            },
        ) as span:
            try:
                now = t or self._current_time or datetime.now()
                self._current_time = now
                self._refresh_visible_skills()
                self.persist_agent_json(tick=None, t=now)
                answer_text = await self.run_react_loop(
                    tick=0,
                    t=now,
                    observations=[],
                    question=message,
                    readonly=readonly,
                )
            except Exception as exc:
                span.attributes["error.message"] = str(exc)[:300]
                raise

            span.attributes["output.summary"] = {"answer_chars": len(answer_text)}
        return answer_text
