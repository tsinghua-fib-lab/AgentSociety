"""仿真社会辅助模块。

本模块提供 :class:`AgentSocietyHelper` 类，实现 Plan-and-Execute 模式的外部请求处理。

LLM 结构化输出统一使用 **XML**（``elemental-xenon`` 修复畸形标签），不再使用 JSON 计划格式。
工具参数以嵌套 XML 传递；列表字段使用重复的 ``<item>`` 子节点。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import json_repair
from litellm import AllMessageValues
from pydantic import BaseModel, Field

from agentsociety2.config import build_client_for_role, get_model_name
from agentsociety2.env import RouterBase
from agentsociety2.logger import get_logger
from agentsociety2.society.llm_xml import (
    XmlParseError,
    normalize_args,
    normalize_steps,
    parse_xml_object,
)

__all__ = ["AgentSocietyHelper"]


def _to_json_string(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return json.dumps({"value": str(value)}, ensure_ascii=False)


def _truncate_text(text: str, max_len: int = 4000) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len] + "\n...[truncated]..."


class PlanStep(BaseModel):
    """A single step in the execution plan."""

    description: str
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    expected_output: str = ""


@dataclass
class _ToolDef:
    schema: dict[str, Any]
    fn: Callable[..., Any]


class AgentSocietyHelper:
    """
    Plan-and-Execute helper that answers external questions or executes interventions
    by first creating a plan, then executing steps, with support for dynamic replanning.
    """

    def __init__(
        self,
        env_router: RouterBase,
        society: Any,
        max_steps: int = 8,
        max_replans: int = 2,
        max_llm_call_retry: int = 10,
    ):
        """Create a plan-and-execute helper bound to a record-based society.

        The helper holds the :class:`AgentSociety` handle and reconstructs
        target agents on demand via ``society._reconstruct_agent`` /
        ``society._reconstruct_agents`` (low-volume external queries; workspaces
        are on local disk). Filter-by-profile over the full population works on
        the society's **specs** (no reconstruction) when the profile field is
        directly readable from the spec.

        :param env_router: Environment router (in-process or ``EnvRouterProxy``).
        :param society: The record-based :class:`AgentSociety` (holds specs/ids +
            reconstruction callbacks). Required.
        :param max_steps: Max plan steps per ask/intervene.
        :param max_replans: Max replan attempts on failure.
        :param max_llm_call_retry: Max LLM retries per planning/summary call.
        """
        self._dispatcher = build_client_for_role("coder")
        self._model_name = get_model_name("coder")
        self._env_router = env_router
        self._society = society
        self._max_steps = max(1, max_steps)
        self._max_replans = max(0, max_replans)
        self._max_llm_call_retry = max(1, max_llm_call_retry)
        self._tools: dict[str, _ToolDef] = {}
        self._current_readonly: bool = True
        self._register_tools()

    def _log_llm_raw_response(self, stage: str, response: str) -> None:
        logger = get_logger()
        logger.debug(
            "AgentSocietyHelper %s raw LLM response:\n%s",
            stage,
            _truncate_text(response),
        )

    def _parse_plan_payload(self, response: str) -> dict[str, Any]:
        """Parse a ``<plan>...</plan>`` XML payload from the model."""
        data = parse_xml_object(response, root_tag="plan")
        raw_steps = normalize_steps(data.get("steps"))
        steps: list[dict[str, Any]] = []
        for raw in raw_steps:
            steps.append(
                {
                    "description": str(raw.get("description") or "").strip(),
                    "tool": str(raw.get("tool") or "").strip(),
                    "args": normalize_args(raw.get("args")),
                    "expected_output": str(raw.get("expected_output") or "").strip(),
                }
            )
        data["steps"] = steps
        return data

    def _parse_answer_payload(self, response: str) -> dict[str, Any]:
        """Parse final-answer XML: ``<result><answer>...</answer></result>`` or bare ``<answer>``."""
        from agentsociety2.society.llm_xml import element_to_value, parse_xml_root

        root = parse_xml_root(response)
        if root.tag == "answer":
            return {"answer": (root.text or "").strip()}
        if root.tag == "result":
            data = {child.tag: element_to_value(child) for child in list(root)}
            if "answer" not in data:
                raise XmlParseError(
                    "Missing <answer> in <result>", raw_content=response
                )
            return data
        # Nested search
        answer_el = root.find(".//answer")
        if answer_el is not None:
            return {"answer": element_to_value(answer_el)}
        raise XmlParseError("No <answer> element found", raw_content=response)

    # ---- public API ----
    async def ask(self, question: str) -> str:
        return await self._run(question, readonly=True)

    async def intervene(self, instruction: str) -> str:
        return await self._run(instruction, readonly=False)

    # ---- internal: Plan-and-Execute loop ----
    async def _run(self, text: str, readonly: bool) -> str:
        mode = "Ask" if readonly else "Intervene"
        print(f"\n{'=' * 60}")
        print(f"AgentSocietyHelper Starting ({mode} Mode)")
        print(f"Task: {text}")
        print(f"{'=' * 60}\n")

        self._current_readonly = readonly

        # Planning stage
        plan = await self._create_plan(text, readonly)
        if isinstance(plan, str):
            # Planning returned direct answer or error
            return plan

        print(f"\n📋 Initial Plan ({len(plan)} steps):")
        for i, step in enumerate(plan, 1):
            print(f"  {i}. {step.description}")
        print()

        # Execution stage with dynamic replanning
        replan_count = 0
        execution_history: list[dict[str, Any]] = []

        while plan and replan_count <= self._max_replans:
            step_index = len(execution_history)
            if step_index >= len(plan):
                # All steps completed
                break

            if len(execution_history) >= self._max_steps:
                print(f"⚠️ Max steps ({self._max_steps}) reached\n")
                break

            current_step = plan[step_index]
            print(f"[Step {step_index + 1}/{len(plan)}] {current_step.description}")

            # Execute step
            try:
                result = await self._execute_step(current_step, execution_history)
                execution_history.append(
                    {
                        "step": current_step,
                        "result": result,
                        "success": True,
                    }
                )
                print(f"  ✓ Result: {_to_json_string(result)}\n")

            except Exception as e:
                get_logger().error(f"Step execution failed: {e}")
                execution_history.append(
                    {
                        "step": current_step,
                        "error": str(e),
                        "success": False,
                    }
                )
                print(f"  ✗ Error: {e!s}\n")

                # Check if replanning is needed
                if replan_count < self._max_replans:
                    print(
                        f"🔄 Replanning (attempt {replan_count + 1}/{self._max_replans})..."
                    )
                    new_plan = await self._replan(
                        text, plan, execution_history, readonly
                    )
                    if new_plan:
                        plan = new_plan
                        replan_count += 1
                        print(f"  Updated Plan ({len(plan)} steps):")
                        for i, step in enumerate(plan, 1):
                            print(f"    {i}. {step.description}")
                        print()
                    else:
                        print("  Replanning failed, continuing with original plan\n")

        # Phase 3: Generate final answer
        final_answer = await self._generate_final_answer(
            text, plan, execution_history, readonly
        )
        print(f"\n{'=' * 60}")
        print(f"✓ Completed ({len(execution_history)} steps executed)")
        print(f"Final Answer: {final_answer}")
        print(f"{'=' * 60}\n")
        return final_answer

    async def _create_plan(self, task: str, readonly: bool) -> str | list[PlanStep]:
        """Create an execution plan for the given task."""
        planning_prompt = self._build_planning_prompt(task, readonly)

        error_history = []
        for retry in range(self._max_llm_call_retry):
            # Build dialog with error history if this is a retry
            current_prompt = planning_prompt
            if error_history:
                error_feedback = "\n\n## Previous Attempt Errors\n"
                error_feedback += (
                    "The following attempts failed. Please fix these issues:\n\n"
                )
                for i, error_info in enumerate(error_history):
                    error_feedback += f"Attempt {i + 1}:\n"
                    error_feedback += f"Response: {error_info['response']}\n"
                    error_feedback += f"Error: {error_info['error']}\n\n"
                current_prompt = planning_prompt + error_feedback

            messages: list[AllMessageValues] = [
                {"role": "user", "content": current_prompt}
            ]

            try:
                resp = await self._dispatcher.call(
                    model=self._model_name,
                    messages=messages,
                    stream=False,
                )
                response = resp.choices[0].message.content  # type: ignore

                if not response:
                    if retry < self._max_llm_call_retry - 1:
                        error_history.append(
                            {
                                "response": "Empty response",
                                "error": "Model returned empty response",
                            }
                        )
                        continue
                    return "Planning failed: Empty model response"

                self._log_llm_raw_response(f"planning attempt {retry + 1}", response)
                plan_data = self._parse_plan_payload(response)

                # Check if this is a direct answer (no planning needed)
                if plan_data.get("direct_answer") is True:
                    return str(plan_data.get("answer", ""))

                # Extract and validate steps with PlanStep
                raw_steps = plan_data.get("steps", [])
                if not raw_steps:
                    if retry < self._max_llm_call_retry - 1:
                        error_history.append(
                            {
                                "response": response,
                                "error": "No valid steps were generated",
                            }
                        )
                        continue
                    return "Unable to create a plan for this task."

                # Validate each step with Pydantic
                try:
                    steps = [PlanStep.model_validate(step) for step in raw_steps]
                    return steps
                except Exception as validation_error:
                    if retry < self._max_llm_call_retry - 1:
                        error_history.append(
                            {
                                "response": response,
                                "error": f"Step validation failed: {validation_error!s}",
                            }
                        )
                        continue
                    return f"Plan validation failed: {validation_error!s}"

            except Exception as e:
                get_logger().error(f"Planning attempt {retry + 1} failed: {e}")
                if retry < self._max_llm_call_retry - 1:
                    error_history.append(
                        {
                            "response": resp.choices[0].message.content
                            if "resp" in locals()
                            else "No response",  # type: ignore
                            "error": str(e),
                        }
                    )
                    continue
                return f"Planning failed: {e!s}"

        return "Unable to create a plan for this task after multiple attempts."

    async def _execute_step(
        self, step: PlanStep, history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Execute a single step from the plan."""
        tool_name = step.tool
        args = dict(step.args or {})

        if tool_name not in self._tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        if tool_name == "ask_agents":
            args = self._enrich_ask_agents_args(args, history)

        result = await self._dispatch_tool(tool_name, args, self._current_readonly)
        return result

    def _enrich_ask_agents_args(
        self, args: dict[str, Any], history: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Fill missing ``agent_ids`` from prior list/filter step results."""
        ids = self._coerce_agent_ids(args.get("agent_ids"))
        if ids:
            args["agent_ids"] = ids
            return args
        for item in reversed(history):
            if not item.get("success"):
                continue
            result = item.get("result") or {}
            if "agent_ids" in result:
                ids = self._coerce_agent_ids(result.get("agent_ids"))
            elif "agents" in result:
                ids = self._coerce_agent_ids(
                    [row.get("id") for row in (result.get("agents") or [])]
                )
            else:
                continue
            if ids:
                args["agent_ids"] = ids
                break
        return args

    async def _replan(
        self,
        original_task: str,
        current_plan: list[PlanStep],
        execution_history: list[dict[str, Any]],
        readonly: bool,
    ) -> list[PlanStep] | None:
        """Create a new plan based on execution history and failures."""
        replanning_prompt = self._build_replanning_prompt(
            original_task, current_plan, execution_history, readonly
        )

        error_history = []
        for retry in range(self._max_llm_call_retry):
            response = None
            # Build dialog with error history if this is a retry
            current_prompt = replanning_prompt
            if error_history:
                error_feedback = "\n\n## Previous Attempt Errors\n"
                error_feedback += (
                    "The following attempts failed. Please fix these issues:\n\n"
                )
                for i, error_info in enumerate(error_history):
                    error_feedback += f"Attempt {i + 1}:\n"
                    error_feedback += f"Response: {error_info['response']}\n"
                    error_feedback += f"Error: {error_info['error']}\n\n"
                current_prompt = replanning_prompt + error_feedback

            try:
                messages: list[AllMessageValues] = [
                    {"role": "user", "content": current_prompt}
                ]

                resp = await self._dispatcher.call(
                    model=self._model_name,
                    messages=messages,
                    stream=False,
                )
                response = resp.choices[0].message.content  # type: ignore

                if not response:
                    if retry < self._max_llm_call_retry - 1:
                        error_history.append(
                            {
                                "response": "Empty response",
                                "error": "Model returned empty response",
                            }
                        )
                        continue
                    return None

                self._log_llm_raw_response(f"replanning attempt {retry + 1}", response)
                plan_data = self._parse_plan_payload(response)
                raw_steps = plan_data.get("steps", [])

                if not raw_steps:
                    if retry < self._max_llm_call_retry - 1:
                        error_history.append(
                            {
                                "response": response,
                                "error": "No valid steps were generated in replanning",
                            }
                        )
                        continue
                    return None

                # Validate steps with Pydantic
                try:
                    steps = [PlanStep.model_validate(step) for step in raw_steps]
                    return steps
                except Exception as validation_error:
                    if retry < self._max_llm_call_retry - 1:
                        error_history.append(
                            {
                                "response": response,
                                "error": f"Step validation failed: {validation_error!s}",
                            }
                        )
                        continue
                    return None

            except Exception as e:
                get_logger().error(f"Replanning attempt {retry + 1} failed: {e}")
                if retry < self._max_llm_call_retry - 1:
                    error_history.append(
                        {
                            "response": (
                                response if response is not None else "No response"
                            ),
                            "error": str(e),
                        }
                    )
                    continue
                return None

        return None

    async def _generate_final_answer(
        self,
        task: str,
        plan: list[PlanStep],
        execution_history: list[dict[str, Any]],
        readonly: bool,
    ) -> str:
        """Generate the final answer based on execution history."""
        summary_prompt = self._build_summary_prompt(
            task, plan, execution_history, readonly
        )

        error_history = []
        for retry in range(self._max_llm_call_retry):
            final_answer = None
            # Build dialog with error history if this is a retry
            current_prompt = summary_prompt
            if error_history:
                error_feedback = "\n\n## Previous Attempt Errors\n"
                error_feedback += (
                    "The following attempts failed. Please fix these issues:\n\n"
                )
                for i, error_info in enumerate(error_history):
                    error_feedback += f"Attempt {i + 1}:\n"
                    error_feedback += f"Response: {error_info['response']}\n"
                    error_feedback += f"Error: {error_info['error']}\n\n"
                current_prompt = summary_prompt + error_feedback

            try:
                messages: list[AllMessageValues] = [
                    {"role": "user", "content": current_prompt}
                ]

                resp = await self._dispatcher.call(
                    model=self._model_name,
                    messages=messages,
                    stream=False,
                )
                final_answer = resp.choices[0].message.content  # type: ignore

                if not final_answer:
                    if retry < self._max_llm_call_retry - 1:
                        error_history.append(
                            {
                                "response": "Empty response",
                                "error": "Model returned empty response",
                            }
                        )
                        continue
                    return "Unable to generate final answer based on execution results."

                self._log_llm_raw_response(
                    f"final answer attempt {retry + 1}", final_answer
                )
                try:
                    answer_data = self._parse_answer_payload(final_answer)
                    if "answer" not in answer_data:
                        if retry < self._max_llm_call_retry - 1:
                            error_history.append(
                                {
                                    "response": final_answer,
                                    "error": "Response XML missing <answer>",
                                }
                            )
                            continue
                        return "Unable to generate final answer based on execution results."
                    return str(answer_data.get("answer"))
                except Exception as parse_error:
                    if retry < self._max_llm_call_retry - 1:
                        error_history.append(
                            {
                                "response": final_answer,
                                "error": f"XML parse failed: {parse_error!s}",
                            }
                        )
                        continue
                    return "Unable to generate final answer based on execution results."

            except Exception as e:
                get_logger().error(
                    f"Final answer generation attempt {retry + 1} failed: {e}"
                )
                if retry < self._max_llm_call_retry - 1:
                    error_history.append(
                        {
                            "response": (
                                final_answer
                                if final_answer is not None
                                else "No response"
                            ),
                            "error": str(e),
                        }
                    )
                    continue
                return "Unable to generate final answer based on execution results."

        return "Unable to generate final answer based on execution results."

    async def _dispatch_tool(self, name: str, args: dict[str, Any], readonly: bool):
        # Internally propagate readonly to tools that interact with env/agents
        if name in {"ask_environment", "ask_agents"}:
            return await self._tools[name].fn(**args, readonly=readonly)
        return await self._tools[name].fn(**args)

    # ---- Prompt builders ----
    def _build_planning_prompt(self, task: str, readonly: bool) -> str:
        """Build the planning prompt with structured format."""
        mode = "information retrieval" if readonly else "intervention and modification"
        restriction = (
            "You MUST NOT modify the environment or agent states. Only use read-only operations."
            if readonly
            else "You MAY modify the environment or agent states as needed to accomplish the task."
        )

        tools_desc = []
        for name, tool_def in self._tools.items():
            func_info = tool_def.schema.get("function", {})
            props = ((func_info.get("parameters") or {}).get("properties")) or {}
            param_names = ", ".join(props.keys()) if isinstance(props, dict) else ""
            tools_desc.append(
                f"- **{name}**: {func_info.get('description', 'No description')}"
                + (f"\n  Args: {param_names}" if param_names else "\n  Args: (none)")
            )
        tools_text = "\n".join(tools_desc)

        return f"""# Task Planning for AgentSocietyHelper

## Objective
Create a step-by-step execution plan for {mode}.

## Task
{task}

## Constraints
{restriction}

## Available Tools
{tools_text}

## Planning Guidelines
1. Analyze the task and break it into sequential tool steps
2. Prefer `list_agents` / `get_agent_profile` / `filter_agents_by_profile` over `ask_environment` for agent roster or profile questions
3. Prefer `get_agent_profile` over `ask_agents` when the answer is already in the agent profile (personality, bio, location, age, specialty)
4. When calling `ask_agents`, always include concrete `<agent_ids><item>...</item></agent_ids>`
5. In intervention mode, `ask_environment` may execute environment actions; readonly mode automatically blocks mutations
6. Minimize steps; avoid redundant tool calls

## Response Format (XML only)
Respond with a single XML document. Do not use JSON.

**Plan that needs tools:**
```xml
<plan>
  <direct_answer>false</direct_answer>
  <reasoning>Brief planning strategy</reasoning>
  <steps>
    <step>
      <description>Clear description of this step</description>
      <tool>list_agents</tool>
      <args></args>
      <expected_output>Agent roster</expected_output>
    </step>
    <step>
      <description>Ask Alice about personality</description>
      <tool>ask_agents</tool>
      <args>
        <agent_ids>
          <item>1</item>
        </agent_ids>
        <question>Describe your personality and interests.</question>
      </args>
      <expected_output>Alice's self-description</expected_output>
    </step>
  </steps>
</plan>
```

**Direct answer (trivial only, no tools):**
```xml
<plan>
  <direct_answer>true</direct_answer>
  <answer>Direct answer text</answer>
</plan>
```

Lists use repeated `<item>` children. Nested tool arguments are nested XML elements, never JSON strings.

Now create the plan as XML:"""

    def _build_replanning_prompt(
        self,
        original_task: str,
        current_plan: list[PlanStep],
        execution_history: list[dict[str, Any]],
        readonly: bool,
    ) -> str:
        """Build the replanning prompt."""
        history_text = []
        for i, entry in enumerate(execution_history, 1):
            step = entry.get("step")
            success = entry.get("success", False)
            status = "SUCCESS" if success else "FAILED"

            if isinstance(step, PlanStep):
                step_desc = step.description
                tool_name = step.tool
            else:
                step_desc = (
                    step.get("description", "N/A") if isinstance(step, dict) else "N/A"
                )
                tool_name = step.get("tool", "N/A") if isinstance(step, dict) else "N/A"

            history_text.append(
                f"Step {i}:\n"
                f"  Description: {step_desc}\n"
                f"  Tool: {tool_name}\n"
                f"  Status: {status}\n"
                f"  Result: {_to_json_string(entry.get('result') if success else entry.get('error'))}"
            )
        history_summary = "\n\n".join(history_text)

        tools_desc = []
        for name, tool_def in self._tools.items():
            func_info = tool_def.schema.get("function", {})
            params_schema = func_info.get("parameters") or {}
            props = params_schema.get("properties") or {}
            param_names = ", ".join(props.keys()) if isinstance(props, dict) else ""
            tools_desc.append(
                f"- **{name}**: {func_info.get('description', 'No description')}"
                + (f"\n  Args: {param_names}" if param_names else "\n  Args: (none)")
            )
        tools_text = "\n".join(tools_desc)

        return f"""# Plan Adjustment for AgentSocietyHelper

## Original Task
{original_task}

## Execution History (with SUCCESS/FAILED status)
{history_summary}

**Note**: Each step includes Status (SUCCESS/FAILED) and Result/error payload.

## Available Tools
{tools_text}

## Replanning Objective
Create an updated plan to finish the original task.

**CRITICAL RULES**:
1. DO NOT repeat SUCCESS steps
2. Learn from FAILED steps and change approach
3. Reuse data returned by SUCCESS steps (especially agent ids)

## Response Format (XML only)
```xml
<plan>
  <reasoning>What failed and how you adjust</reasoning>
  <steps>
    <step>
      <description>...</description>
      <tool>ask_agents</tool>
      <args>
        <agent_ids>
          <item>1</item>
        </agent_ids>
        <question>...</question>
      </args>
      <expected_output>...</expected_output>
    </step>
  </steps>
</plan>
```

Create the updated plan as XML:"""

    def _build_summary_prompt(
        self,
        task: str,
        plan: list[PlanStep],
        execution_history: list[dict[str, Any]],
        readonly: bool,
    ) -> str:
        """Build the summary prompt to generate final answer."""
        history_text = []
        for i, entry in enumerate(execution_history, 1):
            step = entry.get("step")
            success = entry.get("success", False)

            if isinstance(step, PlanStep):
                step_desc = step.description
                tool_name = step.tool
            else:
                step_desc = (
                    step.get("description", "N/A") if isinstance(step, dict) else "N/A"
                )
                tool_name = step.get("tool", "N/A") if isinstance(step, dict) else "N/A"

            history_text.append(
                f"Step {i}: {step_desc}\n"
                f"  Tool: {tool_name}\n"
                f"  Success: {success}\n"
                f"  Result: {_to_json_string(entry.get('result') if success else entry.get('error'))}"
            )
        execution_summary = "\n\n".join(history_text)

        return f"""# Final Answer Generation for AgentSocietyHelper

## Original Task
{task}

## Execution Summary
{execution_summary}

## Objective
Based on the execution results above, generate a clear, concise, and accurate final answer to the original task.

## Guidelines
1. **Synthesize information** from all successful step results
2. **Address the task directly** - answer what was asked
3. **Be concise** - provide only relevant information
4. **Use the user's language** - respond in the same language as the task
5. **Acknowledge failures** if they prevented completing the task
6. **Be factual** - only state what the execution results support

## Response Format (XML only)
```xml
<result>
  <answer>Your clear and direct final answer</answer>
</result>
```

Generate the final answer as XML:"""

    # ---- tool registration ----
    def _register_tools(self):
        self._tools = {
            "get_current_time": _ToolDef(
                schema={
                    "type": "function",
                    "function": {
                        "name": "get_current_time",
                        "description": "Return current simulation datetime as ISO string.",
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
                fn=self._tool_get_current_time,
            ),
            "list_agents": _ToolDef(
                schema={
                    "type": "function",
                    "function": {
                        "name": "list_agents",
                        "description": (
                            "List all agents in the simulation (id and name) from "
                            "society agent specs. Prefer this over ask_environment "
                            "when you need the agent roster."
                        ),
                        "parameters": {"type": "object", "properties": {}},
                    },
                },
                fn=self._tool_list_agents,
            ),
            "get_agent_profile": _ToolDef(
                schema={
                    "type": "function",
                    "function": {
                        "name": "get_agent_profile",
                        "description": (
                            "Return one agent's full profile from society specs "
                            "(no agent LLM call). Look up by agent_id and/or name. "
                            "Prefer this for personality/bio/location questions."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "agent_id": {"type": ["number", "string", "null"]},
                                "name": {"type": ["string", "null"]},
                            },
                        },
                    },
                },
                fn=self._tool_get_agent_profile,
            ),
            "filter_agents_by_profile": _ToolDef(
                schema={
                    "type": "function",
                    "function": {
                        "name": "filter_agents_by_profile",
                        "description": (
                            "Filter agents by asking each agent for a profile field and matching equality. "
                            "Use field like 'gender' and value like 'male' or 'female'."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "field": {"type": "string"},
                                "value": {"type": ["string", "number", "boolean"]},
                            },
                            "required": ["field", "value"],
                        },
                    },
                },
                fn=self._tool_filter_agents_by_profile,
            ),
            "ask_environment": _ToolDef(
                schema={
                    "type": "function",
                    "function": {
                        "name": "ask_environment",
                        "description": (
                            "Send a query or action to the environment. Mutations are "
                            "allowed only in intervention mode."
                        ),
                        "parameters": {
                            "type": "object",
                            "properties": {"question": {"type": "string"}},
                            "required": ["question"],
                        },
                    },
                },
                fn=self._tool_ask_environment,
            ),
            "ask_agents": _ToolDef(
                schema={
                    "type": "function",
                    "function": {
                        "name": "ask_agents",
                        "description": "Ask specific agents a question and aggregate their answers.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "agent_ids": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                },
                                "question": {"type": "string"},
                            },
                            "required": ["agent_ids", "question"],
                        },
                    },
                },
                fn=self._tool_ask_agents,
            ),
        }

    # ---- tool impls ----

    async def _tool_get_current_time(self) -> dict[str, Any]:
        return {"current_time": self._society.current_time.isoformat()}

    async def _tool_list_agents(self) -> dict[str, Any]:
        """Return the agent roster from society specs (no env / reconstruction)."""
        agents = []
        for spec in self._society.agent_specs:
            profile = spec.get("profile") or {}
            agent_id = int(spec.get("id", profile.get("id", 0)))
            name = None
            if isinstance(profile, dict):
                name = profile.get("name")
            agents.append({"id": agent_id, "name": name})
        return {"agents": agents, "count": len(agents)}

    async def _tool_get_agent_profile(
        self,
        agent_id: Any = None,
        name: str | None = None,
    ) -> dict[str, Any]:
        """Return a single agent's profile from specs (deterministic, no agent LLM)."""
        ids = self._coerce_agent_ids(agent_id) if agent_id is not None else []
        name_norm = str(name).strip().lower() if name else ""
        for spec in self._society.agent_specs:
            profile = spec.get("profile") or {}
            if not isinstance(profile, dict):
                profile = {}
            sid = int(spec.get("id", profile.get("id", -1)))
            sname = str(profile.get("name") or "").strip().lower()
            if ids and sid in ids:
                return {"id": sid, "profile": dict(profile)}
            if name_norm and sname == name_norm:
                return {"id": sid, "profile": dict(profile)}
        return {
            "error": "agent not found",
            "agent_id": agent_id,
            "name": name,
        }

    @staticmethod
    def _coerce_agent_ids(raw: Any) -> list[int]:
        """Normalize LLM tool args for ``agent_ids`` into a list of ints."""
        if raw is None:
            return []
        if isinstance(raw, (int, float)):
            return [int(raw)]
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return []
            try:
                return AgentSocietyHelper._coerce_agent_ids(json.loads(text))
            except Exception:
                try:
                    return AgentSocietyHelper._coerce_agent_ids(json_repair.loads(text))
                except Exception:
                    if text.isdigit() or (text.startswith("-") and text[1:].isdigit()):
                        return [int(text)]
                    return []
        if isinstance(raw, dict):
            if "agent_ids" in raw:
                return AgentSocietyHelper._coerce_agent_ids(raw.get("agent_ids"))
            if "id" in raw:
                return AgentSocietyHelper._coerce_agent_ids(raw.get("id"))
            return []
        if isinstance(raw, list):
            out: list[int] = []
            for item in raw:
                out.extend(AgentSocietyHelper._coerce_agent_ids(item))
            return out
        return []

    async def _tool_filter_agents_by_profile(
        self, field: str, value: Any
    ) -> dict[str, Any]:
        """Filter agents by a profile field.

        Operates on the society's **specs** first (cheap, no reconstruction).
        If every spec exposes the field directly in its ``profile`` dict, no
        agent is reconstructed. Only when the field is absent from all profiles
        do we reconstruct and ask each agent (expensive, rare).
        """
        specs = self._society.agent_specs
        target_norm = str(value).strip().lower()
        ids: list[int] = []
        reconstruct_needed: list[dict] = []

        for spec in specs:
            profile = spec.get("profile") or {}
            if isinstance(profile, dict) and field in profile:
                if str(profile.get(field)).strip().lower() == target_norm:
                    ids.append(int(spec["id"]))
            else:
                # Field not directly in the stored profile — need to ask the agent.
                reconstruct_needed.append(spec)

        if reconstruct_needed:
            question = f"Please return your `{field}` field value, only output the original value."
            # Reconstruct only the agents whose profile lacks the field.
            to_ask_ids = [int(s["id"]) for s in reconstruct_needed]
            agents = await self._society._reconstruct_agents(to_ask_ids)
            try:
                results: list[str] = list(
                    await asyncio.gather(
                        *(a.ask(question, readonly=True) for a in agents),
                        return_exceptions=False,
                    )
                )
            finally:
                # Readonly ask shouldn't mutate, but persist defensively.
                for a in agents:
                    try:
                        await a.to_workspace(self._society._workspace_for(a.id))
                    except Exception:
                        logger = get_logger()
                        logger.debug(
                            "Best-effort persistence failed for agent %s",
                            a.id,
                            exc_info=True,
                        )
            for a, ans in zip(agents, results, strict=False):
                try:
                    if str(ans).strip().lower() == target_norm:
                        ids.append(a.id)
                except Exception:
                    continue
        return {"agent_ids": sorted(set(ids))}

    async def _tool_ask_environment(
        self,
        question: str,
        readonly: bool,
    ) -> dict[str, Any]:
        ctx = {}
        more_ctx, answer = await self._env_router.ask(ctx, question, readonly=readonly)
        return {"answer": answer, "context": more_ctx}

    async def _tool_ask_agents(
        self, agent_ids: list[int], question: str, readonly: bool | None = None
    ) -> dict[str, Any]:
        """Ask specific agents a question.

        Reconstructs ONLY the requested agents (by id) on demand. The society
        holds no agent objects; reconstruction is via ``from_workspace``.
        """
        known_ids = set(self._society.agent_ids)
        valid_ids = [i for i in self._coerce_agent_ids(agent_ids) if i in known_ids]
        if not valid_ids:
            return {"answers": {}, "error": f"no valid agent_ids in {agent_ids!r}"}
        agents = await self._society._reconstruct_agents(valid_ids)
        try:
            results: list[str] = list(
                await asyncio.gather(
                    *(a.ask(question, readonly=bool(readonly)) for a in agents),
                    return_exceptions=False,
                )
            )
        finally:
            # Persist any state changes back to workspaces.
            for a in agents:
                try:
                    await a.to_workspace(self._society._workspace_for(a.id))
                except Exception:
                    logger = get_logger()
                    logger.debug(
                        "Best-effort persistence failed for agent %s",
                        a.id,
                        exc_info=True,
                    )
        answers: dict[str, Any] = {}
        for a, ans in zip(agents, results, strict=False):
            answers[str(a.id)] = ans
        return {"answers": answers}
