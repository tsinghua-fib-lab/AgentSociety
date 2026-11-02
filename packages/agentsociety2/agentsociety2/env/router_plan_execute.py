"""
Plan-and-Execute Router Implementation
使用Plan-and-Execute模式：先制定计划，然后执行计划中的步骤
"""

import json
from typing import Any

from litellm import AllMessageValues
from openai.types.chat import ChatCompletionToolParam

from agentsociety2.agent.json_utils import loads_llm_json
from agentsociety2.env.base import EnvBase
from agentsociety2.env.router_base import RouterBase
from agentsociety2.logger import get_logger

__all__ = ["PlanExecuteRouter"]


class PlanExecuteRouter(RouterBase):
    """
    Plan-and-Execute模式Router：先制定计划，然后执行计划中的步骤。

    工作流程：
    1. 收集所有环境模块的工具信息
    2. 第一阶段：使用LLM制定执行计划（不调用工具）
    3. 第二阶段：按照计划逐步执行工具调用
    4. 根据执行结果生成最终答案
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

        # 预收集所有工具
        self._all_tools: list[ChatCompletionToolParam] = []
        self._all_readonly_tools: list[ChatCompletionToolParam] = []
        self._tool_name_to_module: dict[str, EnvBase] = {}
        self._tool_name_to_tool_obj: dict[str, Any] = {}

        self._collect_all_tools()

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

                    # 检查是否是readonly工具
                    readonly_tools = getattr(module.__class__, "_readonly_tools", {})
                    if readonly_tools.get(tool_name, False):
                        self._all_readonly_tools.append(tool_schema)

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
        使用Plan-and-Execute模式处理指令。

        :param ctx: 上下文字典
        :param instruction: 指令字符串
        :param readonly: 是否只读模式
        :param template_mode: 模板模式（PlanExecuteRouter 不使用，仅为签名兼容）

        :returns: (ctx, answer) 元组
        """
        self.set_trace_context(trace_id, parent_span_id)
        try:
            # 添加当前时间信息到 ctx，以便工具调用可以访问
            self._add_current_time_to_ctx(ctx)

            get_logger().info(
                f"PlanExecuteRouter: Processing instruction: {instruction}, readonly: {readonly}"
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

            # 第一阶段：制定计划
            plan = await self._create_plan(instruction, ctx, readonly, available_tools)
            if not plan:
                results = {
                    "status": "fail",
                    "reason": "Failed to create execution plan",
                }
                return results, "Failed to create execution plan."

            get_logger().info(f"PlanExecuteRouter: Created plan with {len(plan)} steps")

            # 第二阶段：执行计划（支持replan）
            results = {}
            execution_log = []
            status = "unknown"  # 初始状态，LLM可以在执行过程中设置
            plan_attempts = 0
            max_plan_attempts = 3  # 最多允许3次replan

            while plan_attempts < max_plan_attempts:
                plan_attempts += 1
                get_logger().info(
                    f"PlanExecuteRouter: Executing plan attempt {plan_attempts}/{max_plan_attempts}"
                )

                # 执行当前计划
                plan_completed = False
                for step_idx, step in enumerate(plan):
                    if step_idx >= self.max_steps:
                        get_logger().warning(
                            f"PlanExecuteRouter: Reached max steps at step {step_idx}"
                        )
                        break

                    get_logger().debug(
                        f"PlanExecuteRouter: Executing step {step_idx + 1}/{len(plan)}: {step.get('description', 'N/A')}"
                    )

                    # 执行步骤
                    step_result = await self._execute_step(
                        step, ctx, readonly, results, execution_log, instruction
                    )
                    execution_log.append(
                        {
                            "step": step_idx + 1,
                            "plan_attempt": plan_attempts,
                            "description": step.get("description", ""),
                            "result": step_result,
                        }
                    )

                    # 检查是否是replan请求或需要replan的错误
                    should_replan = False
                    replan_reason = ""

                    if isinstance(step_result, dict):
                        if step_result.get("_replan_requested"):
                            should_replan = True
                            replan_reason = step_result.get(
                                "reason", "Replan requested"
                            )
                            step_result.pop("_replan_requested", None)
                        elif step_result.get("_error_suggests_replan"):
                            should_replan = True
                            replan_reason = step_result.get(
                                "error", "Recoverable error encountered"
                            )
                            step_result.pop("_error_suggests_replan", None)
                            step_result.pop("_recoverable_error", None)

                    if should_replan:
                        get_logger().info(
                            f"PlanExecuteRouter: Replan triggered at step {step_idx + 1}: {replan_reason}"
                        )
                        # 重新制定计划
                        new_plan = await self._create_replan(
                            instruction,
                            ctx,
                            readonly,
                            available_tools,
                            results,
                            execution_log,
                        )
                        if new_plan:
                            plan = new_plan
                            get_logger().info(
                                f"PlanExecuteRouter: Created new plan with {len(plan)} steps"
                            )
                            # 记录replan事件
                            execution_log.append(
                                {
                                    "step": step_idx + 1,
                                    "plan_attempt": plan_attempts,
                                    "type": "replan",
                                    "description": f"Replanning due to: {replan_reason}",
                                    "new_plan_steps": len(plan),
                                }
                            )
                            plan_completed = False
                            break  # 跳出当前计划执行，开始执行新计划
                        else:
                            get_logger().warning(
                                "PlanExecuteRouter: Failed to create replan, continuing with current plan"
                            )

                    # 更新results
                    if isinstance(step_result, dict):
                        results.update(step_result)
                        # 检查是否设置了status
                        if "status" in step_result:
                            status = step_result["status"]
                            # 如果status是success或fail，计划完成
                            if status in ["success", "fail", "error"]:
                                plan_completed = True
                                break

                # 如果计划完成或达到最大尝试次数，退出循环
                if plan_completed or plan_attempts >= max_plan_attempts:
                    break

            # 初步检查是否有明显的错误
            error = None
            for log_entry in execution_log:
                step_result = log_entry.get("result", {})
                if isinstance(step_result, dict) and "error" in step_result:
                    error = step_result.get("error")
                    break

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

    async def _create_plan(
        self,
        instruction: str,
        ctx: dict,
        readonly: bool,
        available_tools: list[ChatCompletionToolParam],
    ) -> list[dict[str, Any]]:
        """创建执行计划"""
        # 构建工具列表描述
        tools_description = self._format_tools_description(available_tools)

        # 使用改进的prompt构建方法
        base_prompt = self._build_plan_prompt_with_status(instruction, ctx, readonly)

        prompt = f"""{base_prompt}

## Available Tools
{tools_description}

## Instructions
Create a detailed execution plan with the following format:
- Each step should specify: tool name, arguments (as a JSON object), and a brief description
- Steps should be ordered logically
- You can reference results from previous steps using step numbers
- The plan should be complete enough to accomplish the task
- Include a final step with tool="set_status" to set the execution status
- If you encounter issues during execution (e.g., missing parameters, invalid inputs), you can use tool="replan" to request a new plan based on current results

## Output Format
Return a JSON array of steps, where each step is:
{{
    "step": <step_number>,
    "tool": "<tool_name>",
    "arguments": {{<tool_arguments_as_json>}},
    "description": "<brief_description>"
}}

Example:
[
    {{
        "step": 1,
        "tool": "get_user_info",
        "arguments": {{"user_id": 123}},
        "description": "Get user information"
    }},
    {{
        "step": 2,
        "tool": "update_user_status",
        "arguments": {{"user_id": 123, "status": "active"}},
        "description": "Update user status based on step 1 results"
    }},
    {{
        "step": 3,
        "tool": "set_status",
        "arguments": {{"status": "success", "reason": "Task completed successfully"}},
        "description": "Set final execution status"
    }}
]

Note: If during execution you encounter issues like missing parameters or invalid inputs, you can add a step with tool="replan" and arguments={{"reason": "explanation of why replan is needed"}} to request a new plan.

Your plan:"""

        dialog: list[AllMessageValues] = [{"role": "user", "content": prompt}]

        try:
            response = await self.acompletion_with_system_prompt(
                model="coder",
                messages=dialog,
            )

            plan_text = response.choices[0].message.content or "[]"  # type: ignore

            # 尝试从响应中提取JSON
            plan = self._extract_json_from_text(plan_text)

            if not isinstance(plan, list):
                get_logger().error(f"PlanExecuteRouter: Invalid plan format: {plan}")
                return []

            return plan

        except Exception as e:
            get_logger().error(f"PlanExecuteRouter: Failed to create plan: {e!s}")
            return []

    async def _create_replan(
        self,
        instruction: str,
        ctx: dict,
        readonly: bool,
        available_tools: list[ChatCompletionToolParam],
        current_results: dict,
        execution_log: list,
    ) -> list[dict[str, Any]]:
        """创建重新计划，基于当前执行结果和错误信息"""
        # 构建工具列表描述
        tools_description = self._format_tools_description(available_tools)

        # 构建当前执行状态摘要
        execution_summary = self._build_execution_summary(
            execution_log, current_results
        )

        readonly_note = (
            " (READONLY MODE - you can only use read-only tools)" if readonly else ""
        )
        context_repr = repr(ctx)

        prompt = f"""You are a planning assistant. Create a NEW execution plan based on the current execution state and encountered issues.

## Agent Input

### Instruction

The instruction is the task that the agent needs to accomplish:

<instruction>{instruction}</instruction>

### Context

The context is a Python dictionary containing the agent input data. You can access values from context when calling tools:

```python
ctx = {context_repr}
```

## Current Execution State

### Execution Summary
{execution_summary}

### Current Results
```python
{json.dumps(current_results, indent=2, default=str)}
```

## Available Tools
{tools_description}

## Instructions

Create a NEW execution plan that:
1. Takes into account the current execution state and results
2. Addresses any issues encountered in previous execution
3. Uses information gathered so far to complete the task
4. Each step should specify: tool name, arguments (as a JSON object), and a brief description
5. Steps should be ordered logically
6. You can reference results from previous execution using the current results
7. Include a final step with tool="set_status" to set the execution status{readonly_note}

## Status Meanings

- **success**: The task has been completed successfully. All required operations finished without errors.
- **in_progress**: The task is still being executed or more steps are needed. The agent need to check whether it is done in the next steps.
- **fail**: The task could not be completed (e.g., unsupported instruction, missing data, invalid input). Include detailed reason.
- **error**: An error occurred during code execution. Must include error details.

## Output Format

Return a JSON array of steps, where each step is:
{{
    "step": <step_number>,
    "tool": "<tool_name>",
    "arguments": {{<tool_arguments_as_json>}},
    "description": "<brief_description>"
}}

Your new plan:"""

        dialog: list[AllMessageValues] = [{"role": "user", "content": prompt}]

        try:
            response = await self.acompletion_with_system_prompt(
                model="coder",
                messages=dialog,
            )

            plan_text = response.choices[0].message.content or "[]"  # type: ignore

            # 尝试从响应中提取JSON
            plan = self._extract_json_from_text(plan_text)

            if not isinstance(plan, list):
                get_logger().error(f"PlanExecuteRouter: Invalid replan format: {plan}")
                return []

            return plan

        except Exception as e:
            get_logger().error(f"PlanExecuteRouter: Failed to create replan: {e!s}")
            return []

    def _build_execution_summary(
        self, execution_log: list, current_results: dict
    ) -> str:
        """构建执行摘要，用于replan"""
        summary_lines = []

        # 统计执行步骤
        completed_steps = [log for log in execution_log if log.get("type") != "replan"]
        summary_lines.append(f"- Total steps executed: {len(completed_steps)}")

        # 检查错误
        errors = []
        for log_entry in execution_log:
            result = log_entry.get("result", {})
            if isinstance(result, dict) and "error" in result:
                errors.append(
                    {
                        "step": log_entry.get("step", "unknown"),
                        "description": log_entry.get("description", ""),
                        "error": result.get("error", ""),
                    }
                )

        if errors:
            summary_lines.append(f"\n- Errors encountered: {len(errors)}")
            for error_info in errors[:3]:  # 只显示前3个错误
                summary_lines.append(
                    f"  Step {error_info['step']}: {error_info.get('description', 'N/A')}"
                )
                summary_lines.append(f"    Error: {error_info['error']}")

        # 检查成功执行的步骤
        successful_steps = [
            log
            for log in execution_log
            if isinstance(log.get("result"), dict)
            and "error" not in log.get("result", {})
            and log.get("type") != "replan"
        ]
        if successful_steps:
            summary_lines.append(f"\n- Successful steps: {len(successful_steps)}")
            for step in successful_steps[:3]:  # 只显示前3个成功步骤
                summary_lines.append(
                    f"  Step {step.get('step', 'unknown')}: {step.get('description', 'N/A')}"
                )

        # 检查是否有status设置
        if "status" in current_results:
            summary_lines.append(
                f"\n- Current status: {current_results.get('status', 'unknown')}"
            )

        return (
            "\n".join(summary_lines)
            if summary_lines
            else "No execution history available."
        )

    def _extract_json_from_text(self, text: str) -> Any:
        """从文本中提取 JSON；失败时返回空列表。"""
        try:
            return loads_llm_json(text, expect="any")
        except ValueError:
            get_logger().debug("Failed to parse JSON from text", exc_info=True)
            return []

    def _format_tools_description(self, tools: list[ChatCompletionToolParam]) -> str:
        """格式化工具描述"""
        descriptions = []
        for tool in tools:
            func_info = tool["function"]
            descriptions.append(
                f"- {func_info['name']}: {func_info.get('description', 'No description')}\n"
                f"  Parameters: {json.dumps(func_info.get('parameters', {}), indent=2)}"
            )
        return "\n".join(descriptions)

    async def _execute_step(
        self,
        step: dict[str, Any],
        ctx: dict,
        readonly: bool,
        results: dict,
        execution_log: list,
        instruction: str,
    ) -> Any:
        """执行计划中的一个步骤"""
        tool_name = step.get("tool")
        arguments = step.get("arguments", {})

        if not tool_name:
            return {"error": "Step missing tool name"}

        # 处理set_status工具
        if tool_name == "set_status":
            status = arguments.get("status", "unknown")
            reason = arguments.get("reason", "")
            result = {"status": status}
            if reason:
                result["reason"] = reason
            get_logger().info(f"PlanExecuteRouter: Status set to {status}")
            return result

        # 处理replan工具
        if tool_name == "replan":
            reason = arguments.get("reason", "Execution issues encountered")
            get_logger().info(f"PlanExecuteRouter: Replan requested: {reason}")
            return {"_replan_requested": True, "reason": reason}

        try:
            result = await self._execute_tool(tool_name, arguments, readonly)
            # 检查结果中是否有错误，如果有且是参数错误等可恢复的错误，标记为可能需要replan
            if isinstance(result, dict) and "error" in result:
                error_msg = result.get("error", "")
                # 检查是否是参数相关的错误（可能需要replan）
                replan_keywords = [
                    "missing",
                    "required",
                    "invalid",
                    "not found",
                    "cannot",
                    "not available",
                    "not exist",
                ]
                if any(keyword in error_msg.lower() for keyword in replan_keywords):
                    get_logger().warning(
                        f"PlanExecuteRouter: Potential replan trigger - error: {error_msg}"
                    )
                    # 标记错误为可恢复的，但不在这一步自动触发replan
                    # 让计划执行循环检查是否需要replan
                    result["_recoverable_error"] = "true"  # type: ignore
                    result["_error_suggests_replan"] = "true"  # type: ignore
            return result
        except Exception as e:
            error_msg = f"Error executing {tool_name}: {e!s}"
            get_logger().error(f"PlanExecuteRouter: {error_msg}")
            # 检查异常是否是参数相关的
            error_str = str(e).lower()
            replan_keywords = [
                "missing",
                "required",
                "invalid",
                "not found",
                "cannot",
                "not available",
            ]
            result: dict[str, Any] = {"error": error_msg}
            if any(keyword in error_str for keyword in replan_keywords):
                result["_recoverable_error"] = "true"
                result["_error_suggests_replan"] = "true"
            return result

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

    def _build_plan_prompt_with_status(
        self, instruction: str, ctx: dict, readonly: bool
    ) -> str:
        """构建包含status设置说明的计划prompt"""
        readonly_note = (
            " (READONLY MODE - you can only use read-only tools)" if readonly else ""
        )
        context_repr = repr(ctx)

        return f"""You are a planning assistant. Create a step-by-step execution plan to accomplish the given task.

## Agent Input

### Instruction

The instruction is the task that the agent needs to accomplish:

<instruction>{instruction}</instruction>

### Context

The context is a Python dictionary containing the agent input data. You can access values from context when calling tools:

```python
ctx = {context_repr}
```

## Instructions

When creating the plan, you can include a special step to set the execution status:
- Add a step with tool="set_status" and arguments={{"status": "success|in_progress|fail|error", "reason": "optional reason"}}
- This should typically be the last step in your plan
- Use "success" when the task will be completed successfully
- Use "in_progress" when the task requires more steps
- Use "fail" when the task cannot be completed
- Use "error" when an error is expected{readonly_note}

## Status Meanings

- **success**: The task has been completed successfully. All required operations finished without errors.
- **in_progress**: The task is still being executed or more steps are needed. The agent need to check whether it is done in the next steps.
- **fail**: The task could not be completed (e.g., unsupported instruction, missing data, invalid input). Include detailed reason.
- **error**: An error occurred during code execution. Must include error details."""
