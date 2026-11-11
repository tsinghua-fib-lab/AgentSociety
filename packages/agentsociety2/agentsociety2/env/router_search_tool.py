"""
Search Tool as Tool Router Implementation
增加一个search tool，使用search tool先找到合适的模块函数，然后使用function calling调用候选函数
"""

import json
from typing import Any

from litellm import AllMessageValues
from openai.types.chat import ChatCompletionToolParam

from agentsociety2.agent.json_utils import loads_llm_json
from agentsociety2.config.llm_dispatcher import reasoning_fields
from agentsociety2.env.base import EnvBase
from agentsociety2.env.router_base import RouterBase
from agentsociety2.logger import get_logger

__all__ = ["SearchToolRouter"]


class SearchToolRouter(RouterBase):
    """Search Tool as Tool模式Router：增加一个search tool，先搜索合适的模块函数，然后调用候选函数。

    工作流程：
    1. 提供一个``search_tool``，可以搜索所有可用的工具
    2. 使用LLM的function calling能力，先调用``search_tool``找到相关工具
    3. 然后使用function calling调用搜索到的候选工具
    4. 重复直到任务完成
    """

    def __init__(
        self,
        env_modules: list[EnvBase],
        max_steps: int = 10,
        max_llm_call_retry: int = 10,
    ):
        super().__init__(
            env_modules=env_modules,
            max_steps=max_steps,
            max_llm_call_retry=max_llm_call_retry,
        )

        # 预收集所有工具信息
        self._all_tools: list[ChatCompletionToolParam] = []
        self._all_readonly_tools: list[ChatCompletionToolParam] = []
        self._tool_name_to_module: dict[str, EnvBase] = {}
        self._tool_name_to_tool_obj: dict[str, Any] = {}
        self._tool_descriptions: dict[str, str] = {}

        self._collect_all_tools()

        # 创建search tool的schema
        self._search_tool_schema = self._create_search_tool_schema()

        # 创建set_status工具的schema
        self._set_status_tool_schema = self._create_set_status_tool_schema()

    def _collect_all_tools(self):
        """收集所有模块的所有工具"""
        for module in self.env_modules:
            registered_tools = getattr(module.__class__, "_registered_tools", {})

            for tool_name, tool_obj in registered_tools.items():
                # 获取工具的LLM格式schema
                tool_schema: ChatCompletionToolParam | None = None
                for llm_tool in module._llm_tools:
                    if llm_tool["function"]["name"] == tool_name:
                        tool_schema = llm_tool
                        break

                if tool_schema:
                    self._all_tools.append(tool_schema)
                    self._tool_name_to_module[tool_name] = module
                    self._tool_name_to_tool_obj[tool_name] = tool_obj

                    # 保存工具描述
                    func_info = tool_schema["function"]
                    self._tool_descriptions[tool_name] = func_info.get(
                        "description", ""
                    )

                    # 检查是否是readonly工具
                    readonly_tools = getattr(module.__class__, "_readonly_tools", {})
                    if readonly_tools.get(tool_name, False):
                        self._all_readonly_tools.append(tool_schema)

    def _create_search_tool_schema(self) -> dict[str, Any]:
        """创建search tool的schema"""
        return {
            "type": "function",
            "function": {
                "name": "search_tools",
                "description": "Search for available tools that match a query. Use this tool to find relevant tools before calling them.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Search query describing what kind of tool you need (e.g., 'get user information', 'update database', 'send message')",
                        },
                        "max_results": {
                            "type": "integer",
                            "description": "Maximum number of results to return (default: 5)",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
            },
        }

    def _create_set_status_tool_schema(self) -> dict[str, Any]:
        """创建``set_status``工具的schema"""
        return {
            "type": "function",
            "function": {
                "name": "set_status",
                "description": "Set the execution status for the current task. Call this when you have completed the task or determined the outcome.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["success", "in_progress", "fail", "error"],
                            "description": "The execution status: 'success' (task completed successfully), 'in_progress' (task still executing, more steps needed), 'fail' (task cannot be completed), 'error' (error occurred during execution)",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Optional reason or explanation for the status (especially for 'fail' or 'error' status)",
                        },
                    },
                    "required": ["status"],
                },
            },
        }

    async def ask(
        self,
        ctx: dict,
        instruction: str,
        readonly: bool = False,
        template_mode: bool = False,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ) -> tuple[dict, str]:
        """
        使用Search Tool模式处理指令。

        :param ctx: 上下文字典
        :param instruction: 指令字符串
        :param readonly: 是否只读模式
        :param template_mode: 模板模式（SearchToolRouter 不使用，仅为签名兼容）

        :returns: (ctx, answer) 元组
        """
        self.set_trace_context(trace_id, parent_span_id)
        try:
            # 添加当前时间信息到 ctx，以便工具调用可以访问
            self._add_current_time_to_ctx(ctx)

            get_logger().info(
                f"SearchToolRouter: Processing instruction: {instruction}, readonly: {readonly}"
            )

            if not self.env_modules:
                get_logger().warning("No environment modules available")
                results = {
                    "status": "fail",
                    "reason": "No environment modules available",
                }
                return (
                    results,
                    "No environment modules available to handle the request.",
                )

            # 选择可用的工具列表
            available_tools = self._all_readonly_tools if readonly else self._all_tools

            if not available_tools:
                results = {
                    "status": "fail",
                    "reason": "No available tools to handle the request",
                }
                return results, "No available tools to handle the request."

            # 构建初始对话，包含ctx和instruction
            initial_prompt = self._build_initial_prompt(instruction, ctx, readonly)
            dialog: list[AllMessageValues] = [
                {"role": "user", "content": initial_prompt}
            ]

            results = {}
            step_count = 0
            discovered_tools: set = set()  # 已发现的工具集合
            execution_log: list[dict[str, Any]] = []  # 记录执行历史
            # status 表示用户的指令在环境模块中是否被有效地完成了，还是需要等待一段时间后由用户主动检测指令的完成性
            status = "success"
            error = None

            while step_count < self.max_steps:
                step_count += 1
                get_logger().debug(
                    f"SearchToolRouter: Step {step_count}/{self.max_steps}"
                )

                # 确定当前可用的工具列表
                # 如果还没有发现工具，只提供search_tool + set_status
                # 如果已经发现工具，提供search_tool + set_status + 已发现的工具
                current_tools: list[ChatCompletionToolParam | dict[str, Any]] = [
                    self._search_tool_schema,
                    self._set_status_tool_schema,
                ]
                if discovered_tools:
                    # 添加已发现的工具
                    for tool_name in discovered_tools:
                        tool_schema = next(
                            (
                                t
                                for t in available_tools
                                if t["function"]["name"] == tool_name
                            ),
                            None,
                        )
                        if tool_schema:
                            current_tools.append(tool_schema)

                # 调用LLM
                try:
                    call_kwargs = {
                        "model": "coder",
                        "messages": dialog,
                    }
                    # 只有在提供tools时才设置tool_choice
                    if current_tools:
                        call_kwargs["tools"] = current_tools
                        call_kwargs["tool_choice"] = "auto"

                    response = await self.acompletion_with_system_prompt(**call_kwargs)
                except Exception as e:
                    get_logger().error(f"SearchToolRouter: LLM call failed: {e!s}")
                    error = str(e)
                    # 构建过程文本
                    process_text = (
                        json.dumps(execution_log, indent=2, default=str)
                        if execution_log
                        else ""
                    )
                    # 使用基类的generate_final_answer生成最终答案
                    final_answer, determined_status = await self.generate_final_answer(
                        ctx, instruction, results, process_text, "error", error
                    )
                    results["status"] = determined_status
                    results["error"] = error
                    return results, final_answer

                # 检查tool calls
                message = response.choices[0].message  # type: ignore
                tool_calls = getattr(message, "tool_calls", None) or []
                assistant_content = message.content or ""

                # 记录assistant响应
                execution_log.append(
                    {
                        "step": step_count,
                        "type": "assistant_response",
                        "content": assistant_content,
                        "tool_calls_count": len(tool_calls),
                    }
                )

                # 添加assistant响应
                dialog.append(
                    {
                        "role": "assistant",
                        **reasoning_fields(response),
                        "content": assistant_content,
                        "tool_calls": (
                            [
                                {
                                    "id": tc.id,
                                    "type": tc.type,
                                    "function": {
                                        "name": tc.function.name,
                                        "arguments": tc.function.arguments,
                                    },
                                }
                                for tc in tool_calls
                            ]
                            if tool_calls
                            else None
                        ),
                    }
                )

                # 如果没有tool calls，说明LLM认为任务完成
                if not tool_calls:
                    get_logger().info(
                        f"SearchToolRouter: Task completed after {step_count} steps"
                    )
                    # 构建过程文本
                    process_text = (
                        json.dumps(execution_log, indent=2, default=str)
                        if execution_log
                        else ""
                    )
                    # 使用基类的generate_final_answer生成最终答案
                    final_answer, determined_status = await self.generate_final_answer(
                        ctx, instruction, results, process_text, status, error
                    )
                    results["status"] = determined_status
                    if error:
                        results["error"] = error
                    return results, final_answer

                # 执行所有tool calls
                tool_results = []
                step_tool_calls = []
                for tool_call in tool_calls:
                    func_name = tool_call.function.name
                    func_args_str = tool_call.function.arguments

                    try:
                        func_args = loads_llm_json(func_args_str, expect="object")
                    except Exception as e:
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": func_name,
                                "content": json.dumps(
                                    {"error": f"Invalid JSON arguments: {e!s}"}
                                ),
                            }
                        )
                        continue

                    # 处理search_tool调用
                    if func_name == "search_tools":
                        search_result = await self._search_tools(
                            func_args.get("query", ""),
                            func_args.get("max_results", 5),
                            readonly,
                        )
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": func_name,
                                "content": json.dumps(search_result, indent=2),
                            }
                        )
                        # 记录发现的工具
                        for tool_info in search_result.get("tools", []):
                            discovered_tools.add(tool_info["name"])
                        step_tool_calls.append(
                            {
                                "tool": func_name,
                                "arguments": func_args,
                                "result": search_result,
                                "success": True,
                            }
                        )
                    elif func_name == "set_status":
                        status = func_args.get("status", "unknown")
                        reason = func_args.get("reason", "")
                        results["status"] = status
                        if reason:
                            results["reason"] = reason
                        tool_results.append(
                            {
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "name": func_name,
                                "content": json.dumps(
                                    {
                                        "status": status,
                                        "message": "Status set successfully",
                                    }
                                ),
                            }
                        )
                        step_tool_calls.append(
                            {
                                "tool": func_name,
                                "arguments": func_args,
                                "result": {"status": status},
                                "success": True,
                            }
                        )
                        get_logger().info(f"SearchToolRouter: Status set to {status}")
                    else:
                        # 执行普通工具调用
                        try:
                            result = await self._execute_tool(
                                func_name, func_args, readonly
                            )
                            result_str = json.dumps(result, default=str)
                            tool_results.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": func_name,
                                    "content": result_str,
                                }
                            )
                            results[func_name] = result
                            step_tool_calls.append(
                                {
                                    "tool": func_name,
                                    "arguments": func_args,
                                    "result": result,
                                    "success": True,
                                }
                            )
                            get_logger().debug(
                                f"SearchToolRouter: Executed tool {func_name}"
                            )
                        except Exception as e:
                            error_msg = f"Error executing {func_name}: {e!s}"
                            get_logger().error(f"SearchToolRouter: {error_msg}")
                            error_result = {"error": error_msg}
                            tool_results.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": tool_call.id,
                                    "name": func_name,
                                    "content": json.dumps(error_result),
                                }
                            )
                            step_tool_calls.append(
                                {
                                    "tool": func_name,
                                    "arguments": func_args,
                                    "result": error_result,
                                    "success": False,
                                }
                            )
                            # 记录错误，但status由LLM在summary中判定
                            error = error_msg

                # 记录工具调用结果
                execution_log.append(
                    {
                        "step": step_count,
                        "type": "tool_execution",
                        "tool_calls": step_tool_calls,
                    }
                )

                # 将工具执行结果添加到对话
                dialog.extend(tool_results)

            # 达到最大步数
            get_logger().warning(
                f"SearchToolRouter: Reached max steps ({self.max_steps})"
            )
            # 构建过程文本
            process_text = (
                json.dumps(execution_log, indent=2, default=str)
                if execution_log
                else ""
            )
            # 使用基类的generate_final_answer生成最终答案
            final_answer, determined_status = await self.generate_final_answer(
                ctx, instruction, results, process_text, status, error
            )
            results["status"] = determined_status
            if error:
                results["error"] = error
            return results, final_answer
        finally:
            self.clear_trace_context()

    async def _search_tools(
        self, query: str, max_results: int, readonly: bool
    ) -> dict[str, Any]:
        """执行工具搜索"""
        # 使用简单的关键词匹配进行搜索
        query_lower = query.lower()
        query_words = set(query_lower.split())

        # 选择可用的工具
        available_tools = self._all_readonly_tools if readonly else self._all_tools

        # 计算每个工具的相关性分数
        tool_scores = []
        for tool in available_tools:
            tool_name = tool["function"]["name"]
            tool_desc = self._tool_descriptions.get(tool_name, "").lower()

            # 计算匹配分数
            score = 0
            # 名称匹配
            if query_lower in tool_name.lower():
                score += 10

            # 描述匹配
            for word in query_words:
                if word in tool_name.lower():
                    score += 5
                if word in tool_desc:
                    score += 2

            # 参数匹配（简单检查）
            params = tool["function"].get("parameters", {})
            if isinstance(params, dict):
                properties = params.get("properties", {})
                if isinstance(properties, dict):
                    for param_name in properties:
                        if query_lower in param_name.lower():
                            score += 1

            if score > 0:
                tool_scores.append((score, tool))

        # 按分数排序
        tool_scores.sort(key=lambda x: x[0], reverse=True)

        # 返回top结果
        top_tools = tool_scores[:max_results]

        result_tools = []
        for score, tool in top_tools:
            func_info = tool["function"]
            result_tools.append(
                {
                    "name": func_info["name"],
                    "description": func_info.get("description", ""),
                    "parameters": func_info.get("parameters", {}),
                    "relevance_score": score,
                }
            )

        return {
            "query": query,
            "results_count": len(result_tools),
            "tools": result_tools,
        }

    async def _execute_tool(self, tool_name: str, args: dict, readonly: bool) -> Any:
        """执行工具调用"""
        # 获取工具所属的模块
        module = self._tool_name_to_module.get(tool_name)
        if not module:
            raise ValueError(f"Tool {tool_name} not found")

        # 检查readonly约束
        readonly_tools = getattr(module.__class__, "_readonly_tools", {})
        if readonly and not readonly_tools.get(tool_name, False):
            raise ValueError(
                f"Tool {tool_name} is not readonly, but readonly mode is enabled"
            )

        # 获取工具对象
        tool_obj = self._tool_name_to_tool_obj.get(tool_name)
        if not tool_obj:
            raise ValueError(f"Tool object for {tool_name} not found")

        # 获取工具函数
        tool_func = tool_obj.fn
        if not tool_func:
            raise ValueError(f"Tool function for {tool_name} not found")

        # 执行工具函数（可能是async）
        import inspect

        if inspect.iscoroutinefunction(tool_func):
            result = await tool_func(module, **args)
        else:
            result = tool_func(module, **args)

        return result

    def _build_initial_prompt(self, instruction: str, ctx: dict, readonly: bool) -> str:
        """构建初始prompt，包含ctx和instruction"""
        readonly_note = (
            " (READONLY MODE - you can only use read-only tools)" if readonly else ""
        )
        context_repr = repr(ctx)

        prompt = f"""You are an AI assistant helping an agent accomplish tasks in a virtual world simulation environment.

## Agent Input

### Instruction

The instruction is the task that the agent needs to accomplish:

<instruction>{instruction}</instruction>

### Context

The context is a Python dictionary containing the agent input data. You can access values from context when calling tools:

```python
ctx = {context_repr}
```

## Available Tools

You have access to a search tool to find relevant environment tools, and then use those tools to accomplish the task.

## Instructions

1. **Search for tools** using the search_tools function to find relevant tools for your task
2. **Use the discovered tools** to gather information or perform actions
3. **Call set_status** when you have completed the task or determined the outcome:
   - Use "success" when the task is completed successfully
   - Use "in_progress" when the task is still executing and more steps are needed
   - Use "fail" when the task cannot be completed (e.g., unsupported instruction, missing data)
   - Use "error" when an error occurred during execution
4. **Continue the conversation** until the task is complete or you determine it cannot be completed{readonly_note}

## Status Meanings

- **success**: The task has been completed successfully. All required operations finished without errors.
- **in_progress**: The task is still being executed or more steps are needed. The agent need to check whether it is done in the next steps.
- **fail**: The task could not be completed (e.g., unsupported instruction, missing data, invalid input). Include detailed reason.
- **error**: An error occurred during code execution. Must include error details.

Let's start!"""

        return prompt
