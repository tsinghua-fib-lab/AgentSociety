"""Agent skill runtime.

中文：管理 skill 可见性、激活状态、脚本执行和运行时事件。
English: Manages skill visibility, activation state, script execution, and runtime events.
"""

from __future__ import annotations

import asyncio
import contextlib
import importlib.util
import inspect
import io
import json
import os
import sys
import traceback
import types
from collections.abc import Iterable
from dataclasses import dataclass
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
        """List all registered skills.

        Args:
            None.

        Returns:
            Registered skill descriptors.
        """
        return []

    def get(self, skill_id: str) -> SkillDescriptor | None:
        """Return one skill descriptor by id.

        Args:
            skill_id: Registry skill id.

        Returns:
            Matching descriptor, or None.
        """
        return None

    def find_by_name(self, name: str) -> list[SkillDescriptor]:
        """Find skill descriptors by display name.

        Args:
            name: Skill display name.

        Returns:
            Matching descriptors.
        """
        return []

    def read_skill_doc(self, skill_id: str) -> str:
        """Read one skill's SKILL.md.

        Args:
            skill_id: Registry skill id.

        Returns:
            Skill document text, or an empty string.
        """
        return ""

    def read_skill_file(self, skill_id: str, relative_path: str) -> str:
        """Read one file inside a skill directory.

        Args:
            skill_id: Registry skill id.
            relative_path: Path relative to the skill root.

        Returns:
            File text, or an empty string.
        """
        return ""

    def list_hooks(self, hook_type: str) -> list[SkillDescriptor]:
        """List skills declaring one hook.

        Args:
            hook_type: Lifecycle hook name.

        Returns:
            Skill descriptors that declare the hook.
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
        """Return a serializable script result.

        Args:
            None.

        Returns:
            Dictionary representation of this result.
        """
        return {
            "ok": self.ok,
            "exit_code": self.exit_code,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "error_type": self.error_type,
        }


# Serializes the dynamic (entrypoint-less) in-process wrapper, which must touch
# process-global os.environ / cwd / sys.stdout. Entrypoint scripts bypass this
# lock entirely (they are fully parallel via contextvars).
_DYNAMIC_EXEC_LOCK = asyncio.Lock()


class AgentSkillRuntime:
    """Runtime for skill visibility, activation, and execution."""

    def __init__(
        self,
        agent_id: int,
        registry: SkillRegistryLike,
    ) -> None:
        """Initialize the skill runtime.

        Args:
            agent_id: Numeric agent id.
            registry: Skill registry facade used by this runtime.

        Returns:
            None.
        """
        self._agent_id = agent_id
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
        """Bind this runtime to an agent-owned workspace.

        Args:
            workspace_root: Agent workspace root created by the agent.
            fs: Agent-owned workspace filesystem facade.
            trace_writer: Agent-owned trace writer.

        Returns:
            None.
        """
        self._agent_work_dir = workspace_root.resolve()
        self._fs = fs
        self._trace_writer = trace_writer

    def workspace_root(self) -> Path:
        """Return the workspace root.

        Args:
            None.

        Returns:
            Absolute workspace root path.
        """
        if self._agent_work_dir is None:
            raise RuntimeError("Agent workspace is not initialized")
        return self._agent_work_dir

    @property
    def is_initialized(self) -> bool:
        """Return whether the workspace is initialized.

        Args:
            None.

        Returns:
            True when the workspace has been initialized.
        """
        return self._agent_work_dir is not None

    @property
    def fs(self) -> WorkspaceFS:
        """Return the workspace filesystem facade.

        Args:
            None.

        Returns:
            Workspace filesystem facade.
        """
        if self._fs is None:
            raise RuntimeError("Agent workspace is not initialized")
        return self._fs

    # ------------------------------------------------------------------
    # Skill facade
    # ------------------------------------------------------------------

    def set_visible_skills(self, tokens: Iterable[str]) -> None:
        """Set visible skills for this agent.

        Each entry may be a registry skill id (``namespace@name``) or a display
        name; both forms resolve against the whole registry.

        Args:
            tokens: Candidate skill ids or display names.

        Returns:
            None.
        """
        self._visible_skill_ids = {
            sid
            for sid in (
                self.resolve_skill_id(tok, visible_only=False) for tok in tokens
            )
            if sid
        }
        self._activated_skill_ids.intersection_update(self._visible_skill_ids)

    def add_visible_skill(self, token: str) -> bool:
        """Add one visible skill by id or display name.

        Args:
            token: Skill id (``namespace@name``) or display name.

        Returns:
            True when the skill exists and was made visible.
        """
        skill_id = self.resolve_skill_id(token, visible_only=False)
        if not skill_id:
            return False
        self._visible_skill_ids.add(skill_id)
        return True

    def remove_visible_skill(self, token: str) -> bool:
        """Remove one visible skill by id or display name.

        Args:
            token: Skill id (``namespace@name``) or display name.

        Returns:
            True when the skill was visible and removed.
        """
        skill_id = self.resolve_skill_id(token)
        if not skill_id or skill_id not in self._visible_skill_ids:
            return False
        self._visible_skill_ids.remove(skill_id)
        self._activated_skill_ids.discard(skill_id)
        return True

    def visible_skill_ids(self) -> set[str]:
        """Return visible skill ids.

        Args:
            None.

        Returns:
            Copy of the visible skill id set.
        """
        return set(self._visible_skill_ids)

    def visible_skill_count(self) -> int:
        """Return the visible skill count.

        Args:
            None.

        Returns:
            Number of visible skills.
        """
        return len(self._visible_skill_ids)

    def list_visible_skills(self) -> list[SkillDescriptor]:
        """List visible skill descriptors.

        Args:
            None.

        Returns:
            Visible skill descriptors.
        """
        result = [
            self._registry.get(skill_id) for skill_id in sorted(self._visible_skill_ids)
        ]
        return [item for item in result if item is not None]

    def skill_catalog(self) -> list[dict[str, str]]:
        """Build a compact visible skill catalog.

        Args:
            None.

        Returns:
            Catalog entries with name and description.
        """
        return [
            {
                "name": item.name,
                "description": item.description,
            }
            for item in self.list_visible_skills()
        ]

    def set_activated_skills(self, tokens: Iterable[str]) -> None:
        """Set activated skills from visible skills.

        Each entry may be a skill id (``namespace@name``) or a display name;
        both forms resolve against visible skills.

        Args:
            tokens: Candidate skill ids or display names to activate.

        Returns:
            None.
        """
        self._activated_skill_ids = {
            sid for sid in (self.resolve_skill_id(tok) for tok in tokens) if sid
        }

    def add_default_activated_skills(self, tokens: Iterable[str]) -> None:
        """Activate configured default skills when they are visible.

        Each entry may be a skill id or a display name.

        Args:
            tokens: Skill ids or display names requested by outer agent config.

        Returns:
            None.
        """
        for token in tokens:
            sid = self.resolve_skill_id(token)
            if sid:
                self._activated_skill_ids.add(sid)

    def activated_skill_ids(self) -> set[str]:
        """Return activated skill ids.

        Args:
            None.

        Returns:
            Copy of the activated skill id set.
        """
        return set(self._activated_skill_ids)

    def activated_skill_count(self) -> int:
        """Return activated skill count.

        Args:
            None.

        Returns:
            Number of activated skills.
        """
        return len(self._activated_skill_ids)

    def infer_single_script_skill_id(self) -> str:
        """Infer a visible activated skill when exactly one has a default script.

        Args:
            None.

        Returns:
            Skill id for the only active scripted skill, or an empty string.
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
        """Resolve a skill id or display name to a registry skill id.

        Accepts either a registry skill id (``namespace@name``) or a bare
        display ``name`` — every public skill API in this runtime takes the
        same ``token`` and tolerates both forms. When ``visible_only`` is True
        (the default) resolution is restricted to visible skills; when False
        the whole registry is searched (use this for skills that are not yet
        visible, e.g. in :meth:`add_visible_skill`).

        Ambiguous display names (more than one match) resolve only when exactly
        one candidate is currently activated.

        Args:
            token: Skill id (``namespace@name``) or display name from tool
                arguments / agent config.
            visible_only: Restrict resolution to visible skills.

        Returns:
            Matching skill id, or an empty string when not found or ambiguous.
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

    def resolve_skill_id_by_name(self, skill_name: str) -> str:
        """Deprecated alias for :meth:`resolve_skill_id`.

        Args:
            skill_name: Skill id or display name.

        Returns:
            Matching visible skill id, or an empty string.
        """
        return self.resolve_skill_id(skill_name)

    def activate_skill(self, token: str) -> tuple[bool, str, str]:
        """Activate a visible skill by id or display name.

        Args:
            token: Skill id (``namespace@name``) or display name.

        Returns:
            Tuple of ``(activated, skill_id, skill_doc)``.
        """
        skill_id = self.resolve_skill_id(token)
        doc = self.load_skill_doc(skill_id)
        if doc:
            self._activated_skill_ids.add(skill_id)
            self._activated_content_cache_key = None
        return bool(doc), skill_id, doc

    def activate_skill_by_name(self, skill_name: str) -> tuple[bool, str, str]:
        """Deprecated alias for :meth:`activate_skill`.

        Args:
            skill_name: Skill id or display name.

        Returns:
            Tuple of ``(activated, skill_id, skill_doc)``.
        """
        return self.activate_skill(skill_name)

    def deactivate_skill(self, token: str) -> tuple[bool, str]:
        """Deactivate a visible skill by id or display name.

        Args:
            token: Skill id (``namespace@name``) or display name.

        Returns:
            Tuple of ``(removed, skill_id)``.
        """
        skill_id = self.resolve_skill_id(token)
        removed = skill_id in self._activated_skill_ids
        self._activated_skill_ids.discard(skill_id)
        if removed:
            self._activated_content_cache_key = None
        return removed, skill_id

    def deactivate_skill_by_name(self, skill_name: str) -> tuple[bool, str]:
        """Deprecated alias for :meth:`deactivate_skill`.

        Args:
            skill_name: Skill id or display name.

        Returns:
            Tuple of ``(removed, skill_id)``.
        """
        return self.deactivate_skill(skill_name)

    def activated_skill_content_xml(self) -> str:
        """Render docs and resource hints for activated skills.

        Args:
            None.

        Returns:
            XML-like skill content blocks for active skills.
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
        """List visible activated skills that declare one hook.

        Args:
            hook_type: Lifecycle hook name.

        Returns:
            Skill descriptors eligible to run the hook.
        """
        return [
            info
            for info in self._registry.list_hooks(hook_type)
            if info.skill_id in self._visible_skill_ids
            and info.skill_id in self._activated_skill_ids
        ]

    def load_skill_doc(self, skill_id: str) -> str:
        """Read a visible skill document.

        Args:
            skill_id: Registry skill id.

        Returns:
            SKILL.md text, or an empty string.
        """
        if not self._is_visible(skill_id):
            return ""
        return self._registry.read_skill_doc(skill_id)

    def read_skill_file(self, skill_id: str, relative_path: str) -> str:
        """Read one file inside a visible skill.

        Args:
            skill_id: Registry skill id.
            relative_path: Path relative to the skill root.

        Returns:
            File text, or an empty string.
        """
        if not self._is_visible(skill_id):
            return ""
        return self._registry.read_skill_file(skill_id, relative_path)

    def resolve_skill_path(self, path: str | Path) -> tuple[str, str] | None:
        """Map a path to a ``(skill_id, relative_path)`` inside a visible skill.

        Used to recover when an agent tries to ``read`` a skill-bundled file
        (e.g. ``references/examples.md``) via the generic workspace ``read``
        tool, which only sees the agent workspace and rejects such paths as
        "escaping" it. Returning a mapping lets the caller transparently
        delegate to :meth:`read_skill_file` instead of failing.

        Two matching strategies, in order:

        1. Direct containment — the resolved absolute path is inside a
           visible skill root.
        2. Skill-name segment — some path component equals a visible skill's
           ``skill_id`` or ``name`` (e.g. the model-emitted
           ``.../skills/daily-guidance/references/examples.md``). The
           components after that segment are taken as the skill-relative path
           and must resolve to an existing file under the skill root.

        Args:
            path: Path to test (absolute, or relative to be matched by segment).

        Returns:
            ``(skill_id, posix_relative_path)`` if a visible skill file
            matches, else ``None``.
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
        """Run a script inside a visible skill.

        Args:
            skill_id: Registry skill id.
            script_path: Path relative to the skill root, or empty to use the default script.
            argv: Command-line arguments.
            timeout_sec: Execution timeout in seconds.

        Returns:
            Script run result.
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
        """Run a lifecycle hook for a visible skill.

        Args:
            skill_id: Registry skill id.
            hook_type: Lifecycle hook name.
            argv: Command-line arguments.
            timeout_sec: Execution timeout in seconds.

        Returns:
            Script run result.
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
        """Return whether a skill is visible.

        Args:
            skill_id: Registry skill id.

        Returns:
            True when the skill is visible.
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
        """Run a validated skill script path.

        Args:
            info: Skill descriptor.
            relative_script: Script path relative to the skill root.
            argv: Command-line arguments.
            timeout_sec: Execution timeout in seconds.
            op_name: Trace operation name.
            attributes: Extra trace attributes.

        Returns:
            Script run result.
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
        if hook_type:
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
        # Prefer in-process execution (entrypoint -> parallel via contextvars;
        # entrypoint-less -> serialized dynamic wrapper). Falls back to a real
        # subprocess if the module cannot be loaded in-process.
        ctx = SkillScriptContext(
            workspace_root=self.workspace_root(),
            skill_dir=skill_root,
            skill_id=info.skill_id,
            skill_name=info.name,
            env=env,
        )
        result = await self._run_in_process(script_path, argv, ctx, timeout_sec)
        if result is None:
            result = await self.fs.run_command(
                cmd,
                timeout_sec=timeout_sec,
                cwd=".",
                env=env,
            )
        self._trace_writer.end_span(
            span,
            status="ok" if result.ok else "error",
            message=result.stderr if not result.ok else "",
            attributes={
                "script.exit_code": result.exit_code,
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
    ) -> ScriptRunResult:
        """Call a no-arg lifecycle-hook function (sync or async) directly.

        Avoids running the script / argparse / exec entirely, so the hot-path
        hook (e.g. daily-guidance pre_step) does not block the event loop.

        Args:
            fn: The hook callable (no args; may be async).
            info: Skill descriptor.
            skill_root: Skill package root.
            script_path: Absolute script path (for the span).
            relative_script: Script path relative to skill root.
            argv: Original argv (``["--args-json", payload_json]`` for hooks).
            hook_type: Lifecycle hook name.
            op_name: Trace operation name.
            attributes: Extra trace attributes.

        Returns:
            Script run result whose stdout is the function's return value.
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
        try:
            ret = fn()
            if inspect.isawaitable(ret):
                ret = await ret
            if isinstance(ret, str):
                stdout = ret
            elif ret is not None:
                stdout = json.dumps(ret, ensure_ascii=False, default=str)
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
        """Execute a skill script in-process.

        Returns a ``CommandResult`` on success/failure, or ``None`` to fall
        back to a real subprocess (e.g. when the module cannot be imported).

        Args:
            script_path: Absolute script path.
            argv: Command-line arguments after the script path.
            ctx: Per-call skill context (workspace, env snapshot).
            timeout_sec: Best-effort execution timeout.

        Returns:
            Command result, or None to delegate to the subprocess path.
        """
        try:
            module = self._load_script_module(script_path)
        except Exception:
            return None
        entrypoint = getattr(module, "entrypoint", None)
        if callable(entrypoint):
            return await self._call_entrypoint(entrypoint, argv, ctx)
        return await self._exec_script_dynamic(script_path, argv, ctx, timeout_sec)

    def _load_script_module(self, script_path: Path) -> types.ModuleType:
        """Import (and cache) a skill script as a module.

        Args:
            script_path: Absolute script path.

        Returns:
            The imported module, reloaded when the file mtime changes.
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
    ) -> CommandResult:
        """Invoke a skill's in-process ``entrypoint`` directly.

        Skill entrypoints are short (ms) and I/O-bound, so they run inline
        rather than via ``asyncio.to_thread``. The default thread-pool executor
        plus GIL contention made 50 concurrent hooks serialized through
        ``to_thread`` far slower (seconds) than the entrypoint itself (ms).

        Args:
            entrypoint: Callable ``entrypoint(argv[, ctx]) -> str``.
            argv: Command-line arguments after the script path.
            ctx: Per-call skill context.

        Returns:
            Command result built from the entrypoint return value.
        """
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
            if len(params) >= 2:
                ret = entrypoint(list(argv), ctx)
            else:
                ret = entrypoint(list(argv))
            stdout = ""
            if isinstance(ret, str):
                stdout = ret
            elif isinstance(ret, tuple) and ret and isinstance(ret[0], str):
                stdout = ret[0]
            return CommandResult(
                ok=True, exit_code=0, stdout=stdout, stderr="", error_type="none"
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

    async def _exec_script_dynamic(
        self,
        script_path: Path,
        argv: list[str],
        ctx: SkillScriptContext,
        timeout_sec: int,
    ) -> CommandResult:
        """Run an entrypoint-less script in-process via a dynamic wrapper.

        Serialized by a global lock because the wrapper must touch
        process-global ``os.environ`` / ``cwd`` / ``sys.stdout`` (the script
        body runs with ``__name__ == "__main__"`` exactly as a subprocess would,
        reusing the warm interpreter so there is no fork/cold-start).

        Args:
            script_path: Absolute script path.
            argv: Command-line arguments after the script path.
            ctx: Per-call skill context.
            timeout_sec: Best-effort execution timeout.

        Returns:
            Command result.
        """
        async with _DYNAMIC_EXEC_LOCK:
            return await asyncio.to_thread(
                self._exec_source_sync, script_path, argv, ctx
            )

    def _exec_source_sync(
        self,
        script_path: Path,
        argv: list[str],
        ctx: SkillScriptContext,
    ) -> CommandResult:
        """Execute a script's source in a fresh namespace (worker thread).

        Args:
            script_path: Absolute script path.
            argv: Command-line arguments after the script path.
            ctx: Per-call skill context.

        Returns:
            Command result.
        """
        try:
            source = script_path.read_text(encoding="utf-8")
        except Exception as exc:
            return CommandResult(
                ok=False,
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                error_type="validation",
            )
        saved_env = {k: os.environ.get(k) for k in ctx.env}
        for k, v in ctx.env.items():
            os.environ[k] = v
        saved_argv = sys.argv
        sys.argv = [str(script_path), *argv]
        saved_cwd = Path.cwd()
        os.chdir(str(ctx.workspace_root))
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                namespace: dict[str, Any] = {
                    "__name__": "__main__",
                    "__file__": str(script_path),
                }
                exec(compile(source, str(script_path), "exec"), namespace)
            return CommandResult(
                ok=True,
                exit_code=0,
                stdout=buf.getvalue(),
                stderr="",
                error_type="none",
            )
        except SystemExit as exc:
            code = (
                exc.code
                if isinstance(exc.code, int)
                else (0 if exc.code is None else 1)
            )
            return CommandResult(
                ok=code == 0,
                exit_code=code,
                stdout=buf.getvalue(),
                stderr="",
                error_type="systemexit",
            )
        except Exception:
            return CommandResult(
                ok=False,
                exit_code=1,
                stdout=buf.getvalue(),
                stderr=traceback.format_exc(),
                error_type="runtime",
            )
        finally:
            sys.argv = saved_argv
            os.chdir(str(saved_cwd))
            for k, original in saved_env.items():
                if original is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = original

    def _script_error(self, error_type: str, message: str) -> ScriptRunResult:
        """Build and trace a script validation error.

        Args:
            error_type: Error category.
            message: Human-readable error message.

        Returns:
            Failed script run result.
        """
        return ScriptRunResult(
            ok=False,
            exit_code=-1,
            stdout="",
            stderr=message,
            error_type=error_type,
        )
