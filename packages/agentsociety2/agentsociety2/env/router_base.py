"""环境路由器基类模块。

本模块提供环境路由器的抽象基类 :class:`RouterBase`，用于协调智能体与环境模块之间的交互。

路由器负责：

- **请求路由**: 将智能体的请求路由到合适的环境模块
- **工具管理**: 收集和过滤环境模块提供的工具
- **LLM 调用**: 提供统一的 LLM 调用接口，支持重试和速率限制处理
- **状态管理**: 管理仿真时间和 token 使用统计

内置路由器实现：

- :class:`~agentsociety2.env.ReActRouter` — ReAct 模式的路由器
- :class:`~agentsociety2.env.PlanExecuteRouter` — 计划执行模式路由器
- :class:`~agentsociety2.env.CodeGenRouter` — 代码生成模式路由器
- :class:`~agentsociety2.env.TwoTierReActRouter` / :class:`~agentsociety2.env.TwoTierPlanExecuteRouter` — 两层路由
- :class:`~agentsociety2.env.SearchToolRouter` — 带搜索工具的路由

Example::

    from agentsociety2.env import ReActRouter

    router = ReActRouter(env_modules=[env1, env2])
    await router.init(start_datetime)

    ctx: dict = {}
    ctx, answer = await router.ask(ctx, "查询天气信息", readonly=True)
"""

import asyncio
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Literal,
    Optional,
    TypeVar,
    overload,
)

if TYPE_CHECKING:
    from agentsociety2.storage import ReplayWriter

import black
import json_repair
import yaml
from litellm import AllMessageValues
from litellm.litellm_core_utils.streaming_handler import CustomStreamWrapper
from litellm.types.utils import ModelResponse
from pydantic import BaseModel, ValidationError

from agentsociety2.config import (
    Config,
    LLMDispatchError,
    extract_json,
    get_model_name,
)
from agentsociety2.env.base import EnvBase
from agentsociety2.env.function_parser import FunctionParser, FunctionParts
from agentsociety2.env.pydantic_collector import PydanticModelCollector
from agentsociety2.logger import get_logger

T = TypeVar("T", bound=BaseModel)


def _env_skill_catalog_row(skill_md: Path, *, module_name: str) -> str:
    """Return one Markdown table row for an environment-provided skill."""
    try:
        raw = skill_md.read_text(encoding="utf-8")
    except OSError:
        return ""
    meta: dict[str, Any] = {}
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) >= 3:
            loaded = yaml.safe_load(parts[1]) or {}
            meta = loaded if isinstance(loaded, dict) else {}
    name = str(meta.get("name") or skill_md.parent.name).strip()
    description = str(meta.get("description") or "").strip() or "No description."

    def cell(value: Any) -> str:
        return str(value or "-").replace("\n", " ").replace("|", "\\|").strip()

    return f"| {cell(name)} | {cell(module_name)} | {cell(description)} |"


def _empty_env_skill_catalog() -> str:
    """Return an empty Markdown table for environment skill catalog prompts."""
    return "| name | env_module | description |\n| --- | --- | --- |\n| - | - | No environment skills were declared by modules. |"


class TokenUsageStats(BaseModel):
    """
    Token usage statistics for a model.

    :ivar call_count: Number of API calls made.
    :ivar input_tokens: Total number of input tokens consumed.
    :ivar output_tokens: Total number of output tokens consumed.
    :ivar cached_input_tokens: Input tokens served from the provider's
        prompt-prefix cache (a subset of ``input_tokens``).
    """

    call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0

    @property
    def cache_hit_rate(self) -> float:
        """Return ``cached_input_tokens / input_tokens``, clamped to ``[0, 1]``."""
        if self.input_tokens <= 0:
            return 0.0
        return max(0.0, min(1.0, self.cached_input_tokens / self.input_tokens))


class FinalAnswerResponse(BaseModel):
    """
    Pydantic model for LLM final answer response.

    :ivar status: Execution status (success, in_progress, fail, error).
    :ivar summary: Summary of what was accomplished or what went wrong.
    """

    status: Literal["success", "in_progress", "fail", "error"]
    summary: str


class ToolInfo(BaseModel):
    """
    Pydantic model for tool information.

    :ivar function_parts: Parsed function parts (signature, docstring, etc.).
    :ivar name: Tool name.
    :ivar description: Tool description.
    :ivar readonly: Whether the tool is readonly.
    :ivar kind: Tool kind (None, "observe", or "statistics").
    """

    function_parts: FunctionParts
    name: str
    description: str
    readonly: bool
    kind: str | None = None


class ModuleToolsInfo(BaseModel):
    """
    Pydantic model for module tools information.

    Attributes:
        description: Module description
        tools: List of tool information
    """

    description: str
    tools: list[ToolInfo]


# ToolsInfoDict is just a type alias for Dict[str, ModuleToolsInfo]
ToolsInfoDict = dict[str, ModuleToolsInfo]


class RouterBase(ABC):
    """环境路由器抽象基类。

    Router 用于协调 agent 与环境模块（:class:`~agentsociety2.env.base.EnvBase`）的交互，职责包括：

    - 聚合并过滤环境工具（函数调用 schema）
    - 接收编排器推送的仿真时钟（:meth:`set_current_time`），供 env 模块在 agent 阶段读取
    - 提供统一 LLM 调用封装（重试）
    - 生成 world description（可选，用于 PersonAgent 的提示词）
    """

    def __init__(
        self,
        env_modules: list[EnvBase],
        max_steps: int = 10,
        max_llm_call_retry: int = 10,
        replay_writer: Optional["ReplayWriter"] = None,
        llm_clients_spec: dict[str, Any] | None = None,
    ):
        """创建路由器实例。

        :param env_modules: 环境模块列表。
        :param max_steps: 最大执行步数（由具体 router 实现解释）。
        :param max_llm_call_retry: LLM 调用最大重试次数下限（至少为 1）。
        :param replay_writer: 可选回放写入器；若提供会自动注入到各 env module。
        :param llm_clients_spec: 可选。注入的 :class:`LLMClient` 句柄映射，
            例如 ``{"coder": "LLMClient", "default": "LLMClient"}``。提供时
            router 使用注入的 client；为空时按配置构建本地 client。
        """
        # Get model names from environment-based configuration
        # ReAct/codegen uses coder model
        self.codegen_model_name = get_model_name("coder")
        # Summary uses default model
        self.summary_model_name = get_model_name("default")

        # LLM clients: prefer injected handles (carrying connection params);
        # otherwise build them from config. Each client builds its own Router +
        # AIMD semaphore in its own event loop on first call — no module-global
        # pool.
        spec = llm_clients_spec or {}
        from agentsociety2.config.llm_dispatcher import build_client_for_role

        self._coder_dispatcher = spec.get("coder") or build_client_for_role("coder")
        self._summary_dispatcher = spec.get("default") or build_client_for_role(
            "default"
        )

        self.env_modules = env_modules
        self.max_steps = max_steps
        self.max_llm_call_retry = max(max_llm_call_retry, 1)
        self._replay_writer = replay_writer
        self.run_dir: Path | None = None  # 由 cli.py 设置
        # 各 env 模块 workspace 的根（``<run_dir>/env``）。
        self._env_workspace_root: Path | None = None
        if replay_writer is not None:
            for env_module in env_modules:
                env_module.set_replay_writer(replay_writer)

        # Current datetime
        self.t = datetime.now()

        # Pydantic model collector for collecting BaseModel types from tool functions
        self._pydantic_collector = PydanticModelCollector()

        # World Description
        self._world_description = None
        self._generate_world_description_lock = asyncio.Lock()

        # Trace: optional sync sharded-writer adapter (append_record/flush) used
        # to emit env-side LLM spans. None = no tracing. Per-ask trace context
        # (trace_id, parent_span_id, agent_id) is carried in a ContextVar so
        # concurrent ask() calls on the same router don't clobber each other.
        self._trace_sink: Any = None
        self._trace_ctx: ContextVar[tuple] = ContextVar(
            f"envrouter_trace_ctx_{id(self)}", default=(None, None, None)
        )

    def set_trace_sink(self, sink: Any) -> None:
        """Inject a sync sharded-writer adapter for env-side trace spans.

        :param sink: An object exposing ``append_record(record_dict)`` (and
            optionally ``flush()``), e.g. the adapter built by
            :func:`~agentsociety2.trace.build_local_sink`.
            Pass ``None`` to disable tracing.
        """
        self._trace_sink = sink

    def _set_trace_context(
        self, trace_id: str | None, parent_span_id: str | None, agent_id: Any
    ):
        """Bind the current ask()'s trace context (returns a reset token)."""
        return self._trace_ctx.set((trace_id, parent_span_id, agent_id))

    def _reset_trace_context(self, token) -> None:
        """Reset the trace context to its prior value."""
        self._trace_ctx.reset(token)

    @contextmanager
    def _llm_completion_span(self, model_name: str, message_count: int):
        """Emit an ``llm.completion`` span for an env-side LLM call.

        No-op when no trace sink or trace context is bound. The span is parented
        to the current ask()'s ``parent_span_id`` so env codegen/summary LLM
        calls appear in the agent's trace tree (previously a blind spot).
        """
        trace_id, parent_span_id, agent_id = self._trace_ctx.get()
        sink = self._trace_sink
        if sink is None or trace_id is None:
            yield
            return
        span_id = uuid.uuid4().hex[:16]
        start = time.time_ns()
        status = "ok"
        message = ""
        try:
            yield
        except Exception as exc:
            status = "error"
            message = str(exc)
            raise
        finally:
            record = {
                "resource": {
                    "service.name": "agentsociety2.env_router",
                    "agent.id": agent_id if agent_id is not None else 0,
                },
                "scope": {
                    "name": "agentsociety2.env.codegen",
                    "version": "1",
                },
                "trace_id": trace_id,
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "name": "llm.completion",
                "kind": "internal",
                "start_time_unix_nano": start,
                "end_time_unix_nano": time.time_ns(),
                "status": {"code": status, "message": message},
                "attributes": {
                    "operation.type": "llm",
                    "llm.model": model_name or "",
                    "llm.source": "env_router",
                    "input.message_count": message_count,
                },
                "events": [],
            }
            try:
                sink.append_record(record)
            except Exception:
                get_logger().debug(
                    "Failed to append trace record to sink", exc_info=True
                )

    def _add_current_time_to_ctx(self, ctx: dict) -> None:
        """向 ctx 注入当前时间信息（原地修改）。"""
        ctx["current_time"] = {
            "datetime": self.t.isoformat(),
            "formatted": self.t.strftime("%Y-%m-%d %H:%M:%S"),
            "weekday": self.t.strftime("%A"),
            "timestamp": self.t.timestamp(),
        }

    def set_current_time(self, t: datetime) -> None:
        """Push the society's current clock to the router and env modules.

        This is NOT time advancement — the society advances its own clock in
        ``step()`` and calls this so that, during the agent phase (which runs
        before :meth:`step`), env modules observe the correct simulation time.
        Several env modules read ``self.t`` inside ``@tool`` methods (e.g. event
        scheduling, social-media post timestamps), so the time must be set
        before agents start querying the environment.
        """
        self.t = t
        for env_module in self.env_modules:
            env_module.t = t

    @abstractmethod
    async def ask(
        self,
        ctx: dict,
        instruction: str,
        readonly: bool = False,
        template_mode: bool = False,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> tuple[dict, str]:
        """与环境交互的统一入口（由子类实现具体路由策略）。

        :param ctx: 上下文字典。模板模式下可包含 ``variables``，用于 ``{var}`` 替换。
        :param instruction: 指令文本。模板模式下会进行变量替换后再执行。
        :param readonly: 是否只读（只读时应避免改变环境状态）。
        :param template_mode: 是否启用模板模式。
        :param trace_id: OTel trace ID（UUID hex），用于跨 agent/env 的追踪关联。
        :param parent_span_id: OTel parent span ID，用于构建 span 层级。
        :returns: ``(ctx, answer)``，其中 ctx 可能被环境更新。
        """
        raise NotImplementedError

    async def init(self, start_datetime: datetime) -> bool:
        """初始化路由器与环境模块。

        :param start_datetime: 仿真起始时间。
        :returns: 是否有 env 模块恢复了 checkpoint（即 resume）。
        """
        self.t = start_datetime
        for env_module in self.env_modules:
            await env_module.init(start_datetime)
        # restore 必须在 ``init()`` 之后：部分模块的 ``init()`` 会重置状态
        # （如 PrisonersDilemmaEnv 清空 round_history），后置才能让 checkpoint 覆盖。
        # fresh 启动时无快照，``restore()`` 返回 False。
        return await self.from_workspaces()

    async def step(self, tick: int, t: datetime):
        """推进环境模块一个仿真步。

        :param tick: 本步时间跨度（秒）。
        :param t: 本步结束后的仿真时间。
        """
        self.t = t
        await asyncio.gather(*[m.step(tick, self.t) for m in self.env_modules])

    async def close(self):
        """关闭路由器（关闭所有环境模块）。"""
        for env_module in self.env_modules:
            await env_module.close()

    # ==================== workspace 持久化（无状态 resume） ====================

    def bind_env_workspaces(self, root: Path, module_types: list[str]) -> None:
        """把每个 env 模块绑定到 root/module_type（幂等）。

        ``module_types`` 与 ``env_modules`` 按位置对应，同时作为目录键
        （与 ``env_kwargs`` 对齐，避免同类多实例冲突）。
        """
        self._env_workspace_root = Path(root)
        self._env_workspace_root.mkdir(parents=True, exist_ok=True)
        for module, module_type in zip(self.env_modules, module_types):
            ws = self._env_workspace_root / module_type
            module._bind_workspace(ws)

    async def from_workspaces(self) -> bool:
        """恢复各已绑定模块的状态（存在快照时）。

        默认严格模式：任一模块 ``restore()`` 抛错则中止整个 resume（所有模块先
        尝试恢复、汇总失败后统一抛错，便于一次看清全部损坏点）。静默降级——失败
        模块以初始状态继续跑——会让模块状态与 ``SOCIETY_STEP.json`` 记录的步数
        脱钩，损坏只会在下游指标才暴露。设置 ``AGENTSOCIETY_ENV_RESTORE_ALLOW_FRESH=1``
        可恢复旧的降级行为：失败模块 fresh 启动并 ERROR 汇总告警，其余模块照常恢复。

        :returns: 是否有任一模块加载了快照（即 resume）。
        :raises RuntimeError: 严格模式下存在恢复失败的模块。
        """
        any_restored = False
        failed: dict[str, Exception] = {}
        for module in self.env_modules:
            if module._workspace_root is None:
                continue
            try:
                restored = await module.restore(module._workspace_root)
            except Exception as exc:
                get_logger().error(
                    "Env module %s restore failed: %s",
                    module.name,
                    exc,
                )
                failed[module.name] = exc
                restored = False
            any_restored = any_restored or restored
        if failed:
            if not Config.ENV_RESTORE_ALLOW_FRESH:
                details = "; ".join(f"{n}: {e}" for n, e in failed.items())
                raise RuntimeError(
                    f"Env resume aborted: {len(failed)} module(s) failed to "
                    f"restore ({sorted(failed)}), refusing to silently start "
                    "fresh and desync from the recorded step count (set "
                    "AGENTSOCIETY_ENV_RESTORE_ALLOW_FRESH=1 to allow the "
                    f"fresh-start fallback). Failures: {details}"
                )
            get_logger().error(
                "Partial env resume (ENV_RESTORE_ALLOW_FRESH=1): %d module(s) "
                "failed to restore and start fresh while others resumed from "
                "checkpoint — env state may be inconsistent: %s",
                len(failed),
                sorted(failed),
            )
        return any_restored

    async def to_workspaces(self) -> None:
        """把每个模块的动态状态写入其 workspace。

        用 ``return_exceptions=True`` 收集结果，单个模块落盘失败不会让本步其它
        模块的持久化全部丢失（否则一次序列化异常会导致整步 checkpoint 落后）。
        """
        if self._env_workspace_root is None:
            return
        results = await asyncio.gather(
            *[m.to_workspace() for m in self.env_modules], return_exceptions=True
        )
        for module, result in zip(self.env_modules, results):
            if isinstance(result, BaseException):
                get_logger().error(
                    "Env module %s to_workspace failed: %s", module.name, result
                )

    def get_tool_call_history(self) -> list[dict[str, Any]]:
        """汇总所有环境模块的工具调用历史（按时间排序）。

        :returns: 调用记录列表（按 ``timestamp`` 升序）。
        """
        all_history: list[dict[str, Any]] = []
        for env_module in self.env_modules:
            module_name = env_module.name
            module_history = env_module.get_tool_call_history()
            # Add module_name to each call record
            for call_record in module_history:
                call_record_with_module = call_record.copy()
                call_record_with_module["module_name"] = module_name
                all_history.append(call_record_with_module)

        # Sort by timestamp (oldest first)
        all_history.sort(key=lambda x: x.get("timestamp", ""))
        return all_history

    def reset_tool_call_history(self):
        """清空所有环境模块的工具调用历史。"""
        for env_module in self.env_modules:
            env_module.reset_tool_call_history()

    # ==================== Trace Context Methods ====================

    def set_trace_context(
        self, trace_id: str | None, parent_span_id: str | None
    ) -> None:
        """为所有环境模块设置当前 OTel trace 上下文。

        Router 子类应在 ``ask`` 入口处调用此方法，使 ``@tool``
        装饰器能将 ``trace_id`` 写入 tool call history。

        :param trace_id: OTel trace ID（UUID hex）。
        :param parent_span_id: OTel parent span ID。
        """
        ctx = {"trace_id": trace_id, "parent_span_id": parent_span_id}
        for env_module in self.env_modules:
            env_module._current_trace_context = ctx

    def clear_trace_context(self) -> None:
        """清除所有环境模块的 trace 上下文。"""
        for env_module in self.env_modules:
            env_module._current_trace_context = {}

    # ==================== Replay Data Methods ====================

    def set_replay_writer(self, writer: "ReplayWriter") -> None:
        """为所有环境模块设置回放写入器。

        :param writer: :class:`~agentsociety2.storage.ReplayWriter` 实例。
        """
        for env_module in self.env_modules:
            env_module.set_replay_writer(writer)

    def get_system_prompt(self) -> str:
        """构建 router 侧的通用 system prompt（不含具体任务指令）。

        :returns: system prompt 文本。
        """

        prompt = """You are an AI assistant that helps LLM agents accomplish tasks in a virtual world simulation environment.

## Guidelines

- This is a VIRTUAL WORLD simulation. ONLY USE tools and features explicitly provided by the environment modules rather than trying to access the real world.
- REJECT and report any requests that require functionality not provided by the environment modules as `fail` status.
"""

        return prompt

    @overload
    async def acompletion(
        self,
        model: Literal["coder", "summary"],
        messages: list[AllMessageValues],
        stream: Literal[False] = False,
        **kwargs: Any,
    ) -> ModelResponse:
        raise NotImplementedError

    @overload
    async def acompletion(
        self,
        model: Literal["coder", "summary"],
        messages: list[AllMessageValues],
        stream: Literal[True] = True,
        **kwargs: Any,
    ) -> CustomStreamWrapper:
        raise NotImplementedError

    async def acompletion(
        self,
        model: Literal["coder", "summary"],
        messages: list[AllMessageValues],
        stream: bool = False,
        max_retries: int | None = None,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        **kwargs: Any,
    ):
        """封装 LLM 调度（Dispatcher 负责并发控制与 HTTP 重试）。

        :param model: ``coder`` 或 ``summary``。
        :param messages: 消息列表（不自动追加 system prompt；若需要请用 :meth:`acompletion_with_system_prompt`）。
        :param stream: 是否流式返回。
        :param max_retries: 可选。最大重试次数；为空则使用 ``self.max_llm_call_retry``。
        :param base_delay: 429 类错误的指数退避基准延迟。
        :param max_delay: 指数退避最大延迟。
        :returns: LLM 响应对象（stream=False 时为 :class:`litellm.types.utils.ModelResponse`）。
        :raises ValueError: 超过重试次数仍失败时抛出。
        """
        if max_retries is None:
            max_retries = self.max_llm_call_retry
        else:
            max_retries = max(max_retries, 1)

        dispatcher = (
            self._coder_dispatcher if model == "coder" else self._summary_dispatcher
        )
        model_name = (
            self.codegen_model_name if model == "coder" else self.summary_model_name
        )

        with self._llm_completion_span(model_name, len(messages)):
            response = await dispatcher.call(
                model_name,
                messages,
                stream=stream,
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                **kwargs,
            )

        # Token accounting is handled centrally by the shared TokenStatsActor
        # (per-process token stats; see get_dispatch_token_stats).
        return response

    async def acompletion_with_system_prompt(
        self,
        model: Literal["coder", "summary"],
        messages: list[AllMessageValues],
        **kwargs: Any,
    ):
        """发送补全请求并自动在最前追加 router system prompt。

        :param model: ``coder`` 或 ``summary``。
        :param messages: 消息列表。
        :returns: LLM 响应对象。
        """
        system_prompt = self.get_system_prompt()
        request_messages: list[AllMessageValues] = [
            {"role": "system", "content": system_prompt},
            *messages.copy(),  # type: ignore
        ]
        response = await self.acompletion(
            model=model,
            messages=request_messages,
            stream=False,
            **kwargs,
        )
        return response

    async def acompletion_with_pydantic_validation(
        self,
        model: Literal["coder", "summary"],
        model_type: type[T],
        messages: list[AllMessageValues],
        max_retries: int = 10,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        error_feedback_prompt: str | None = None,
        **kwargs: Any,
    ) -> T:
        """发送补全并校验为指定 Pydantic 模型（失败时自动反馈并重试）。

        :param model: ``coder`` 或 ``summary``。
        :param model_type: 用于校验的 Pydantic 模型类型。
        :param messages: 消息列表（会自动追加 system prompt）。
        :param max_retries: 最大重试次数（不含首次尝试）。
        :param base_delay: 传给 LLM dispatcher 的指数退避基准延迟。
        :param max_delay: 传给 LLM dispatcher 的指数退避最大延迟。
        :param error_feedback_prompt: 可选。自定义错误反馈模板（需包含 ``{error_message}`` 与 ``{model_schema}`` 占位符）。
        :returns: 校验通过的 Pydantic 实例。
        :raises ValueError: 解析/校验在重试后仍失败时抛出。
        """
        logger = get_logger()

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
                system_prompt = self.get_system_prompt()
                request_messages: list[AllMessageValues] = [
                    {"role": "system", "content": system_prompt},
                    *conversation_messages.copy(),  # type: ignore
                ]

                # Send request to LLM
                response = await self.acompletion(
                    model=model,
                    messages=request_messages,
                    stream=False,
                    max_retries=max_retries,
                    base_delay=base_delay,
                    max_delay=max_delay,
                    **kwargs,
                )

                content = response.choices[0].message.content  # type: ignore
                if content is None:
                    raise ValueError("LLM returned empty content")
                conversation_messages.append({"role": "assistant", "content": content})

                # Extract JSON from response
                json_str = extract_json(content)
                if json_str is None:
                    raise ValueError("Failed to extract JSON from LLM response")

                # Repair JSON if needed
                try:
                    parsed_data = json_repair.loads(json_str)
                except Exception as e:
                    raise ValueError(f"Failed to parse JSON: {e!s}") from e

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
                        ) from e

                    # Prepare error feedback message
                    error_feedback = error_prompt_template.format(
                        error_message=error_message, model_schema=model_schema
                    )

                    # Add error feedback to conversation
                    conversation_messages.append(
                        {"role": "user", "content": error_feedback}
                    )

                    # For validation errors, retry immediately without delay
                    logger.warning(
                        f"Validation failed (attempt {attempt + 1}/{max_retries + 1}). "
                        f"Retrying immediately. Error: {error_message}"
                    )
                    # No delay for validation errors

            except Exception as e:
                if isinstance(e, LLMDispatchError):
                    raise

                # If this is the last attempt, raise the error
                if attempt >= max_retries:
                    raise ValueError(
                        f"Failed to get valid response after {max_retries + 1} attempts. Last error: {e!s}"
                    ) from e

                # For other errors (ValueError, etc.), prepare error feedback and retry immediately
                error_message = str(e)
                error_feedback = error_prompt_template.format(
                    error_message=error_message, model_schema=model_schema
                )

                # Add error feedback to conversation
                conversation_messages.append(
                    {"role": "user", "content": error_feedback}
                )

                logger.warning(
                    f"Request failed (attempt {attempt + 1}/{max_retries + 1}). "
                    f"Retrying immediately. Error: {error_message}"
                )
                # No delay for non-429 errors

                last_error = e

        # This should never be reached, but just in case
        raise ValueError(
            f"Failed to get valid response after {max_retries + 1} attempts. Last error: {last_error!s}"
        )

    def get_token_usages(self):
        """Return aggregated token usage from this router's LLM clients.

        Each dispatcher (:class:`LLMClient`) tracks its own per-loop usage; we
        snapshot them here (without clearing). Returns
        ``{model: TokenUsageStats}``.
        """
        from agentsociety2.config.llm_dispatcher import merge_token_stats

        deltas = []
        for dispatcher in (self._coder_dispatcher, self._summary_dispatcher):
            if dispatcher is not None and hasattr(dispatcher, "snapshot_token_stats"):
                deltas.append(dispatcher.snapshot_token_stats())
        snapshot = merge_token_stats(*deltas) if deltas else {}
        return {
            model: TokenUsageStats(
                call_count=int(s.get("calls", 0)),
                input_tokens=int(s.get("input", 0)),
                output_tokens=int(s.get("output", 0)),
                cached_input_tokens=int(s.get("cached_input", 0)),
            )
            for model, s in snapshot.items()
        }

    def reset_token_usages(self):
        """Reset aggregated token usage on this router's LLM clients (drain)."""
        for dispatcher in (self._coder_dispatcher, self._summary_dispatcher):
            if dispatcher is not None and hasattr(dispatcher, "take_token_stats"):
                dispatcher.take_token_stats()

    @staticmethod
    def get_status_descriptions() -> dict[str, str]:
        """
        Get standard status descriptions.

        The status indicates whether the user's instruction has been effectively
        completed in the environment modules, or needs to wait for some time
        before the user actively checks completion.

        :returns: Dictionary mapping status values to their descriptions: - success: The task has been completed successfully. All required operations finished without errors. - in_progress: The task is still being executed or more steps are needed. The agent need to check whether it is done in the next steps. - fail: The task could not be completed (e.g., unsupported instruction, missing data, invalid input). Include detailed reason in results. - error: An error occurred during code execution. Must include error details in results['error']. - unknown: Execution status unknown
        """
        return {
            "success": "The task has been completed successfully. All required operations finished without errors.",
            "in_progress": "The task is still being executed or more steps are needed. The agent need to check whether it is done in the next steps.",
            "fail": "The task could not be completed (e.g., unsupported instruction, missing data, invalid input). Include detailed reason in results.",
            "error": "An error occurred during code execution. Must include error details in results['error'].",
            "unknown": "Execution status unknown",
        }

    async def get_world_description(self) -> str:
        """
        Get the world description.
        """
        if self._world_description is None:
            async with self._generate_world_description_lock:
                if self._world_description is None:
                    self._world_description = (
                        await self.generate_world_description_from_tools()
                    )
        return self._world_description

    async def generate_world_description_from_tools(
        self, max_retries: int | None = None
    ) -> str:
        """
        根据环境路由器的模块信息生成简短世界描述。

        world_description 只承担“这个仿真世界大概是什么、如何通过 ask_env
        与环境交互”的轻量背景说明。模块级细节应由 env skill、工具 schema 或
        router 自身处理，避免 world section 挤占 prompt 中 env skill 的空间。

        :returns: str: 简短世界描述文本，可直接作为 PersonAgent 的 world section
        """
        logger = get_logger()
        logger.info("\n【生成世界描述】从环境模块摘要生成简短world_description...")

        try:
            all_tools_info = self._collect_tools_info()
            tools_pyi = self._format_tools_pyi(all_tools_info, 0)

            module_descriptions = [
                f"- {module.name}: {module.description()}"
                for module in self.env_modules
            ]

            env_skill_catalog_rows = [
                "| name | env_module | description |",
                "| --- | --- | --- |",
            ]
            for env_module in self.env_modules:
                try:
                    skill_dirs = env_module.skill_dirs()
                except Exception as e:
                    logger.warning(
                        f"Failed to get env skill dirs from {env_module.name}: {e}"
                    )
                    skill_dirs = []
                for skills_dir in skill_dirs:
                    try:
                        base = Path(skills_dir)
                        if not base.is_dir():
                            continue
                        for child in sorted(base.iterdir()):
                            skill_md = child / "SKILL.md"
                            if not child.is_dir() or not skill_md.is_file():
                                continue
                            row = _env_skill_catalog_row(
                                skill_md,
                                module_name=env_module.name,
                            )
                            if row:
                                env_skill_catalog_rows.append(row)
                    except Exception as e:
                        logger.warning(
                            f"Failed to summarize env skills from {skills_dir}: {e}"
                        )
            env_skill_catalog = (
                "\n".join(env_skill_catalog_rows)
                if len(env_skill_catalog_rows) > 2
                else _empty_env_skill_catalog()
            )

            prompt = f"""Generate a short world description for a simulated person agent.

The world section should be a compact orientation, not a full tool manual. It must:
- Briefly describe what environment modules exist and what kind of interaction they support, based on the module descriptions and pyi tool information.
- Tell the agent to use ask_env for concrete observation/action requests.
- Explicitly guide the agent to inspect and activate environment-module skills from the skill catalog when it needs module-specific behavior rules.
- Use the provided environment skill catalog to mention what kinds of env skills are relevant.
- Avoid listing every tool in prose.
- Do not copy or summarize the pyi signatures one by one.
- Keep it under 500 words.

Available environment tools in pyi format:
```python
{tools_pyi}
```

Module descriptions:
{chr(10).join(module_descriptions) if module_descriptions else "- None."}

Environment skill catalog:
{env_skill_catalog}

Generated world description:"""

            dialog: list[AllMessageValues] = [{"role": "user", "content": prompt}]
            completion_kwargs: dict[str, Any] = {
                "model": "summary",
                "messages": dialog,
                "stream": False,
                # 每个 run 只生成一次并缓存（见本方法上方的 lazy 缓存），推理既无
                # 收益又给 run 之间引入额外方差。
                "thinking": "off",
            }
            if max_retries is not None:
                completion_kwargs["max_retries"] = max_retries
            response = await self.acompletion(**completion_kwargs)
            world_description = response.choices[0].message.content or ""  # type: ignore
            logger.info(f"  ✓ 生成世界描述的response: {world_description}")

            if not world_description.strip():
                logger.warning("  ⚠ LLM返回空描述，使用默认简短描述")
                lines = [
                    "You are operating in a simulated environment.",
                    "Use ask_env with clear natural-language instructions to observe or act.",
                    "When module-specific behavior rules are needed, inspect the skill catalog and activate relevant env module skills.",
                ]
                if all_tools_info:
                    lines.append(
                        "Available environment modules: "
                        + ", ".join(sorted(all_tools_info.keys()))
                        + "."
                    )
                world_description = "\n".join(lines)

            logger.info(f"  ✓ 成功生成世界描述（长度: {len(world_description)} 字符）")
            return world_description.strip()

        except Exception as e:
            logger.error(f"  ❌ 生成世界描述时出错: {e!s}")
            import traceback

            logger.error(traceback.format_exc())
            # 返回一个基本的默认描述
            return (
                "You are operating in a simulated environment. "
                "Use natural language instructions to interact with the environment router to accomplish your goals."
            )

    def _collect_tools_info(self) -> ToolsInfoDict:
        """
        收集所有环境模块的工具信息，按模块组织。
        返回所有工具，不进行任何过滤。
        同时收集所有工具函数的参数类型和返回值类型中的 Pydantic BaseModel。

        :returns: 按模块组织的工具信息字典，使用 Pydantic 模型定义
        """
        parser = FunctionParser()
        # 重置 collector，准备收集新的模型
        self._pydantic_collector.reset()
        modules_info: ToolsInfoDict = {}

        for module in self.env_modules:
            # 收集所有工具（包括可写和只读）
            all_module_tools = module._llm_tools
            registered_tools = getattr(module.__class__, "_registered_tools", {})
            tool_kinds_dict = getattr(module.__class__, "_tool_kinds", {})
            readonly_tools_dict = getattr(module.__class__, "_readonly_tools", {})

            tools_list: list[ToolInfo] = []
            for tool in all_module_tools:
                func_info = tool["function"]
                tool_name = func_info["name"]

                # 获取工具的实际readonly状态和kind
                tool_readonly = readonly_tools_dict.get(tool_name, False)
                tool_kind = tool_kinds_dict.get(tool_name)

                # 使用 FunctionParser 解析函数
                tool_obj = registered_tools.get(tool_name)
                if not (tool_obj and hasattr(tool_obj, "fn")):
                    continue

                fn = tool_obj.fn._original_func
                function_parts = parser.parse_function(fn)

                # 如果解析失败，跳过该工具
                if function_parts is None:
                    get_logger().debug(
                        f"Failed to parse function for tool {tool_name}, skipping"
                    )
                    continue

                self._pydantic_collector.collect_from_function(fn)

                tool_info = ToolInfo(
                    function_parts=function_parts,
                    name=tool_name,
                    description=func_info.get("description", ""),
                    readonly=tool_readonly,
                    kind=tool_kind,
                )
                tools_list.append(tool_info)

            if tools_list:  # 只添加有工具的模块
                modules_info[module.name] = ModuleToolsInfo(
                    description=module.description(),
                    tools=tools_list,
                )

        return modules_info

    def _filter_tools_info(
        self,
        tools_info: ToolsInfoDict,
        readonly: bool | None = None,
        kind: str | None = None,
    ) -> ToolsInfoDict:
        """
        根据 readonly 和 kind 过滤工具信息。

        :param tools_info: 完整的工具信息字典
        :param readonly: 是否只读模式（None 表示不过滤）
        :param kind: 工具类型筛选（None 表示不过滤），如 "observe" 或 "statistics"

        :returns: 过滤后的工具信息字典
        """
        filtered_info: ToolsInfoDict = {}

        for module_name, module_data in tools_info.items():
            filtered_tools: list[ToolInfo] = []

            for tool_info in module_data.tools:
                # 根据 readonly 过滤
                if readonly is not None and tool_info.readonly != readonly:
                    continue

                # 根据 kind 过滤
                if kind is not None and tool_info.kind != kind:
                    continue

                filtered_tools.append(tool_info)

            if filtered_tools:  # 只添加有工具的模块
                filtered_info[module_name] = ModuleToolsInfo(
                    description=module_data.description,
                    tools=filtered_tools,
                )

        return filtered_info

    def get_collected_pydantic_models(self) -> dict[type[BaseModel], str]:
        """
        获取已收集的所有 Pydantic BaseModel 类型及其源代码。

        这些模型是在调用 _collect_tools_info() 时从工具函数的参数类型和返回值类型中收集的。

        :returns: 字典，key 是 BaseModel 类型，value 是其源代码
        """
        return self._pydantic_collector.get_collected_models()

    def _format_tools_pyi(
        self, modules_info: ToolsInfoDict, max_body_code_lines: int
    ) -> str:
        """
        将工具信息格式化为类似 pyi 文件的 Python 代码格式。

        格式：
        1. 上方：所有相关的 pydantic BaseModel 的完整代码
        2. 下方：模块类的 class XXX 及其 docstring（描述变成 docstring）
        3. 在 class 中包含相关函数的签名和 docstring

        :param modules_info: 按模块组织的工具信息字典（使用新的 Pydantic 模型）

        :returns: 格式化的 Python 代码字符串（类似 pyi 文件）
        """
        # 收集所有相关的 pydantic BaseModel
        pydantic_models = self.get_collected_pydantic_models()

        # 构建输出
        lines: list[str] = []
        lines.append("# Type definitions for environment modules")
        lines.append("from pydantic import BaseModel, Field")
        lines.append(
            "from typing import Any, Optional, Union, List, Dict, Literal, Tuple"
        )
        lines.append("from datetime import datetime")
        lines.append("")

        # 添加所有 pydantic BaseModel 的完整代码
        if pydantic_models:
            lines.append("# Pydantic BaseModel definitions")
            for source_code in pydantic_models.values():
                lines.append("")
                lines.append(source_code)
            lines.append("")
            lines.append("")

        if len(modules_info) > 0:
            lines.append("# Environment modules")
            lines.append(
                "# These are what you can call to interact with the environment."
            )
        else:
            lines.append("# No environment modules")
            lines.append("# You can't interact with the environment.")
        lines.append("")

        # 为每个模块生成类定义
        for module_name, module_data in modules_info.items():
            # 模块类定义和 docstring
            lines.append(f"class {module_name}:")
            description = module_data.description
            if description:
                lines.append(f'    """{description}"""')
            lines.append("")

            # 添加每个工具函数
            for tool_info in module_data.tools:
                # 直接使用 function_parts，已经解析好了
                function_parts = tool_info.function_parts
                sig_str = function_parts.signature

                lines.append(f"    {sig_str}")
                lines.append(f'        """{function_parts.docstring}"""')
                # 以代码注释形式呈现body_code
                for line in function_parts.body_code[:max_body_code_lines]:
                    lines.append(f"        # {line}")
                lines.append("        ...")
                lines.append("")

        pyi_code = "\n".join(lines)

        # 使用 black 格式化 pyi 代码
        try:
            # 使用 black 格式化代码
            formatted_code = black.format_str(pyi_code, mode=black.Mode())
            return formatted_code
        except Exception as e:
            # 如果格式化失败，记录警告并返回原始代码
            get_logger().warning(f"Failed to format pyi code with black: {e}")
            return pyi_code

    def _format_tools_pyi_trimmed(
        self, modules_info: ToolsInfoDict, max_body_code_lines: int
    ) -> str:
        """将工具信息格式化为保留缩减函数体的 pyi 代码。

        与 ``_format_tools_pyi`` 不同，函数体以实际代码形式呈现（非注释），
        超出 ``max_body_code_lines`` 的部分用 ``...`` 裁剪标记替代。
        在工具描述头部添加裁剪说明。
        """
        pydantic_models = self.get_collected_pydantic_models()

        lines: list[str] = []
        lines.append("# Type definitions for environment modules")
        lines.append("from pydantic import BaseModel, Field")
        lines.append(
            "from typing import Any, Optional, Union, List, Dict, Literal, Tuple"
        )
        lines.append("from datetime import datetime")
        lines.append("")

        if pydantic_models:
            lines.append("# Pydantic BaseModel definitions")
            for source_code in pydantic_models.values():
                lines.append("")
                lines.append(source_code)
            lines.append("")
            lines.append("")

        if len(modules_info) > 0:
            lines.append("# Environment modules")
            lines.append(
                "# These are what you can call to interact with the environment."
            )
            lines.append(
                "# NOTE: Function bodies are trimmed for brevity. The '...' at the end "
                "indicates omitted implementation details."
            )
        else:
            lines.append("# No environment modules")
            lines.append("# You can't interact with the environment.")
        lines.append("")

        for module_name, module_data in modules_info.items():
            lines.append(f"class {module_name}:")
            description = module_data.description
            if description:
                lines.append(f'    """{description}"""')
            lines.append("")

            for tool_info in module_data.tools:
                function_parts = tool_info.function_parts
                sig_str = function_parts.signature

                lines.append(f"    {sig_str}")
                if function_parts.docstring:
                    lines.append(f'        """{function_parts.docstring}"""')
                # Show body as actual code, not commented out
                body = function_parts.body_code
                trimmed = body[:max_body_code_lines]
                for line in trimmed:
                    lines.append(f"        {line}")
                if len(body) > max_body_code_lines:
                    lines.append("        # ... (trimmed)")
                lines.append("        ...")
                lines.append("")

        code = "\n".join(lines)
        try:
            return black.format_str(code, mode=black.Mode())
        except Exception as e:
            get_logger().warning(f"Failed to format trimmed pyi code with black: {e}")
            return code

    def _format_tools_pyi_ratio(self, modules_info: ToolsInfoDict, ratio: float) -> str:
        """将工具信息格式化为按比例保留函数体的代码。

        :param modules_info: 按模块组织的工具信息字典。
        :param ratio: 代码保留比例 (0.0 ~ 1.0)。
            0.0 = 仅签名 + docstring；1.0 = 完整函数体。
        """
        pydantic_models = self.get_collected_pydantic_models()

        lines: list[str] = []
        lines.append("# Type definitions for environment modules")
        lines.append("from pydantic import BaseModel, Field")
        lines.append(
            "from typing import Any, Optional, Union, List, Dict, Literal, Tuple"
        )
        lines.append("from datetime import datetime")
        lines.append("")

        if pydantic_models:
            lines.append("# Pydantic BaseModel definitions")
            for source_code in pydantic_models.values():
                lines.append("")
                lines.append(source_code)
            lines.append("")
            lines.append("")

        if len(modules_info) > 0:
            lines.append("# Environment modules")
            lines.append(
                "# These are what you can call to interact with the environment."
            )
            lines.append(
                f"# NOTE: Function bodies are trimmed to ~{ratio:.0%} for brevity."
            )
        else:
            lines.append("# No environment modules")
            lines.append("# You can't interact with the environment.")
        lines.append("")

        for module_name, module_data in modules_info.items():
            lines.append(f"class {module_name}:")
            description = module_data.description
            if description:
                lines.append(f'    """{description}"""')
            lines.append("")

            for tool_info in module_data.tools:
                function_parts = tool_info.function_parts
                sig_str = function_parts.signature

                lines.append(f"    {sig_str}")
                if function_parts.docstring:
                    lines.append(f'        """{function_parts.docstring}"""')
                body = function_parts.body_code
                keep = max(1, round(len(body) * ratio)) if body else 0
                for line in body[:keep]:
                    lines.append(f"        {line}")
                if body and len(body) > keep:
                    lines.append("        # ... (trimmed)")
                lines.append("        ...")
                lines.append("")

        code = "\n".join(lines)
        try:
            return black.format_str(code, mode=black.Mode())
        except Exception as e:
            get_logger().warning(f"Failed to format ratio pyi code with black: {e}")
            return code

    def _format_tools_raw_code(self, modules_info: ToolsInfoDict) -> str:
        """将工具信息格式化为原始 Python 代码（不使用 AST/pyi 解析，直接输出完整源码）。

        与 ``_format_tools_pyi`` 不同，此方法直接使用 ``inspect.getsource``
        获取每个工具函数的完整源码，不做类型存根提取。

        :param modules_info: 按模块组织的工具信息字典。
        :returns: 格式化的 Python 代码字符串。
        """

        lines: list[str] = []
        lines.append("# Type definitions for environment modules")
        lines.append("from pydantic import BaseModel, Field")
        lines.append(
            "from typing import Any, Optional, Union, List, Dict, Literal, Tuple"
        )
        lines.append("from datetime import datetime")
        lines.append("")

        pydantic_models = self.get_collected_pydantic_models()
        if pydantic_models:
            lines.append("# Pydantic BaseModel definitions")
            for source_code in pydantic_models.values():
                lines.append("")
                lines.append(source_code)
            lines.append("")
            lines.append("")

        if len(modules_info) > 0:
            lines.append("# Environment modules (raw source code)")
            lines.append(
                "# These are what you can call to interact with the environment."
            )
        else:
            lines.append("# No environment modules")
        lines.append("")

        for module_name, module_data in modules_info.items():
            lines.append(f"class {module_name}:")
            description = module_data.description
            if description:
                lines.append(f'    """{description}"""')
            lines.append("")

            for tool_info in module_data.tools:
                fp = tool_info.function_parts
                lines.append(f"    {fp.signature}")
                if fp.docstring:
                    lines.append(f'        """{fp.docstring}"""')
                for body_line in fp.body_code:
                    lines.append(f"        {body_line}")
                lines.append("")

        raw_code = "\n".join(lines)
        try:
            formatted_code = black.format_str(raw_code, mode=black.Mode())
            return formatted_code
        except Exception as e:
            get_logger().warning(f"Failed to format raw code with black: {e}")
            return raw_code

    async def generate_final_answer(
        self,
        ctx: dict,
        instruction: str,
        results: dict[str, Any],
        process_text: str | None = None,
        status: str = "unknown",
        error: str | None = None,
    ) -> tuple[str, str]:
        """
        根据用户输入和Router输出生成最终答案。

        这个方法接收用户输入（ctx, instruction）和Router输出（results和过程文本），
        使用LLM总结为一个answer，并确定执行状态。
        使用JSON格式返回，通过Pydantic model验证。

        :param ctx: 上下文字典，包含环境变量等信息
        :param instruction: 用户的原始指令
        :param results: Router执行的结果字典
        :param process_text: 过程文本（可选），描述执行过程的文本信息
        :param status: 初步的执行状态（可能被LLM更新）
        :param error: 错误信息（如果有）

        :returns: Tuple[str, str]: (final_answer, determined_status) - final_answer: LLM生成的最终答案（summary文本） - determined_status: 确定的执行状态（success/in_progress/fail/error）
        """
        # logger.debug(
        #     f"RouterBase: Generating final answer - instruction: {instruction[:100]}..., "
        #     f"preliminary status: {status}, results keys: {list(results.keys())}"
        # )

        # 构建结果字符串
        error_str = error or "None"

        # 构建过程文本部分
        process_section = ""
        if process_text:
            process_section = f"""## Execution Process
{process_text}"""

        # 构建status描述
        status_descriptions = self.get_status_descriptions()
        status_desc = status_descriptions.get(status, f"状态: {status}")

        # 使用多行f-string构建prompt
        prompt = f"""# Summarize the Final Answer

Based on the agent input (`ctx` and `instruction`), execution process and results, provide a structured JSON answer to the agent.
The answer should be scenario-based instead of technical details.
But `id` related information should be included in the summary to help the agent identify.

## Agent Input

Instruction: {instruction}

Context:
```python
{ctx}
```

{process_section}

## Results

Status: {status.upper()}

Description: {status_desc}

Results:
```python
{results}
```

{f"Error: {error_str if error_str else 'None'}" if error_str else ""}

## Format

Your answer should be a JSON object with the following structure:
```json
{{
    "status": "success|fail|in_progress|error",
    "summary": "Summarize what was accomplished (or what went wrong). Include relevant information from the execution results. Reference the semantic process information to explain the process"
}}
```

Guidelines:
1. **status**: Use one of: "success", "fail", "in_progress", "error"
    - If the returned status is "unknown", SELECT ONE OF THESE STATUSES based on the execution results
    - **success**: The task has been completed successfully. All required operations finished without errors.
    - **in_progress**: The task is still being executed or more steps are needed. The agent need to check whether it is done in the next steps.
    - **fail**: The task could not be completed (e.g., unsupported instruction, missing data, invalid input). Include detailed reason.
    - **error**: An error occurred during code execution. Must include error details.
2. **summary**: Be short, clear and helpful. Should be scenario-based instead of technical details.
    - If the execution results contain time information (e.g., from ctx['current_time']), include it in the summary when relevant.
    - Summarize what was accomplished (or what went wrong)
    - Include relevant information from the execution results
    - Reference the process information to explain the process
    - If status is 'in_progress', mentions that more steps may be needed
    - If status is 'fail' or 'error', explains why it failed

## Important Notes
- Analyze the semantic meaning of the called environment functions and their results
- Consider whether the task requires waiting for completion when choosing the status (e.g., scheduled tasks)
- The status should reflect the actual completion state in the environment modules, not just whether more tool calls are needed

Return ONLY valid JSON, nothing else.

Final Answer:"""

        # logger.debug(f"RouterBase: Built final answer prompt - length: {len(prompt)}")
        # logger.info("--------------------------------")
        # logger.info(prompt)
        # logger.info("--------------------------------")

        dialog: list[AllMessageValues] = [{"role": "user", "content": prompt}]

        response = await self.acompletion_with_pydantic_validation(
            model="summary",
            model_type=FinalAnswerResponse,
            messages=dialog,
        )

        # 增加时间标签到summary (包含星期)
        time_tag = f"[{self.t.strftime('%A')}, {self.t.strftime('%Y-%m-%d %H:%M:%S')}]"
        response.summary = f"{time_tag} {response.summary}"
        return response.summary, response.status
