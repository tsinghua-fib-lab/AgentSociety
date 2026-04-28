"""Tool module for PersonAgent.

Components:
- decision: ToolDecision model for LLM output
- utils: JSON handling, string truncation, pagination, retry
- loop_detection: Loop detection service to prevent infinite loops
- security: Bash command security checking
"""

from agentsociety2.agent.tool.decision import ToolDecision, VALID_TOOL_NAMES
from agentsociety2.agent.tool.loop_detection import (
    LoopDetectionConfig,
    LoopDetectionService,
)
from agentsociety2.agent.tool.security import (
    BashSecurityChecker,
)
from agentsociety2.agent.tool.policy import ToolPolicy, ToolPolicyContext
from agentsociety2.agent.tool.utils import (
    async_retry_on_transient,
    jr_dumps,
    jr_parse,
    jr_parse_from_llm,
    json_dumps_tool_result_for_thread,
    paginate,
    pagination_from_args,
    slice_text_page,
    trunc_str,
    truncate,
)

__all__ = [
    "ToolDecision",
    "VALID_TOOL_NAMES",
    "truncate",
    "trunc_str",
    "jr_dumps",
    "jr_parse",
    "jr_parse_from_llm",
    "paginate",
    "pagination_from_args",
    "slice_text_page",
    "json_dumps_tool_result_for_thread",
    "async_retry_on_transient",
    "LoopDetectionService",
    "LoopDetectionConfig",
    "BashSecurityChecker",
    "ToolPolicy",
    "ToolPolicyContext",
]
