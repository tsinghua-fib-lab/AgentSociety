"""分析工具层的执行辅助。"""

import asyncio
import fnmatch
import json
import os
import platform
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from agentsociety2.logger import get_logger

logger = get_logger()


@dataclass
class ExecutionResult:
    """代码执行结果。"""

    success: bool
    stdout: str = ""
    stderr: str = ""
    artifacts: list[str] = field(default_factory=list)
    generated_code: str = ""
    error: str = ""


@dataclass
class ToolInfo:
    """工具元数据。"""

    name: str
    description: str
    tool_type: str = "builtin"
    parameters: list[str] = field(default_factory=list)


class ToolResult(BaseModel):
    """工具执行结果。"""

    success: bool
    content: str
    error: str | None = None
    data: Any = None


class ToolRegistry:
    """内置分析工具的注册表。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)
        self._tools: dict[str, ToolInfo] = {}
        self._tool_classes: dict[str, type] = {}
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        builtin_tools = {
            "list_directory": (ListDirectoryTool, "List directory contents"),
            "read_file": (ReadFileTool, "Read file contents"),
            "write_file": (WriteFileTool, "Write content to files"),
            "glob": (GlobTool, "Find files matching glob patterns"),
            "search_file_content": (
                SearchFileContentTool,
                "Search for content in files",
            ),
            "replace": (ReplaceTool, "Replace text in files"),
            "run_shell_command": (RunShellCommandTool, "Execute shell commands"),
            "write_todos": (WriteTodoTool, "Manage todo lists"),
            "literature_search": (LiteratureSearchTool, "Search literature"),
            "load_literature": (LoadLiteratureTool, "Load literature entries"),
        }

        for name, (tool_class, description) in builtin_tools.items():
            self._tools[name] = ToolInfo(
                name=name,
                description=description,
                tool_type="builtin",
            )
            self._tool_classes[name] = tool_class

    def list_tools(self) -> dict[str, ToolInfo]:
        return self._tools.copy()

    async def execute_tool(self, name: str, parameters: dict[str, Any]) -> ToolResult:
        if name not in self._tool_classes:
            return ToolResult(
                success=False,
                content=f"Tool not found: {name}",
                error="tool_not_found",
            )

        tool_class = self._tool_classes[name]
        tool = tool_class(workspace_path=self.workspace_path)
        return await tool.execute(parameters)


class GlobTool:
    """查找匹配 glob 模式的文件。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        pattern = arguments.get("pattern", "")
        path_arg = arguments.get("path", ".")

        search_dir = (self.workspace_path / path_arg).resolve()
        try:
            search_dir.relative_to(self.workspace_path)
        except ValueError:
            return ToolResult(
                success=False,
                content="Path outside workspace",
                error="path_outside_workspace",
            )

        if not search_dir.exists():
            return ToolResult(
                success=False,
                content=f"Path not found: {search_dir}",
                error="path_not_found",
            )

        matches = []
        for item in sorted(search_dir.rglob(pattern)):
            if item.is_file():
                try:
                    matches.append(str(item.relative_to(self.workspace_path)))
                except ValueError:
                    continue

        return ToolResult(
            success=True,
            content=f"Found {len(matches)} files matching '{pattern}'",
            data={"matches": matches, "count": len(matches)},
        )


class ListDirectoryTool:
    """列出目录内容。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        rel_path = arguments.get("path", ".").strip()
        ignore_patterns = arguments.get("ignore", [])

        target_dir = (self.workspace_path / rel_path).resolve()
        try:
            target_dir.relative_to(self.workspace_path)
        except ValueError:
            return ToolResult(
                success=False,
                content="Path outside workspace",
                error="path_outside_workspace",
            )

        if not target_dir.exists() or not target_dir.is_dir():
            return ToolResult(
                success=False,
                content=f"Not a directory: {rel_path}",
                error="not_a_directory",
            )

        entries = []
        for entry in target_dir.iterdir():
            should_ignore = any(fnmatch.fnmatch(entry.name, p) for p in ignore_patterns)
            if not should_ignore:
                entries.append(
                    {
                        "name": entry.name,
                        "type": "directory" if entry.is_dir() else "file",
                    }
                )

        entries.sort(key=lambda x: (x["type"] != "directory", x["name"]))
        return ToolResult(
            success=True,
            content=f"Listed {len(entries)} entries in {rel_path}",
            data={"entries": entries, "path": rel_path},
        )


class ReadFileTool:
    """读取文件内容。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        file_path = arguments.get("path", "").strip()
        limit = arguments.get("limit")

        target_file = (self.workspace_path / file_path).resolve()
        try:
            target_file.relative_to(self.workspace_path)
        except ValueError:
            return ToolResult(
                success=False,
                content="Path outside workspace",
                error="path_outside_workspace",
            )

        if not target_file.exists() or not target_file.is_file():
            return ToolResult(
                success=False,
                content=f"File not found: {file_path}",
                error="file_not_found",
            )

        content = target_file.read_text(encoding="utf-8")
        if limit and len(content) > limit:
            content = content[:limit] + "\n... (truncated)"

        return ToolResult(
            success=True,
            content=f"Read {len(content)} characters from {file_path}",
            data={"path": file_path, "content": content},
        )


class WriteFileTool:
    """写入文件内容。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        file_path = arguments.get("path", "").strip()
        content = arguments.get("content", "")
        create_directories = arguments.get("create_directories", False)

        target_file = (self.workspace_path / file_path).resolve()
        try:
            target_file.relative_to(self.workspace_path)
        except ValueError:
            return ToolResult(
                success=False,
                content="Path outside workspace",
                error="path_outside_workspace",
            )

        if create_directories:
            target_file.parent.mkdir(parents=True, exist_ok=True)

        target_file.write_text(content, encoding="utf-8")
        return ToolResult(
            success=True,
            content=f"Wrote {len(content)} characters to {file_path}",
            data={"path": file_path},
        )


class SearchFileContentTool:
    """搜索文件内容。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        pattern = arguments.get("pattern", "")
        path_arg = arguments.get("path", ".")
        case_sensitive = arguments.get("case_sensitive", False)

        search_dir = (self.workspace_path / path_arg).resolve()
        results = []

        flags = 0 if case_sensitive else re.IGNORECASE
        regex = re.compile(pattern, flags)

        for item in search_dir.rglob("*"):
            if not item.is_file():
                continue
            try:
                content = item.read_text(encoding="utf-8", errors="ignore")
                matches = []
                for line_num, line in enumerate(content.splitlines(), 1):
                    if regex.search(line):
                        matches.append({"line": line_num, "text": line})
                if matches:
                    rel_path = item.relative_to(self.workspace_path)
                    results.append({"path": str(rel_path), "matches": matches[:10]})
            except Exception:
                continue

        return ToolResult(
            success=True,
            content=f"Found pattern in {len(results)} files",
            data={"results": results, "count": len(results)},
        )


class ReplaceTool:
    """替换文件中的文本。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        file_path = arguments.get("path", "").strip()
        old_text = arguments.get("old_text", "")
        new_text = arguments.get("new_text", "")

        target_file = (self.workspace_path / file_path).resolve()
        try:
            target_file.relative_to(self.workspace_path)
        except ValueError:
            return ToolResult(
                success=False,
                content="Path outside workspace",
                error="path_outside_workspace",
            )

        if not target_file.exists():
            return ToolResult(
                success=False,
                content=f"File not found: {file_path}",
                error="file_not_found",
            )

        content = target_file.read_text(encoding="utf-8")
        count = content.count(old_text)
        new_content = content.replace(old_text, new_text)
        target_file.write_text(new_content, encoding="utf-8")

        return ToolResult(
            success=True,
            content=f"Replaced {count} occurrence(s) in {file_path}",
            data={"path": file_path, "count": count},
        )


class RunShellCommandTool:
    """在工作区内执行 shell 命令。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        command = (arguments.get("command") or "").strip()
        directory = arguments.get("directory")

        if not command:
            return ToolResult(
                success=False,
                content="Command is required",
                error="missing_command",
            )

        exec_dir = self.workspace_path
        if directory:
            exec_dir = (self.workspace_path / directory).resolve()
        try:
            exec_dir.relative_to(self.workspace_path)
        except ValueError:
            return ToolResult(
                success=False,
                content="Directory is outside workspace",
                error="directory_outside_workspace",
            )

        if not exec_dir.exists():
            return ToolResult(
                success=False,
                content=f"Directory not found: {exec_dir}",
                error="directory_not_found",
            )

        if platform.system() == "Windows":
            shell_executable = os.environ.get("ComSpec", "powershell.exe")
            shell_args = (
                ["-NoProfile", "-Command"]
                if shell_executable.endswith("powershell.exe")
                else ["/c"]
            )
        else:
            shell_executable = "/bin/bash"
            shell_args = ["-c"]

        process = await asyncio.create_subprocess_exec(
            shell_executable,
            *shell_args,
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(exec_dir),
        )
        stdout_data, stderr_data = await process.communicate()
        stdout = stdout_data.decode("utf-8", errors="replace") if stdout_data else ""
        stderr = stderr_data.decode("utf-8", errors="replace") if stderr_data else ""
        exit_code = process.returncode or 0

        content_parts = [f"Command: {command}", f"Exit Code: {exit_code}"]
        if stdout:
            content_parts.append(f"\nStdout:\n{stdout}")
        if stderr:
            content_parts.append(f"\nStderr:\n{stderr}")

        return ToolResult(
            success=exit_code == 0,
            content="\n".join(content_parts),
            data={
                "command": command,
                "stdout": stdout,
                "stderr": stderr,
                "exit_code": exit_code,
            },
        )


class WriteTodoTool:
    """管理 todo 列表。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        todos_data = arguments.get("todos", [])
        if not isinstance(todos_data, list):
            return ToolResult(
                success=False,
                content="Invalid argument: 'todos' must be an array",
                error="InvalidArgument",
            )

        in_progress_count = sum(
            1 for todo in todos_data if todo.get("status") == "in_progress"
        )
        if in_progress_count > 1:
            return ToolResult(
                success=False,
                content="Only one task can be marked as 'in_progress' at a time",
                error="MultipleInProgress",
            )

        if not todos_data:
            content_text = "Todo list cleared."
        else:
            status_icons = {
                "pending": "⏳",
                "in_progress": "🔄",
                "completed": "✅",
                "cancelled": "❌",
            }
            content_text = f"Todo list updated with {len(todos_data)} items.\n\n"
            for todo in todos_data:
                icon = status_icons.get(todo.get("status", "pending"), "•")
                content_text += (
                    f"{icon} {todo.get('description', '')} ({todo.get('status')})\n"
                )

        return ToolResult(
            success=True,
            content=content_text,
            data={"todos": todos_data, "count": len(todos_data)},
        )


class LoadLiteratureTool:
    """加载已建立索引的文献条目。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        path = arguments.get("path", "papers/literature_index.json")
        target_file = (self.workspace_path / path).resolve()

        if not target_file.exists():
            return ToolResult(
                success=False,
                content=f"Literature file not found: {path}",
                error="file_not_found",
            )

        data = json.loads(target_file.read_text(encoding="utf-8"))
        entries = data.get("entries", [])

        return ToolResult(
            success=True,
            content=f"Loaded {len(entries)} literature entries",
            data={"entries": entries, "count": len(entries)},
        )


class LiteratureSearchTool:
    """检索文献并将结果保存到工作区。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)

    async def execute(self, arguments: dict[str, Any]) -> ToolResult:
        from agentsociety2.skills.literature import search_literature_and_save

        query = arguments.get("query", "")
        limit = arguments.get("limit", 10)

        result = await search_literature_and_save(
            query=query,
            workspace_path=self.workspace_path,
            limit=limit,
        )

        if result.get("success"):
            return ToolResult(
                success=True,
                content=result.get("content", ""),
                data=result,
            )
        return ToolResult(
            success=False,
            content=result.get("content", ""),
            error=result.get("error"),
        )
