"""环境模块基类。

本模块提供环境模块的基类 :class:`EnvBase` 和工具注册装饰器 :func:`tool` 。

环境模块定义智能体可执行的操作和可观察的状态。通过 ``@tool`` 装饰器注册方法为可调用工具，供 Router 调用执行。

工具类型
========

- **常规工具**: ``@tool(readonly=False)`` — 可修改环境状态
- **只读工具**: ``@tool(readonly=True)`` — 仅查询，不修改状态
- **观察工具**: ``@tool(readonly=True, kind="observe")`` — 每个 step 自动调用
- **统计工具**: ``@tool(readonly=True, kind="statistics")`` — 统计信息

Example::

    from agentsociety2.env import EnvBase, tool

    class MyEnv(EnvBase):
        @tool(readonly=True, kind="observe")
        def get_location(self, agent_id: int) -> str:
            '''获取 Agent 当前位置'''
            return self._locations.get(agent_id, "unknown")

        @tool(readonly=False)
        def move(self, agent_id: int, destination: str) -> str:
            '''移动 Agent 到指定位置'''
            self._locations[agent_id] = destination
            return f"Moved to {destination}"
"""

import asyncio
import functools
import inspect
import json
import re
from collections.abc import Callable
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    TypeVar,
    overload,
)

if TYPE_CHECKING:
    from agentsociety2.storage import ReplayWriter

from mcp.server.mcpserver.tools.base import Tool
from mcp.server.mcpserver.tools.tool_manager import ToolManager
from openai.types.chat import ChatCompletionToolParam

__all__ = [
    "EnvBase",
    "tool",
]


def dump_int_map(mapping: dict[int, Any]) -> dict[str, Any]:
    """``dict[int, ...]`` → JSON 友好的 ``dict[str, ...]`` （JSON 键只能是字符串）。"""
    return {str(k): v for k, v in mapping.items()}


def load_int_map(mapping: dict[str, Any] | None) -> dict[int, Any]:
    """JSON 还原后的 ``dict[str, ...]`` → ``dict[int, ...]`` 。"""
    if not mapping:
        return {}
    return {int(k): v for k, v in mapping.items()}


F = TypeVar("F", bound=Callable)


@overload
def tool(
    readonly: Literal[True],
    name: str | None = None,
    description: str | None = None,
    kind: Literal["observe", "statistics"] = ...,
) -> Callable[[F], F]:
    """observe/statistics 工具(必须只读)的重载。"""


@overload
def tool(
    readonly: bool,
    name: str | None = None,
    description: str | None = None,
    kind: None = None,
) -> Callable[[F], F]:
    """常规工具的重载。"""


def tool(
    readonly: bool,
    name: str | None = None,
    description: str | None = None,
    kind: Literal["observe", "statistics"] | None = None,
) -> Callable[[F], F]:
    """将环境方法注册为可调用工具（供 Router/LLM 调用）。

    :param readonly: 是否只读。
        当 ``kind`` 为 ``observe`` 或 ``statistics`` 时必须为 ``True`` （运行时强校验）。
    :param name: 可选。工具名（默认使用函数名）。
    :param description: 可选。工具描述（用于模型函数调用 schema）。
    :param kind: 可选。工具类型：

        - ``observe`` ：观测工具（通常每步自动调用），除 ``self`` 外最多 1 个参数
        - ``statistics`` ：统计工具，除 ``self`` 外不能有参数
        - ``None`` ：普通工具
    :returns: 装饰器函数。
    :raises ValueError: ``kind`` 与 ``readonly``/参数签名不匹配时抛出。
    """

    def tool_decorator(func: F) -> F:
        # Validate readonly constraint for observe/statistics tools
        if kind in ("observe", "statistics") and not readonly:
            raise ValueError(
                f"Tool '{func.__name__}' with kind='{kind}' must have readonly=True. "
                f"Tools of kind 'observe' or 'statistics' are read-only by design."
            )

        # Validate kind parameter if provided
        if kind is not None:
            if kind not in ("observe", "statistics"):
                raise ValueError(
                    f"Invalid kind '{kind}'. Must be 'observe', 'statistics', or None."
                )

            # Get function signature to validate parameters
            sig = inspect.signature(func)
            params = list(sig.parameters.values())

            # Exclude the first parameter (self) for class methods
            # For instance methods, the first parameter is typically 'self'
            non_self_params = params[1:] if len(params) > 0 else []

            if kind == "observe":
                # Observe functions can have at most one parameter besides self
                if len(non_self_params) > 1:
                    param_names = [p.name for p in non_self_params]
                    raise ValueError(
                        f"Tool '{func.__name__}' with kind='observe' can have at most one "
                        f"parameter besides self, but found {len(non_self_params)}: {param_names}. The only one allowed parameter is agent_id, id, or person_id"
                    )
            elif kind == "statistics":
                # Statistics functions can only have self parameter
                if len(non_self_params) > 0:
                    param_names = [p.name for p in non_self_params]
                    raise ValueError(
                        f"Tool '{func.__name__}' with kind='statistics' can only have self "
                        f"parameter, but found additional parameters: {param_names}"
                    )

        # Store the tool information in the function's attribute for Metaclass usage
        tool = Tool.from_function(
            func,
            name=name,
            description=description,
        )
        func._tool_info = {  # type: ignore
            "mcp.Tool": tool,
            "readonly": readonly,
            "kind": kind,
        }

        # Wrap the function to record call history
        original_func = func
        tool_name = name if name else func.__name__

        # Get function signature to convert args to kwargs
        sig = inspect.signature(func)
        param_names = list(sig.parameters.keys())
        # Skip 'self' parameter for instance methods
        if param_names and param_names[0] == "self":
            param_names = param_names[1:]

        def _normalize_to_kwargs(args, kwargs):
            """
            按函数签名把 args 与 kwargs 归并为统一的 kwargs dict。

            :param args: 位置参数(不含 self)。
            :param kwargs: 关键字参数。

            :returns: 以参数名为键的参数 dict。
            """
            normalized_kwargs = {}

            # Process positional args first (map to parameter names by position)
            for i, arg in enumerate(args):
                if i < len(param_names):
                    param_name = param_names[i]
                    # Only add if not already in kwargs (kwargs take precedence)
                    if param_name not in kwargs:
                        normalized_kwargs[param_name] = arg

            # Add all kwargs
            normalized_kwargs.update(kwargs)

            return normalized_kwargs

        def _create_call_record(
            args,
            kwargs,
            return_value,
            exception_occurred,
            exception_info,
            trace_ctx,
        ):
            """创建调用记录的辅助函数。"""
            # Convert args and kwargs to unified kwargs dict
            normalized_kwargs = _normalize_to_kwargs(args, kwargs)
            kwargs_repr = _serialize_to_literal(normalized_kwargs)
            return_value_repr = (
                _serialize_to_literal(return_value)
                if return_value is not None
                else None
            )

            record = {
                "function_name": tool_name,
                "kwargs": kwargs_repr,
                "return_value": return_value_repr,
                "exception_occurred": exception_occurred,
                "exception_info": exception_info,
                "timestamp": datetime.now(UTC).isoformat(),
            }
            # Attach OTel trace context if available
            if trace_ctx:
                record["trace_id"] = trace_ctx.get("trace_id")
                record["parent_span_id"] = trace_ctx.get("parent_span_id")
            return record

        if inspect.iscoroutinefunction(func):

            @functools.wraps(original_func)
            async def async_wrapper(self, *args, **kwargs):
                exception_occurred = False
                exception_info = None
                return_value = None
                trace_ctx = getattr(self, "_current_trace_context", {})

                try:
                    return_value = await original_func(self, *args, **kwargs)
                except Exception as e:
                    exception_occurred = True
                    exception_info = {
                        "type": type(e).__name__,
                        "message": str(e),
                    }
                    raise
                finally:
                    # Record the call history
                    if hasattr(self, "_tool_call_history"):
                        call_record = _create_call_record(
                            args,
                            kwargs,
                            return_value,
                            exception_occurred,
                            exception_info,
                            trace_ctx,
                        )
                        self._tool_call_history.append(call_record)
                return return_value

            wrapped_func = async_wrapper
        else:
            # Sync function wrapper using functools.wraps
            @functools.wraps(original_func)
            def sync_wrapper(self, *args, **kwargs):
                exception_occurred = False
                exception_info = None
                return_value = None
                trace_ctx = getattr(self, "_current_trace_context", {})

                try:
                    return_value = original_func(self, *args, **kwargs)
                except Exception as e:
                    exception_occurred = True
                    exception_info = {
                        "type": type(e).__name__,
                        "message": str(e),
                    }
                    raise
                finally:
                    # Record the call history
                    if hasattr(self, "_tool_call_history"):
                        call_record = _create_call_record(
                            args,
                            kwargs,
                            return_value,
                            exception_occurred,
                            exception_info,
                            trace_ctx,
                        )
                        self._tool_call_history.append(call_record)
                return return_value

            wrapped_func = sync_wrapper

        # Set custom attributes
        wrapped_func._tool_info = func._tool_info  # type: ignore
        wrapped_func._original_func = original_func  # type: ignore

        return wrapped_func  # type: ignore

    return tool_decorator


def _serialize_to_literal(value: Any) -> Any:
    """
    把值序列化为 JSON 可序列化的字面量表示。

    :param value: 待序列化的值。

    :returns: 该值的 JSON 可序列化表示。
    """
    try:
        # Try to serialize directly
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        # If not directly serializable, convert to string representation
        try:
            return repr(value)
        except Exception:
            return str(type(value).__name__)


class EnvMeta(type):
    """元类：收集 ``@tool`` 装饰的方法并注册到 ``tool_manager``。"""

    def __new__(cls, name, bases, namespace, **kwargs):
        new_class = super().__new__(cls, name, bases, namespace, **kwargs)

        registered_tools: dict[str, Any] = {}
        readonly_tools: dict[str, bool] = {}
        tool_kinds: dict[str, str | None] = {}
        for attr_name, attr_value in namespace.items():
            if callable(attr_value) and hasattr(attr_value, "_tool_info"):
                tool_info = attr_value._tool_info  # type: ignore
                # tool_info is a dict, containing "mcp.Tool", "readonly", and "kind"
                tool_obj = tool_info["mcp.Tool"]
                tool_obj.fn = attr_value  # Bind the actual function
                tool_key = tool_obj.name if tool_obj.name else attr_name
                registered_tools[tool_key] = tool_obj
                readonly_tools[tool_key] = tool_info.get("readonly", False)
                tool_kinds[tool_key] = tool_info.get("kind", None)
        new_class._registered_tools = registered_tools  # type: ignore
        new_class._readonly_tools = readonly_tools  # type: ignore
        new_class._tool_kinds = tool_kinds  # type: ignore
        return new_class


class EnvBase(metaclass=EnvMeta):
    """环境模块基类。

    环境模块定义 Agent 可执行的操作和可观察的状态。通过 ``@tool`` 装饰器注册方法为可调用工具，供 Router 调用。

    工具类型：
        - **常规工具**: ``@tool(readonly=False)`` — 可修改环境状态
        - **只读工具**: ``@tool(readonly=True)`` — 仅查询，不修改状态
        - **观察工具**: ``@tool(readonly=True, kind="observe")`` — 自动调用
        - **统计工具**: ``@tool(readonly=True, kind="statistics")`` — 统计信息

    子类应实现：
        - 使用 ``@tool`` 装饰器定义可执行操作
        - 可选：实现 ``observe()`` 方法（默认收集 kind="observe" 的工具）
    """

    # 声明式状态持久化：子类覆盖以自动创建 replay 表
    _agent_state_columns: ClassVar[list] = []
    _env_state_columns: ClassVar[list] = []

    @classmethod
    def is_concurrency_safe(cls) -> bool:
        """返回本模块的工具是否允许被并发调用。

        并发安全的模块不在其工具中修改共享(跨 agent)状态,因此 router
        可以不加全局 ``_execute_lock`` 执行其生成的代码,env Ray actor 也能并行扇出 ``ask`` 调用。默认为 ``False``(保守);只持有 per-agent
        状态(以 ``agent_id`` 为键、无共享可变结构)的模块应将其覆写为 ``True`` 。

        :returns: 并发调用工具安全时为 True。
        """
        return False

    @classmethod
    def _state_table_prefix_from_class(cls) -> str:
        """从类名推导表名前缀（PascalCase -> ``snake_case``，去常见后缀）"""
        name = cls.__name__
        for suffix in ("Space", "Env", "Module"):
            if name.endswith(suffix) and len(name) > len(suffix):
                name = name[: -len(suffix)]
                break
        return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name).lower()

    def __init__(self):
        self.t = datetime.now()

        # Initialize tool call history storage
        self._tool_call_history: list[dict[str, Any]] = []

        # Current trace context (set by router before tool execution)
        self._current_trace_context: dict[str, str | None] = {}

        # Replay writer for storing simulation state
        self._replay_writer: ReplayWriter | None = None
        self._state_tables_registered: bool = False

        # workspace 持久化槽位（无状态 resume）。
        self._workspace_root: Path | None = None

        tools = list(getattr(self.__class__, "_registered_tools", {}).values())
        self._tool_manager = ToolManager(tools=tools)
        self._readonly_llm_tools: list[ChatCompletionToolParam] = []
        self._llm_tools: list[ChatCompletionToolParam] = []
        """
        Tool Schema for LLM to call
        """
        for t in self._tool_manager.list_tools():
            parameters = deepcopy(t.parameters)
            # remove self
            if "properties" in parameters and "self" in parameters["properties"]:
                del parameters["properties"]["self"]
            if "required" in parameters and "self" in parameters["required"]:
                parameters["required"].remove("self")
            # convert format
            func: ChatCompletionToolParam = {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": parameters,
                },
            }
            self._llm_tools.append(func)
            readonly_tools = getattr(self.__class__, "_readonly_tools", {})
            if readonly_tools.get(t.name, False):
                self._readonly_llm_tools.append(func)

    def _set_llm_tools(self, tools: list[ChatCompletionToolParam]):
        self._llm_tools = tools

    @property
    def name(self):
        """环境模块名称。"""
        return self.__class__.__name__

    @classmethod
    def description(cls) -> str:
        """返回用于 router/world 定位的模块简短描述。"""
        if cls is EnvBase:
            return "Abstract base class for environment modules."
        doc = (cls.__doc__ or "").strip().splitlines()
        if doc:
            return doc[0].strip()
        first = cls.init_description().strip().splitlines()
        return first[0].strip() if first else f"{cls.__name__}: Environment module."

    @classmethod
    def init_description(cls) -> str:
        """
        返回本环境模块的可供 AI 阅读的初始化指引。

        :returns: 包含类名、构造 kwargs、接受的数据形态、默认值,以及必要
            时最小 kwargs 示例的 Markdown 文本。
        """
        # Check if this is the base class being called directly
        if cls is EnvBase:
            return f"""{cls.__name__}: Abstract base class for environment modules.

**Description:** {cls.__doc__ or "No description available"}

**Note:** This is an abstract base class. Do not use it directly. Subclasses should override this method to provide specific descriptions, initialization parameters, and usage examples.
"""
        else:
            # For subclasses that don't override this method
            return f"""{cls.__name__}: Environment module.

**Description:** {cls.__doc__ or "No description available"}

**Note:** This subclass has not provided a detailed description. Please refer to the class documentation or source code for initialization parameters and usage.
"""

    # ---- Skill Discovery ----

    @classmethod
    def skill_dirs(cls) -> list[Path]:
        """返回本环境模块提供的 agent skill 所在目录。

        本方法使环境模块能捆绑 agent 在该环境中操作时应使用的专用 skill。
        skill 通过扫描返回目录中的 SKILL.md 文件来发现。

        **默认发现约定：**

        基类实现自动从以下位置发现 skill:

        1. 包模块(如 ``mobility_space/__init__.py``):
           扫描 ``<module_dir>/agent_skills/`` 目录。

        2. 单文件模块(如 ``economy_space.py``):
           扫描 ``<module_dir>/<stem>_agent_skills/`` 目录。

        **自定义路径时覆写：**

        子类可覆写本方法以指定自定义 skill 目录::

            @classmethod
            def skill_dirs(cls) -> list[Path]:
                from pathlib import Path
                skills_dir = Path(__file__).parent.parent / "skills"
                return [skills_dir] if skills_dir.is_dir() else []

        **skill 目录结构：**

        每个 skill 目录应包含带 SKILL.md 文件的子目录,例如
        ``agent_skills/navigation/SKILL.md`` 及可选的
        ``agent_skills/navigation/scripts/`` 。

        :returns: 指向含 skill 子目录的目录的 Path 对象列表。无 skill 时
            为空列表。
        """
        import inspect

        module_file = Path(inspect.getfile(cls))
        parent = module_file.parent
        dirs: list[Path] = []

        # Single-file module: economy_space.py → economy_space_agent_skills/
        stem_dir = parent / f"{module_file.stem}_agent_skills"
        if stem_dir.is_dir():
            dirs.append(stem_dir)

        # Package module: mobility_space/ → mobility_space/agent_skills/
        pkg_dir = parent / "agent_skills"
        if pkg_dir.is_dir():
            dirs.append(pkg_dir)

        return dirs

    async def init(self, start_datetime: datetime):
        """初始化环境模块。

        :param start_datetime: 仿真起始时间。
        """
        self.t = start_datetime

    async def step(self, tick: int, t: datetime):
        """推进环境模块一个仿真步。

        :param tick: 本步时间跨度（秒）。
        :param t: 本步结束后的仿真时间。
        :raises NotImplementedError: 基类不提供默认实现。
        """
        raise NotImplementedError

    async def close(self):
        """关闭环境模块并释放资源（可选重写）。"""

    # ==================== workspace 持久化（无状态 resume） ====================
    #
    # 基类只提供「绑定到一个 workspace 目录」+ 一对供子类覆盖的落盘/恢复钩子，
    # 不规定状态格式、文件名或目录结构——子类自行决定如何序列化（JSON / 多文件 /
    # 二进制都行）。未覆盖的钩子为 no-op（模块不持久化，重启后状态丢失但不报错）。

    def _bind_workspace(self, workspace_path: Path) -> None:
        """绑定到 env workspace 目录（幂等），创建该目录。

        :param workspace_path: env workspace 根目录。
        """
        self._workspace_root = Path(workspace_path).resolve()
        self._workspace_root.mkdir(parents=True, exist_ok=True)

    async def to_workspace(self, workspace_path: Path | None = None) -> None:
        """把动态状态写入 workspace（每步由 society 经 router 调用）。

        默认 no-op。子类按自选的格式/文件名把需要跨重启保留的状态写到
        ``self._workspace_root`` （或传入的 ``workspace_path`` ）下。建议用
        :func:`~agentsociety2.storage.workspace_state.atomic_write_text` 原子写。
        """
        if workspace_path is not None:
            self._bind_workspace(workspace_path)

    async def restore(self, workspace_path: Path) -> bool:
        """从 workspace 恢复动态状态（resume 路径）。

        默认返回 ``False`` 。子类读取自己写入的状态并还原；返回是否成功加载（供 router 区分 fresh / resume）。仅在 ``__init__`` 与 ``init()`` 之后调用，故可安全覆盖 ``init()`` 设置的字段。
        """
        self._bind_workspace(workspace_path)
        return False

    @classmethod
    async def from_workspace(
        cls, workspace_path: Path, **init_kwargs: Any
    ) -> "EnvBase":
        """从 workspace 重建就绪模块：``cls(**init_kwargs)`` 后 ``restore`` 。

        :param init_kwargs: 构造该模块用的 kwargs（resume 时由 actor 从 ``SOCIETY.json`` 取）。
        """
        module = cls(**init_kwargs)
        await module.restore(Path(workspace_path))
        return module

    def get_tool_call_history(self) -> list[dict[str, Any]]:
        """获取工具调用历史（浅拷贝）。

        :returns: 调用记录列表。每条包含 ``function_name`` 、``kwargs`` 、``return_value`` 、
            ``exception_occurred`` 、``exception_info`` 、``timestamp`` 。
        """
        return self._tool_call_history.copy()

    def reset_tool_call_history(self):
        """清空工具调用历史。"""
        self._tool_call_history.clear()

    # ==================== Replay Data Methods ====================

    def set_replay_writer(self, writer: "ReplayWriter") -> None:
        """设置回放写入器（用于自动建表与写入状态）。

        :param writer: :class:`~agentsociety2.storage.ReplayWriter` 实例。
        """
        self._replay_writer = writer
        if writer is not None and (
            self._agent_state_columns or self._env_state_columns
        ):
            try:
                loop = asyncio.get_running_loop()
                task = loop.create_task(self._register_state_tables())
                task.add_done_callback(self._on_register_state_tables_done)
            except RuntimeError:
                # No running event loop; register lazily on first write
                import logging

                logging.getLogger(__name__).debug(
                    "No running event loop for state table registration; deferring"
                )

    @staticmethod
    def _on_register_state_tables_done(task: "asyncio.Task[None]") -> None:
        """``_register_state_tables`` 任务的回调,用于记录异常日志。"""
        if task.cancelled():
            return
        exc = task.exception()
        if exc is not None:
            import logging

            logging.getLogger(__name__).error(
                "Failed to register state tables: %s", exc, exc_info=exc
            )

    @property
    def _state_table_prefix(self) -> str:
        """从类名推导表名前缀（PascalCase → ``snake_case``，去常见后缀）"""
        return type(self)._state_table_prefix_from_class()

    async def _register_state_tables(self) -> None:
        """根据 ``_agent_state_columns`` / ``_env_state_columns`` 声明自动注册 replay 表"""
        if self._replay_writer is None or self._state_tables_registered:
            return

        from agentsociety2.storage import ColumnDef, ReplayDatasetSpec, TableSchema

        prefix = self._state_table_prefix

        if self._agent_state_columns:
            table_name = f"{prefix}_agent_state"
            columns = [
                ColumnDef(
                    "agent_id",
                    "INTEGER",
                    nullable=False,
                    logical_type="identifier",
                    analysis_role="identifier",
                    description="Agent identifier for this snapshot row.",
                ),
                ColumnDef(
                    "step",
                    "INTEGER",
                    nullable=False,
                    logical_type="step",
                    analysis_role="timestamp",
                    description="Simulation step for this snapshot row.",
                ),
                ColumnDef(
                    "t",
                    "TIMESTAMP",
                    nullable=False,
                    logical_type="timestamp",
                    analysis_role="timestamp",
                    description="Simulation timestamp for this snapshot row.",
                ),
                *self._agent_state_columns,
            ]
            schema = TableSchema(
                name=table_name,
                columns=[
                    *columns,
                ],
                primary_key=["agent_id", "step"],
                indexes=[["step"], ["t"]],
            )
            await self._replay_writer.register_table(schema)
            capabilities = ["agent_snapshot", "timeseries"]
            column_names = {col.name for col in columns}
            if {"lng", "lat"}.issubset(column_names):
                capabilities.extend(["geo_point", "trajectory"])
            await self._replay_writer.register_dataset(
                ReplayDatasetSpec(
                    dataset_id=f"{prefix}.agent_state",
                    table_name=table_name,
                    module_name=self.name,
                    kind="entity_snapshot",
                    title=f"{self.name} Agent State",
                    description=f"Per-agent replay snapshots exported by {self.name}.",
                    entity_key="agent_id",
                    step_key="step",
                    time_key="t",
                    default_order=["step", "agent_id"],
                    capabilities=capabilities,
                ),
                columns,
            )

        if self._env_state_columns:
            table_name = f"{prefix}_env_state"
            columns = [
                ColumnDef(
                    "step",
                    "INTEGER",
                    nullable=False,
                    logical_type="step",
                    analysis_role="timestamp",
                    description="Simulation step for this environment snapshot row.",
                ),
                ColumnDef(
                    "t",
                    "TIMESTAMP",
                    nullable=False,
                    logical_type="timestamp",
                    analysis_role="timestamp",
                    description="Simulation timestamp for this environment snapshot row.",
                ),
                *self._env_state_columns,
            ]
            schema = TableSchema(
                name=table_name,
                columns=[
                    *columns,
                ],
                primary_key=["step"],
                indexes=[["t"]],
            )
            await self._replay_writer.register_table(schema)
            await self._replay_writer.register_dataset(
                ReplayDatasetSpec(
                    dataset_id=f"{prefix}.env_state",
                    table_name=table_name,
                    module_name=self.name,
                    kind="env_snapshot",
                    title=f"{self.name} Environment State",
                    description=f"Per-step environment snapshots exported by {self.name}.",
                    entity_key=None,
                    step_key="step",
                    time_key="t",
                    default_order=["step"],
                    capabilities=["env_snapshot", "timeseries"],
                ),
                columns,
            )

        self._state_tables_registered = True

    async def _write_agent_state(
        self, agent_id: int, step: int, t: datetime, **data: Any
    ) -> None:
        """写入 per-agent 交互状态到 ``{prefix}_agent_state`` 表

        :param agent_id: Agent ID
        :param step: 当前步数
        :param t: 当前模拟时间
            **data: 模块自定义字段（需与 _agent_state_columns 声明匹配）
        """
        if self._replay_writer is None:
            return
        if not self._state_tables_registered:
            await self._register_state_tables()
        table_name = f"{self._state_table_prefix}_agent_state"
        await self._replay_writer.write(
            table_name, {"agent_id": agent_id, "step": step, "t": t, **data}
        )

    async def _write_agent_state_batch(
        self, step: int, t: datetime, records: list[dict[str, Any]]
    ) -> None:
        """批量写入 per-agent 交互状态

        :param step: 当前步数
        :param t: 当前模拟时间
        :param records: 记录列表，每条需包含 ``agent_id`` 和模块自定义字段
        """
        if self._replay_writer is None or not records:
            return
        if not self._state_tables_registered:
            await self._register_state_tables()
        table_name = f"{self._state_table_prefix}_agent_state"
        rows = [{"step": step, "t": t, **rec} for rec in records]
        await self._replay_writer.write_batch(table_name, rows)

    async def _write_env_state(self, step: int, t: datetime, **data: Any) -> None:
        """写入环境全局状态到 ``{prefix}_env_state`` 表

        :param step: 当前步数
        :param t: 当前模拟时间
            **data: 模块自定义字段（需与 _env_state_columns 声明匹配）
        """
        if self._replay_writer is None:
            return
        if not self._state_tables_registered:
            await self._register_state_tables()
        table_name = f"{self._state_table_prefix}_env_state"
        await self._replay_writer.write(table_name, {"step": step, "t": t, **data})
