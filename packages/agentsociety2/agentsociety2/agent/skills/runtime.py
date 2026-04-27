"""Agent 技能运行时（workspace + skill 执行）。

该模块提供 :class:`~agentsociety2.agent.skills.runtime.AgentSkillRuntime`，用于把 PersonAgent 的
"工作目录隔离、文件读写、thread/tool 日志、skill 激活与执行"等细节集中在一个组件内，
避免 agent 主体过度膨胀。

模块功能
========

- **Workspace 管理**: 独立工作区、文件读写、路径安全检查
- **Skill 执行**: 技能激活、读取、执行
- **日志管理**: Thread 消息、工具调用、会话状态持久化
- **上下文维护**: AGENT.md 自动更新、状态同步
- **行为追踪**: 仿真行为事件记录与统计
- **文件发现**: 在 AGENT.md 中自动维护文件索引

类结构
======

- :class:`AgentSkillRuntime`: 主运行时类

示例
====

基本使用::

    from agentsociety2.agent.skills import SkillRegistry
    from agentsociety2.agent.skills.runtime import AgentSkillRuntime

    registry = SkillRegistry()
    registry.scan_builtin()

    runtime = AgentSkillRuntime(agent_id=1, registry=registry)
    runtime.ensure_agent_work_dir(env_router)

    # 文件操作
    runtime.workspace_write("state/test.json", '{"key": "value"}')
    content = runtime.workspace_read("state/test.json")

    # 状态同步
    runtime.sync_state_to_context()

    # 文件清单
    runtime.write_file_manifest()
"""

from __future__ import annotations

import json
import logging
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

from agentsociety2.agent.skills import SkillRegistry
from agentsociety2.agent.tool import jr_dumps, jr_parse

logger = logging.getLogger(__name__)

AGENT_DOCUMENT = "AGENT.md"
RUNTIME_DIR = ".runtime"
RUNTIME_LOG_DIR = f"{RUNTIME_DIR}/logs"
FILE_INDEX_START = "<!-- AGENT_FILE_INDEX_START -->"
FILE_INDEX_END = "<!-- AGENT_FILE_INDEX_END -->"


class AgentSkillRuntime:
    """独立的 Skill 运行时组件。

    PersonAgent 仅通过组合使用该组件，避免把 skill/workspace 执行细节堆在 agent 主体里。

    :ivar _agent_id: Agent ID。
    :ivar _registry: Skill 注册表。
    :ivar _agent_work_dir: Agent 工作目录。
    :ivar _state_config: 状态文件配置（可选）。
    """

    def __init__(
        self,
        agent_id: int,
        registry: SkillRegistry,
        state_config: Any = None,
    ) -> None:
        """初始化运行时。

        :param agent_id: Agent ID。
        :param registry: Skill 注册表。
        :param state_config: 状态文件配置（StateConfig 实例）。
        """
        self._agent_id = agent_id
        self._registry = registry
        self._agent_work_dir: Path | None = None
        self._state_config = state_config

    def ensure_agent_work_dir(self, env_obj: Any) -> Path:
        """确保 agent 工作目录已初始化并返回其路径。

        :param env_obj: 通常为 env_router；若其包含 ``run_dir`` 属性则以其为基准目录，
            否则退化为当前工作目录。
        :returns: agent 工作目录路径（形如 ``<run_dir>/agents/agent_0001``）。
        """
        if self._agent_work_dir is not None:
            return self._agent_work_dir

        # 优先从 env_router 获取 run_dir
        run_dir = getattr(env_obj, "run_dir", None)
        if run_dir is not None:
            base_path = Path(run_dir)
        else:
            base_path = Path.cwd()

        self._agent_work_dir = (
            base_path / "agents" / f"agent_{self._agent_id:04d}"
        ).resolve()
        self._agent_work_dir.mkdir(parents=True, exist_ok=True)
        return self._agent_work_dir

    def ensure_standard_workspace_dirs(self) -> None:
        """确保 workspace 标准目录结构存在。

        创建以下目录：
        - ``state/`` - Skills 状态文件
        - ``memory/`` - 长期记忆
        - ``input/`` - 外部输入
        - ``custom/skills/`` - 自定义技能
        - ``.runtime/logs/`` - 运行时日志
        """
        if self._agent_work_dir is None:
            raise RuntimeError("Agent workspace is not initialized")

        standard_dirs = ["state", "memory", "input", "custom/skills", RUNTIME_LOG_DIR]
        for dir_name in standard_dirs:
            dir_path = self._agent_work_dir / dir_name
            try:
                dir_path.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning(
                    f"Agent {self._agent_id}: failed to create workspace dir '{dir_name}': {e}"
                )

    def _resolve_workspace_path(self, relative_path: str) -> Path:
        """将相对路径解析到 workspace 内并做越界保护。"""
        if self._agent_work_dir is None:
            raise RuntimeError("Agent workspace is not initialized")
        work_dir = self._agent_work_dir
        target = (work_dir / relative_path).resolve()
        if target != work_dir and work_dir not in target.parents:
            raise ValueError(f"Path escapes agent workspace: {relative_path}")
        return target

    def workspace_root(self) -> Path:
        """:returns: workspace 根目录路径。"""
        if self._agent_work_dir is None:
            raise RuntimeError("Agent workspace is not initialized")
        return self._agent_work_dir

    def workspace_read(self, relative_path: str) -> str:
        """读取 workspace 内文件内容。

        :param relative_path: 相对 workspace 的路径。
        :returns: 文件文本内容；若文件不存在则返回空字符串。
        """
        target = self._resolve_workspace_path(relative_path)
        if not target.exists() or not target.is_file():
            return ""
        return target.read_text(encoding="utf-8")

    def workspace_write(self, relative_path: str, content: str) -> str:
        """写入 workspace 内文件（UTF-8）。

        :param relative_path: 相对 workspace 的路径。
        :param content: 写入内容。
        :returns: 实际写入的绝对路径字符串。
        """
        target = self._resolve_workspace_path(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return str(target)

    def workspace_exists(self, relative_path: str) -> bool:
        """:returns: workspace 内路径是否存在。"""
        target = self._resolve_workspace_path(relative_path)
        return target.exists()

    def workspace_delete(self, relative_path: str) -> bool:
        """删除 workspace 内文件（仅文件，目录不删除）。"""
        target = self._resolve_workspace_path(relative_path)
        if not target.exists() or target.is_dir():
            return False
        target.unlink()
        return True

    def workspace_list(self, relative_path: str = ".") -> list[str]:
        """列出 workspace 内文件（递归）。

        :param relative_path: 相对 workspace 的根路径。
        :returns: 文件相对路径列表（相对 workspace 根）。
        """
        work_dir = self.workspace_root()  # raises RuntimeError if not initialized
        root = self._resolve_workspace_path(relative_path)
        if not root.exists():
            return []
        if root.is_file():
            return [str(root.relative_to(work_dir))]
        return sorted(
            str(p.relative_to(work_dir)) for p in root.rglob("*") if p.is_file()
        )

    def skill_list(self, names: list[str]) -> list[dict[str, Any]]:
        return self._registry.list_selection_metadata(names=names, only_enabled=True)

    def skill_activate(self, name: str) -> str:
        return self._registry.activate(name)

    def skill_read(self, name: str, relative_path: str) -> str:
        return self._registry.read(name, relative_path)

    async def execute(
        self,
        skill_name: str,
        args: dict[str, Any],
        codegen_executor: (
            Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None
        ) = None,
    ) -> dict[str, Any]:
        """执行某个 skill（转发到 registry）。

        :param skill_name: skill 名称。
        :param args: 执行参数（由 skill 脚本/协议自行定义）。
        :param codegen_executor: 可选。用于把 skill 内部的 codegen 调度回 env 的执行器。
        :returns: 执行结果字典（由 :class:`~agentsociety2.agent.skills.SkillRegistry` 约定）。
        :raises RuntimeError: workspace 未初始化时抛出。
        """
        if self._agent_work_dir is None:
            raise RuntimeError("Agent workspace is not initialized")
        work_dir = self._agent_work_dir
        return await self._registry.execute(
            skill_name=skill_name,
            args=args,
            agent_work_dir=work_dir,
            codegen_executor=codegen_executor,
        )

    def persist_session_state(
        self,
        tick: int,
        t: datetime,
        selected_skills: set[str],
        activated_skills: set[str] | None = None,
    ) -> None:
        """落地当前会话状态到 workspace，并追加到历史记录。

        :param tick: 当前 tick。
        :param t: 当前仿真时间。
        :param selected_skills: 本步可见/可选技能集合。
        :param activated_skills: 可选。已激活技能集合。
        """
        state = {
            "agent_id": self._agent_id,
            "tick": tick,
            "time": t.isoformat(),
            "selected_skills": sorted(selected_skills),
            "activated_skills": sorted(activated_skills or set()),
        }
        self.workspace_write(f"{RUNTIME_LOG_DIR}/session_state.json", jr_dumps(state))
        self.append_session_state_event(state)

    def append_session_state_event(self, state: dict[str, Any]) -> None:
        """追加 session_state 事件到 runtime 日志。"""
        if self._agent_work_dir is None:
            raise RuntimeError("Agent workspace is not initialized")
        path = self._agent_work_dir / RUNTIME_LOG_DIR / "session_state_history.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(jr_dumps(state, indent=None) + "\n")

    def append_tool_log(self, entry: dict[str, Any]) -> None:
        """追加单条工具调用日志（jsonl）。"""
        if self._agent_work_dir is None:
            raise RuntimeError("Agent workspace is not initialized")
        log_path = self._agent_work_dir / RUNTIME_LOG_DIR / "tool_calls.jsonl"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(jr_dumps(entry, indent=None) + "\n")

    def append_step_replay(
        self,
        tick: int,
        t: datetime,
        selected_skills: set[str],
        tool_history: list[dict[str, Any]],
    ) -> None:
        """追加 step 回放记录（jsonl）。"""
        if self._agent_work_dir is None:
            raise RuntimeError("Agent workspace is not initialized")
        replay_path = self._agent_work_dir / RUNTIME_LOG_DIR / "step_replay.jsonl"
        replay_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "tick": tick,
            "time": t.isoformat(),
            "selected_skills": sorted(selected_skills),
            "tool_history": tool_history,
        }
        with replay_path.open("a", encoding="utf-8") as f:
            f.write(jr_dumps(record, indent=None) + "\n")

    def read_json(self, relative_path: str, default: Any) -> Any:
        """读取工作目录中的 JSON 文件；空内容返回 default。"""
        raw = self.workspace_read(relative_path)
        if not raw:
            return default
        return jr_parse(raw)

    def read_recent_tool_logs(self, limit: int = 20) -> list[dict[str, Any]]:
        """读取最近 N 条工具调用日志。"""
        if self._agent_work_dir is None:
            raise RuntimeError("Agent workspace is not initialized")
        path = self._agent_work_dir / RUNTIME_LOG_DIR / "tool_calls.jsonl"
        if not path.exists():
            return []
        if limit > 0:
            recent_lines: deque[str] = deque(maxlen=limit)
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        recent_lines.append(line)
            source = list(recent_lines)
        else:
            with path.open("r", encoding="utf-8") as f:
                source = [line for line in f if line.strip()]
        return [jr_parse(line) for line in source]

    def append_thread_message(
        self,
        role: str,
        content: str,
        tick: int,
        t: datetime,
        *,
        tool_result_full: Optional[dict[str, Any]] = None,
    ) -> None:
        """追加 thread 消息到 runtime thread 日志。

        ``content`` 为喂给 LLM 的文本；若提供 ``tool_result_full``，则同条记录落盘完整工具结果
        （读取 thread 时仍只用 ``content`` 构造 messages）。
        """
        if self._agent_work_dir is None:
            raise RuntimeError("Agent workspace is not initialized")
        path = self._agent_work_dir / RUNTIME_LOG_DIR / "thread_messages.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        entry: dict[str, Any] = {
            "tick": tick,
            "time": t.isoformat(),
            "role": role,
            "content": content,
        }
        if tool_result_full is not None:
            entry["tool_result_full"] = tool_result_full
        with path.open("a", encoding="utf-8") as f:
            f.write(jr_dumps(entry, indent=None) + "\n")

    def read_recent_thread_messages(self, limit: int = 40) -> list[dict[str, str]]:
        """读取最近 N 条 thread 消息并转换为 LLM messages 结构。"""
        if self._agent_work_dir is None:
            raise RuntimeError("Agent workspace is not initialized")
        path = self._agent_work_dir / RUNTIME_LOG_DIR / "thread_messages.jsonl"
        if not path.exists():
            return []
        if limit > 0:
            recent_lines: deque[str] = deque(maxlen=limit)
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        recent_lines.append(line)
            recent = list(recent_lines)
        else:
            with path.open("r", encoding="utf-8") as f:
                recent = [line.rstrip("\n") for line in f if line.strip()]
        messages: list[dict[str, str]] = []
        for line in recent:
            if not line.strip():
                continue
            obj = jr_parse(line)
            role = str(obj.get("role", "")).strip()
            content = str(obj.get("content", ""))
            if role in {"user", "assistant"} and content:
                messages.append({"role": role, "content": content})
        return messages

    def build_workspace_structure_prompt(self) -> str:
        """构建 workspace 结构说明（Claude/Cursor 风格：极简 + 动态发现）。

        不维护复杂的 manifest/registry，只提供目录约定，让 Agent 自己探索。
        状态文件示例从配置或实际文件动态生成。

        :returns: workspace 结构说明文本。
        """
        lines = [
            "## Workspace Structure",
            "",
            'All files are in the workspace root. Use `workspace_list(".")` to see what exists.',
            "",
            "### Generated Context Files",
            "- `AGENT.md` - concise agent context and generated file index",
            "",
            "### Directory Convention",
            "- `state/` - Skill state files (dynamically discovered)",
            "- `state/*.json` - current structured state",
            "- `state/*.jsonl` - event/history streams",
            "- `memory/` - optional long-term memory directory",
            "- `input/` - External input from environment",
            "- `.runtime/` - Runtime internals (logs, checkpoints, WAL)",
            "",
            "### Quick Discovery",
            '- `workspace_list("state/")` - See all skill state files',
            '- `workspace_read("AGENT.md")` - Read concise current context and file index',
            "",
            "Let the agent discover what it needs dynamically.",
        ]

        # 动态添加当前存在的 state 文件
        if self._agent_work_dir is not None:
            state_dir = self._agent_work_dir / "state"
            if state_dir.exists() and state_dir.is_dir():
                state_files = sorted(
                    f.name
                    for f in state_dir.iterdir()
                    if f.is_file() and (f.suffix == ".json" or f.suffix == ".txt")
                )
                if state_files:
                    lines.append("")
                    lines.append("### Current State Files")
                    for filename in state_files:
                        lines.append(f"- `state/{filename}`")

        return "\n".join(lines)

    @staticmethod
    def _replace_generated_file_index(content: str, manifest: str) -> str:
        """替换 AGENT.md 中的自动文件索引块，保留人工内容。"""
        block = f"{FILE_INDEX_START}\n{manifest.rstrip()}\n{FILE_INDEX_END}"
        if FILE_INDEX_START in content and FILE_INDEX_END in content:
            before, _, rest = content.partition(FILE_INDEX_START)
            _, _, after = rest.partition(FILE_INDEX_END)
            return f"{before.rstrip()}\n\n{block}\n{after.lstrip()}".strip()
        if content.strip():
            return f"{content.rstrip()}\n\n{block}"
        return block

    def refresh_workspace_documents(self) -> None:
        """同步工作区动态文档。"""
        self.sync_state_to_context()
        self.write_file_manifest()
        self.emit_behavior_event(
            "state_sync",
            {
                "document": AGENT_DOCUMENT,
                "workspace_files": len(self.workspace_list(".")),
            },
            name="refresh_workspace_documents",
            output_summary={"document": AGENT_DOCUMENT},
        )

    # ==================== AGENT.md Support ====================

    def read_agent_context(self) -> dict[str, Any]:
        """读取 AGENT.md 文件内容。

        该文件是agent的自我声明文件，包含当前任务、重要上下文等信息。
        使用YAML frontmatter格式，便于程序解析。

        :returns: 解析后的上下文字典，包含metadata和content两部分。
        """
        content = self.workspace_read(AGENT_DOCUMENT)
        if not content:
            return {"metadata": {}, "content": ""}

        return self._parse_context_md(content)

    def _parse_context_md(self, content: str) -> dict[str, Any]:
        """解析 AGENT.md 文件（YAML frontmatter + markdown）。

        :param content: 文件原始内容。
        :returns: {"metadata": {...}, "content": "markdown内容"}
        """
        metadata: dict[str, Any] = {}
        body = content

        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    from ruamel.yaml import YAML

                    yaml = YAML(typ="safe")
                    metadata = yaml.load(parts[1]) or {}
                except Exception:
                    pass
                body = parts[2].strip()

        return {"metadata": metadata, "content": body}

    def update_agent_context(self, updates: dict[str, Any]) -> None:
        """更新 AGENT.md（合并而非覆盖）。

        :param updates: 要更新的metadata字段。
        """
        existing = self.read_agent_context()
        existing["metadata"].update(updates)
        self._write_agent_context(existing["metadata"], existing["content"])

    def set_agent_context_content(self, content: str) -> None:
        """设置 AGENT.md 的内容部分（保留metadata）。

        :param content: 新的markdown内容。
        """
        existing = self.read_agent_context()
        self._write_agent_context(existing["metadata"], content)

    def _write_agent_context(self, metadata: dict[str, Any], content: str) -> None:
        """写入 AGENT.md 文件。"""
        from ruamel.yaml import YAML
        from io import StringIO

        yaml = YAML()
        yaml.default_flow_style = False

        stream = StringIO()
        stream.write("---\n")
        yaml.dump(metadata, stream)
        stream.write("---\n\n")
        stream.write(content)

        self.workspace_write(AGENT_DOCUMENT, stream.getvalue())

    def auto_update_agent_context(
        self,
        current_task: str | None = None,
        active_goal: str | None = None,
        priority: str | None = None,
        notes: str | None = None,
    ) -> None:
        """自动更新 AGENT.md（仿真人行为追踪）。

        根据仿真人当前状态自动维护上下文文件，支持跨会话持久化。

        :param current_task: 当前任务描述。
        :param active_goal: 活跃目标。
        :param priority: 优先级。
        :param notes: 额外备注。
        """
        updates: dict[str, Any] = {}
        if current_task is not None:
            updates["current_task"] = current_task
        if active_goal is not None:
            updates["active_goal"] = active_goal
        if priority is not None:
            updates["priority"] = priority
        if updates:
            updates["last_updated"] = datetime.now(timezone.utc).isoformat()
            self.update_agent_context(updates)

        if notes is not None:
            existing = self.read_agent_context()
            existing_content = existing.get("content", "")
            # 追加时间戳备注
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
            new_content = (
                f"{existing_content}\n\n## [{timestamp}]\n{notes}\n"
                if existing_content
                else f"## [{timestamp}]\n{notes}\n"
            )
            self.set_agent_context_content(new_content.strip())

    @staticmethod
    def _flatten_summary_value(value: Any, max_len: int = 100) -> str:
        """将状态字段压缩成适合放入上下文的短文本。"""
        if value is None:
            return ""
        if isinstance(value, str):
            return value[:max_len]
        if isinstance(value, bool):
            return str(value).lower()
        if isinstance(value, (int, float)):
            return f"{value:.3g}" if isinstance(value, float) else str(value)
        if isinstance(value, list):
            parts = [
                AgentSkillRuntime._flatten_summary_value(v, max_len=40)
                for v in value[:3]
            ]
            text = ", ".join(p for p in parts if p)
            if len(value) > 3:
                text += f", +{len(value) - 3} more"
            return text[:max_len]
        if isinstance(value, dict):
            parts: list[str] = []
            for k, v in list(value.items())[:4]:
                flattened = AgentSkillRuntime._flatten_summary_value(v, max_len=40)
                if flattened:
                    parts.append(f"{k}={flattened}")
            return "; ".join(parts)[:max_len]
        return str(value)[:max_len]

    @classmethod
    def _summarize_state_json(
        cls,
        data: Any,
        *,
        summary_field: str = "",
        max_len: int = 100,
    ) -> str:
        """从任意 JSON 状态中提取通用短摘要。

        运行时不理解具体 skill 的字段语义。技能若希望被稳定摘要，可写入
        ``_summary`` 或 ``summary``；否则这里只展示少量顶层结构，帮助定位文件。
        """
        if not isinstance(data, dict) or not data:
            return ""
        if summary_field:
            value = data.get(summary_field)
            text = cls._flatten_summary_value(value, max_len=max_len)
            if text:
                return text

        for key in ("_summary", "summary"):
            if key in data:
                text = cls._flatten_summary_value(data[key], max_len=max_len)
                if text:
                    return text[:max_len]

        scalar_parts: list[str] = []
        structural_parts: list[str] = []
        for key, value in data.items():
            if key.startswith("_"):
                continue
            if isinstance(value, (str, int, float, bool)) or value is None:
                text = cls._flatten_summary_value(value, max_len=32)
                if text:
                    scalar_parts.append(f"{key}={text}")
            elif isinstance(value, list):
                structural_parts.append(f"{key}[{len(value)}]")
            elif isinstance(value, dict):
                structural_parts.append(f"{key}{{{len(value)}}}")
            if len(scalar_parts) >= 3:
                break
        if scalar_parts:
            return "; ".join(scalar_parts)[:max_len]

        if structural_parts:
            return "; ".join(structural_parts[:4])[:max_len]
        return ""

    @classmethod
    def _describe_state_json(cls, data: Any, max_len: int = 100) -> str:
        """从自描述状态文件中提取文件用途。

        只读取通用元数据，不解释任何具体 skill 字段。
        推荐技能写入 ``_meta.purpose`` 或 ``_meta.description``。
        """
        if not isinstance(data, dict):
            return ""
        meta = data.get("_meta")
        if not isinstance(meta, dict):
            return ""
        for key in ("purpose", "description", "owner", "skill"):
            text = cls._flatten_summary_value(meta.get(key), max_len=max_len)
            if text:
                return text
        return ""

    def _memory_file_candidates(self) -> list[Path]:
        """返回当前 workspace 中可能的长期记忆文件路径。"""
        if self._agent_work_dir is None:
            return []
        return [
            self._agent_work_dir / "state" / "memory.jsonl",
            self._agent_work_dir / "memory" / "memory.jsonl",
            self._agent_work_dir / "memory.jsonl",
        ]

    @staticmethod
    def _count_nonempty_lines(path: Path) -> int:
        """统计非空行数。"""
        try:
            with path.open("r", encoding="utf-8") as f:
                return sum(1 for line in f if line.strip())
        except Exception:
            return 0

    def sync_state_to_context(self) -> None:
        """将当前状态同步到 AGENT.md。

        只做通用文件发现和短摘要，不理解具体 skill 的字段语义。
        """
        if self._agent_work_dir is None:
            return

        context = self.read_agent_context()
        metadata = dict(context.get("metadata", {}) or {})
        state_summary: dict[str, str] = {}
        state_purpose: dict[str, str] = {}
        state_files_index: list[str] = []
        max_len = 100
        if self._state_config is not None:
            max_len = getattr(self._state_config, "summary_max_length", 100)

        state_dir = self._agent_work_dir / "state"
        if state_dir.exists() and state_dir.is_dir():
            state_files_index = sorted(
                p.relative_to(self._agent_work_dir).as_posix()
                for p in state_dir.rglob("*")
                if p.is_file()
                and p.suffix in {".json", ".jsonl", ".txt"}
                and not any(
                    part.startswith(".")
                    for part in p.relative_to(self._agent_work_dir).parts
                )
            )
            for state_file in sorted(state_dir.rglob("*.json")):
                rel_path = state_file.relative_to(self._agent_work_dir).as_posix()
                data = self.read_json(rel_path, {})
                if data:
                    purpose = self._describe_state_json(data, max_len=max_len)
                    if purpose:
                        state_purpose[rel_path] = purpose
                    summary = self._summarize_state_json(data, max_len=max_len)
                    if summary:
                        state_summary[rel_path] = summary

        if not state_files_index and self._agent_work_dir is not None:
            state_dir = self._agent_work_dir / "state"
            if state_dir.exists() and state_dir.is_dir():
                state_files_index = sorted(
                    f"state/{p.name}"
                    for p in state_dir.iterdir()
                    if p.is_file()
                    and p.suffix in {".json", ".jsonl", ".txt"}
                    and not p.name.startswith(".")
                )

        memory_counts = {
            str(path.relative_to(self._agent_work_dir)): self._count_nonempty_lines(
                path
            )
            for path in self._memory_file_candidates()
            if path.exists()
        }

        if state_summary or state_files_index or memory_counts:
            metadata["state_summary"] = state_summary
            metadata["state_purpose"] = state_purpose
            metadata["state_files"] = state_files_index[:80]
            if memory_counts:
                metadata["memory_files"] = memory_counts
            metadata["last_sync"] = datetime.now(timezone.utc).isoformat()
            self._write_agent_context(metadata, str(context.get("content", "")))

    def build_workspace_summary(self) -> str:
        """生成 workspace 内容摘要。

        用于在step开始时让agent快速了解workspace状态。
        动态发现 state/ 目录下的所有状态文件。

        :returns: workspace摘要文本。
        """
        if self._agent_work_dir is None:
            return ""

        summary = []

        context = self.read_agent_context()
        if context.get("metadata"):
            task = context["metadata"].get("current_task", "")
            if task:
                summary.append(f"**Current Task**: {task}")

        state_dir = self._agent_work_dir / "state"
        if state_dir.exists():
            state_files = sorted(state_dir.rglob("*.json"))
            if state_files:
                summary.append(f"**state/**: {len(state_files)} files")
                for state_file in state_files:
                    try:
                        data = jr_parse(state_file.read_text())
                        value = self._summarize_state_json(data, max_len=80)
                        if value:
                            key = state_file.relative_to(
                                self._agent_work_dir
                            ).as_posix()
                            summary.append(f"  - {key}: {value}")
                    except Exception:
                        pass

        memory_parts = []
        for memory_file in self._memory_file_candidates():
            if memory_file.exists():
                rel = memory_file.relative_to(self._agent_work_dir)
                line_count = self._count_nonempty_lines(memory_file)
                memory_parts.append(f"`{rel.as_posix()}`: {line_count} entries")
        if memory_parts:
            summary.append("**memory**: " + "; ".join(memory_parts))

        return "\n".join(summary) if summary else ""

    # ==================== Behavior Tracking (Observability) ====================

    def emit_behavior_event(
        self,
        event_type: str,
        data: dict[str, Any],
        tick: int | None = None,
        *,
        trace_id: str | None = None,
        span_id: str | None = None,
        parent_span_id: str | None = None,
        name: str | None = None,
        input_summary: dict[str, Any] | None = None,
        output_summary: dict[str, Any] | None = None,
        error: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """发送结构化行为事件到追踪日志。

        采用通用 trace/span 形态，不绑定具体 skill 语义。

        :param event_type: 事件类型（如 "tool_call", "skill_activate", "decision"）。
        :param data: 事件数据。
        :param tick: 当前 tick（可选）。
        :param trace_id: 当前 step/run 的追踪 ID。
        :param span_id: 当前操作 span ID。
        :param parent_span_id: 父 span ID。
        :param name: 操作名称。
        :param input_summary: 输入摘要，不写大内容或隐私内容。
        :param output_summary: 输出摘要。
        :param error: 错误摘要。
        :param duration_ms: 操作耗时毫秒。
        """
        if self._agent_work_dir is None:
            return

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent_id": self._agent_id,
            "event_type": event_type,
            "tick": tick,
            "trace_id": trace_id,
            "span_id": span_id,
            "parent_span_id": parent_span_id,
            "name": name,
            "input_summary": input_summary or {},
            "output_summary": output_summary or {},
            "error": error,
            "duration_ms": duration_ms,
            "data": data,
        }

        # 追加到行为追踪日志
        path = self._agent_work_dir / RUNTIME_LOG_DIR / "behavior_trace.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(jr_dumps(event, indent=None) + "\n")

    def get_behavior_summary(self, limit: int = 100) -> dict[str, Any]:
        """获取行为摘要统计。

        :param limit: 读取的事件数量上限。
        :return: 行为摘要字典。
        """
        if self._agent_work_dir is None:
            return {}

        path = self._agent_work_dir / RUNTIME_LOG_DIR / "behavior_trace.jsonl"
        if not path.exists():
            return {}

        # 读取最近事件
        events: list[dict] = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    try:
                        events.append(jr_parse(line))
                    except Exception:
                        pass

        if not events:
            return {}

        recent = events[-limit:] if len(events) > limit else events

        # 统计
        tool_counts: dict[str, int] = {}
        skill_activations: dict[str, int] = {}
        errors: list[dict] = []

        for event in recent:
            event_type = event.get("event_type", "")
            data = event.get("data", {})

            if event_type == "tool_call":
                tool = event.get("name") or data.get("tool", "unknown")
                tool_counts[tool] = tool_counts.get(tool, 0) + 1
            elif event_type == "skill_activate":
                skill = event.get("name") or data.get("skill", "unknown")
                skill_activations[skill] = skill_activations.get(skill, 0) + 1
            elif event_type == "error":
                errors.append(
                    {
                        "tool": event.get("name") or data.get("tool", "unknown"),
                        "error": str(event.get("error") or data.get("error", ""))[:100],
                    }
                )

        return {
            "total_events": len(recent),
            "tool_usage": tool_counts,
            "skill_activations": skill_activations,
            "recent_errors": errors[-5:],
            "last_tick": recent[-1].get("tick") if recent else None,
        }

    # ==================== File Discovery ====================

    def build_file_manifest(self) -> str:
        """构建 workspace 文件清单。

        动态扫描 workspace 目录，生成 Markdown 格式的短文件索引。

        :returns: Markdown 格式的文件清单。
        """
        if self._agent_work_dir is None:
            return ""

        workspace_root = self._agent_work_dir
        lines = [
            "# Workspace Files",
            "",
            "Generated index for quick discovery. Use `workspace_list` for the live file tree.",
            "",
            f"**Root**: `{workspace_root}`",
            "",
        ]

        ignored_dirs = {RUNTIME_DIR, "__pycache__"}

        root_files = sorted(
            p
            for p in workspace_root.iterdir()
            if p.is_file() and not p.name.startswith(".") and p.name != AGENT_DOCUMENT
        )
        if root_files:
            lines.append("## Root Files")
            for file_path in root_files:
                rel = file_path.relative_to(workspace_root)
                size_str = self._format_file_size(file_path.stat().st_size)
                lines.append(f"- `{rel.as_posix()}` ({size_str})")
            lines.append("")

        state_dir = workspace_root / "state"
        if state_dir.exists() and state_dir.is_dir():
            state_files = sorted(
                p
                for p in state_dir.rglob("*")
                if p.is_file()
                and not any(
                    part.startswith(".") for part in p.relative_to(workspace_root).parts
                )
            )
            if state_files:
                lines.append("## state/")
                for file_path in state_files[:120]:
                    rel = file_path.relative_to(workspace_root)
                    size_str = self._format_file_size(file_path.stat().st_size)
                    extra = ""
                    if file_path.suffix == ".json":
                        try:
                            data = jr_parse(file_path.read_text(encoding="utf-8"))
                            purpose = self._describe_state_json(data, max_len=80)
                            state_summary = self._summarize_state_json(
                                data,
                                max_len=80,
                            )
                            details = [x for x in [purpose, state_summary] if x]
                            if details:
                                extra = " - " + " | ".join(details)
                        except Exception:
                            extra = " - unreadable json"
                    elif file_path.suffix == ".jsonl":
                        count = self._count_nonempty_lines(file_path)
                        extra = f" - {count} entries"
                    lines.append(f"- `{rel.as_posix()}` ({size_str}){extra}")
                if len(state_files) > 120:
                    lines.append(f"- ... {len(state_files) - 120} more state files")
                lines.append("")

        for dirname in ["memory", "input", "custom"]:
            dir_path = workspace_root / dirname
            if not dir_path.exists() or not dir_path.is_dir():
                continue
            files = sorted(
                p
                for p in dir_path.rglob("*")
                if p.is_file()
                and not any(
                    part.startswith(".") for part in p.relative_to(workspace_root).parts
                )
            )
            lines.append(f"## {dirname}/")
            for file_path in files[:80]:
                rel = file_path.relative_to(workspace_root)
                size_str = self._format_file_size(file_path.stat().st_size)
                extra = ""
                if file_path.suffix == ".jsonl":
                    extra = f" - {self._count_nonempty_lines(file_path)} entries"
                lines.append(f"- `{rel.as_posix()}` ({size_str}){extra}")
            if len(files) > 80:
                lines.append(f"- ... {len(files) - 80} more files")
            lines.append("")

        summarized_dirs = []
        for dirname in sorted(ignored_dirs):
            dir_path = workspace_root / dirname
            if dir_path.exists() and dir_path.is_dir():
                count = sum(1 for p in dir_path.rglob("*") if p.is_file())
                summarized_dirs.append(
                    f"- `{dirname}/` ({count} files, summarized only)"
                )
        if summarized_dirs:
            lines.append("## Runtime Directories")
            lines.extend(summarized_dirs)
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_file_size(size: int) -> str:
        """格式化文件大小。"""
        if size < 1024:
            return f"{size}B"
        elif size < 1024 * 1024:
            return f"{size / 1024:.1f}KB"
        else:
            return f"{size / (1024 * 1024):.1f}MB"

    def write_file_manifest(self) -> None:
        """将文件索引写入 AGENT.md 的自动生成区块。"""
        manifest = self.build_file_manifest()
        if manifest:
            existing = self.read_agent_context()
            content = self._replace_generated_file_index(
                str(existing.get("content", "")),
                manifest,
            )
            self._write_agent_context(dict(existing.get("metadata", {}) or {}), content)
