"""PersonAgent 的核心记忆运行时。

中文：封装 PersonAgent 的记忆上下文、检索工具、抽取和合并流程。
English: Encapsulates memory context, retrieval tools, extraction, and consolidation.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Mapping
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agentsociety2.agent.memory import (
    AgentMemoryStore,
    MemoryConsolidationConfig,
    MemoryExtractionResult,
)
from agentsociety2.agent.person_prompt import xml_block

MEMORY_CONSOLIDATION_SYSTEM_PROMPT = """
Rewrite MEMORY.md for a simulated person.

You MUST output the complete refreshed MEMORY.md as Markdown directly in your
response message. Do NOT call any tool. Do NOT wrap the output in JSON, code
fences, or quotes. Do NOT escape or remove newlines. Write real Markdown with
real line breaks — your response is written to MEMORY.md verbatim.

Formatting rules (critical):
- Start with a single H1 line: `# Memory`.
- Every section heading MUST be on its own line as `## <Section Name>`.
- Every bullet MUST be on its own line and start with `- `.
- Put one blank line between the H1 and the first section, and between sections.
- Use plain `- text` bullets; no nested sub-bullets.
- Keep the document compact, stable, and useful as long-term background.

Use exactly these section headings, in this order:
## Identity And Profile
## Stable Preferences
## Relationships
## Durable Goals And Commitments
## Important Past Events
## Known Constraints

Verbatim example of the required structure and line breaks — imitate it exactly:

# Memory

## Identity And Profile
- 28-year-old female, marketing analyst, Bachelor's degree.
- Home AOI 500038964; work AOI 500021584.

## Stable Preferences
- Sleeps 23:00-07:00.

## Relationships
- None recorded.

## Durable Goals And Commitments
- None recorded.

## Important Past Events
- None recorded.

## Known Constraints
- None recorded.

Section guidance:
- Identity And Profile includes age, education, occupation, home AOI, work AOI,
  workplace, and other profile facts.
- Relationships is only for named people or social ties, never home/work
  locations.
- Stable Preferences is only for durable preferences or routines, not one-day
  sleep or meal segments.

Do not promote into long-term memory:
- Current-step actions.
- One-day schedules.
- Timestamps.
- Routine simulation events.
""".strip()


@dataclass(frozen=True)
class MemoryRuntimeConfig:
    """核心文件记忆的运行时配置。

    :param enabled: 是否启用核心记忆。
    :param context_max_chars: MEMORY.md 提示上下文的字符预算。
    :param recent_limit: 纳入提示上下文的最近 episode 数量。
    :param consolidation: 程序化的合并触发配置。
    """

    enabled: bool = True
    context_max_chars: int = 4000
    recent_limit: int = 8
    consolidation: MemoryConsolidationConfig = field(
        default_factory=MemoryConsolidationConfig
    )


class PersonMemoryRuntime:
    """持有记忆上下文、检索工具、抽取与合并流程。

    :param agent_id: 数字 agent id。
    :param config: 记忆运行时配置。
    :param get_model_name: 返回当前生效 LLM 模型名的回调。
    :param dispatch_llm: 用于调用 LLM dispatcher 的回调。
    :param logger: 用于输出告警的 logger 类对象。
    """

    def __init__(
        self,
        *,
        agent_id: int,
        config: MemoryRuntimeConfig,
        get_model_name: Callable[[], str | None],
        dispatch_llm: Callable[..., Awaitable[Any]],
        logger: Any,
        trace_span: Callable[..., Any] | None = None,
        consolidation_system_prompt: str | None = None,
    ) -> None:
        """初始化记忆运行时。

        :param agent_id: 数字 agent id。
        :param config: 记忆运行时配置。
        :param get_model_name: 返回当前生效 LLM 模型名的回调。
        :param dispatch_llm: 用于调用 LLM dispatcher 的回调。
        :param logger: 用于输出告警的 logger 类对象。
        :param trace_span: 可选的 OTel span 上下文管理器工厂,用于追踪记忆
            LLM 调用与文件 I/O 阶段(否则这些阶段没有 span,在 agent.step
            中呈现为无法解释的空档)。
        :param consolidation_system_prompt: run 级 MEMORY.md 合并 system
            prompt override;``None`` 用编译期默认(逐字节一致)。
        :returns: 无返回值。
        """
        self.agent_id = agent_id
        self._consolidation_system_prompt = (
            consolidation_system_prompt or MEMORY_CONSOLIDATION_SYSTEM_PROMPT
        )
        self.config = config
        self._get_model_name = get_model_name
        self._dispatch_llm = dispatch_llm
        self._logger = logger
        self._trace_span_cb = trace_span
        self._store: AgentMemoryStore | None = None

    def _span(self, name: str, **attributes: Any) -> Any:
        """返回一个 span 上下文管理器(未启用追踪时为 no-op)。

        :param name: span 名称。
        :param attributes: 起始属性。
        :returns: 上下文管理器。
        """
        if self._trace_span_cb is None:
            return nullcontext()
        return self._trace_span_cb(name, attributes=dict(attributes) or None)

    @property
    def enabled(self) -> bool:
        """返回是否启用记忆。

        :returns: 核心记忆应当运行时返回 True。
        """
        return self.config.enabled

    def ensure_store(self, workspace_root: Path) -> AgentMemoryStore | None:
        """启用时返回已初始化的核心记忆存储。

        :param workspace_root: 单个 agent 工作区的根目录。
        :returns: 启用时返回记忆存储,否则返回 None。
        """
        if not self.enabled:
            return None
        if self._store is None:
            self._store = AgentMemoryStore(workspace_root, agent_id=self.agent_id)
        self._store.ensure()
        return self._store

    @property
    def store(self) -> AgentMemoryStore | None:
        """返回当前的记忆存储。

        :returns: 已启用且已初始化时返回记忆存储,否则返回 None。
        """
        return self._store if self.enabled else None

    def build_context(self) -> dict[str, Any]:
        """从 MEMORY.md 与最近的 episodes 构建紧凑的提示上下文。

        :returns: 可直接进入提示的记忆上下文字典。
        """
        store = self.store
        if store is None:
            return {}
        return {
            "memory_md": store.read_memory_md(max_chars=self.config.context_max_chars),
            "recent_episodes": store.recent(limit=self.config.recent_limit)
            if self.config.recent_limit > 0
            else [],
            "files": {
                "summary": "MEMORY.md",
                "episodes": "memory/episodes.jsonl",
            },
        }

    def dispatch_tool(
        self, action: str, args: dict[str, Any]
    ) -> tuple[bool, str, dict[str, Any]]:
        """分发内置的只读记忆检索工具。

        :param action: 记忆工具名。
        :param args: 模型给出的工具参数。
        :returns: ``(ok, observation, data)`` 三元组。
        """
        store = self.store
        if store is None:
            return (
                False,
                "memory feature is disabled",
                {"error": "memory feature is disabled"},
            )
        if action == "memory_recent":
            data = {"episodes": store.recent(limit=int(args.get("limit") or 8))}
            return (
                True,
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "memory_search":
            data = {
                "episodes": store.search(
                    str(args.get("query") or ""),
                    limit=int(args.get("limit") or 20),
                )
            }
            return (
                True,
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "memory_range":
            start_step = args.get("start_step")
            end_step = args.get("end_step")
            start_tick = args.get("start_tick")
            end_tick = args.get("end_tick")
            data = {
                "episodes": store.range(
                    start_step=int(start_step) if start_step is not None else None,
                    end_step=int(end_step) if end_step is not None else None,
                    start_tick=int(start_tick) if start_tick is not None else None,
                    end_tick=int(end_tick) if end_tick is not None else None,
                    start_time=str(args.get("start_time") or "") or None,
                    end_time=str(args.get("end_time") or "") or None,
                    limit=int(args.get("limit") or 50),
                )
            }
            return (
                True,
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                data,
            )
        if action == "memory_read":
            ids = args.get("ids")
            id_list = [str(item) for item in ids] if isinstance(ids, list) else []
            data = {"episodes": store.read_ids(id_list)}
            return (
                True,
                json.dumps(data, ensure_ascii=False, indent=2, default=str),
                data,
            )
        return False, f"unknown action: {action}", {"action": action}

    async def after_step(
        self,
        *,
        tick: int,
        t: datetime,
        step_count: int,
        finish_memories: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        """摄取步骤记忆并在触发条件满足时刷新 MEMORY.md。

        记忆生成完全发生在 step 模式的 ``finish`` 工具中,没有专门的
        抽取 LLM 调用(也没有回退)。``finish_memories`` 携带模型内联记录
        的 episodes,当其缺失或为空(如循环达到轮次上限仍未 finish,或模型
        未报告任何值得记录的内容)时,本步骤不记录任何内容。

        :param tick: 当前仿真 tick。
        :param t: 当前仿真时间。
        :param step_count: 当前 agent 步数。
        :param finish_memories: step 模式 finish 工具内联记录的记忆,
            ``None`` 或为空表示本步骤不记录任何内容。
        :returns: 本步骤写入的 episode 记录。
        """
        store = self.store
        if store is None or not finish_memories:
            return []
        try:
            with self._span("memory.extract", operation_type="memory"):
                memories = self._validate_finish_memories(finish_memories)
        except Exception as exc:
            # Don't drop the whole step when the model supplied malformed
            # episodes: fall back to per-item validation, coercing any invalid
            # item into a minimal valid episode so the durable info the model
            # did provide still survives. Only truly empty input yields nothing.
            self._logger.warning(
                "Agent %s: finish-memory validation failed (%s); coercing "
                "individual items as fallback",
                self.agent_id,
                exc,
            )
            memories = self._validate_finish_memories_lenient(finish_memories)
            if not memories:
                return []
        with self._span("memory.append_episodes", operation_type="memory"):
            written = await asyncio.to_thread(
                store.append_episodes,
                memories,
                tick=tick,
                t=t,
                step_count=step_count,
            )
        if not written:
            return []
        with self._span("memory.should_consolidate", operation_type="memory"):
            should, reason = await asyncio.to_thread(
                store.should_consolidate,
                written,
                step_count=step_count,
                config=self.config.consolidation,
            )
        if should:
            state = await asyncio.to_thread(store.read_state)
            cooldown_until = int(state.get("consolidation_cooldown_until_step") or 0)
            if step_count < cooldown_until:
                self._logger.info(
                    "Agent %s: memory consolidation skipped (fuse active until "
                    "step %d; last merges returned empty).",
                    self.agent_id,
                    cooldown_until,
                )
                return written
            try:
                with self._span("memory.consolidate", operation_type="memory"):
                    merged_ok = await self._consolidate_memory_md(
                        tick=tick,
                        t=t,
                        step_count=step_count,
                        reason=reason,
                    )
            except Exception as exc:
                self._logger.warning(
                    "Agent %s: memory consolidation failed: %s", self.agent_id, exc
                )
            else:
                await asyncio.to_thread(
                    self._record_consolidation_outcome,
                    store,
                    merged_ok,
                    step_count,
                )
        return written

    def _record_consolidation_outcome(
        self,
        store: Any,
        merged_ok: bool,
        step_count: int,
    ) -> None:
        """持久化合并熔断的计数器(不调用 LLM)。

        先重新读取状态:一次成功的合并已经重写了它(游标已前进),直接
        修补合并前的快照会把游标回滚。成功的合并清零连续计数,连续两次
        空合并将触发冷却,否则游标永不前进,每一步都会为同样的必然为空
        的结果消耗一次完整的合并 LLM 调用。
        """
        state = store.read_state()
        streak = int(state.get("consolidation_empty_streak") or 0)
        if merged_ok:
            if streak:
                state["consolidation_empty_streak"] = 0
                store.write_state(state)
            return
        streak += 1
        state["consolidation_empty_streak"] = streak
        if streak >= 2:
            # 2x the default interval (8) as a fuse horizon; readable steps.
            state["consolidation_cooldown_until_step"] = step_count + 16
            state["consolidation_empty_streak"] = 0
            self._logger.warning(
                "Agent %s: memory consolidation returned empty twice; pausing "
                "consolidation attempts until step %d.",
                self.agent_id,
                state["consolidation_cooldown_until_step"],
            )
        store.write_state(state)

    def _validate_finish_memories(self, raw: Any) -> list[dict[str, Any]]:
        """校验 step 模式 ``finish`` 工具内联给出的记忆。

        通过 :class:`MemoryExtractionResult` 校验,失败时调用方
        (:meth:`after_step`)回退到逐条宽松转换。不调用 LLM,记忆生成完全
        在 finish 工具中完成。

        :param raw: finish 工具参数中的 ``memories`` 列表。
        :returns: 可直接传给 ``store.append_episodes`` 的已校验 episode 字典。
        """
        if not isinstance(raw, list):
            raise ValueError("finish `memories` must be a list")
        parsed = MemoryExtractionResult.model_validate({"memories": raw})
        return [item.model_dump() for item in parsed.memories]

    def _validate_finish_memories_lenient(self, raw: Any) -> list[dict[str, Any]]:
        """finish 记忆的尽力而为回退校验。

        在严格的 :meth:`_validate_finish_memories` 抛出异常时使用(某个坏
        条目污染了整个列表)。逐条独立校验:合法的 episode 原样保留,非法
        条目被转换为用模型给出的任意文本构造的最小合法 ``observation``
        episode,并打上 ``source=finish_memory_coerced`` 标签使降级可追踪。
        没有可用文本的条目被丢弃。

        :param raw: finish 工具参数中的 ``memories`` 列表。
        :returns: 可直接传给 ``store.append_episodes`` 的已校验/已转换
            episode 字典(可能为空)。
        """
        if not isinstance(raw, list):
            return []
        from agentsociety2.agent.memory import ExtractedMemoryEpisode

        coerced: list[dict[str, Any]] = []
        for item in raw:
            try:
                episode = ExtractedMemoryEpisode.model_validate(item)
                coerced.append(episode.model_dump())
                continue
            except Exception:
                self._logger.debug(
                    "Skipping malformed memory episode during validation", exc_info=True
                )
            # Coerce: salvage any text-like field from the raw item.
            text = ""
            if isinstance(item, Mapping):
                for key in ("text", "content", "summary", "description"):
                    candidate = str(item.get(key) or "").strip()
                    if candidate:
                        text = candidate
                        break
            elif isinstance(item, str):
                text = item.strip()
            if not text:
                continue
            try:
                episode = ExtractedMemoryEpisode.model_validate(
                    {
                        "type": "observation",
                        "importance": 0.4,
                        "text": text[:1000],
                        "source": "finish_memory_coerced",
                    }
                )
                coerced.append(episode.model_dump())
            except Exception:
                continue
        return coerced

    async def _consolidate_memory_md(
        self,
        *,
        tick: int,
        t: datetime,
        step_count: int,
        reason: str,
    ) -> bool:
        """从当前紧凑记忆与最近的 episodes 刷新 MEMORY.md。

        :param tick: 当前仿真 tick。
        :param t: 当前仿真时间。
        :param step_count: 当前 agent 步数。
        :param reason: 程序化触发原因。
        :returns: MEMORY.md 被重写时返回 True;模型返回空内容时返回 False
            (文件保持不变,游标不前进,由调用方计入合并熔断)。
        """
        model_name = self._require_model_name()
        store = self._require_store()

        def _gather_consolidation_input() -> tuple[
            list[dict[str, Any]], list[dict[str, Any]], str
        ]:
            # All sync store I/O (now mostly cache-backed for unconsolidated/
            # search; read_memory_md is one small file read). Coalesced into a
            # single thread offload so none of it blocks the event loop.
            new_eps = [
                item
                for item in store.unconsolidated()
                if store.is_long_term_memory_candidate(item)
            ]
            if not new_eps:
                return [], [], ""
            keywords = {
                str(keyword)
                for episode in new_eps
                for keyword in episode.get("keywords", [])
                if str(keyword).strip()
            }
            related: list[dict[str, Any]] = []
            for keyword in sorted(keywords)[:12]:
                related.extend(store.search(keyword, limit=3))
            related_by_id = {str(item.get("id")): item for item in related}
            current_md = store.read_memory_md(max_chars=self.config.context_max_chars)
            return new_eps, list(related_by_id.values())[:30], current_md

        new_episodes, related_list, current_md = await asyncio.to_thread(
            _gather_consolidation_input
        )
        if not new_episodes:
            return
        payload = {
            "reason": reason,
            "tick": tick,
            "time": t.isoformat(),
            "current_memory_md": current_md,
            "new_episodes": new_episodes[-30:],
            "related_old_episodes": related_list,
            "max_chars": self.config.context_max_chars,
        }
        messages = [
            {
                "role": "system",
                "content": self._consolidation_system_prompt,
            },
            {
                "role": "user",
                "content": xml_block(
                    "memory_consolidation_input",
                    json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                ),
            },
        ]
        with self._span(
            "llm.completion",
            operation_type="llm",
            llm_purpose="memory_consolidate",
            llm_model=model_name,
        ):
            response = await self._dispatch_llm(
                model=model_name,
                messages=messages,
                stream=False,
                # 单次摘要重写，推理无收益且拖慢每步收尾。
                thinking="off",
            )
        # 直接取 LLM 返回的 Markdown 文本作为新 MEMORY.md，不走 tool calling。
        content = ""
        if getattr(response, "choices", None):
            message = getattr(response.choices[0], "message", None)
            content = str(getattr(message, "content", "") or "")
        content = content.strip()
        if not content:
            # No usable output: keep the existing MEMORY.md. Warn (don't raise)
            # so this is visible — because the consolidation cursor is only
            # advanced on a successful write, a model that consistently returns
            # empty would re-trigger consolidation every step and burn LLM
            # calls. The caller's fuse now pauses attempts after repeats.
            self._logger.warning(
                "Agent %s: memory consolidation returned empty content; "
                "MEMORY.md left unchanged (consolidation may re-trigger).",
                self.agent_id,
            )
            return False
        await asyncio.to_thread(
            store.write_memory_md, content, step_count=step_count, tick=tick
        )
        return True

    def _require_model_name(self) -> str:
        """返回配置的模型名。

        :returns: 当前生效的模型名。
        """
        model_name = self._get_model_name()
        assert model_name is not None, "LLM is not initialized"
        return model_name

    def _require_store(self) -> AgentMemoryStore:
        """返回已初始化的记忆存储。

        :returns: 当前生效的记忆存储。
        """
        store = self.store
        if store is None:
            raise RuntimeError("Memory store is not initialized")
        return store
