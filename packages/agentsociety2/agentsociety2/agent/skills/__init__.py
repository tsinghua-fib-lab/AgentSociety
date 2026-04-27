"""Skill discovery, metadata, and execution.

Skills are discovered from `SKILL.md` YAML frontmatter and exposed via
progressive-disclosure: the model sees lightweight metadata and loads
full skill content only after activation.

Module Structure
================

- :class:`SkillInfo`: Skill metadata container
- :class:`SkillRegistry`: Skill registry for discovery, management, and execution

Skill Metadata Fields
=====================

SKILL.md YAML frontmatter supports:

- name: Unique skill identifier
- description: Short description for catalog display
- inputs: Input file list (for dependency discovery)
- outputs: Output file list
- script: Optional Python script path
- requires: Dependencies on other skills
- priority: Priority for ordering

Example
=======

SKILL.md::

    ---
    name: cognition
    description: Generate emotion, needs, and intention
    inputs:
      - state/observation.txt
    outputs:
      - state/emotion.json
      - state/needs.json
      - state/intention.json
    priority: 80
    ---

Usage::

    from agentsociety2.agent.skills import SkillRegistry, get_skill_registry

    registry = get_skill_registry()

    # List available skills
    for info in registry.list_enabled():
        print(f"{info.name}: {info.description}")

    # Activate skill
    content = registry.activate("cognition")

    # Execute skill script
    result = await registry.execute(
        skill_name="memory",
        args={"observation": "..."},
        agent_work_dir=workspace,
    )

Built-in Skills
===============

| Skill | Function |
|-------|----------|
| observation | Fetch environment perception |
| cognition | Generate emotion, needs, intention |
| memory | Long-term memory and relationships |
| plan | Execute intentions via environment |
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

from agentsociety2.agent.config import ALLOWED_ENV_VARS
from agentsociety2.logger import get_logger

logger = get_logger()
_BUILTIN_ROOT = Path(__file__).resolve().parent


@dataclass
class SkillInfo:
    """Metadata container for a skill.

    Skills are discovered from SKILL.md YAML frontmatter. This dataclass
    holds all metadata fields needed for skill discovery, activation, and execution.
    """

    name: str
    description: str = ""
    argument_hint: str = ""
    user_invocable: bool = True
    allowed_tools: list[str] = field(default_factory=list)
    script: str = ""
    executor: str = ""  # codegen
    source: str = ""  # builtin | custom | env:<name>
    path: str = ""
    enabled: bool = True
    disable_model_invocation: bool = False
    paths: list[str] = field(default_factory=list)
    requires: list[str] = field(default_factory=list)
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    priority: int = 0
    skill_md: str = ""
    skill_md_loaded: bool = field(default=False, repr=False)

    def copy(self) -> "SkillInfo":
        """创建浅拷贝，列表字段重新创建以避免共享。

        :return: 新的 SkillInfo 实例。
        """
        return SkillInfo(
            name=self.name,
            description=self.description,
            argument_hint=self.argument_hint,
            user_invocable=self.user_invocable,
            allowed_tools=list(self.allowed_tools),
            script=self.script,
            executor=self.executor,
            source=self.source,
            path=self.path,
            enabled=self.enabled,
            disable_model_invocation=self.disable_model_invocation,
            paths=list(self.paths),
            requires=list(self.requires),
            inputs=list(self.inputs),
            outputs=list(self.outputs),
            priority=self.priority,
            skill_md=self.skill_md,
            skill_md_loaded=self.skill_md_loaded,
        )


# 全局子进程并发限制：所有 agent 的 registry 共享同一个 semaphore，
# 避免 N 个 agent 各自拥有 16 个配额导致 N×16 个子进程。
# 使用懒初始化确保在 asyncio 事件循环启动后才创建。
_global_subprocess_semaphore: asyncio.Semaphore | None = None


def _get_global_subprocess_semaphore() -> asyncio.Semaphore:
    global _global_subprocess_semaphore
    if _global_subprocess_semaphore is None:
        max_workers_str = os.getenv("AGENT_SKILL_SUBPROCESS_MAX_WORKERS", "16")
        try:
            max_workers = max(1, int(max_workers_str))
        except ValueError:
            max_workers = 16
        _global_subprocess_semaphore = asyncio.Semaphore(max_workers)
    return _global_subprocess_semaphore


class SkillRegistry:
    """Registry for skill discovery, management, and execution.

    The SkillRegistry provides:
    - Discovery: Scan skills from builtin, custom, and environment directories
    - Listing: List skills with metadata for model selection
    - Activation: Load and activate skill content on demand
    - Execution: Run skill scripts with argument passing

    Example usage::

        registry = SkillRegistry()
        registry.scan_builtin()

        # List available skills
        for info in registry.list_enabled():
            print(f"{info.name}: {info.description}")

        # Activate and get skill content
        content = registry.activate("needs")
    """

    def __init__(self) -> None:
        """Initialize a skill registry with built-in skills loaded."""
        self._skills: dict[str, SkillInfo] = {}
        self._builtin_scanned = False
        self.scan_builtin()

    def copy_from(self, other: "SkillRegistry") -> None:
        """从另一个 registry 复制所有技能。

        使用浅拷贝共享 SkillInfo 实例，减少内存占用。
        每个 SkillInfo 的列表字段会重新创建以避免意外共享。

        :param other: 源 registry。
        """
        self._skills = {name: info.copy() for name, info in other._skills.items()}
        self._builtin_scanned = other._builtin_scanned

    # ---------- discover ----------
    def scan_builtin(self, root: Path = _BUILTIN_ROOT) -> None:
        """Scan built-in skills from the agent/skills directory.

        Built-in skills are always available and cannot be overridden by
        custom or environment skills with the same name.
        """
        if self._builtin_scanned:
            return
        for info in _discover_skills(root, source="builtin"):
            self._skills[info.name] = info
        self._builtin_scanned = True

    def scan_custom(self, workspace_path: str | Path) -> list[str]:
        """Scan custom skills from a workspace directory.

        Looks for skills in `<workspace_path>/custom/skills/`.
        Custom skills can override environment skills but not built-in skills.

        :param workspace_path: Root path containing ``custom/skills/`` directory.
        :returns: List of skill names that were added.
        """
        custom_root = Path(workspace_path) / "custom" / "skills"
        if not custom_root.is_dir():
            return []
        new_names: list[str] = []
        for info in _discover_skills(custom_root, source="custom"):
            # Built-in skills cannot be overridden.
            if (
                info.name in self._skills
                and self._skills[info.name].source == "builtin"
            ):
                continue
            # Preserve enabled state if skill already exists
            if info.name in self._skills:
                existing = self._skills[info.name]
                info.enabled = existing.enabled
            self._skills[info.name] = info
            new_names.append(info.name)
        return new_names

    def scan_env_skills(self, skills_dir: Path, env_name: str) -> list[str]:
        """Scan skills from an environment module's skill directory.

        Environment modules can bundle specialized skills via `get_agent_skills_dirs()`.
        These skills are automatically discovered when PersonAgent initializes.

        Environment skills can override other environment skills and custom skills,
        but not built-in skills.

        :param skills_dir: Directory containing skill subdirectories with ``SKILL.md`` files.
        :param env_name: Name of the environment module (for source tracking).
        :returns: List of skill names that were added.

        .. seealso::
           :meth:`agentsociety2.env.base.EnvBase.get_agent_skills_dirs`
        """
        if not skills_dir.is_dir():
            return []
        source = f"env:{env_name}"
        new_names: list[str] = []
        for info in _discover_skills(skills_dir, source=source):
            # Built-in skills cannot be overridden
            if (
                info.name in self._skills
                and self._skills[info.name].source == "builtin"
            ):
                continue
            # Preserve enabled state if skill already exists
            if info.name in self._skills:
                existing = self._skills[info.name]
                info.enabled = existing.enabled
            self._skills[info.name] = info
            new_names.append(info.name)
        return new_names

    # ---------- list ----------
    def list_all(self) -> list[SkillInfo]:
        return sorted(self._skills.values(), key=lambda s: s.name)

    def list_enabled(self) -> list[SkillInfo]:
        return [s for s in self.list_all() if s.enabled]

    def list_selection_metadata(
        self, names: list[str] | None = None, only_enabled: bool = True
    ) -> list[dict[str, Any]]:
        """Return minimal catalog entries for model selection.

        This is the progressive-disclosure layer: only lightweight metadata is returned.
        Full SKILL.md content is loaded only after activation.
        """
        base = self.list_enabled() if only_enabled else self.list_all()
        name_set = set(names) if names is not None else None
        result: list[dict[str, Any]] = []
        for info in base:
            if info.disable_model_invocation:
                continue
            if name_set is not None and info.name not in name_set:
                continue
            entry: dict[str, Any] = {
                "name": info.name,
                "description": info.description,
            }
            if info.argument_hint:
                entry["argument_hint"] = info.argument_hint
            entry["user_invocable"] = bool(info.user_invocable)
            if info.paths:
                entry["paths"] = list(info.paths)
            if info.requires:
                entry["requires"] = list(info.requires)
            if info.inputs:
                entry["inputs"] = list(info.inputs)
            if info.outputs:
                entry["outputs"] = list(info.outputs)
            if info.priority:
                entry["priority"] = info.priority
            result.append(entry)
        return result

    # ---------- dependency validation ----------
    def validate_dependencies(self) -> dict[str, Any]:
        """Validate skill dependencies and detect cycles.

        :returns: Dict with ``valid`` boolean, ``missing`` list, and ``cycles`` list.
        """
        missing: list[tuple[str, str]] = []
        cycles: list[list[str]] = []

        for name, info in self._skills.items():
            for req in info.requires:
                if req not in self._skills:
                    missing.append((name, req))

        visited: set[str] = set()
        rec_stack: set[str] = set()

        def detect_cycle(skill_name: str, path: list[str]) -> bool:
            if skill_name in rec_stack:
                cycle_start = path.index(skill_name)
                cycles.append(path[cycle_start:] + [skill_name])
                return True
            if skill_name in visited:
                return False
            visited.add(skill_name)
            rec_stack.add(skill_name)
            info = self._skills.get(skill_name)
            if info:
                for req in info.requires:
                    if detect_cycle(req, path + [skill_name]):
                        break
            rec_stack.remove(skill_name)
            return False

        for name in self._skills:
            detect_cycle(name, [])

        return {
            "valid": len(missing) == 0 and len(cycles) == 0,
            "missing": missing,
            "cycles": cycles,
        }

    def get_dependency_order(self, skill_names: list[str]) -> list[str]:
        """Return skills in dependency-resolved order.

        :param skill_names: Skills to order.
        :returns: List with dependencies before dependents.
        """
        result: list[str] = []
        visited: set[str] = set()

        def visit(name: str) -> None:
            if name in visited or name not in self._skills:
                return
            visited.add(name)
            info = self._skills[name]
            for req in info.requires:
                if req in self._skills:
                    visit(req)
            result.append(name)

        for name in skill_names:
            visit(name)

        return result

    def list_with_state(
        self, workspace_files: set[str], names: list[str] | None = None
    ) -> list[dict[str, Any]]:
        """Return catalog entries with output file state information.

        :param workspace_files: Set of file paths currently in workspace.
        :param names: Optional filter by skill names.
        :return: List of catalog entries with outputs_exist status.
        """
        base = self.list_selection_metadata(names=names, only_enabled=True)
        result: list[dict[str, Any]] = []
        for entry in base:
            entry_copy = entry.copy()
            outputs = entry.get("outputs", [])
            if outputs:
                entry_copy["outputs_exist"] = all(f in workspace_files for f in outputs)
                entry_copy["outputs_missing"] = [
                    f for f in outputs if f not in workspace_files
                ]
            result.append(entry_copy)
        return result

    # ---------- read ----------
    def activate(self, name: str) -> str:
        info = self._skills.get(name)
        if not info:
            return ""
        return _ensure_skill_md_loaded(info)

    def read(self, name: str, relative_path: str) -> str:
        info = self._skills.get(name)
        if not info:
            return ""
        skill_root = Path(info.path).resolve()
        target = (skill_root / relative_path).resolve()
        if not target.exists() or not target.is_file():
            return ""
        if skill_root != target and skill_root not in target.parents:
            return ""
        return target.read_text(encoding="utf-8")

    # ---------- state ----------
    def enable(self, name: str) -> bool:
        info = self._skills.get(name)
        if not info:
            return False
        info.enabled = True
        return True

    def disable(self, name: str) -> bool:
        info = self._skills.get(name)
        if not info:
            return False
        info.enabled = False
        return True

    def remove_custom(self, name: str) -> bool:
        """Remove a custom skill from registry only.

        NOTE: This does not delete files on disk. Callers (e.g. API layer) should
        handle filesystem removal, then call this method to drop it from memory.
        """
        info = self._skills.get(name)
        if not info:
            return False
        if info.source != "custom":
            return False
        del self._skills[name]
        return True

    def reload_skill(self, name: str) -> bool:
        """Hot-reload a skill's metadata and clear cached SKILL.md content.

        This is designed for the current skills-first architecture:
        - skills are discovered from SKILL.md frontmatter (+ optional script path)
        - activation lazily loads full SKILL.md into memory
        """
        info = self._skills.get(name)
        if not info:
            return False

        skill_root = Path(info.path)
        skill_md = skill_root / "SKILL.md"
        if not skill_md.exists():
            return False

        meta = _parse_frontmatter_from_file(skill_md)
        new_name = str(meta.get("name", info.name)).strip() or info.name
        if new_name != name:
            if new_name in self._skills:
                return False
            del self._skills[name]
            self._skills[new_name] = info

        info.name = new_name
        info.description = str(meta.get("description", info.description))
        info.argument_hint = str(
            meta.get("argument_hint", meta.get("argument-hint", info.argument_hint))
        ).strip()
        info.user_invocable = _to_bool(
            meta.get("user_invocable", meta.get("user-invocable", info.user_invocable))
        )
        info.allowed_tools = _to_list(
            meta.get("allowed_tools", meta.get("allowed-tools", info.allowed_tools))
        )
        info.script = str(meta.get("script", info.script)).strip()
        info.executor = str(meta.get("executor", info.executor)).strip().lower()
        info.disable_model_invocation = _to_bool(
            meta.get("disable_model_invocation", meta.get("disable-model-invocation"))
        )
        info.requires = _to_list(meta.get("requires"))
        info.inputs = _to_list(meta.get("inputs"))
        info.outputs = _to_list(meta.get("outputs"))
        info.priority = int(meta.get("priority", 0))
        info.skill_md_loaded = False
        info.skill_md = ""
        return True

    def get_skill_info(self, name: str, load_content: bool = True) -> SkillInfo | None:
        info = self._skills.get(name)
        if info and load_content:
            _ensure_skill_md_loaded(info)
        return info

    # ---------- execute ----------
    async def execute(
        self,
        skill_name: str,
        args: dict[str, Any],
        agent_work_dir: str | Path,
        timeout_sec: int = 30,
        codegen_executor: (
            Callable[[dict[str, Any]], Awaitable[dict[str, Any]]] | None
        ) = None,
    ) -> dict[str, Any]:
        """执行指定技能。

        根据技能配置选择执行方式：
        - executor="codegen": 通过环境执行
        - 有 script 字段: 执行 Python 脚本
        - 无 script: 返回空成功结果

        :param skill_name: 技能名称。
        :param args: 传递给技能的参数。
        :param agent_work_dir: Agent 工作目录。
        :param timeout_sec: 执行超时秒数。
        :param codegen_executor: codegen 执行器回调。
        :return: 执行结果字典，包含 ok、exit_code、stdout、stderr、artifacts 等字段。
        :rtype: dict[str, Any]
        """
        info = self._skills.get(skill_name)
        if not info:
            return _error("validation", f"Skill not found: {skill_name}")

        if info.executor == "codegen":
            if codegen_executor is None:
                return _error("validation", "Codegen executor is not available")
            return await codegen_executor(args)

        if not info.script:
            return {
                "ok": True,
                "exit_code": 0,
                "stdout": "",
                "stderr": "",
                "error_type": "none",
                "artifacts": [],
            }

        skill_root = Path(info.path).resolve()
        script_path = (skill_root / info.script).resolve()
        if not script_path.exists() or not script_path.is_file():
            return _error("validation", f"Script not found: {info.script}")
        if skill_root not in script_path.parents:
            return _error("validation", "Script path escapes skill directory")

        work_dir = Path(agent_work_dir).resolve()
        work_dir.mkdir(parents=True, exist_ok=True)
        before_files = {
            str(p.relative_to(work_dir)) for p in work_dir.rglob("*") if p.is_file()
        }

        # 使用环境变量白名单，避免泄露敏感信息
        env = {k: v for k, v in os.environ.items() if k in ALLOWED_ENV_VARS}
        env["SKILL_NAME"] = skill_name
        env["SKILL_DIR"] = str(skill_root)
        env["AGENT_WORK_DIR"] = str(work_dir)

        async with _get_global_subprocess_semaphore():
            proc = await asyncio.create_subprocess_exec(
                sys.executable,
                str(script_path),
                "--args-json",
                json.dumps(args, ensure_ascii=False),
                cwd=str(work_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                stdout_b, stderr_b = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout_sec
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return _error(
                    "timeout", f"Skill execution timed out after {timeout_sec}s"
                )

        stdout = (stdout_b or b"").decode("utf-8", errors="replace")
        stderr = (stderr_b or b"").decode("utf-8", errors="replace")
        exit_code = int(proc.returncode or 0)
        after_files = {
            str(p.relative_to(work_dir)) for p in work_dir.rglob("*") if p.is_file()
        }
        artifacts = sorted(after_files - before_files)
        return {
            "ok": exit_code == 0,
            "exit_code": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "error_type": "none" if exit_code == 0 else "runtime",
            "artifacts": artifacts,
        }


def _error(error_type: str, message: str) -> dict[str, Any]:
    return {
        "ok": False,
        "exit_code": -1,
        "stdout": "",
        "stderr": message,
        "error_type": error_type,
        "artifacts": [],
    }


def _discover_skills(root: Path, source: str) -> list[SkillInfo]:
    """发现指定目录下的所有技能。

    扫描目录中的子目录，查找 SKILL.md 文件并解析 frontmatter。

    :param root: 要扫描的根目录。
    :param source: 技能来源标识（"builtin"、"custom" 或 "env:<name>"）。
    :return: 发现的 SkillInfo 列表。
    :rtype: list[SkillInfo]
    """
    result: list[SkillInfo] = []
    if not root.is_dir():
        return result
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith(("_", ".")):
            continue
        # 新架构要求必须有 SKILL.md
        skill_md = child / "SKILL.md"
        if not skill_md.exists():
            continue
        meta = _parse_frontmatter_from_file(skill_md)
        info = SkillInfo(
            name=str(meta.get("name", child.name)),
            description=str(meta.get("description", "")),
            argument_hint=str(
                meta.get("argument_hint", meta.get("argument-hint", ""))
            ).strip(),
            user_invocable=_to_bool(
                meta.get("user_invocable", meta.get("user-invocable", True))
            ),
            allowed_tools=_to_list(
                meta.get("allowed_tools", meta.get("allowed-tools"))
            ),
            script=str(meta.get("script", "")).strip(),
            executor=str(meta.get("executor", "")).strip().lower(),
            source=source,
            path=str(child.resolve()),
            enabled=_to_bool(meta.get("enabled", True)),
            disable_model_invocation=_to_bool(
                meta.get(
                    "disable_model_invocation", meta.get("disable-model-invocation")
                )
            ),
            paths=_to_list(meta.get("paths")),
            requires=_to_list(meta.get("requires")),
            inputs=_to_list(meta.get("inputs")),
            outputs=_to_list(meta.get("outputs")),
            priority=int(meta.get("priority", 0)),
            skill_md_loaded=False,
        )
        result.append(info)
    return result


def _to_bool(raw: Any) -> bool:
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return str(raw).strip().lower() in ("true", "1", "yes")


def _to_list(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    if isinstance(raw, str):
        s = raw.strip()
        if not s:
            return []
        # Handle empty array notation from simplified YAML parsing
        if s == "[]":
            return []
        # Support comma-separated frontmatter values (e.g., allowed-tools).
        if "," in s:
            return [part.strip() for part in s.split(",") if part.strip()]
        return [s]
    return []


def _ensure_skill_md_loaded(info: SkillInfo) -> str:
    if info.skill_md_loaded:
        return info.skill_md
    path = Path(info.path) / "SKILL.md"
    if path.exists():
        info.skill_md = path.read_text(encoding="utf-8")
    info.skill_md_loaded = True
    return info.skill_md


def _parse_frontmatter_from_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}
    data: dict[str, Any] = {}
    key: str | None = None
    list_acc: list[str] | None = None
    for line in lines[1:]:
        s = line.rstrip("\n")
        stripped = s.strip()
        if stripped == "---":
            break
        if not stripped:
            continue
        if stripped.startswith("- ") and key is not None and list_acc is not None:
            list_acc.append(stripped[2:].strip())
            continue
        if key is not None and list_acc is not None:
            data[key] = list_acc
            key, list_acc = None, None
        if ":" not in stripped:
            continue
        k, _, v = stripped.partition(":")
        k = k.strip()
        v = v.strip()
        if not v:
            key = k
            list_acc = []
        else:
            data[k] = v
    if key is not None and list_acc is not None:
        data[key] = list_acc
    return data


_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
        _registry.scan_builtin()
    return _registry
