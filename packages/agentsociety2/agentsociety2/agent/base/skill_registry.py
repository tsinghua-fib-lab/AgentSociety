"""Skill 注册表。

中文：扫描、解析和查询 Agent skill 元数据。
English: Scans, parses, and queries Agent skill metadata.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path
from typing import Any

import yaml

# Built-in skills live under ``agentsociety2/agent/skills/`` (sibling of this
# ``agent/base/`` package). Compute it from this file's location so the
# registry keeps scanning the real skill content directory regardless of where
# this module itself is imported from / located.
_BUILTIN_ROOT = Path(__file__).resolve().parent.parent / "skills"
_RESOURCE_FILES_CACHE: dict[tuple[str, int, int, int], list[str]] = {}
_RESOURCE_FILES_CACHE_MAX = 1024


@dataclass(frozen=True)
class SkillDescriptor:
    """Skill 元数据。

    :param skill_id: 稳定的注册表 skill id。
    :param name: 来自 SKILL.md 的显示名。
    :param namespace: skill 命名空间。
    :param description: 目录描述。
    :param root: skill 根目录。
    :param source: 来源类别。
    :param source_label: 人类可读的来源标签。
    :param script: 可选的默认脚本路径。
    :param hooks: 生命周期钩子脚本映射。
    """

    skill_id: str
    name: str
    namespace: str
    description: str
    root: Path
    source: str
    source_label: str
    script: str | None
    hooks: dict[str, str]

    def resource_files(self) -> list[str]:
        """列出随本 skill 根目录交付的文件。

        :returns: skill 根下的相对资源文件路径。
        """
        try:
            stat = self.root.stat()
        except OSError:
            return []
        # Reinstalling can preserve the old mtime but always publishes a new tree.
        cache_key = (str(self.root), stat.st_dev, stat.st_ino, stat.st_mtime_ns)
        cached = _RESOURCE_FILES_CACHE.get(cache_key)
        if cached is not None:
            return list(cached)

        resources: list[str] = []
        for path in sorted(
            (item for item in self.root.rglob("*") if item.is_file()),
            key=lambda item: item.relative_to(self.root).as_posix().casefold(),
        ):
            relative = path.relative_to(self.root)
            if _is_hidden_or_cache_path(relative):
                continue
            resources.append(relative.as_posix())
        if len(_RESOURCE_FILES_CACHE) >= _RESOURCE_FILES_CACHE_MAX:
            _RESOURCE_FILES_CACHE.clear()
        _RESOURCE_FILES_CACHE[cache_key] = resources
        return list(resources)


# Parsed frontmatter is immutable to callers and shared across fresh registries.
# Equal-size rapid edits can retain identical filesystem timestamps. Hash the
# same content that is parsed; metadata alone cannot establish cache freshness.
_FRONTMATTER_CACHE: dict[bytes, dict[str, Any]] = {}
_FRONTMATTER_CACHE_MAX = 1024
_FRONTMATTER_DELIMITER = re.compile(r"^---$", re.MULTILINE)


class SkillRegistry:
    """Skill 元数据注册表。"""

    def __init__(self) -> None:
        """初始化一个空注册表。

        :returns: 无返回值。
        """
        self._skills: dict[str, SkillDescriptor] = {}
        self._builtin_scanned = False

    def scan_builtin(self, root: Path | None = None) -> list[str]:
        """扫描内置 skill(仅一次)。

        :param root: 可选的内置 skill 根目录覆盖值。
        :returns: 新增的 skill id 列表。
        """
        if self._builtin_scanned:
            return []
        added = self._scan_root(
            root or _BUILTIN_ROOT,
            namespace="built-in",
            source="built-in",
            source_label="built-in",
        )
        self._builtin_scanned = True
        return added

    def scan_custom(self, skills_root: Path, namespace: str = "custom") -> list[str]:
        """扫描一个自定义 skill 根目录。

        :param skills_root: 包含 skill 子目录的目录。
        :param namespace: 赋予所发现 skill 的命名空间。
        :returns: 新增的 skill id 列表。
        """
        ns = namespace.strip() or "custom"
        return self._scan_root(
            skills_root,
            namespace=ns,
            source="custom",
            source_label=str(skills_root),
        )

    def register_installed_custom(
        self, descriptor: SkillDescriptor, destination: Path
    ) -> None:
        """Publish a validated custom skill at its final path, replacing stale entries."""
        installed = replace(
            descriptor, root=destination, source_label=str(destination.parent)
        )
        # A previous scan may have registered a different name at this path, or
        # this name at a different path. Publish the new mapping in one assignment.
        self._skills = {
            skill_id: current
            for skill_id, current in self._skills.items()
            if current.namespace != "custom" or current.root != destination
        } | {installed.skill_id: installed}

    def scan_env(self, skills_dir: Path, env_name: str) -> list[str]:
        """扫描某个环境模块提供的 skill。

        :param skills_dir: 包含 skill 子目录的目录。
        :param env_name: 环境模块名。
        :returns: 新增的 skill id 列表。
        """
        namespace = f"env:{env_name.strip() or 'unknown'}"
        return self._scan_root(
            skills_dir,
            namespace=namespace,
            source="env",
            source_label=str(skills_dir),
        )

    def list_all(self) -> list[SkillDescriptor]:
        """列出全部已注册的 skill。

        :returns: 已注册的 skill 描述符。
        """
        return sorted(self._skills.values(), key=lambda item: item.skill_id)

    def get(self, skill_id: str) -> SkillDescriptor | None:
        """按 id 返回单个 skill 描述符。

        :param skill_id: 注册表 skill id。
        :returns: 匹配的描述符,未找到时为 None。
        """
        return self._skills.get(skill_id)

    def find_by_name(self, name: str) -> list[SkillDescriptor]:
        """按显示名查找 skill 描述符。

        :param name: skill 显示名。
        :returns: 匹配的描述符列表。
        """
        return [item for item in self.list_all() if item.name == name]

    def read_skill_doc(self, skill_id: str) -> str:
        """读取某个 skill 的 SKILL.md。

        :param skill_id: 注册表 skill id。
        :returns: skill 文档文本,否则返回空字符串。
        """
        info = self.get(skill_id)
        if info is None:
            return ""
        path = info.root / "SKILL.md"
        if not path.is_file():
            return ""
        return path.read_text(encoding="utf-8")

    def read_skill_file(self, skill_id: str, relative_path: str) -> str:
        """读取 skill 目录内的一个文件。

        :param skill_id: 注册表 skill id。
        :param relative_path: 相对 skill 根的路径。
        :returns: 文件文本,否则返回空字符串。
        """
        info = self.get(skill_id)
        if info is None:
            return ""
        target = self._resolve_inside(info.root, relative_path)
        if target is None or not target.is_file():
            return ""
        return target.read_text(encoding="utf-8")

    def list_hooks(self, hook_type: str) -> list[SkillDescriptor]:
        """列出声明了某个钩子的 skill。

        :param hook_type: 生命周期钩子名。
        :returns: 声明了该钩子的 skill 描述符。
        """
        return [item for item in self.list_all() if item.hooks.get(hook_type)]

    def _scan_root(
        self,
        root: Path,
        *,
        namespace: str,
        source: str,
        source_label: str,
    ) -> list[str]:
        """扫描一个 skill 根目录。

        :param root: 包含 skill 子目录的目录。
        :param namespace: 赋予所发现 skill 的命名空间。
        :param source: 来源类别。
        :param source_label: 人类可读的来源标签。
        :returns: 新增的 skill id 列表。
        """
        added: list[str] = []
        base = root.resolve()
        if not base.is_dir():
            self._drop_stale_skills(namespace)
            return added

        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name.startswith((".", "_")):
                continue
            try:
                resolved_child = child.resolve()
                if base not in resolved_child.parents:
                    continue
                descriptor = _read_skill_descriptor(
                    resolved_child,
                    namespace=namespace,
                    source=source,
                    source_label=source_label,
                )
            except (OSError, RuntimeError, ValueError, yaml.YAMLError):
                # A damaged skill must not interrupt discovery of its neighbors.
                continue
            current = self._skills.get(descriptor.skill_id)
            if current is None:
                self._skills[descriptor.skill_id] = descriptor
                added.append(descriptor.skill_id)
            elif source == "custom" and (
                current.root == descriptor.root
                or (
                    current.root.parent == descriptor.root.parent == base
                    and descriptor.root.name == descriptor.name
                )
            ):
                # Refresh the same directory; prefer canonical installs over siblings.
                self._skills[descriptor.skill_id] = descriptor

        # Drop entries whose directory disappeared since the previous scan;
        # otherwise /list keeps advertising deleted skills until restart.
        self._drop_stale_skills(namespace)
        return added

    def _drop_stale_skills(self, namespace: str) -> None:
        """Remove descriptors in ``namespace`` whose root directory is gone.

        :param namespace: Registry namespace to prune.
        """
        for skill_id, descriptor in list(self._skills.items()):
            if descriptor.namespace == namespace and not descriptor.root.is_dir():
                del self._skills[skill_id]

    @staticmethod
    def _resolve_inside(root: Path, relative_path: str) -> Path | None:
        """解析根目录内的一个路径。

        :param root: 根目录。
        :param relative_path: 候选相对路径。
        :returns: 路径保持在根内时返回解析结果,否则返回 None。
        """
        base = root.resolve()
        target = (base / str(relative_path or ".")).resolve()
        if target == base or base in target.parents:
            return target
        return None


def describe_custom_skill(root: Path) -> SkillDescriptor:
    """Validate a staged custom skill without modifying the registry."""
    root = root.resolve()
    descriptor = _read_skill_descriptor(
        root, namespace="custom", source="custom", source_label=str(root.parent)
    )
    if descriptor.name != root.name:
        raise ValueError("SKILL.md name must match the skill directory name")
    return descriptor


def _read_skill_descriptor(
    root: Path, *, namespace: str, source: str, source_label: str
) -> SkillDescriptor:
    skill_md = root / "SKILL.md"
    if not skill_md.is_file() or not skill_md.resolve().is_relative_to(root):
        raise ValueError("Skill directory must contain SKILL.md")
    raw = skill_md.read_text(encoding="utf-8")
    cache_key = sha256(raw.encode("utf-8")).digest()
    meta = _FRONTMATTER_CACHE.get(cache_key)
    if meta is None:
        meta = _parse_frontmatter(raw)
        if len(_FRONTMATTER_CACHE) >= _FRONTMATTER_CACHE_MAX:
            _FRONTMATTER_CACHE.clear()
        _FRONTMATTER_CACHE[cache_key] = meta

    name = meta.get("name")
    if not isinstance(name, str) or not name or name != name.strip():
        raise ValueError("SKILL.md must declare a non-empty string name")
    description = meta.get("description", "")
    if not isinstance(description, str):
        raise ValueError("SKILL.md description must be a string")
    return SkillDescriptor(
        skill_id=f"{namespace}@{name}",
        name=name,
        namespace=namespace,
        description=description.strip(),
        root=root,
        source=source,
        source_label=source_label,
        script=_require_relative_script(root, meta["script"])
        if "script" in meta
        else None,
        hooks=_parse_hooks(root, meta),
    )


def _parse_frontmatter(raw: str) -> dict[str, Any]:
    """Parse a YAML mapping delimited by standalone ``---`` lines."""
    opening = "---\n"
    if not raw.startswith(opening):
        raise ValueError("SKILL.md must begin with YAML frontmatter")
    closing = _FRONTMATTER_DELIMITER.search(raw, len(opening))
    if closing is None:
        raise ValueError("SKILL.md YAML frontmatter is missing its closing delimiter")
    loaded = yaml.safe_load(raw[len(opening) : closing.start()])
    if not isinstance(loaded, dict):
        raise ValueError("SKILL.md YAML frontmatter must be a mapping")
    return loaded


def _require_relative_script(root: Path, value: Any) -> str:
    """Validate a script reference and return its relative POSIX path."""
    if isinstance(value, str) and value.strip():
        path = Path(value.strip().replace("\\", "/"))
        if not path.is_absolute() and not path.drive:
            target = (root / path).resolve()
            if target.is_relative_to(root) and target.is_file():
                return target.relative_to(root).as_posix()
    raise ValueError(
        "SKILL.md script and hook paths must reference files within the skill directory"
    )


def _is_hidden_or_cache_path(relative_path: Path) -> bool:
    """判断一个相对资源路径是否应从目录中隐藏。

    :param relative_path: 相对某个 skill 根的候选路径。
    :returns: 路径为隐藏文件、缓存生成或编译产物时返回 True。
    """
    parts = relative_path.parts
    if any(part.startswith(".") for part in parts):
        return True
    if "__pycache__" in parts:
        return True
    return relative_path.suffix in {".pyc", ".pyo"}


def _parse_hooks(root: Path, meta: dict[str, Any]) -> dict[str, str]:
    """解析生命周期钩子声明。

    :param root: skill 根目录。
    :param meta: 已解析的 frontmatter 映射。
    :returns: 钩子类型到脚本路径的映射。
    """
    raw_hooks = meta.get("hooks", {})
    if not isinstance(raw_hooks, dict):
        raise ValueError("SKILL.md hooks must be a mapping")
    hooks: dict[str, str] = {}
    for hook_type, path in raw_hooks.items():
        if not isinstance(hook_type, str) or not hook_type.strip():
            raise ValueError("SKILL.md hook names must be non-empty strings")
        hooks[hook_type.strip()] = _require_relative_script(root, path)
    return hooks


_registry: SkillRegistry | None = None


def get_skill_registry() -> SkillRegistry:
    """返回全局 Skill 注册表。

    :returns: 已扫描内置 skill 的全局注册表。
    """
    global _registry
    if _registry is None:
        _registry = SkillRegistry()
        _registry.scan_builtin()
    return _registry
