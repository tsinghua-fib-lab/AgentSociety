import asyncio
import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from mem0 import AsyncMemory
from mem0.memory.main import MemoryConfig

from agentsociety2.agent.base import AgentBase


class LLMDonorAgent(AgentBase):
    """LLM 驱动的捐赠者智能体

    核心特性：
    1. 基于 LLM 动态决策
    2. 集成记忆系统（mem0）用于学习
    3. 周期性观察顶尖智能体并学习
    4. 根据情境信息（声誉、收益、记忆）做出决策

    Profile 字段（字典格式）：
    - learning_frequency: int (可选) -> 学习频率，默认5（每5步学习一次）
    - personality: str (可选) -> 智能体个性描述
    - initial_mood: float (可选) -> 初始情绪值（-1.0 ~ 1.0）
    - risk_tolerance: float (可选) -> 风险偏好（0.0 ~ 1.0）
    """

    # 常量定义
    DEFAULT_POPULATION_SIZE = 5
    DEFAULT_LEARNING_FREQUENCY = 5
    MOOD_DECAY_RATE = 0.95
    MOOD_ADJUSTMENT_STEP = 0.1
    PAYOFF_THRESHOLD_HIGH = 50.0
    PAYOFF_THRESHOLD_LOW = 0.0
    MOOD_THRESHOLD_NEGATIVE = -0.3
    RISK_THRESHOLD_LOW = 0.3
    RECENT_MEMORIES_COUNT = 5
    DECISION_HISTORY_LIMIT = 100
    TOP_AGENTS_COUNT = 5

    @classmethod
    def init_description(cls) -> str:
        """
        Return AI-readable initialization guidance for this agent class.
        Includes parameter descriptions.
        """
        description = f"""{cls.__name__}: LLM-driven donor agent with memory and learning capabilities.

**Description:** LLM-driven donor agent that makes donation decisions based on reputation, payoffs, and memory. Features dynamic mood and risk tolerance that influence decision-making.

**Initialization Parameters:**
- id (int): The unique identifier for the agent.
- profile (dict | Any): The profile of the agent. Can include custom_fields with:
  - learning_frequency (int, optional): How often to learn from top agents (default: 5)
  - personality (str, optional): Agent personality description (affects decision-making)
  - initial_mood (float, optional): Initial mood value from -1.0 (negative) to 1.0 (positive)
  - risk_tolerance (float, optional): Risk preference from 0.0 (conservative) to 1.0 (risk-taking)
- memory_config (dict | None, optional): Configuration for mem0 memory system
- learning_frequency (int, optional): Learning frequency override (default: 5)

**Game Rules:**
This agent participates in a reputation-based donation game where it can choose to cooperate (donate) or defect. Donations cost 1 point but give the recipient 5 points. The agent considers reputation, past experiences, mood, and risk tolerance when making decisions.

**Example initialization config:**
```json
{{
  "id": 1,
  "profile": {{
    "custom_fields": {{
      "learning_frequency": 5,
      "personality": "You are a rational and cautious agent, tending to maximize long-term benefits.",
      "initial_mood": 0.5,
      "risk_tolerance": 0.6
    }}
  }},
  "memory_config": null,
  "learning_frequency": 5
}}
```
"""
        return description

    # ==================== Workspace 契约 ====================

    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        """Create the initial agent workspace.

        .. note::
           The mem0 external memory system is NOT persisted in the workspace
           (it has its own backend). Only the LLM-decision state is round-tripped.
        """
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "config.json").write_text(
            json.dumps(config or {}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        agent_id = int(profile.get("id", 0))
        name = str(profile.get("name") or f"Agent_{agent_id}")
        (workspace_path / "AGENT.json").write_text(
            json.dumps(
                {
                    "id": agent_id,
                    "name": name,
                    "profile": profile,
                    "step_count": 0,
                    "decision_history": [],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    async def from_workspace(
        cls, workspace_path: Path, service_proxy: Any
    ) -> "LLMDonorAgent":
        """Reconstruct a ready LLMDonorAgent from its workspace.

        Restores decision_history, step_count, personality, mood, and
        risk_tolerance from ``AGENT.json``. The mem0 memory system is
        re-initialized from config (mem0 manages its own persistence).
        """
        agent = cls()
        await agent._restore(workspace_path, service_proxy)
        return agent

    async def _restore(self, workspace_path: Path, service_proxy: Any) -> None:
        """Restore game-agent state from AGENT.json + config.json (no super() —
        game agents don't use the skill/workspace runtime that
        AgentBase._restore binds)."""
        workspace_path = Path(workspace_path)
        cfg = {}
        config_path = workspace_path / "config.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
        meta = json.loads((workspace_path / "AGENT.json").read_text(encoding="utf-8"))
        self._id = int(meta.get("agent_id", meta.get("id", 0)))
        self._profile = meta.get("profile", cfg.get("profile", {}))
        self._name = meta.get("name") or f"Agent_{self._id}"
        self._config = dict(cfg or {})
        self._bind_services(service_proxy)
        self._step_count = int(meta.get("step_count", 0))

        # 记忆系统（mem0）
        resolved_memory_config = cfg.get("memory_config")
        self._memory_user_id = f"agent_{self._id}"
        self._memory: AsyncMemory | None = None
        if resolved_memory_config is not None:
            memory_config_obj = MemoryConfig.model_validate(resolved_memory_config)
            self._memory = AsyncMemory(config=memory_config_obj)

        # 学习配置
        custom_fields = self._extract_custom_fields(self._profile)
        learning_freq = (
            custom_fields.get("learning_frequency")
            if isinstance(custom_fields, dict)
            else None
        )
        resolved_learning_frequency = cfg.get(
            "learning_frequency", self.DEFAULT_LEARNING_FREQUENCY
        )
        self._learning_frequency = self._coerce_int(
            learning_freq,
            int(resolved_learning_frequency)
            if resolved_learning_frequency is not None
            else self.DEFAULT_LEARNING_FREQUENCY,
        )

        # 状态追踪
        self._decision_history: list[dict] = list(meta.get("decision_history", []))
        # 缓存 Z 值（种群大小），第一次使用时从环境查询
        self._cached_Z: int | None = None

        # 主观情绪/个性状态（用于影响决策）
        self._personality = custom_fields.get(
            "personality", self._generate_random_personality()
        )
        self._mood = self._coerce_float(
            custom_fields.get("initial_mood"), random.uniform(-1.0, 1.0)
        )
        self._risk_tolerance = self._coerce_float(
            custom_fields.get("risk_tolerance"), random.uniform(0.0, 1.0)
        )
        # Restore subjective state if persisted; otherwise keep init defaults.
        if "personality" in meta:
            self._personality = str(meta["personality"])
        if "mood" in meta:
            self._mood = float(meta["mood"])
        if "risk_tolerance" in meta:
            self._risk_tolerance = float(meta["risk_tolerance"])

    async def to_workspace(self, workspace_path: Path) -> None:
        """Write current dynamic state back to the workspace.

        Persists decision_history, step_count, personality, mood, and
        risk_tolerance. The mem0 memory system is NOT flushed here.
        """
        workspace_path = Path(workspace_path)
        profile_data = self._profile
        if hasattr(self._profile, "to_dict"):
            profile_data = self._profile.to_dict()
        elif not isinstance(profile_data, dict):
            profile_data = {"raw": str(profile_data)}
        (workspace_path / "AGENT.json").write_text(
            json.dumps(
                {
                    "id": self._id,
                    "name": self._name,
                    "profile": profile_data,
                    "step_count": self._step_count,
                    "decision_history": self._decision_history[
                        -self.DECISION_HISTORY_LIMIT :
                    ],
                    "personality": self._personality,
                    "mood": self._mood,
                    "risk_tolerance": self._risk_tolerance,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def _generate_random_personality(self) -> str:
        """生成随机个性描述（仅在未提供 personality 时使用，作为后备方案）"""
        # 默认个性列表（仅在未提供 personality 时使用）
        personalities = [
            "You are a rational and cautious agent, tending to maximize long-term benefits.",
            "You are an emotional agent, and your decisions are influenced by your current emotional state.",
            "You are a fair-minded agent, tending to help those with good reputation and refusing to help those with bad reputation.",
            "You are an altruistic agent, more willing to help others even if it may harm your short-term benefits.",
            "You are a selfish agent, mainly focusing on your own benefits and not caring much about others' reputation.",
            "You are a vengeful agent, if others treat you badly, you will remember and take revenge.",
            "You are an optimistic agent, believing that cooperation will bring better results.",
            "You are a pessimistic agent, tending to protect yourself and not trusting others much.",
        ]
        return random.choice(personalities)

    @staticmethod
    def _extract_custom_fields(profile: Any) -> dict[str, Any]:
        """从 profile 中提取 custom_fields"""
        if isinstance(profile, dict):
            return profile.get("custom_fields", {}) or {}
        else:
            custom_fields = getattr(profile, "custom_fields", {}) or {}
            if isinstance(custom_fields, dict):
                return custom_fields
            else:
                # 如果不是字典，尝试转换为字典
                return {"raw": str(custom_fields)}

    @staticmethod
    def _coerce_int(value: Any, default: int) -> int:
        """将值转换为整数，失败时返回默认值"""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _coerce_float(value: Any, default: float) -> float:
        """将值转换为浮点数，失败时返回默认值"""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    async def step(self, tick: int, t: datetime) -> str:
        """每个 tick 执行一次

        流程：
        1. 随机选择接受者
        2. 收集情境信息（声誉、收益、记忆）
        3. LLM 决策（合作/背叛）
        4. 执行捐赠
        5. 周期性学习
        """
        self._step_count += 1

        # 1. 随机选择接受者
        target_id = await self._select_recipient()

        # 2. 收集情境信息
        context_info = await self._gather_context(target_id)

        # 3. LLM 决策
        decision = await self._make_decision(context_info, target_id)

        # 4. 执行捐赠
        result = await self._execute_donation(target_id, decision)

        # 5. 周期性学习
        if self._step_count % self._learning_frequency == 0:
            await self._learn_from_top_agents()

        return result

    async def _get_population_size(self) -> int:
        """从环境获取种群大小 Z，并缓存结果"""
        if self._cached_Z is not None:
            return self._cached_Z

        # 从环境查询 Z 值
        try:
            ctx, _ans = await self.ask_env(
                {}, "Query the population size (Z) of the environment.", readonly=True
            )
            Z = ctx.get("population_size") or ctx.get("Z")
            if Z is not None:
                self._cached_Z = int(Z)
                return self._cached_Z
        except Exception:
            # Query failed; use default value
            import logging

            logging.getLogger(__name__).debug(
                "Failed to query population size", exc_info=True
            )

        # 如果查询失败，使用默认值（向后兼容）
        self._cached_Z = self.DEFAULT_POPULATION_SIZE
        return self._cached_Z

    async def _select_recipient(self) -> int:
        """选择接受者（随机选择）"""
        # 从环境获取 Z 值（带缓存）
        Z = await self._get_population_size()
        candidates = [i for i in range(Z) if i != self.id]
        if not candidates:
            # 如果只有自己，抛出异常而不是返回无效值
            raise ValueError(
                f"Agent {self.id}: No valid recipients available (population size: {Z})"
            )
        return random.choice(candidates)

    async def _query_agent_reputation(self, agent_id: int) -> str:
        """查询智能体的声誉"""
        ctx, _ = await self.ask_env(
            {"agent_id": agent_id},
            f"Query the current reputation of Agent {agent_id}. Use agent_id={agent_id} exactly.",
            readonly=True,
        )
        return ctx.get("reputation", "good")

    async def _query_agent_payoff(self, agent_id: int) -> float:
        """查询智能体的收益"""
        ctx, _ = await self.ask_env(
            {"agent_id": agent_id},
            f"Query the cumulative payoff of Agent {agent_id}. Use agent_id={agent_id} exactly.",
            readonly=True,
        )
        return self._coerce_float(ctx.get("payoff"), 0.0)

    async def _get_recent_memories(self) -> str:
        """获取最近的记忆摘要"""
        if not self._memory:
            return ""
        try:
            memories = await self._memory.get_all(user_id=self._memory_user_id)
            if isinstance(memories, dict):
                items = memories.get("memories", []) or memories.get("data", [])
                if items:
                    # 取最近N条记忆
                    recent_memories = (
                        items[-self.RECENT_MEMORIES_COUNT :]
                        if len(items) > self.RECENT_MEMORIES_COUNT
                        else items
                    )
                    return "\n".join(
                        [f"- {m.get('memory', '')}" for m in recent_memories]
                    )
        except Exception:
            # Memory query failed; continue without memory context
            import logging

            logging.getLogger(__name__).debug(
                "Failed to query recent memories", exc_info=True
            )
        return ""

    async def _gather_context(self, recipient_id: int) -> dict[str, Any]:
        """收集决策所需的情境信息（并行查询以提高效率）"""
        # 并行查询自己的声誉和收益，以及接受者的声誉
        my_rep_task = self._query_agent_reputation(self.id)
        my_payoff_task = self._query_agent_payoff(self.id)
        recipient_rep_task = self._query_agent_reputation(recipient_id)
        memory_task = self._get_recent_memories()

        # 等待所有查询完成
        my_rep, my_payoff, recipient_rep, memory_summary = await asyncio.gather(
            my_rep_task, my_payoff_task, recipient_rep_task, memory_task
        )

        return {
            "my_id": self.id,
            "my_reputation": my_rep,
            "my_payoff": my_payoff,
            "recipient_id": recipient_id,
            "recipient_reputation": recipient_rep,
            "memory_summary": memory_summary,
        }

    async def _make_decision(
        self, context_info: dict[str, Any], recipient_id: int
    ) -> str:
        """LLM 决策：合作或背叛（基于主观情绪和个性）"""

        # 根据当前收益和情绪状态更新情绪
        self._update_mood(context_info)

        # 构建情绪描述
        mood_description = self._get_mood_description()
        risk_description = self._get_risk_description()

        prompt = f"""You are an agent participating in a donation game.

{self._personality}

Current situation:
- Your ID: {context_info["my_id"]}
- Your current reputation: {context_info["my_reputation"]}
- Your cumulative payoff: {context_info["my_payoff"]:.2f}
- Recipient ID: {recipient_id}
- Recipient's reputation: {context_info["recipient_reputation"]}

Your subjective state:
- Current mood: {mood_description} (mood value: {self._mood:.2f}, range: -1.0 to 1.0)
- Risk preference: {risk_description} (risk tolerance: {self._risk_tolerance:.2f}, range: 0.0 to 1.0)

Historical memories:
{context_info["memory_summary"] if context_info["memory_summary"] else "(No memories yet)"}

Action options:
1. Cooperate: Pay cost c=1, recipient gains benefit b=5
2. Defect: Pay no cost, recipient gains no benefit

Important notes:
- Your decision should be influenced by your personality, current mood, and risk preference
- Don't always choose to cooperate, make authentic decisions based on your subjective feelings
- If you are in a negative mood or have low risk preference, you may tend to protect yourself (defect)
- If you are in a positive mood or have high risk preference, you may be more willing to try cooperation
- Consider the recipient's reputation: if the recipient has a bad reputation, you may be less willing to help them

Please make an authentic decision based on your personality, mood state, risk preference, and current situation.
Only return "cooperate" or "defect", do not return any other content.
"""

        response = await self.acompletion(
            [{"role": "user", "content": prompt}], stream=False
        )

        # 安全地提取响应内容
        if not response or not response.choices or not response.choices[0].message:
            # 如果响应无效，使用默认决策逻辑
            if (
                self._mood < self.MOOD_THRESHOLD_NEGATIVE
                or self._risk_tolerance < self.RISK_THRESHOLD_LOW
            ):
                decision = "defect"
            else:
                decision = "cooperate"
            decision_text = decision
        else:
            content = response.choices[0].message.content
            decision_text = (content or "").strip().lower()

        # 解析决策
        if "cooperate" in decision_text or "合作" in decision_text:
            decision = "cooperate"
        elif (
            "defect" in decision_text
            or "背叛" in decision_text
            or "拒绝" in decision_text
        ):
            decision = "defect"
        else:
            # 根据情绪和风险偏好决定默认行为，而不是总是合作
            # 如果情绪消极或风险容忍度低，默认背叛；否则默认合作
            if (
                self._mood < self.MOOD_THRESHOLD_NEGATIVE
                or self._risk_tolerance < self.RISK_THRESHOLD_LOW
            ):
                decision = "defect"
            else:
                decision = "cooperate"

        # 记录决策历史
        self._decision_history.append(
            {
                "step": self._step_count,
                "recipient_id": recipient_id,
                "decision": decision,
                "context": context_info,
                "mood": self._mood,
                "risk_tolerance": self._risk_tolerance,
            }
        )

        return decision

    def _update_mood(self, context_info: dict[str, Any]):
        """根据当前情境更新情绪状态"""
        # 如果收益较低，情绪可能变差
        my_payoff = context_info.get("my_payoff", 0.0)

        # 简单的情绪更新规则：
        # - 如果收益低于平均值，情绪可能变差
        # - 如果收益高于平均值，情绪可能变好
        # - 情绪会逐渐回归到中性（0.0）

        # 情绪衰减（逐渐回归中性）
        self._mood *= self.MOOD_DECAY_RATE

        # 根据收益调整情绪（假设平均收益约为 0）
        if my_payoff < self.PAYOFF_THRESHOLD_LOW:
            self._mood -= self.MOOD_ADJUSTMENT_STEP
        elif my_payoff > self.PAYOFF_THRESHOLD_HIGH:
            self._mood += self.MOOD_ADJUSTMENT_STEP

        # 限制情绪范围
        self._mood = max(-1.0, min(1.0, self._mood))

    def _get_mood_description(self) -> str:
        """获取情绪的文字描述"""
        if self._mood > 0.5:
            return "very positive and optimistic"
        elif self._mood > 0.2:
            return "positive and optimistic"
        elif self._mood > -0.2:
            return "neutral, emotionally stable"
        elif self._mood > -0.5:
            return "negative and pessimistic"
        else:
            return "very negative and pessimistic"

    def _get_risk_description(self) -> str:
        """获取风险偏好的文字描述"""
        if self._risk_tolerance > 0.7:
            return "high risk preference, willing to take risks"
        elif self._risk_tolerance > 0.4:
            return "moderate risk preference"
        else:
            return "low risk preference, tending to be conservative"

    async def _execute_donation(self, recipient_id: int, decision: str) -> str:
        """执行捐赠决策"""
        ctx = {
            "donor_id": self.id,
            "recipient_id": recipient_id,
            "action": decision,
        }
        message = (
            f"Execute donation: I am the donor with ID={self.id}, "
            f"the recipient is Agent {recipient_id}, "
            f"my decision is {decision}. "
            f"Use donor_id={self.id} and recipient_id={recipient_id} exactly."
        )

        _ctx2, ans = await self.ask_env(ctx, message, readonly=False)

        # 保存记忆
        if self._memory:
            try:
                action_text = "cooperated" if decision == "cooperate" else "defected"
                await self._memory.add(
                    f"At step {self._step_count}, I {action_text} with Agent {recipient_id}. "
                    f"Result: {ans}",
                    user_id=self._memory_user_id,
                )
            except Exception:
                # Memory save failure is non-critical; continue without persisting
                import logging

                logging.getLogger(__name__).debug(
                    "Failed to save memory", exc_info=True
                )

        return ans

    async def _learn_from_top_agents(self):
        """从顶尖智能体学习"""
        # 查询顶尖智能体
        ctx, ans = await self.ask_env(
            {"top_k": self.TOP_AGENTS_COUNT},
            f"Query the summary of top {self.TOP_AGENTS_COUNT} agents by payoff, including their reputation and recent actions. Use top_k={self.TOP_AGENTS_COUNT}.",
            readonly=True,
        )

        top_agents = ctx.get("top_agents", [])
        if not top_agents:
            return

        # LLM 分析成功模式
        analysis_prompt = f"""Analyze the common characteristics of the following top-performing agents:

{ans}

Please summarize their success patterns and provide suggestions: How should I adjust my strategy?
"""

        try:
            analysis_response = await self.acompletion(
                [{"role": "user", "content": analysis_prompt}], stream=False
            )

            # 安全地提取分析内容
            if (
                analysis_response
                and analysis_response.choices
                and analysis_response.choices[0].message
            ):
                analysis = analysis_response.choices[0].message.content or ""
            else:
                analysis = "Failed to analyze top agents' patterns."

            # 保存学习结果到记忆
            if self._memory:
                try:
                    await self._memory.add(
                        f"Learned success patterns: {analysis}",
                        user_id=self._memory_user_id,
                    )
                except Exception:
                    import logging

                    logging.getLogger(__name__).debug(
                        "Failed to add memory entry", exc_info=True
                    )
        except Exception:
            # Learning failure is non-critical; continue without learning
            import logging

            logging.getLogger(__name__).debug(
                "Learning from top agents failed", exc_info=True
            )

    async def ask(self, message: str, readonly: bool = True) -> str:
        """用 LLM(可选地结合记忆)回答一个问题。

        :param message: 要回答的问题。
        :param readonly: 是否只读操作(默认 True)。
        :returns: 字符串形式的回答。
        """
        # Try to get relevant memories if available
        memory_context = ""
        if self._memory:
            try:
                results = await self._memory.search(
                    message, user_id=self._memory_user_id, limit=3
                )
                if results and "results" in results:
                    memory_items = []
                    for result in results["results"][:3]:
                        memory_items.append(f"- {result.get('memory', '')}")
                    if memory_items:
                        memory_context = "\n".join(memory_items)
            except Exception:
                import logging

                logging.getLogger(__name__).debug(
                    "Failed to retrieve memory context", exc_info=True
                )

        # Build prompt with memory context
        if memory_context:
            prompt = f"""You are an LLM Donor Agent participating in a reputation game.

Relevant memories:
{memory_context}

Question: {message}

Please answer the question based on your knowledge and memories."""
        else:
            prompt = f"""You are an LLM Donor Agent participating in a reputation game.

Question: {message}

Please answer the question."""

        try:
            response = await self.acompletion(
                [{"role": "user", "content": prompt}], stream=False
            )

            # 安全地提取响应内容
            if (
                response
                and response.choices
                and response.choices[0].message
                and response.choices[0].message.content
            ):
                return str(response.choices[0].message.content)
            else:
                return "I'm sorry, I couldn't generate a response."
        except Exception as e:
            return f"I encountered an error while processing your question: {e!s}"

    async def close(self):
        """清理资源"""
        return
