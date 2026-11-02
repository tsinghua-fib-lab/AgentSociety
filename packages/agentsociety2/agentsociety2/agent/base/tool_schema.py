"""ReAct 工具循环使用的通用 OpenAI function/tool schema。

中文：集中定义 ReAct 工具循环使用的通用 OpenAI function/tool schema
（``react_tool_schemas`` 和 ``readonly_tool_names``）。这些 schema 与具体
agent（PersonAgent 等）无关，只描述 workspace / skill / memory 检索 / TODO
/ ask_env 等通用动作。
English: Defines the generic OpenAI function/tool schemas used by the ReAct
tool loop (``react_tool_schemas`` and ``readonly_tool_names``). These schemas
are agent-agnostic and only describe workspace / skill / memory retrieval /
TODO / ask_env actions.

person 专属的 memory schema(抽取、整理)仍位于
:mod:`agentsociety2.agent.person_tools`。
"""

from __future__ import annotations

from typing import Any


def react_tool_schemas(
    *,
    enable_todo_list: bool = True,
    enable_memory: bool = True,
    disable_skills: bool = False,
    readonly: bool = False,
    overrides: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """为 ReAct 动作构建 OpenAI tool schema。

    :param enable_todo_list: 是否暴露 TODO 工具。
    :param enable_memory: 是否暴露 memory 检索工具。
    :param disable_skills: 是否隐藏技能激活与执行工具。
    :param readonly: 是否过滤为 readonly 安全的工具。
    :param overrides: 可选的 tool name -> 完整 tool schema dict 映射。名字
        命中键的工具被替换为给定 schema(不存在则追加)。在 ``readonly``
        过滤之前应用,因此子类可按模式替换工具(如 PersonAgent 在 ask
        模式把 ``finish`` 换成仅含 answer 的变体,step 模式换成
        result+memories 变体)。
    :returns: LLM dispatcher 接受的 tool schema dict 列表。
    """
    tools: list[dict[str, Any]] = []

    def add(
        name: str,
        description: str,
        properties: dict[str, Any] | None = None,
        required: list[str] | None = None,
    ) -> None:
        """追加一条 function tool schema。

        :param name: function tool 名称。
        :param description: function tool 描述。
        :param properties: 参数的 JSON schema properties。
        :param required: 必填参数名。
        :returns: 无。
        """
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": {
                        "type": "object",
                        "properties": properties or {},
                        "required": required or [],
                        "additionalProperties": False,
                    },
                },
            }
        )

    add(
        "finish",
        (
            "End this step or external question and return your result. "
            "For an external <question>, put your complete answer in `answer` "
            "(include the full requested payload, e.g. the JSON with reason and answer). "
            "For a simulation step, put a short result in `final`."
        ),
        {
            "answer": {
                "type": "string",
                "description": (
                    "Final answer returned to the caller. Required when answering an "
                    "external <question>; use this in ask mode."
                ),
            },
            "final": {
                "type": "string",
                "description": "Final simulation step result text; used in step mode.",
            },
        },
        [],
    )
    add(
        "read",
        "Read one UTF-8 text file inside the agent workspace.",
        {"path": {"type": "string"}},
        ["path"],
    )
    add(
        "write",
        "Create or replace one UTF-8 text file inside the agent workspace.",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"],
    )
    add(
        "append",
        "Append UTF-8 text to one file inside the agent workspace.",
        {"path": {"type": "string"}, "content": {"type": "string"}},
        ["path", "content"],
    )
    add(
        "list",
        "Inspect files before choosing what to read.",
        {"path": {"type": "string", "default": "."}},
    )
    add(
        "grep",
        "Search workspace text before reading files.",
        {
            "pattern": {"type": "string"},
            "path": {"type": "string", "default": "."},
            "limit": {"type": "integer", "default": 50, "minimum": 1},
        },
        ["pattern"],
    )
    if enable_memory:
        add(
            "memory_recent",
            "Read the latest event memories from memory/episodes.jsonl.",
            {"limit": {"type": "integer", "default": 8, "minimum": 1}},
        )
        add(
            "memory_search",
            "Search event memories by substring or keyword.",
            {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 20, "minimum": 1},
            },
            ["query"],
        )
        add(
            "memory_range",
            "Retrieve event memories in a step or time range. Prefer start_step/end_step for simulation step ranges; tick is the per-step duration in seconds.",
            {
                "start_step": {"type": "integer"},
                "end_step": {"type": "integer"},
                "start_tick": {"type": "integer"},
                "end_tick": {"type": "integer"},
                "start_time": {"type": "string"},
                "end_time": {"type": "string"},
                "limit": {"type": "integer", "default": 50, "minimum": 1},
            },
        )
        add(
            "memory_read",
            "Read exact event memories by id.",
            {
                "ids": {
                    "type": "array",
                    "items": {"type": "string"},
                },
            },
            ["ids"],
        )
    if not disable_skills:
        add(
            "activate_skill",
            "Load a skill's SKILL.md before relying on its instructions.",
            {
                "skill_name": {
                    "type": "string",
                    "description": "Skill name shown in <available_skills>, or its registry skill id (namespace@name). Both forms are accepted.",
                },
            },
            ["skill_name"],
        )
        add(
            "deactivate_skill",
            "Remove a skill's SKILL.md from the prompt when it is no longer needed.",
            {
                "skill_name": {
                    "type": "string",
                    "description": "Skill name or registry skill id (namespace@name). Both forms are accepted.",
                }
            },
            ["skill_name"],
        )
        add(
            "read_skill_file",
            "Read a skill file after SKILL.md references it.",
            {
                "skill_name": {
                    "type": "string",
                    "description": "Skill name or registry skill id (namespace@name). Both forms are accepted.",
                },
                "path": {"type": "string"},
            },
            ["skill_name", "path"],
        )
        add(
            "execute_skill_script",
            "Execute a visible skill's Python script. script_path may be omitted when the skill declares a default script.",
            {
                "skill_name": {
                    "type": "string",
                    "description": "Skill name or registry skill id (namespace@name). Both forms are accepted.",
                },
                "script_path": {
                    "type": "string",
                    "description": "Optional path relative to the skill root; defaults to the skill's declared script.",
                },
                "argv": {
                    "type": "array",
                    "items": {"type": "string"},
                    "default": [],
                },
                "readonly": {
                    "type": "boolean",
                    "default": False,
                    "description": "For environment skills redirected to ask_env, set true for observe/query-only operations.",
                },
                "timeout_sec": {"type": "integer", "default": 30, "minimum": 1},
            },
            ["skill_name"],
        )
    add(
        "ask_env",
        (
            "Observe or act in the simulation environment through RouterBase.ask. "
            "Environment calls always run in template/cache mode: write `instruction` "
            "as a reusable template with stable wording, and put changing runtime "
            "values in `variables` instead of embedding them directly in the text."
        ),
        {
            "instruction": {
                "type": "string",
                "description": (
                    "Reusable natural-language template passed to RouterBase.ask. "
                    "Keep the wording stable across similar calls and refer to "
                    "dynamic values by variable name, e.g. 'move person {person_id} "
                    "to home AOI {home_aoi}'."
                ),
            },
            "readonly": {"type": "boolean", "default": False},
            "ctx": {"type": "object", "additionalProperties": True},
            "variables": {
                "type": "object",
                "additionalProperties": True,
                "description": (
                    "Required mapping of every changing value used by the instruction "
                    "template. Include ids, categories, radii, coordinates, modes, "
                    "and other literals here, e.g. {'person_id': 35, "
                    "'home_aoi': 500030277, 'mode': 'walking'}. Use {} only when "
                    "the instruction has no dynamic values."
                ),
            },
        },
        ["instruction", "variables"],
    )
    if enable_todo_list:
        add(
            "todo_list",
            "Read structured cross-step TODOs.",
            {
                "status": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1},
            },
        )
        add(
            "todo_add",
            "Add one TODO. Put non-core fields such as location under metadata.",
            {
                "title": {"type": "string"},
                "kind": {"type": "string"},
                "priority": {"type": "number"},
                "due": {"type": "string"},
                "duration_min": {"type": "integer"},
                "recurrence": {"type": "string"},
                "created_by": {"type": "string"},
                "metadata": {"type": "object", "additionalProperties": True},
            },
            ["title"],
        )
        add(
            "todo_update",
            "Patch one TODO by id.",
            {
                "todo_id": {"type": "string"},
                "patch": {"type": "object", "additionalProperties": True},
            },
            ["todo_id", "patch"],
        )
        add(
            "todo_start",
            "Mark one TODO as the only active task.",
            {"todo_id": {"type": "string"}},
            ["todo_id"],
        )
        add(
            "todo_complete",
            "Mark one TODO done and clear it if active.",
            {"todo_id": {"type": "string"}, "outcome": {"type": "string"}},
            ["todo_id"],
        )
        add(
            "todo_defer",
            "Defer one TODO and record why.",
            {
                "todo_id": {"type": "string"},
                "new_due": {"type": "string"},
                "reason": {"type": "string"},
            },
            ["todo_id", "reason"],
        )
        add(
            "update_config",
            (
                "Update this agent's own config.json through the validated "
                "channel. Only whitelisted keys are accepted (max_react_turns, "
                "enable_todo_list, enable_memory, memory_context_max_chars, "
                "recent_memory_limit, memory_consolidation_pending_threshold, "
                "memory_consolidation_interval_steps, "
                "memory_high_importance_threshold, idle_skip_enabled, "
                "default_activated_skill_ids, disabled_skill_ids, "
                "extra_skill_paths). Changes take effect on the next restore; "
                "a backup snapshot is written before applying, and every "
                "change is logged to config_changes.jsonl."
            ),
            {"changes": {"type": "object", "additionalProperties": True}},
            ["changes"],
        )
        add(
            "todo_clear_completed",
            (
                "Archive finished (done/cancelled) TODOs to state/todos_archive.jsonl "
                "and remove them from the active list, keeping the most recent few. "
                "Use this at day boundaries to keep the list tidy. Pending/active/"
                "deferred/blocked items are never archived."
            ),
            {"keep_recent": {"type": "integer", "default": 2, "minimum": 0}},
        )
    if overrides:
        index = {t["function"]["name"]: i for i, t in enumerate(tools)}
        for name, schema in overrides.items():
            if name in index:
                tools[index[name]] = schema
            else:
                tools.append(schema)
    if readonly:
        allowed = readonly_tool_names()
        return [item for item in tools if item["function"]["name"] in allowed]
    return tools


def readonly_tool_names() -> set[str]:
    """返回 readonly 外部 ask 请求允许使用的工具集合。

    :returns: 不会直接修改仿真状态的工具名集合。
    """
    return {
        "finish",
        "read",
        "list",
        "grep",
        "activate_skill",
        "deactivate_skill",
        "read_skill_file",
        "execute_skill_script",
        "ask_env",
        "memory_recent",
        "memory_search",
        "memory_range",
        "memory_read",
        "todo_list",
    }
