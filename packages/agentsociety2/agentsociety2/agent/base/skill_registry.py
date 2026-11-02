"""Skill 注册表。

中文：扫描、解析和查询 Agent skill 元数据。
English: Scans, parses, and queries Agent skill metadata.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

# Built-in skills live under ``agentsociety2/agent/skills/`` (sibling of this
# ``agent/base/`` package). Compute it from this file's location so the
# registry keeps scanning the real skill content directory regardless of where
# this module itself is imported from / located.
_BUILTIN_ROOT = Path(__file__).resolve().parent.parent / "skills"
_RESOURCE_FILES_CACHE: dict[tuple[str, int], list[str]] = {}


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
        if not self.root.is_dir():
            return []
        try:
            mtime_ns = self.root.stat().st_mtime_ns
        except OSError:
            mtime_ns = 0
        cache_key = (str(self.root), mtime_ns)
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
        _RESOURCE_FILES_CACHE[cache_key] = resources
        return list(resources)


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
            return added
        # Ensure the resolved path hasn't escaped via symlink traversal.
        try:
            base.relative_to(root.resolve())
        except ValueError:
            # resolved path is outside the original root — reject
            return added

        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name.startswith((".", "_")):
                continue
            skill_md = child / "SKILL.md"
            if not skill_md.is_file():
                continue
            meta = _parse_frontmatter(skill_md)
            name = str(meta.get("name") or child.name).strip()
            if not name:
                continue
            skill_id = f"{namespace}@{name}"
            if skill_id in self._skills:
                continue
            description = str(meta.get("description") or "").strip()
            descriptor = SkillDescriptor(
                skill_id=skill_id,
                name=name,
                namespace=namespace,
                description=description,
                root=child.resolve(),
                source=source,
                source_label=source_label,
                script=_clean_relative_script(child, meta.get("script")),
                hooks=_parse_hooks(child, meta),
            )
            self._skills[skill_id] = descriptor
            added.append(skill_id)
        return added

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


def _parse_frontmatter(path: Path) -> dict[str, Any]:
    """从 SKILL.md 文件解析 YAML frontmatter。

    :param path: SKILL.md 路径。
    :returns: 解析出的 frontmatter 映射。
    """
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        return {}
    parts = raw.split("---", 2)
    if len(parts) < 3:
        return {}
    loaded = yaml.safe_load(parts[1]) or {}
    return loaded if isinstance(loaded, dict) else {}


def _clean_relative_script(root: Path, raw: Any) -> str | None:
    """校验并规范化脚本路径。

    :param root: skill 根目录。
    :param raw: 来自 frontmatter 的原始 script 值。
    :returns: 规范化后的相对脚本路径,无效时返回 None。
    """
    text = str(raw or "").strip()
    if not text:
        return None
    base = root.resolve()
    target = (base / text).resolve()
    if target.is_file() and (target == base or base in target.parents):
        return text.replace("\\", "/")
    return None


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
    hooks: dict[str, str] = {}

    raw_hooks = meta.get("hooks")
    if isinstance(raw_hooks, dict):
        for key, value in raw_hooks.items():
            hook_type = str(key or "").strip()
            script = _clean_relative_script(root, value)
            if hook_type and script:
                hooks[hook_type] = script

    hook_type = str(meta.get("hook") or "").strip()
    hook_script = _clean_relative_script(root, meta.get("hook_script"))
    if hook_type and hook_script:
        hooks[hook_type] = hook_script
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
