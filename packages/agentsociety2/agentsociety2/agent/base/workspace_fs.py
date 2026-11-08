"""面向 agent 本地文件的工作区文件系统。

中文：提供受限的 agent workspace 文件访问、搜索和命令执行能力。
English: Provides restricted agent workspace file access, search, and command execution.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import signal
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

RUNTIME_DIR = ".runtime"


@dataclass(frozen=True)
class FileInfo:
    """工作区文件元数据。

    :param path: 相对工作区根的路径。
    :param size: 文件字节大小,目录为零。
    :param is_dir: 该路径是否为目录。
    """

    path: str
    size: int
    is_dir: bool = False


@dataclass(frozen=True)
class FileOpResult:
    """工作区文件操作结果。

    :param ok: 操作是否成功。
    :param path: 相对工作区根的路径。
    :param bytes_written: 适用时写入的字节数。
    :param error: 可选的错误信息。
    """

    ok: bool
    path: str
    bytes_written: int = 0
    error: str = ""


@dataclass(frozen=True)
class GrepMatch:
    """单条文本搜索匹配。

    :param path: 相对工作区根的路径。
    :param line: 从 1 开始计数的行号。
    :param text: 匹配到的行文本。
    """

    path: str
    line: int
    text: str


@dataclass(frozen=True)
class CommandResult:
    """受限命令执行结果。

    :param ok: 命令是否成功退出。
    :param exit_code: 进程退出码,校验/超时失败时为 -1。
    :param stdout: 捕获的标准输出。
    :param stderr: 捕获的标准错误。
    :param error_type: 错误类别。
    """

    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    error_type: str = "none"


class WorkspaceFS:
    """单个 agent 工作区的受限文件系统门面。"""

    def __init__(
        self,
        root: Path,
        *,
        ignored_dirs: set[str] | None = None,
    ) -> None:
        """初始化工作区文件系统。

        :param root: 工作区根目录。
        :param ignored_dirs: 在递归列目录/搜索中隐藏的目录名。
        :returns: 无返回值。
        """
        self.root = root.resolve()
        self.ignored_dirs = ignored_dirs or {RUNTIME_DIR, "__pycache__"}

    def resolve(self, relative_path: str) -> Path:
        """解析工作区内的一个路径。

        :param relative_path: 相对工作区根的路径。
        :returns: 解析后的绝对路径。
        """
        target = (self.root / str(relative_path or ".")).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError(f"Path escapes agent workspace: {relative_path}")
        return target

    def read_text(self, path: str) -> str:
        """读取 UTF-8 文本文件。

        :param path: 相对工作区根的路径。
        :returns: 文件文本,文件不存在时返回空字符串。
        """
        target = self.resolve(path)
        if not target.exists() or not target.is_file():
            return ""
        return target.read_text(encoding="utf-8")

    def _is_runtime_owned(self, relative_path: str) -> bool:
        """该路径是否落在运行时目录(``.runtime/``,核心持有,LLM 不可写)。"""
        target = self.resolve(relative_path)
        return any(
            part.casefold() == RUNTIME_DIR
            for part in target.relative_to(self.root).parts
        )

    def write_text(self, path: str, content: str) -> FileOpResult:
        """写入 UTF-8 文本文件。

        :param path: 相对工作区根的路径。
        :param content: 要写入的文本内容。
        :returns: 文件操作结果。
        """
        if self._is_runtime_owned(path):
            return FileOpResult(ok=False, path=path, error="runtime-owned path")
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = str(content)
        target.write_text(text, encoding="utf-8")
        return FileOpResult(
            ok=True,
            path=target.relative_to(self.root).as_posix(),
            bytes_written=len(text.encode("utf-8")),
        )

    def append_text(self, path: str, content: str) -> FileOpResult:
        """向文件追加 UTF-8 文本。

        :param path: 相对工作区根的路径。
        :param content: 要追加的文本内容。
        :returns: 文件操作结果。
        """
        if self._is_runtime_owned(path):
            return FileOpResult(ok=False, path=path, error="runtime-owned path")
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        text = str(content)
        with target.open("a", encoding="utf-8") as f:
            f.write(text)
        return FileOpResult(
            ok=True,
            path=target.relative_to(self.root).as_posix(),
            bytes_written=len(text.encode("utf-8")),
        )

    def delete(self, path: str) -> FileOpResult:
        """删除单个文件。

        :param path: 相对工作区根的路径。
        :returns: 文件操作结果。
        """
        if self._is_runtime_owned(path):
            return FileOpResult(ok=False, path=path, error="runtime-owned path")
        target = self.resolve(path)
        if not target.exists() or target.is_dir():
            return FileOpResult(ok=False, path=path, error="file not found")
        target.unlink()
        return FileOpResult(ok=True, path=target.relative_to(self.root).as_posix())

    def exists(self, path: str) -> bool:
        """返回工作区路径是否存在。

        :param path: 相对工作区根的路径。
        :returns: 路径存在时返回 True。
        """
        return self.resolve(path).exists()

    def list(
        self,
        path: str = ".",
        *,
        glob: str | None = None,
        limit: int = 200,
    ) -> list[FileInfo]:
        """列出工作区某路径下的文件和目录。

        :param path: 相对工作区根的路径。
        :param glob: 可选的 glob 模式。
        :param limit: 最大条目数。
        :returns: 文件元数据条目。
        """
        target = self.resolve(path)
        if not target.exists():
            return []
        if target.is_file():
            return [self._file_info(target)]

        candidates = target.rglob(glob or "*")
        result: list[FileInfo] = []
        for item in sorted(candidates):
            rel_parts = item.relative_to(self.root).parts
            if any(part in self.ignored_dirs for part in rel_parts):
                continue
            result.append(self._file_info(item))
            if len(result) >= limit:
                break
        return result

    async def grep(
        self,
        pattern: str,
        path: str = ".",
        *,
        limit: int = 100,
    ) -> list[GrepMatch]:
        """用 ripgrep 或 grep 搜索文本文件。

        :param pattern: 搜索模式。
        :param path: 相对工作区根的路径。
        :param limit: 最大匹配数。
        :returns: 搜索匹配结果。
        """
        target = self.resolve(path)
        if not target.exists():
            return []

        if sys.platform == "win32":
            return self._grep_python(target, pattern, limit=limit)

        tool = shutil.which("rg")
        if tool:
            argv = [
                tool,
                "--line-number",
                "--no-heading",
                "--color",
                "never",
                "--glob",
                f"!{RUNTIME_DIR}/**",
                "--glob",
                "!__pycache__/**",
                # 二轮审计修复:pattern 裸拼裸位置参数可被注入成
                # rg 选项(--pre=<命令> 即 RCE,绕过 run_command 的
                # 解释器白名单)。-e 之后必为 pattern 本体。
                "-e",
                pattern,
                "--",
                str(target),
            ]
        else:
            grep = shutil.which("grep")
            if not grep:
                return self._grep_python(target, pattern, limit=limit)
            argv = [
                grep,
                "-r",
                "-n",
                "--exclude-dir",
                RUNTIME_DIR,
                # 同 rg:-e 守护选项注入(如 -f/--include 被注入)。
                "-e",
                pattern,
                "--",
                str(target),
            ]

        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(self.root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        # 审计修复(2026-11-04):grep -R 遇 FIFO/特殊文件会阻塞读取且
        # 永不返回(rg 会跳过;workspace 恰是 skill 脚本可写区域,可 mkfifo);
        # grep 又在并行安全名单里,挂死会放大为整个 react 轮停摆。加超时
        # 并杀进程组;returncode==2(坏 pattern)不再与"无匹配"混淆。
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=30)
        except (TimeoutError, asyncio.CancelledError) as exc:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError, OSError):
                proc.kill()
            await proc.communicate()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise RuntimeError(
                f"grep timed out after 30s (pathological pattern or "
                f"special files in workspace): {pattern!r}"
            )
        if proc.returncode not in {0, 1}:
            detail = (stderr_b or b"").decode("utf-8", "replace")[:200]
            raise RuntimeError(
                f"grep failed with returncode={proc.returncode}: {detail}"
            )
        return self._parse_grep_output(stdout_b, limit=limit)

    async def run_command(
        self,
        argv: list[str],
        *,
        timeout_sec: int = 30,
        cwd: str = ".",
        env: dict[str, str] | None = None,
        input_text: str | None = None,
    ) -> CommandResult:
        """在工作区内运行一条被允许的命令。

        :param argv: 命令参数向量。
        :param timeout_sec: 超时秒数。
        :param cwd: 相对工作区根的工作目录。
        :param env: 可选的进程环境变量。
        :param input_text: 可选的标准输入，避免将结构化负载放入命令行。
        :returns: 命令执行结果。
        """
        if not argv:
            return CommandResult(False, -1, "", "empty argv", "validation")
        if Path(argv[0]).name not in {"python", "python3", Path(sys.executable).name}:
            return CommandResult(False, -1, "", "command not allowed", "validation")
        work_dir = self.resolve(cwd)
        if not work_dir.is_dir():
            return CommandResult(False, -1, "", "cwd not found", "validation")

        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(work_dir),
            env=env,
            stdin=asyncio.subprocess.PIPE if input_text is not None else None,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=os.name == "posix",
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(
                proc.communicate(
                    input_text.encode("utf-8") if input_text is not None else None
                ),
                timeout=timeout_sec,
            )
        except (TimeoutError, asyncio.CancelledError) as exc:
            # 终止整组普通子进程，避免后代进程继续持有输出管道或写工作区。
            # 子进程可能恰好已退出，只忽略进程不存在这一竞争结果。
            with suppress(ProcessLookupError):
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
            await proc.communicate()
            if isinstance(exc, asyncio.CancelledError):
                raise
            return CommandResult(
                False,
                -1,
                "",
                f"command timed out after {timeout_sec}s",
                "timeout",
            )

        stdout = (stdout_b or b"").decode("utf-8", errors="replace")
        stderr = (stderr_b or b"").decode("utf-8", errors="replace")
        exit_code = int(proc.returncode or 0)
        return CommandResult(
            ok=exit_code == 0,
            exit_code=exit_code,
            stdout=stdout,
            stderr=stderr,
            error_type="none" if exit_code == 0 else "runtime",
        )

    def _file_info(self, path: Path) -> FileInfo:
        """构造单个路径的元数据。

        :param path: 工作区内的绝对路径。
        :returns: 文件元数据。
        """
        rel = path.relative_to(self.root).as_posix()
        return FileInfo(
            path=rel,
            size=path.stat().st_size if path.is_file() else 0,
            is_dir=path.is_dir(),
        )

    def _grep_python(
        self, target: Path, pattern: str, *, limit: int
    ) -> list[GrepMatch]:
        regex = re.compile(pattern)
        candidates = [target] if target.is_file() else sorted(target.rglob("*"))
        matches: list[GrepMatch] = []
        for path in candidates:
            if not path.is_file():
                continue
            rel_parts = path.relative_to(self.root).parts
            if any(part in self.ignored_dirs for part in rel_parts):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            for lineno, line in enumerate(text.splitlines(), start=1):
                if not regex.search(line):
                    continue
                matches.append(
                    GrepMatch(
                        path=path.relative_to(self.root).as_posix(),
                        line=lineno,
                        text=line,
                    )
                )
                if len(matches) >= limit:
                    return matches
        return matches

    def _parse_grep_output(self, stdout_b: bytes, *, limit: int) -> list[GrepMatch]:
        """解析 grep 兼容的 stdout。

        :param stdout_b: 原始 grep 输出字节。
        :param limit: 最大匹配数。
        :returns: 解析后的搜索匹配。
        """
        matches: list[GrepMatch] = []
        stdout = (stdout_b or b"").decode("utf-8", errors="replace")
        for raw_line in stdout.splitlines():
            path_part, sep, rest = raw_line.partition(":")
            if not sep:
                continue
            line_part, sep, text = rest.partition(":")
            if not sep:
                continue
            try:
                line_no = int(line_part)
            except ValueError:
                continue
            rel_path = self._normalize_match_path(path_part)
            matches.append(GrepMatch(path=rel_path, line=line_no, text=text))
            if len(matches) >= limit:
                break
        return matches

    def _normalize_match_path(self, raw_path: str) -> str:
        """将一个匹配路径规范化为工作区相对路径。

        :param raw_path: grep 输出中的路径字符串。
        :returns: 可行时返回工作区相对路径。
        """
        path = Path(raw_path)
        if not path.is_absolute():
            path = self.root / path
        try:
            return path.resolve().relative_to(self.root).as_posix()
        except ValueError:
            return raw_path
