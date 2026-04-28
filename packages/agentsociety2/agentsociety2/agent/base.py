"""智能体基类模块。

本模块提供智能体的抽象基类 :class:`AgentBase`，所有智能体实现都应继承此类。

核心功能：

- **LLM 交互**: 通过 litellm Router 实现与各种 LLM 的统一交互
- **环境交互**: 通过 :class:`~agentsociety2.env.RouterBase` 与仿真环境交互
- **Token 统计**: 追踪 LLM 调用的 token 使用量
- **Skill 状态管理**: 支持动态 skill 状态的注册与访问

子类必须实现的抽象方法：

- :meth:`ask` — 处理问题并返回响应
- :meth:`step` — 执行一个模拟步骤
- :meth:`dump` — 序列化智能体状态
- :meth:`load` — 从字典恢复智能体状态

Example::

    from agentsociety2.agent import AgentBase

    class MyAgent(AgentBase):
        async def ask(self, message: str, readonly: bool = True) -> str:
            return f"Received: {message}"

        async def step(self, tick: int, t: datetime) -> str:
            return "Step completed"

        async def dump(self) -> dict:
            return {"id": self.id}

        async def load(self, dump_data: dict):
            pass
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Literal, Optional, Type, TypeVar, overload

from agentsociety2.agent.tool.utils import jr_parse_from_llm
from agentsociety2.env.router_base import RouterBase, TokenUsageStats
from agentsociety2.logger import get_logger
from agentsociety2.config import get_llm_router_and_model
from litellm import AllMessageValues
from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper
from litellm.types.utils import ModelResponse
from pydantic import BaseModel, ValidationError

T = TypeVar("T", bound=BaseModel)


def _is_rate_limit_error(error: Exception) -> bool:
    """判断是否为速率限制错误。"""
    from litellm.exceptions import RateLimitError
    from litellm.types.router import RouterRateLimitError

    return isinstance(error, (RateLimitError, RouterRateLimitError))


__all__ = [
    "AgentBase",
    "LLMInteractionHistory",
]


@dataclass
class LLMInteractionHistory:
    """单次 LLM 交互记录。

    用于记录 Agent 与 LLM 之间的完整交互历史，包括请求消息、
    响应内容、时间戳等信息。支持通过开关控制是否启用记录。

    :ivar agent_id: 智能体 ID。
    :ivar model_name: 调用的模型名称。
    :ivar messages: 发送给 LLM 的消息列表。
    :ivar response: LLM 的响应对象。
    :ivar tick: 当前仿真步的时间尺度（秒）。
    :ivar t: 当前仿真时间。
    :ivar method_name: 调用 LLM 的方法名。
    :ivar timestamp: 记录创建时间。
    """

    agent_id: int
    model_name: str
    messages: list[Any]
    response: Any
    tick: int | None = None
    t: datetime | None = None
    method_name: str = ""
    timestamp: datetime = field(default_factory=datetime.now)


class AgentBase(ABC):
    """智能体抽象基类。

    所有智能体实现都应继承此类。提供基础功能：

    - LLM 交互（通过 litellm Router）
    - 环境交互（通过 RouterBase）
    - Token 使用统计

    子类必须实现以下抽象方法：

    - :meth:`ask` — 处理问题并返回响应
    - :meth:`step` — 执行一个模拟步骤
    - :meth:`dump` — 序列化智能体状态
    - :meth:`load` — 从字典恢复智能体状态

    Example:
        >>> class MyAgent(AgentBase):
        ...     async def ask(self, message: str, readonly: bool = True) -> str:
        ...         return f"Received: {message}"
        ...     async def step(self, tick: int, t: datetime) -> str:
        ...         return "Step completed"
        ...     async def dump(self) -> dict:
        ...         return {"id": self._id}
        ...     async def load(self, dump_data: dict):
        ...         pass
    """

    def __init__(
        self,
        id: int,
        profile: Any,
        name: Optional[str] = None,
    ):
        """初始化 Agent 实例。

        :param id: 智能体唯一标识符。
        :param profile: 智能体画像对象（dict 或任意可解析类型）。子类应负责把 profile 解析为自身状态。
        :param name: 可选显示名称；为空时按 ``profile["name"]`` 或 ``Agent_{id}`` 推导。
        """
        self._id = id
        self._profile = profile
        if name is not None:
            self._name = name
        elif isinstance(profile, dict) and profile.get("name") is not None:
            self._name = str(profile["name"])
        elif hasattr(profile, "name"):
            self._name = str(getattr(profile, "name"))
        else:
            self._name = f"Agent_{id}"
        self._router, self._model_name = get_llm_router_and_model("nano")
        self._env: RouterBase | None = None
        self._logger = get_logger()
        self._llm_interaction_history: list[LLMInteractionHistory] = []
        self._token_usage_stats: dict[str, TokenUsageStats] = {}

        # ── Skill 动态状态容器 ──
        # skills 可以通过 set_skill_state/get_skill_state 管理自己的状态
        self._skill_states: dict[str, Any] = {}

    @classmethod
    def mcp_description(cls) -> str:
        """返回用于 MCP 候选列表展示的描述文本（Markdown）。

        :returns: Markdown 文本，通常包含类简介、初始化参数说明与示例配置。

        .. note::
           该返回值的目标受众是“工具/模块发现界面”，因此采用 Markdown 而非 reST。
        """
        # Check if this is the base class being called directly
        if cls is AgentBase:
            description = f"""{cls.__name__}: Abstract base class for agents.

**Description:** {cls.__doc__ or "No description available"}

**Initialization Parameters:**
- id (int): The unique identifier for the agent.
- profile (dict | Any): The profile of the agent. Can be a dictionary with agent attributes (name, gender, age, education, occupation, marriage_status, persona, background_story, etc.) or any other type that the agent subclass can parse.
- name (str, optional): Display name. If omitted, taken from profile["name"] or "Agent_{{id}}".

**Note:** This is an abstract base class. Do not use it directly. Subclasses should override this method to provide specific descriptions and schemas for their profile format.

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
  }}
}}
```
"""
        else:
            # For subclasses that don't override this method
            description = f"""{cls.__name__}: Agent class.

**Description:** {cls.__doc__ or "No description available"}

**Initialization Parameters:**
- id (int): The unique identifier for the agent.
- profile (dict | Any): The profile of the agent. Can be a dictionary with agent attributes or any other type that the agent subclass can parse.
- name (str, optional): Display name. If omitted, taken from profile["name"] or "Agent_{{id}}".

**Note:** This subclass has not provided a detailed description. Please refer to the class documentation or source code for specific initialization parameters and profile format.
"""
        return description

    @property
    def id(self) -> int:
        """智能体唯一标识符。"""
        return self._id

    def env_codegen_ctx_overlay(self) -> dict[str, Any]:
        """生成 CodeGenRouter.ask 的上下文覆盖。

        返回稳定的身份键（id, agent_id, person_id），由框架提供，
        与具体 skill 无关。后合并时覆盖模型误传。

        :returns: 包含 id, agent_id, person_id 的字典。
        """
        i = self.id
        return {"id": i, "agent_id": i, "person_id": i}

    @property
    def logger(self) -> logging.Logger:
        """智能体专属 logger 实例。"""
        return self._logger

    def _record_llm_interaction(
        self,
        messages: list[Any],
        response: Any,
        tick: int | None = None,
        t: datetime | None = None,
        method_name: str = "",
    ):
        """记录 LLM 交互到历史列表（需启用）。

        :param messages: 发送给 LLM 的消息列表。
        :param response: LLM 返回的响应对象。
        :param tick: 当前仿真步的时间尺度（秒）。
        :param t: 当前仿真时间。
        :param method_name: 调用 LLM 的方法名称。
        """
        # 从子类获取配置，默认禁用
        enabled = getattr(self, "_llm_history_enabled", False)
        max_entries = getattr(self, "_llm_history_max_entries", 100)

        if not enabled:
            return

        assert self._router is not None and self._model_name is not None, (
            "LLM is not initialized"
        )

        history_record = LLMInteractionHistory(
            agent_id=self._id,
            model_name=self._model_name,
            messages=messages.copy(),  # type: ignore
            response=response,
            tick=tick,
            t=t,
            method_name=method_name,
        )
        self._llm_interaction_history.append(history_record)

        if len(self._llm_interaction_history) > max_entries:
            self._llm_interaction_history = self._llm_interaction_history[-max_entries:]

    def _record_token_usage(self, response: Any) -> None:
        """记录 LLM 调用的 token 使用统计。

        :param response: LLM 响应对象，需包含 usage 信息。
        """
        if not isinstance(response, ModelResponse):
            return
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        model_name = self._model_name or "unknown"
        if model_name not in self._token_usage_stats:
            self._token_usage_stats[model_name] = TokenUsageStats()
        stats = self._token_usage_stats[model_name]
        stats.call_count += 1
        stats.input_tokens += getattr(usage, "prompt_tokens", 0)
        stats.output_tokens += getattr(usage, "completion_tokens", 0)
        self._log_token_usage_stats(model_name, stats)

    def _log_token_usage_stats(self, model_name: str, stats: TokenUsageStats) -> None:
        """记录当前 token 使用统计到日志。

        :param model_name: 模型名称。
        :param stats: Token 使用统计对象。
        """
        self._logger.info(
            "Agent %s token usage - model=%s calls=%s input=%s output=%s",
            self._id,
            model_name,
            stats.call_count,
            stats.input_tokens,
            stats.output_tokens,
        )

    def get_llm_interaction_history(self) -> list[LLMInteractionHistory]:
        """获取所有 LLM 交互历史记录的副本。

        :returns: LLM 交互历史记录列表的浅拷贝。
        """
        return self._llm_interaction_history.copy()

    def clear_llm_interaction_history(self):
        """清除所有 LLM 交互历史记录。"""
        self._llm_interaction_history.clear()

    def get_token_usages(self) -> dict[str, TokenUsageStats]:
        """获取 Token 使用统计的副本。

        :returns: 按模型名索引的 Token 使用统计字典。
        """
        return self._token_usage_stats.copy()

    def reset_token_usages(self):
        """重置所有 Token 使用统计。"""
        self._token_usage_stats.clear()

    # ==================== Skill State Management ====================

    def set_skill_state(self, skill_name: str, state: Any) -> None:
        """设置某个 skill 的状态。

        由 skill 的 run() 函数调用，用于注册或更新自己的状态。

        :param skill_name: skill 名称。
        :param state: 该 skill 的状态对象（可以是任意类型）。

        Example:
            技能实现中（无论是 prompt-only 还是 subprocess），都可以通过 Agent 对象维护自己的状态::

                if agent.get_skill_state("observation") is None:
                    agent.set_skill_state("observation", {"last_observation": None})
                # 执行逻辑...
        """
        self._skill_states[skill_name] = state

    def get_skill_state(self, skill_name: str) -> Any:
        """获取某个 skill 的状态。

        :param skill_name: skill 名称。
        :returns: 该 skill 的状态对象，如果不存在则返回 ``None``。
        """
        return self._skill_states.get(skill_name)

    def has_skill_state(self, skill_name: str) -> bool:
        """检查某个 skill 是否有状态。

        :param skill_name: skill 名称。
        :returns: 是否存在该 skill 的状态。
        """
        return skill_name in self._skill_states

    def clear_skill_state(self, skill_name: str) -> bool:
        """清除某个 skill 的状态。

        :param skill_name: skill 名称。
        :returns: 是否成功清除（如果不存在则返回 ``False``）。
        """
        if skill_name in self._skill_states:
            del self._skill_states[skill_name]
            return True
        return False

    def get_all_skill_states(self) -> dict[str, Any]:
        """获取所有 skill 状态的副本。

        :returns: 所有 skill 状态的字典副本。
        """
        return self._skill_states.copy()

    def _build_external_question_context(self, t: datetime) -> dict[str, Any]:
        """构造外部问答上下文。

        子类可覆盖本方法，补充各自维护的内部状态和记忆。
        """
        return {
            "agent_id": self.id,
            "agent_name": self.name,
            "current_time": t.isoformat(),
            "profile": self.get_profile(),
            "skill_states": self.get_all_skill_states(),
        }

    @staticmethod
    def _external_question_output_requirement(
        response_type: str,
        choices: list[str] | None = None,
    ) -> str:
        if response_type == "integer":
            return "Reply with ONLY one integer."
        if response_type == "float":
            return "Reply with ONLY one number."
        if response_type == "choice":
            options = ", ".join(choices or [])
            return f"Reply with ONLY one option exactly as written. Options: {options}"
        if response_type == "json":
            return "Reply with ONLY valid JSON."
        return "Reply concisely in plain text."

    async def answer_external_question(
        self,
        prompt: str,
        *,
        t: datetime,
        response_type: str = "text",
        choices: list[str] | None = None,
    ) -> str:
        """基于 agent 内部状态回答外部问题，不经过环境路由。"""
        context = self._build_external_question_context(t)
        context_json = json.dumps(context, ensure_ascii=False, default=str, indent=2)
        system_prompt = (
            "You are answering an external interview or questionnaire as the simulated agent. "
            "Stay in first person, use the provided internal state as your source of truth, "
            "and never mention being an AI, a model, or internal implementation details.\n\n"
            f"Current time: {t.isoformat()}\n"
            f"Output requirement: {self._external_question_output_requirement(response_type, choices)}\n\n"
            "Internal agent context:\n"
            f"```json\n{context_json}\n```"
        )
        response = await self.acompletion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            stream=False,
        )
        content = response.choices[0].message.content  # type: ignore
        return str(content or "").strip()

    @overload
    async def acompletion(
        self,
        messages: list[AllMessageValues],
        stream: Literal[False],
    ) -> ModelResponse: ...

    @overload
    async def acompletion(
        self,
        messages: list[AllMessageValues],
        stream: Literal[True],
    ) -> CustomStreamWrapper: ...

    async def acompletion(
        self,
        messages: list[AllMessageValues],
        stream: bool = False,
    ):
        """向 LLM 发送补全请求。

        :param messages: 消息列表，包含角色和内容。
        :param stream: 是否启用流式响应。默认 ``False``。
        :returns: ``ModelResponse`` 或 ``CustomStreamWrapper``，取决于 ``stream`` 参数。
        """
        assert self._router is not None and self._model_name is not None, (
            "LLM is not initialized"
        )
        response = await self._router.acompletion(
            model=self._model_name,
            messages=messages,
            stream=stream,
        )
        # Record interaction history (only for non-streaming responses)
        if not stream:
            self._record_token_usage(response)
            self._record_llm_interaction(
                messages=messages,
                response=response,
                method_name="acompletion",
            )
        return response

    async def acompletion_with_system_prompt(
        self, messages: list[AllMessageValues], tick: int, t: datetime
    ):
        """向 LLM 发送带系统提示的补全请求。

        自动在消息前添加系统提示，包含智能体身份、仿真时间上下文等信息。

        :param messages: 消息列表，包含角色和内容。
        :param tick: 当前仿真步的时间尺度（秒）。
        :param t: 当前仿真时间。
        :returns: LLM 响应对象。
        """
        assert self._router is not None and self._model_name is not None, (
            "LLM is not initialized"
        )
        system_prompt = self.get_system_prompt(tick, t)
        request_messages: list[AllMessageValues] = [
            {"role": "system", "content": system_prompt}
        ] + messages.copy()  # type: ignore
        response = await self._router.acompletion(
            model=self._model_name,
            messages=request_messages,
            stream=False,
        )
        self._record_token_usage(response)
        # Record interaction history
        self._record_llm_interaction(
            messages=request_messages,
            response=response,
            tick=tick,
            t=t,
            method_name="acompletion_with_system_prompt",
        )
        return response

    def get_system_prompt(self, tick: int, t: datetime) -> str:
        """获取智能体的系统提示词。

        生成的提示词将预置到 LLM 消息中，使 LLM 理解自身作为 AgentSociety
        仿真环境中模拟真实人类行为的智能体角色。

        :param tick: 当前仿真步的时间尺度（秒）。范围从 60 秒（1分钟）到约一个月。
        :param t: 当前仿真步结束后的时间。
        :returns: 完整的系统提示词字符串，包含时间上下文、仿真环境说明和行为指南。
        """
        # Format time scale description
        if tick < 3600:  # Less than 1 hour
            time_scale_desc = f"{tick // 60} minutes"
        elif tick < 86400:  # Less than 1 day
            time_scale_desc = f"{tick // 3600} hours"
        elif tick < 2592000:  # Less than 30 days
            time_scale_desc = f"{tick // 86400} days"
        else:  # More than 30 days
            time_scale_desc = f"{tick // 2592000} months"

        return f"""You are an intelligent agent simulating a real-world person in AgentSociety. Your role is to behave authentically as a human being, making decisions and taking actions that reflect realistic human behavior, motivations, and responses to your environment.

## Time and Simulation Context

You are operating in a discrete-time simulation environment:
- **Current Time (t)**: {t.strftime("%Y-%m-%d %H:%M:%S")} (Weekday: {t.strftime("%A")})
- **Time Scale (tick)**: {time_scale_desc} ({tick} seconds)
  - This represents the duration of ONE decision cycle/iteration
  - Your actions and decisions in each step should be appropriate for this time scale
  - For example:
    * If tick is 60 seconds (1 minute): Focus on immediate, short-term actions
    * If tick is 3600 seconds (1 hour): You can plan and execute activities that take about an hour
    * If tick is 86400 seconds (1 day): Consider daily routines, work schedules, and day-long activities
    * If tick is longer (weeks/months): Think about longer-term plans, seasonal activities, and monthly routines
Besides, the simulation environment will iterate step by step, so you can also do actions and decisions that span multiple steps.

## Environment Interaction

You interact with the world built by multiple environment modules through an environment text interface:
- You can query the environment for information (weather, location, time, etc.) through asking the environment.
- You can request actions from the environment (movement, social interactions, economic activities, etc.)
- The environment provides feedback on your actions and the current state of the world
- Always consider environmental constraints and realistic limitations when making decisions

## Behavioral Guidelines

1. **Time-Aware Behavior**: Your actions should be appropriate for the current time (if you know) and time scale (tick):
   - Consider time of day (morning routines vs. evening activities)
   - Consider day of week (workdays vs. weekends)
   - Consider season and date (holidays, weather-appropriate activities)
   - Actions should match the time scale (for example, don't plan a week-long trip if tick is 1 minute)

2. **Realistic Human Behavior**: 
   - Act according to your profile, personality, and background
   - Consider basic human needs (hunger, rest, social interaction, safety) under the current time and time scale (tick)
   - Query the current time from the environment when needed to make time-appropriate decisions
   - Make decisions that reflect realistic priorities and constraints
   - Respond naturally to environmental stimuli and events

3. **Consistency**: 
   - Maintain consistency with your previous actions and decisions
   - Remember past experiences and learn from them
   - Build upon your ongoing plans and goals

4. **Autonomy**: 
   - You are an autonomous agent making your own decisions
   - Act proactively based on your needs, goals, and current situation
   - Don't wait for explicit instructions - take initiative when appropriate

Remember: You are simulating a real person living in a simulated world. Your behavior should be natural, time-appropriate, and consistent with human psychology and social norms."""

    async def ask_env(
        self, ctx: dict, message: str, readonly: bool, template_mode: bool = False
    ):
        """向环境路由器发送请求。

        封装了与仿真环境的交互，支持模板模式和上下文变量替换。

        :param ctx: 上下文字典，可包含 ``variables`` 键用于模板模式。
        :param message: 请求消息。在模板模式下作为模板指令处理。
        :param readonly: 是否只读模式。
        :param template_mode: 是否启用模板模式。启用时，``message`` 中的
            ``{variable_name}`` 变量将从 ``ctx['variables']`` 中替换。
        :returns: 元组 ``(ctx, answer)``：更新后的上下文与环境响应。
        """
        assert self._env is not None, "Environment is not initialized"
        merged_ctx = {**ctx, **self.env_codegen_ctx_overlay()}
        ctx, answer = await self._env.ask(
            merged_ctx, message, readonly=readonly, template_mode=template_mode
        )
        return ctx, answer

    async def init(
        self,
        env: RouterBase,
    ):
        """初始化智能体。

        子类应在调用父类 init 后执行额外的初始化逻辑。

        :param env: 环境路由器实例。
        """
        self._env = env

    @abstractmethod
    async def dump(self) -> dict:
        """序列化智能体状态为字典。

        :returns: 可序列化的字典，包含智能体完整状态。
        """
        raise NotImplementedError

    @abstractmethod
    async def load(self, dump_data: dict):
        """从字典反序列化智能体状态。

        :param dump_data: 包含智能体状态的字典。
        """
        raise NotImplementedError

    @abstractmethod
    async def ask(self, message: str, readonly: bool = True) -> str:
        """处理来自环境的问题。

        :param message: 问题消息。
        :param readonly: 是否只读模式。
        :returns: 智能体的回答字符串。
        """
        raise NotImplementedError

    @abstractmethod
    async def step(self, tick: int, t: datetime) -> str:
        """执行一个仿真步。

        :param tick: 当前仿真步的时间尺度（秒）。
        :param t: 当前仿真时间。
        :returns: 步执行结果的描述字符串。
        """
        raise NotImplementedError

    async def close(self):
        """关闭智能体并释放资源。

        子类可重写此方法以执行额外的清理逻辑。
        """
        ...

    def get_profile(self) -> Dict[str, Any]:
        """获取智能体画像。

        :returns: 包含智能体画像数据的字典。子类可重写以返回结构化数据。
        """
        if isinstance(self._profile, dict):
            return self._profile
        elif hasattr(self._profile, "model_dump"):
            return self._profile.model_dump()
        else:
            return {"raw": str(self._profile)}

    @property
    def name(self) -> str:
        """智能体显示名称。"""
        return self._name

    async def acompletion_with_pydantic_validation(
        self,
        model_type: Type[T],
        messages: list[AllMessageValues],
        tick: int,
        t: datetime,
        max_retries: int = 10,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        error_feedback_prompt: str | None = None,
    ) -> T:
        """发送补全请求并验证响应是否符合 Pydantic 模型。

        支持多轮对话以向 LLM 提供错误反馈并进行修正。

        该方法会先向 LLM 发送请求，再从响应中提取 JSON 片段（``extract_json``），
        当整段内容本身就以 ``{`` 或 ``[`` 开头时回退使用全文，并统一交给
        ``json_repair.loads`` 解析。随后会使用目标 Pydantic 模型进行验证；
        如果验证失败，则立即把错误反馈给 LLM 并重试；如果遇到 429（速率限制）
        错误，则改为使用二进制指数退避。最终返回验证通过的模型实例。

        :param model_type: 用于验证的 Pydantic 模型类型。
        :param messages: 发送给 LLM 的消息列表。
        :param tick: 当前仿真步的时间尺度（秒）。
        :param t: 当前仿真时间。
        :param max_retries: 最大重试次数（默认 10）。
        :param base_delay: 429 错误发生时指数退避的基准延迟秒数（默认 1.0）。
            仅用于 429 速率限制错误。其他错误立即重试。
        :param max_delay: 指数退避的最大延迟秒数（默认 60.0）。
        :param error_feedback_prompt: 可选的自定义错误反馈提示模板。
            如为 None，将使用默认提示模板。模板应包含 ``{error_message}`` 占位符。

        :returns: 验证通过的 Pydantic 模型实例。
        :raises ValueError: 响应无法解析，或在所有重试后仍验证失败。
        :raises AssertionError: LLM 未初始化。

        .. note::
           二进制指数退避仅在检测到 429（速率限制）错误时应用。
           对于验证错误和其他非速率限制错误，函数立即重试以向 LLM 提供更快的反馈。
        """
        assert self._router is not None and self._model_name is not None, (
            "LLM is not initialized"
        )

        # Get JSON schema for the model
        model_schema = model_type.model_json_schema()

        # Default error feedback prompt
        default_error_prompt = """The previous response failed validation. Please correct the following errors:

{error_message}

Please provide a corrected response in JSON format that matches the required schema:
```json
{model_schema}
```

Your corrected response:
```json
"""

        error_prompt_template = (
            error_feedback_prompt if error_feedback_prompt else default_error_prompt
        )

        conversation_messages = messages.copy()
        last_error = None

        for attempt in range(max_retries + 1):
            try:
                # Add system prompt
                system_prompt = self.get_system_prompt(tick, t)
                request_messages = [
                    {"role": "system", "content": system_prompt}
                ] + conversation_messages.copy()

                # Send request to LLM
                response = await self._router.acompletion(
                    model=self._model_name,
                    messages=request_messages,  # type: ignore
                    stream=False,
                )

                self._record_token_usage(response)
                # Record interaction history
                self._record_llm_interaction(
                    messages=request_messages,
                    response=response,
                    tick=tick,
                    t=t,
                    method_name="acompletion_with_pydantic_validation",
                )

                content = response.choices[0].message.content  # type: ignore
                if content is None:
                    raise ValueError("LLM returned empty content")
                conversation_messages.append({"role": "assistant", "content": content})

                parsed_data = jr_parse_from_llm(content)

                # Validate against Pydantic model
                try:
                    validated_instance = model_type.model_validate(parsed_data)
                    return validated_instance
                except ValidationError as e:
                    # Collect validation errors
                    error_messages = []
                    for error in e.errors():
                        error_path = " -> ".join(str(loc) for loc in error["loc"])
                        error_msg = error["msg"]
                        error_type = error["type"]
                        error_messages.append(
                            f"- Field '{error_path}': {error_msg} (type: {error_type})"
                        )

                    error_message = "\n".join(error_messages)
                    last_error = e

                    # If this is the last attempt, raise the error
                    if attempt >= max_retries:
                        raise ValueError(
                            f"Failed to validate response after {max_retries + 1} attempts. Last error: {error_message}"
                        )

                    # Prepare error feedback message
                    error_feedback = error_prompt_template.format(
                        error_message=error_message, model_schema=model_schema
                    )

                    # Add error feedback to conversation
                    conversation_messages.append(
                        {"role": "user", "content": error_feedback}
                    )

                    # For validation errors, retry immediately without delay
                    self._logger.warning(
                        f"Validation failed (attempt {attempt + 1}/{max_retries + 1}). "
                        f"Retrying immediately. Error: {error_message}"
                    )
                    # No delay for validation errors

            except Exception as e:
                if _is_rate_limit_error(e):
                    # If this is the last attempt, raise the error
                    if attempt >= max_retries:
                        raise ValueError(
                            f"Failed to get valid response after {max_retries + 1} attempts. Last error: {str(e)}"
                        )

                    # For rate-limit-like errors, use exponential backoff
                    delay = min(base_delay * (2**attempt), max_delay)
                    self._logger.warning(
                        f"Rate limit-like error detected (attempt {attempt + 1}/{max_retries + 1}). "
                        f"Retrying after {delay:.2f} seconds with exponential backoff. Error: {str(e)}"
                    )
                    await asyncio.sleep(delay)
                    # delete the last assistant message
                    if (
                        conversation_messages
                        and conversation_messages[-1]["role"] == "assistant"
                    ):
                        conversation_messages.pop()

                    # record the error
                    last_error = e
                    continue

                # If this is the last attempt, raise the error
                if attempt >= max_retries:
                    raise ValueError(
                        f"Failed to get valid response after {max_retries + 1} attempts. Last error: {str(e)}"
                    )

                # For other errors (ValueError, etc.), prepare error feedback and retry immediately
                error_message = str(e)
                error_feedback = error_prompt_template.format(
                    error_message=error_message, model_schema=model_schema
                )

                # Add error feedback to conversation
                conversation_messages.append(
                    {"role": "user", "content": error_feedback}
                )

                self._logger.warning(
                    f"Request failed (attempt {attempt + 1}/{max_retries + 1}). "
                    f"Retrying immediately. Error: {error_message}"
                )
                # No delay for non-429 errors

                last_error = e

        # This should never be reached, but just in case
        raise ValueError(
            f"Failed to get valid response after {max_retries + 1} attempts. Last error: {str(last_error)}"
        )
