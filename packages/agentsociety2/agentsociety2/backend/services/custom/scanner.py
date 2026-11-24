"""
自定义模块扫描服务

扫描 custom/ 目录，发现用户自定义的 Agent 和环境模块，并输出结构化诊断。
"""

from __future__ import annotations

import importlib.util
import inspect
import sys
from pathlib import Path
from typing import Any

from agentsociety2.backend.path_security import (
    resolve_under_root,
    resolve_workspace_root,
)
from agentsociety2.backend.services.custom.compatibility import (
    build_agent_scan_diagnostic,
    build_env_scan_diagnostic,
    build_import_error_diagnostic,
)
from agentsociety2.backend.services.custom.models import (
    CompatibilityIssue,
    ScanDiagnostic,
)


class CustomModuleScanner:
    """自定义模块扫描服务"""

    def __init__(
        self, workspace_path: str | Path, *, validate_workspace_root: bool = True
    ):
        if validate_workspace_root:
            self.workspace_path = resolve_workspace_root(str(workspace_path))
        else:
            self.workspace_path = Path(workspace_path).expanduser().resolve()
        self.custom_dir = resolve_under_root(self.workspace_path, "custom")

    def scan_all(self) -> dict[str, Any]:
        """扫描所有自定义模块。"""

        result: dict[str, Any] = {
            "agents": [],
            "envs": [],
            "errors": [],
            "agent_diagnostics": [],
            "env_diagnostics": [],
        }

        if not self.custom_dir.exists():
            result["errors"].append(f"custom/ 目录不存在: {self.custom_dir}")
            return result

        agents_dir = self.custom_dir / "agents"
        if agents_dir.exists():
            agent_result = self._scan_agents(agents_dir, skip_examples=True)
            result["agents"] = agent_result["modules"]
            result["agent_diagnostics"] = agent_result["diagnostics"]
            result["errors"].extend(agent_result["errors"])
        else:
            result["errors"].append("custom/agents/ 目录不存在")

        envs_dir = self.custom_dir / "envs"
        if envs_dir.exists():
            env_result = self._scan_envs(envs_dir, skip_examples=True)
            result["envs"] = env_result["modules"]
            result["env_diagnostics"] = env_result["diagnostics"]
            result["errors"].extend(env_result["errors"])
        else:
            result["errors"].append("custom/envs/ 目录不存在")

        return result

    def _scan_agents(
        self, agents_dir: Path, skip_examples: bool = True
    ) -> dict[str, Any]:
        """扫描 Agent 目录。"""

        agents: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        errors: list[str] = []

        for py_file in agents_dir.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue
            if skip_examples and "examples" in py_file.relative_to(
                self.workspace_path
            ).parts:
                continue

            module_path = str(py_file.relative_to(self.workspace_path))
            try:
                module_name = f"custom_module_{id(py_file)}"
                module = self._load_module(py_file, module_name)
                from agentsociety2.agent.base import AgentBase

                found = False
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, AgentBase)
                        and obj is not AgentBase
                        and obj.__module__ == module_name
                    ):
                        found = True
                        diagnostic = build_agent_scan_diagnostic(
                            workspace_path=self.workspace_path,
                            module_path=module_path,
                            file_path=py_file,
                            cls=obj,
                        )
                        diagnostics.append(diagnostic.model_dump(mode="json"))
                        if diagnostic.accepted:
                            agents.append(
                                {
                                    "type": obj.__name__,
                                    "class_name": obj.__name__,
                                    "module_path": module_path,
                                    "file_path": str(py_file),
                                    "description": self._get_safe_description(obj),
                                }
                            )
                if not found:
                    diagnostics.append(
                        ScanDiagnostic(
                            module_kind="agent",
                            module_path=module_path,
                            file_path=str(py_file),
                            class_name=None,
                            accepted=False,
                            issues=[
                                CompatibilityIssue(
                                    code="no_agent_class",
                                    check="class_discovery",
                                    message=f"{py_file.name} 中未发现 AgentBase 子类",
                                )
                            ],
                            metadata={},
                        ).model_dump(mode="json")
                    )
                self._cleanup_module(module_name)
            except Exception as exc:
                self._cleanup_module(module_name)
                errors.append(f"Agent scan failed for {module_path}: {exc}")
                diagnostics.append(
                    build_import_error_diagnostic(
                        module_kind="agent",
                        file_path=py_file,
                        module_path=module_path,
                        error=exc,
                    ).model_dump(mode="json")
                )

        return {"modules": agents, "diagnostics": diagnostics, "errors": errors}

    def _scan_envs(self, envs_dir: Path, skip_examples: bool = True) -> dict[str, Any]:
        """扫描环境模块目录。"""

        envs: list[dict[str, Any]] = []
        diagnostics: list[dict[str, Any]] = []
        errors: list[str] = []

        for py_file in envs_dir.rglob("*.py"):
            if py_file.name.startswith("__"):
                continue
            if skip_examples and "examples" in py_file.relative_to(
                self.workspace_path
            ).parts:
                continue

            module_path = str(py_file.relative_to(self.workspace_path))
            try:
                module_name = f"custom_module_{id(py_file)}"
                module = self._load_module(py_file, module_name)
                from agentsociety2.env.base import EnvBase

                found = False
                for _, obj in inspect.getmembers(module, inspect.isclass):
                    if (
                        issubclass(obj, EnvBase)
                        and obj is not EnvBase
                        and obj.__module__ == module_name
                    ):
                        found = True
                        diagnostic = build_env_scan_diagnostic(
                            workspace_path=self.workspace_path,
                            module_path=module_path,
                            file_path=py_file,
                            cls=obj,
                        )
                        diagnostics.append(diagnostic.model_dump(mode="json"))
                        if diagnostic.accepted:
                            envs.append(
                                {
                                    "type": obj.__name__,
                                    "class_name": obj.__name__,
                                    "module_path": module_path,
                                    "file_path": str(py_file),
                                    "description": self._get_safe_description(obj),
                                }
                            )
                if not found:
                    diagnostics.append(
                        ScanDiagnostic(
                            module_kind="env_module",
                            module_path=module_path,
                            file_path=str(py_file),
                            class_name=None,
                            accepted=False,
                            issues=[
                                CompatibilityIssue(
                                    code="no_env_class",
                                    check="class_discovery",
                                    message=f"{py_file.name} 中未发现 EnvBase 子类",
                                )
                            ],
                            metadata={},
                        ).model_dump(mode="json")
                    )
                self._cleanup_module(module_name)
            except Exception as exc:
                self._cleanup_module(module_name)
                errors.append(f"Env scan failed for {module_path}: {exc}")
                diagnostics.append(
                    build_import_error_diagnostic(
                        module_kind="env_module",
                        file_path=py_file,
                        module_path=module_path,
                        error=exc,
                    ).model_dump(mode="json")
                )

        return {"modules": envs, "diagnostics": diagnostics, "errors": errors}

    def _load_module(self, file_path: Path, module_name: str):
        """Load a Python file into a temporary module."""

        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法为 {file_path} 创建模块 spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _cleanup_module(self, module_name: str) -> None:
        """Remove a temporary module from sys.modules."""

        if module_name in sys.modules:
            del sys.modules[module_name]

    def _get_safe_description(self, cls: type[Any]) -> str:
        try:
            if hasattr(cls, "description"):
                return cls.description()
            return cls.__doc__ or f"{cls.__name__}: 无描述"
        except Exception:
            return f"{cls.__name__}: 描述获取失败"
