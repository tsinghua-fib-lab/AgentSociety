"""Agent skill 运行时。

中文：管理 skill 可见性、激活状态、脚本执行和运行时事件。
English: Manages skill visibility, activation state, script execution, and runtime events.
"""

from __future__ import annotations

import ast
import asyncio
import importlib.util
import inspect
import json
import os
import sys
import traceback
import types
from collections.abc import Iterable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from agentsociety2.agent.base.skill_hook_context import (
    HookContext,
    _reset_hook_context,
    _set_hook_context,
)
from agentsociety2.agent.base.skill_registry import SkillDescriptor
from agentsociety2.agent.base.skill_script_context import SkillScriptContext
from agentsociety2.agent.base.workspace_fs import CommandResult, WorkspaceFS
from agentsociety2.agent.person_prompt import skill_content_xml
from agentsociety2.trace import JsonlTraceWriter

ALLOWED_ENV_VARS = frozenset(
    {
        "PATH",
        "HOME",
        "USER",
        "SHELL",
        "PYTHONUNBUFFERED",
        "LITELLM_MODEL",
        "LITELLM_BASE_URL",
        "AGENT_MEMORY_MAX_ENTRIES",
        "AGENT_MEMORY_STRENGTH",
    }
)


class SkillRegistryLike(Protocol):
    """Runtime 使用的 registry 接口。"""

    def list_all(self) -> list[SkillDescriptor]:
        """列出全部已注册的 skill。

        :returns: 已注册的 skill 描述符。
        """
        return []

    def get(self, skill_id: str) -> SkillDescriptor | None:
        """按 id 返回一个 skill 描述符。

        :param skill_id: registry skill id。
        :returns: 匹配的描述符,无匹配时为 None。
        """
        return None

    def find_by_name(self, name: str) -> list[SkillDescriptor]:
        """按显示名查找 skill 描述符。

        :param name: skill 显示名。
        :returns: 匹配的描述符。
        """
        return []

    def read_skill_doc(self, skill_id: str) -> str:
        """读取一个 skill 的 SKILL.md。

        :param skill_id: registry skill id。
        :returns: skill 文档文本,失败时为空字符串。
        """
        return ""

    def read_skill_file(self, skill_id: str, relative_path: str) -> str:
        """读取 skill 目录内的一个文件。

        :param skill_id: registry skill id。
        :param relative_path: 相对 skill 根目录的路径。
        :returns: 文件文本,失败时为空字符串。
        """
        return ""

    def list_hooks(self, hook_type: str) -> list[SkillDescriptor]:
        """列出声明了某个 hook 的 skill。

        :param hook_type: 生命周期 hook 名。
        :returns: 声明了该 hook 的 skill 描述符。
        """
        return []


@dataclass(frozen=True)
class ScriptRunResult:
    """Skill 脚本执行结果。"""

    ok: bool
    exit_code: int
    stdout: str
    stderr: str
    error_type: str

    def as_dict(self) -> dict[str, Any]:
        """返回可序列化的脚本执行结果。

        :returns: 本结果的字典表示。
        """
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error_type": self.error_type,
        }


class AgentSkillRuntime:
    """管理 skill 可见性、激活与执行的运行时。"""

    def __init__(
        self,
        registry: SkillRegistryLike,
    ) -> None:
        """初始化 skill runtime。

        :param registry: 本 runtime 使用的 skill registry 门面。
        :returns: 无返回值。
        """
        self._registry = registry
        self._agent_work_dir: Path | None = None
        self._fs: WorkspaceFS | None = None
        self._trace_writer: JsonlTraceWriter | None = None
        self._visible_skill_ids: set[str] = set()
        self._activated_skill_ids: set[str] = set()
        # Imported skill-script modules, cached by (path, mtime) so the module
        # body runs once; later calls just invoke its entrypoint.
        self._script_module_cache: dict[tuple[str, float], types.ModuleType] = {}
        self._activated_content_cache_key: tuple[str, ...] | None = None
        self._activated_content_cache_value: str = ""

    # ------------------------------------------------------------------
    # Workspace lifecycle
    # ------------------------------------------------------------------

    def bind_workspace(
        self,
        *,
        workspace_root: Path,
        fs: WorkspaceFS,
        trace_writer: JsonlTraceWriter,
    ) -> None:
        """将本 runtime 绑定到 agent 持有的 workspace。

        :param workspace_root: agent 创建的 workspace 根目录。
        :param fs: agent 持有的 workspace 文件系统门面。
        :param trace_writer: agent 持有的 trace writer。
        :returns: 无返回值。
        """
        self._agent_work_dir = workspace_root.resolve()
        self._fs = fs
        self._trace_writer = trace_writer

    def workspace_root(self) -> Path:
        """返回 workspace 根目录。

        :returns: 绝对 workspace 根路径。
        """
        if self._agent_work_dir is None:
            raise RuntimeError("Agent workspace is not initialized")
        return self._agent_work_dir

    @property
    def fs(self) -> WorkspaceFS:
        """返回 workspace 文件系统门面。

        :returns: workspace 文件系统门面。
        """
        if self._fs is None:
            raise RuntimeError("Agent workspace is not initialized")
        return self._fs

    # ------------------------------------------------------------------
    # Skill facade
    # ------------------------------------------------------------------

    def set_visible_skills(self, tokens: Iterable[str]) -> None:
        """设置本 agent 的可见 skill。

        每项可以是 registry skill id(``namespace@name``)或显示名;两种
        形式都面向整个 registry 解析。

        :param tokens: 候选 skill id 或显示名。
        :returns: 无返回值。
        """
        self._visible_skill_ids = {
            sid
            for sid in (
                self.resolve_skill_id(tok, visible_only=False) for tok in tokens
            )
            if sid
        }
        self._activated_skill_ids.intersection_update(self._visible_skill_ids)

    def visible_skill_ids(self) -> set[str]:
        """返回可见 skill id。

        :returns: 可见 skill id 集合的副本。
        """
        return set(self._visible_skill_ids)

    def visible_skill_count(self) -> int:
        """返回可见 skill 数量。

        :returns: 可见 skill 的数量。
        """
        return len(self._visible_skill_ids)

    def list_visible_skills(self) -> list[SkillDescriptor]:
        """列出可见 skill 的描述符。

        :returns: 可见 skill 的描述符。
        """
        result = [
            self._registry.get(skill_id) for skill_id in sorted(self._visible_skill_ids)
        ]
        return [item for item in result if item is not None]

    def skill_catalog(self) -> list[dict[str, str]]:
        """构建紧凑的可见 skill 目录。

        :returns: 含 name 与 description 的目录条目。
        """
        return [
            {
                "name": item.name,
                "description": item.description,
            }
            for item in self.list_visible_skills()
        ]

    def set_activated_skills(self, tokens: Iterable[str]) -> None:
        """从可见 skill 中设置已激活的 skill。

        每项可以是 skill id(``namespace@name``)或显示名;两种形式都
        面向可见 skill 解析。

        :param tokens: 要激活的候选 skill id 或显示名。
        :returns: 无返回值。
        """
        self._activated_skill_ids = {
            sid for sid in (self.resolve_skill_id(tok) for tok in tokens) if sid
        }

    def add_default_activated_skills(self, tokens: Iterable[str]) -> None:
        """在可见时激活配置的默认 skill。

        每项可以是 skill id 或显示名。

        :param tokens: 外层 agent config 请求的 skill id 或显示名。
        :returns: 无返回值。
        """
        for token in tokens:
            sid = self.resolve_skill_id(token)
            if sid:
                self._activated_skill_ids.add(sid)

    def activated_skill_ids(self) -> set[str]:
        """返回已激活的 skill id。

        :returns: 已激活 skill id 集合的副本。
        """
        return set(self._activated_skill_ids)

    def infer_single_script_skill_id(self) -> str:
        """恰有一个可见且已激活的 skill 带默认脚本时推断该 skill。

        :returns: 唯一带脚本的活跃 skill 的 skill id,否则为空字符串。
        """
        candidates = [
            skill_id
            for skill_id in sorted(self._activated_skill_ids)
            if skill_id in self._visible_skill_ids
            and (self._registry.get(skill_id) is not None)
            and self._registry.get(skill_id).script
        ]
        if len(candidates) == 1:
            return candidates[0]
        return ""

    def resolve_skill_id(self, token: str, *, visible_only: bool = True) -> str:
        """将 skill id 或显示名解析为 registry skill id。

        接受 registry skill id(``namespace@name``)或裸显示名 ``name``
        ——本 runtime 的每个公开 skill API 都取同样的 ``token`` 并兼容
        两种形式。``visible_only`` 为 True(默认)时解析限于可见 skill;
        为 False 时搜索整个 registry(用于尚未可见的 skill,如
        :meth:`set_visible_skills` 中)。

        有歧义的显示名(多于一个匹配)只在恰有一个候选当前已激活时
        才能解析。

        :param token: 来自工具参数 / agent config 的 skill id
            (``namespace@name``)或显示名。
        :param visible_only: 是否将解析限制在可见 skill 内。
        :returns: 匹配的 skill id;未找到或有歧义时为空字符串。
        """
        text = str(token or "").strip()
        if not text:
            return ""
        pool = (
            self._visible_skill_ids
            if visible_only
            else {item.skill_id for item in self._registry.list_all()}
        )
        if text in pool:
            return text
        matches = [
            item for item in self._registry.find_by_name(text) if item.skill_id in pool
        ]
        if len(matches) == 1:
            return matches[0].skill_id
        active_matches = [
            item for item in matches if item.skill_id in self._activated_skill_ids
        ]
        if len(active_matches) == 1:
            return active_matches[0].skill_id
        return ""

    def activate_skill(self, token: str) -> tuple[bool, str, str]:
        """按 id 或显示名激活一个可见 skill。

        :param token: skill id(``namespace@name``)或显示名。
        :returns: ``(activated, skill_id, skill_doc)`` 三元组。
        """
        skill_id = self.resolve_skill_id(token)
        doc = self.load_skill_doc(skill_id)
        if doc:
            self._activated_skill_ids.add(skill_id)
            self._activated_content_cache_key = None
        return bool(doc), skill_id, doc

    def deactivate_skill(self, token: str) -> tuple[bool, str]:
        """按 id 或显示名停用一个可见 skill。

        :param token: skill id(``namespace@name``)或显示名。
        :returns: ``(removed, skill_id)`` 二元组。
        """
        skill_id = self.resolve_skill_id(token)
        removed = skill_id in self._activated_skill_ids
        self._activated_skill_ids.discard(skill_id)
        if removed:
            self._activated_content_cache_key = None
        return removed, skill_id

    def activated_skill_content_xml(self) -> str:
        """渲染已激活 skill 的文档与资源提示。

        :returns: 活跃 skill 的 XML 风格内容块。
        """
        cache_key = tuple(sorted(self._activated_skill_ids))
        if (
            self._activated_content_cache_key == cache_key
            and self._activated_content_cache_value is not None
        ):
            return self._activated_content_cache_value

        blocks: list[str] = []
        for skill_id in cache_key:
            info = self._registry.get(skill_id)
            if info is None:
                continue
            doc = self.load_skill_doc(skill_id)
            if not doc:
                continue
            blocks.append(
                skill_content_xml(
                    name=info.name,
                    content=doc,
                    resources=info.resource_files(),
                )
            )
        rendered = "\n\n".join(blocks)
        self._activated_content_cache_key = cache_key
        self._activated_content_cache_value = rendered
        return rendered

    def active_hook_skills(self, hook_type: str) -> list[SkillDescriptor]:
        """列出声明了某个 hook 的可见且已激活的 skill。

        :param hook_type: 生命周期 hook 名。
        :returns: 有资格运行该 hook 的 skill 描述符。
        """
        return [
            info
            for info in self._registry.list_hooks(hook_type)
            if info.skill_id in self._visible_skill_ids
            and info.skill_id in self._activated_skill_ids
        ]

    def load_skill_doc(self, skill_id: str) -> str:
        """读取一个可见 skill 的文档。

        :param skill_id: registry skill id。
        :returns: SKILL.md 文本,失败时为空字符串。
        """
        if not self._is_visible(skill_id):
            return ""
        return self._registry.read_skill_doc(skill_id)

    def read_skill_file(self, skill_id: str, relative_path: str) -> str:
        """读取一个可见 skill 内部的文件。

        :param skill_id: registry skill id。
        :param relative_path: 相对 skill 根目录的路径。
        :returns: 文件文本,失败时为空字符串。
        """
        if not self._is_visible(skill_id):
            return ""
        return self._registry.read_skill_file(skill_id, relative_path)

    def resolve_skill_path(self, path: str | Path) -> tuple[str, str] | None:
        """将一个路径映射为可见 skill 内的 ``(skill_id, relative_path)``。

        用于兜底恢复:agent 经由通用 workspace ``read`` 工具尝试 ``read``
        一个 skill 内嵌文件(如 ``references/examples.md``)时,该工具只
        能看到 agent workspace,会把这类路径当作"越界"拒绝。返回映射使
        调用方可以透明转交给 :meth:`read_skill_file`,而非直接失败。

        两种匹配策略,按顺序:

        1. 直接包含——解析后的绝对路径位于某个可见 skill 根目录内。
        2. skill 名段——某个路径分量等于某个可见 skill 的 ``skill_id``
           或 ``name``(如模型生成的
           ``.../skills/daily-guidance/references/examples.md``)。该段之后
           的分量被当作 skill 相对路径,且必须能解析到 skill 根下确实
           存在的文件。

        :param path: 待测试路径(绝对路径,或按段匹配的相对路径)。
        :returns: 命中可见 skill 文件时为 ``(skill_id, posix_relative_path)``,
            否则为 ``None``。
        """
        descriptors = self.list_visible_skills()
        by_root: list[tuple[str, Path]] = [
            (d.skill_id, Path(d.root)) for d in descriptors if d.root
        ]
        name_to_id: dict[str, str] = {}
        for d in descriptors:
            name_to_id[d.skill_id] = d.skill_id
            if d.name:
                name_to_id[d.name] = d.skill_id

        try:
            target = Path(path).expanduser().resolve(strict=False)
        except OSError:
            target = Path(str(path))

        # Strategy 1: direct containment under a skill root.
        for skill_id, root in by_root:
            try:
                rel = target.relative_to(root.resolve())
            except (ValueError, OSError):
                continue
            if (root / rel).is_file():
                return skill_id, rel.as_posix()

        # Strategy 2: a path segment names a visible skill.
        parts = [p for p in Path(path).parts if p not in ("", "/", ".")]
        for idx, part in enumerate(parts):
            skill_id = name_to_id.get(part)
            if skill_id is None or idx + 1 >= len(parts):
                continue
            rel = Path(*parts[idx + 1 :]).as_posix()
            root = next((r for sid, r in by_root if sid == skill_id), None)
            if root is not None and (root / rel).is_file():
                return skill_id, rel
        return None

    async def run_skill_script(
        self,
        skill_id: str,
        script_path: str,
        argv: list[str],
        *,
        timeout_sec: int = 30,
    ) -> ScriptRunResult:
        """运行可见 skill 内的一个脚本。

        :param skill_id: registry skill id。
        :param script_path: 相对 skill 根目录的路径;留空则使用默认脚本。
        :param argv: 命令行参数。
        :param timeout_sec: 执行超时秒数。
        :returns: 脚本执行结果。
        """
        info = self._registry.get(skill_id)
        if info is None:
            return self._script_error("validation", f"Skill not found: {skill_id}")
        if not self._is_visible(skill_id):
            return self._script_error("validation", f"Skill not visible: {skill_id}")
        script = str(script_path or "").strip()
        if not script:
            script = str(info.script or "").strip()
        elif (
            info.script
            and "/" not in script
            and "\\" not in script
            and Path(script).name == Path(str(info.script)).name
        ):
            script = str(info.script).strip()
        if not script:
            return self._script_error(
                "validation",
                "Script path is required because this skill declares no default script",
            )
        return await self._run_skill_path(
            info,
            script,
            argv,
            timeout_sec=timeout_sec,
            op_name="script.run",
            attributes={"skill.id": skill_id, "script.kind": "skill_file"},
        )

    async def run_skill_hook(
        self,
        skill_id: str,
        hook_type: str,
        argv: list[str],
        *,
        timeout_sec: int = 30,
    ) -> ScriptRunResult:
        """运行可见 skill 的一个生命周期 hook。

        :param skill_id: registry skill id。
        :param hook_type: 生命周期 hook 名。
        :param argv: 命令行参数。
        :param timeout_sec: 执行超时秒数。
        :returns: 脚本执行结果。
        """
        info = self._registry.get(skill_id)
        if info is None:
            return self._script_error("validation", f"Skill not found: {skill_id}")
        if not self._is_visible(skill_id):
            return self._script_error("validation", f"Skill not visible: {skill_id}")
        script = info.hooks.get(hook_type)
        if not script:
            return self._script_error(
                "validation",
                f"Hook not declared: {skill_id}:{hook_type}",
            )
        return await self._run_skill_path(
            info,
            script,
            argv,
            timeout_sec=timeout_sec,
            op_name="script.run_hook",
            attributes={
                "skill.id": skill_id,
                "script.kind": "hook",
                "hook.type": hook_type,
            },
        )

    def _is_visible(self, skill_id: str) -> bool:
        """返回一个 skill 是否可见。

        :param skill_id: registry skill id。
        :returns: skill 可见时为 True。
        """
        return skill_id in self._visible_skill_ids

    async def _run_skill_path(
        self,
        info: SkillDescriptor,
        relative_script: str,
        argv: list[str],
        *,
        timeout_sec: int,
        op_name: str,
        attributes: dict[str, Any],
    ) -> ScriptRunResult:
        """运行一个已校验的 skill 脚本路径。

        :param info: skill 描述符。
        :param relative_script: 相对 skill 根目录的脚本路径。
        :param argv: 命令行参数。
        :param timeout_sec: 执行超时秒数。
        :param op_name: trace 操作名。
        :param attributes: 额外的 trace 属性。
        :returns: 脚本执行结果。
        """
        skill_root = info.root.resolve()
        script_path = (skill_root / relative_script).resolve()
        if not script_path.is_file():
            return self._script_error(
                "validation", f"Script not found: {relative_script}"
            )
        if skill_root not in script_path.parents:
            return self._script_error(
                "validation", "Script path escapes skill directory"
            )

        # Function-hook fast path: if this is a lifecycle hook and the script
        # module defines a no-arg callable named after the hook type (e.g.
        # ``pre_step``), call it directly (sync or async) instead of running the
        # script — no exec/argparse, no event-loop blocking.
        hook_type = attributes.get("hook.type")
        trusted = info.namespace == "built-in"
        if (
            trusted
            and hook_type
            and self._source_defines_callable(script_path, hook_type)
        ):
            # 静态确认有 hook 函数才 import:顶层代码导入即执行,
            # 无谓的 import 会白白跑一遍脚本副作用(还搭上事件循环)。
            try:
                module = self._load_script_module(script_path)
            except Exception:
                module = None
            fn = getattr(module, hook_type, None) if module is not None else None
            if callable(fn) and getattr(fn, "__module__", None) == module.__name__:
                return await self._run_hook_function(
                    fn,
                    info,
                    skill_root,
                    script_path,
                    relative_script,
                    argv,
                    hook_type,
                    op_name,
                    attributes,
                    timeout_sec=timeout_sec,
                )

        env = {k: v for k, v in os.environ.items() if k in ALLOWED_ENV_VARS}
        env.update(
            {
                "SKILL_ID": info.skill_id,
                "SKILL_NAME": info.name,
                "SKILL_DIR": str(skill_root),
                "AGENT_WORK_DIR": str(self.workspace_root()),
            }
        )
        cmd = [sys.executable, str(script_path), *argv]
        if self._trace_writer is None:
            raise RuntimeError("Agent workspace is not initialized")
        span = self._trace_writer.start_span(
            op_name,
            attributes={
                "operation.type": "script",
                "script.path": relative_script,
                "script.argv": argv,
                **attributes,
            },
        )
        # entrypoint 复用进程内上下文；普通脚本在独立子进程中执行。
        ctx = SkillScriptContext(
            workspace_root=self.workspace_root(),
            skill_dir=skill_root,
            skill_id=info.skill_id,
            skill_name=info.name,
            env=env,
        )
        callable_name = (
            hook_type
            if hook_type and self._source_defines_callable(script_path, hook_type)
            else "entrypoint"
        )
        isolated_callable = not trusted and self._source_defines_callable(
            script_path, callable_name
        )
        try:
            if isolated_callable:
                # 自定义函数原先可读取宿主环境；保留其 SDK、代理等配置，
                # 再叠加本次技能上下文。普通脚本仍使用原有环境白名单。
                env = {**os.environ, **env}
                request = json.dumps(
                    {
                        "path": str(script_path),
                        "name": callable_name,
                        "argv": argv,
                        "skill_id": info.skill_id,
                        "skill_name": info.name,
                    },
                    ensure_ascii=False,
                )
                result = await self.fs.run_command(
                    [
                        sys.executable,
                        str(Path(__file__).with_name("skill_worker.py")),
                    ],
                    timeout_sec=timeout_sec,
                    env=env,
                    input_text=request,
                )
                if result.ok:
                    try:
                        response = CommandResult(**json.loads(result.stdout))
                        result = replace(
                            response, stderr=result.stderr + response.stderr
                        )
                    except (TypeError, ValueError):
                        result = CommandResult(
                            False, 1, "", "Invalid skill worker response", "runtime"
                        )
            elif trusted:
                result = await self._run_in_process(script_path, argv, ctx, timeout_sec)
            else:
                result = None
            ran_in_process = result is not None and not isolated_callable
            if result is None:
                result = await self.fs.run_command(
                    cmd,
                    timeout_sec=timeout_sec,
                    cwd=".",
                    env=env,
                )
        except asyncio.CancelledError:
            self._trace_writer.end_span(
                span,
                status="error",
                message="Skill invocation cancelled",
                attributes={"script.cancelled": True},
            )
            raise
        self._trace_writer.end_span(
            span,
            status="ok" if result.ok else "error",
            message=result.stderr if not result.ok else "",
            attributes={
                "script.exit_code": result.exit_code,
                # 自定义函数与普通脚本均已等待子进程终止。
                # 进程内路径仍保守标记超时后的潜在副作用。
                "script.timeout_leaked": ran_in_process
                and result.error_type == "timeout",
            },
        )
        return ScriptRunResult(
            ok=result.ok,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            error_type=result.error_type,
        )

    async def _run_hook_function(
        self,
        fn: Any,
        info: SkillDescriptor,
        skill_root: Path,
        script_path: Path,
        relative_script: str,
        argv: list[str],
        hook_type: str,
        op_name: str,
        attributes: dict[str, Any],
        timeout_sec: int = 30,
    ) -> ScriptRunResult:
        """直接调用无参的生命周期 hook 函数(同步或异步)。

        完全避免运行脚本 / argparse / exec,使热路径 hook(如
        daily-guidance 的 pre_step)不阻塞事件循环。

        :param fn: hook 可调用对象(无参;可为 async)。
        :param info: skill 描述符。
        :param skill_root: skill 包根目录。
        :param script_path: 脚本绝对路径(用于 span)。
        :param relative_script: 相对 skill 根目录的脚本路径。
        :param argv: 原始 argv(hook 为 ``["--args-json", payload_json]``)。
        :param hook_type: 生命周期 hook 名。
        :param op_name: trace 操作名。
        :param attributes: 额外的 trace 属性。
        :returns: stdout 为函数返回值的脚本执行结果。
        """
        if self._trace_writer is None:
            raise RuntimeError("Agent workspace is not initialized")
        payload: dict[str, Any] = {}
        if len(argv) >= 2 and argv[0] == "--args-json":
            try:
                loaded = json.loads(argv[1])
                if isinstance(loaded, dict):
                    payload = loaded
            except Exception:
                payload = {}
        span = self._trace_writer.start_span(
            op_name,
            attributes={
                "operation.type": "hook",
                "script.path": relative_script,
                "hook.type": hook_type,
                "hook.kind": "function",
                **attributes,
            },
        )
        ctx = HookContext(
            workspace_root=self.workspace_root(),
            skill_dir=skill_root,
            skill_id=info.skill_id,
            hook_type=hook_type,
            payload=payload,
        )
        token = _set_hook_context(ctx)
        ok = True
        stdout = ""
        stderr = ""
        error_type = "none"
        timeout = max(int(timeout_sec), 1)
        try:
            if inspect.iscoroutinefunction(fn):
                # async hook: wait_for 零热路径成本(async 本来就让出)。
                ret = await asyncio.wait_for(fn(), timeout)
            else:
                # 内置同步 hook 保持进程内热路径。
                ret = fn()
                if inspect.isawaitable(ret):
                    ret = await asyncio.wait_for(ret, timeout)
            if isinstance(ret, str):
                stdout = ret
            elif ret is not None:
                stdout = json.dumps(ret, ensure_ascii=False, default=str)
        except TimeoutError:
            ok = False
            error_type = "timeout"
            stderr = f"hook {hook_type} timed out after {timeout}s"
        except SystemExit as exc:  # pragma: no cover - defensive
            ok = exc.code in (None, 0)
            error_type = "systemexit"
            if not ok:
                stderr = f"hook {hook_type} exited with {exc.code}"
        except Exception:
            ok = False
            error_type = "runtime"
            stderr = traceback.format_exc()
        finally:
            _reset_hook_context(token)
        self._trace_writer.end_span(
            span,
            status="ok" if ok else "error",
            message=stderr if not ok else "",
            attributes={"hook.exit_ok": ok},
        )
        return ScriptRunResult(
            ok=ok,
            exit_code=0 if ok else 1,
            stdout=stdout,
            stderr=stderr,
            error_type=error_type,
        )

    async def _run_in_process(
        self,
        script_path: Path,
        argv: list[str],
        ctx: SkillScriptContext,
        timeout_sec: int,
    ) -> CommandResult | None:
        """在进程内执行 skill 脚本。

        成功/失败时返回 ``CommandResult``;返回 ``None`` 表示回退到真实
        subprocess(如模块无法导入时)。

        :param script_path: 脚本绝对路径。
        :param argv: 脚本路径之后的命令行参数。
        :param ctx: 单次调用的 skill 上下文(workspace、env 快照)。
        :param timeout_sec: 尽力而为的执行超时。
        :returns: 命令结果;返回 None 时转交 subprocess 路径。
        """
        if self._source_defines_callable(script_path, "entrypoint"):
            try:
                module = self._load_script_module(script_path)
            except Exception:
                return None
            entrypoint = getattr(module, "entrypoint", None)
            if callable(entrypoint):
                return await self._call_entrypoint(
                    entrypoint, argv, ctx, timeout_sec=timeout_sec
                )
        # 无 entrypoint 的脚本交给子进程，超时后可终止且不改变父进程状态。
        return None

    def _source_defines_callable(self, script_path: Path, name: str) -> bool:
        """静态判断脚本顶层是否定义了给定名字的可调用,不执行代码。

        决定"是否值得 import 该模块"的前置检查:entrypoint-less 脚本的
        顶层代码即副作用本体,``exec_module`` 会在导入时把它跑一遍
        (且在事件循环线程上、不受任何超时保护),随后动态执行又跑第
        二遍——顶层副作用双执行 + 挂死即冻结事件循环。有此静态检查后,
        无 entrypoint 的脚本完全不 import，只在子进程中执行一次。

        :param script_path: 脚本绝对路径。
        :param name: 顶层定义名(如 ``"entrypoint"`` 或 hook 名)。
        :returns: 顶层是否定义了该名字(函数/异步函数/赋值)。语法错误
            返回 False,交由后续执行路径报出真实错误。
        """
        try:
            tree = ast.parse(script_path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, ValueError):
            return False
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.name == name:
                    return True
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == name:
                        return True
        return False

    def _load_script_module(self, script_path: Path) -> types.ModuleType:
        """将 skill 脚本作为模块导入(并缓存)。

        :param script_path: 脚本绝对路径。
        :returns: 导入的模块;文件 mtime 变化时重新加载。
        """
        mtime = script_path.stat().st_mtime
        key = (str(script_path), mtime)
        cached = self._script_module_cache.get(key)
        if cached is not None:
            return cached
        module_name = f"_skill_script_{abs(hash(str(script_path)))}"
        spec = importlib.util.spec_from_file_location(module_name, script_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot create import spec for {script_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self._script_module_cache = {
            k: v
            for k, v in self._script_module_cache.items()
            if k[0] != str(script_path)
        }
        self._script_module_cache[key] = module
        return module

    async def _call_entrypoint(
        self,
        entrypoint: Any,
        argv: list[str],
        ctx: SkillScriptContext,
        *,
        timeout_sec: int = 30,
    ) -> CommandResult:
        """直接调用技能的进程内 ``entrypoint``。

        仅用于内置技能。自定义技能的导入与执行由子进程负责。
        异步入口使用协作式超时，同步入口保持内联热路径。

        :param entrypoint: 可调用 ``entrypoint(argv[, ctx]) -> str``。
        :param argv: 脚本路径之后的命令行参数。
        :param ctx: 每次调用的技能上下文(workspace、env 快照)。
        :param timeout_sec: 非内联路径的执行超时秒数。
        :returns: 由 entrypoint 返回值构造的命令结果。
        """
        timeout = max(int(timeout_sec), 1)
        try:
            params = [
                p
                for p in inspect.signature(entrypoint).parameters.values()
                if p.kind
                in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                )
            ]

            def _call() -> Any:
                if len(params) >= 2:
                    return entrypoint(list(argv), ctx)
                return entrypoint(list(argv))

            if inspect.iscoroutinefunction(entrypoint):
                ret = await asyncio.wait_for(_call(), timeout)
            else:
                ret = _call()
                if inspect.isawaitable(ret):
                    ret = await asyncio.wait_for(ret, timeout)
            stdout = ""
            if isinstance(ret, str):
                stdout = ret
            elif isinstance(ret, tuple) and ret and isinstance(ret[0], str):
                stdout = ret[0]
            return CommandResult(
                ok=True, exit_code=0, stdout=stdout, stderr="", error_type="none"
            )
        except TimeoutError:
            return CommandResult(
                ok=False,
                exit_code=-1,
                stdout="",
                stderr=f"command timed out after {timeout}s",
                error_type="timeout",
            )
        except SystemExit as exc:  # pragma: no cover - defensive
            code = (
                exc.code
                if isinstance(exc.code, int)
                else (0 if exc.code is None else 1)
            )
            return CommandResult(
                ok=code == 0,
                exit_code=code,
                stdout="",
                stderr="",
                error_type="systemexit",
            )
        except Exception:
            return CommandResult(
                ok=False,
                exit_code=1,
                stdout="",
                stderr=traceback.format_exc(),
                error_type="runtime",
            )

    def _script_error(self, error_type: str, message: str) -> ScriptRunResult:
        """构造并 trace 一个脚本校验错误。

        :param error_type: 错误类别。
        :param message: 人类可读的错误消息。
        :returns: 失败的脚本执行结果。
        """
        return ScriptRunResult(
            ok=False,
            exit_code=-1,
            stdout="",
            stderr=message,
            error_type=error_type,
        )
