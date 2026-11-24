"""
安全测试执行器

使用动态导入和反射机制测试自定义模块，避免代码注入风险。
"""

from __future__ import annotations

import importlib
import importlib.util
import inspect
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from typing import Any, ClassVar

from agentsociety2.backend.path_security import (
    resolve_workspace_relative,
    resolve_workspace_root,
)
from agentsociety2.backend.services.custom.compatibility import (
    get_registered_tool_names,
    overrides_base_method,
)
from agentsociety2.backend.services.custom.models import (
    ValidationCheck,
)
from agentsociety2.env.base import EnvBase


@dataclass
class TestResult:
    """单个测试结果"""

    name: str
    success: bool
    output: str
    error: str | None = None
    checks: list[ValidationCheck] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    module_kind: str = "env_module"


@dataclass
class ModuleTestReport:
    """模块测试报告"""

    success: bool
    results: list[TestResult]
    total_tests: int
    passed_tests: int
    failed_tests: int
    stdout: str
    stderr: str


class SafeModuleTester:
    """安全的模块测试器。"""

    ALLOWED_PATH_PREFIXES: ClassVar[list[str]] = [
        "custom.agents",
        "custom.envs",
        "agentsociety2",
    ]

    def __init__(self, workspace_path: str):
        self.workspace_path = resolve_workspace_root(workspace_path)

    def _validate_module_path(self, module_path: str) -> bool:
        clean_path = module_path.replace(".py", "").replace("/", ".")
        return any(
            clean_path.startswith(prefix) for prefix in self.ALLOWED_PATH_PREFIXES
        )

    def _safe_import_class(self, module_path: str, class_name: str) -> type | None:
        if not self._validate_module_path(module_path):
            raise ValueError(
                f"模块路径不在白名单内: {module_path}. "
                f"允许的前缀: {self.ALLOWED_PATH_PREFIXES}"
            )
        if not class_name.replace("_", "").isalnum():
            raise ValueError(f"类名包含非法字符: {class_name}")

        module_import_path = module_path.replace(".py", "").replace("/", ".")
        try:
            if module_import_path.startswith("custom."):
                file_path = resolve_workspace_relative(self.workspace_path, module_path)
                module_name = f"_custom_test_{class_name}_{id(file_path)}"
                spec = importlib.util.spec_from_file_location(module_name, file_path)
                if spec is None or spec.loader is None:
                    raise ImportError(f"无法为 {file_path} 创建导入 spec")
                module = importlib.util.module_from_spec(spec)
                # 仅在执行该模块期间临时加入 workspace 根，避免全局 sys.path
                # 被永久污染、影响后续惰性 import。
                workspace_str = str(self.workspace_path)
                inserted = workspace_str not in sys.path
                if inserted:
                    sys.path.insert(0, workspace_str)
                try:
                    sys.modules[module_name] = module
                    spec.loader.exec_module(module)
                finally:
                    if inserted:
                        try:
                            sys.path.remove(workspace_str)
                        except ValueError:
                            pass
            else:
                importlib.invalidate_caches()
                module = importlib.import_module(module_import_path)
            cls = getattr(module, class_name)
            if not inspect.isclass(cls):
                raise ValueError(f"{class_name} 不是一个类")
            return cls
        except ImportError as exc:
            raise ImportError(f"无法导入模块 {module_import_path}: {exc}") from exc
        except AttributeError as exc:
            raise AttributeError(f"模块中没有类 {class_name}: {exc}") from exc

    def _check(
        self, name: str, passed: bool, message: str, **details: Any
    ) -> ValidationCheck:
        return ValidationCheck(
            name=name,
            passed=passed,
            message=message,
            details=details,
        )

    def _finalize_result(
        self,
        *,
        name: str,
        module_kind: str,
        output_lines: list[str],
        checks: list[ValidationCheck],
        metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> TestResult:
        success = all(check.passed for check in checks)
        return TestResult(
            name=name,
            module_kind=module_kind,
            success=success,
            output="\n".join(output_lines),
            error=error if not success else None,
            checks=checks,
            metadata=metadata or {},
        )

    def _test_agent_class(self, cls: type, class_name: str) -> TestResult:
        output_lines = [f"--- 测试 {class_name} ---"]
        checks: list[ValidationCheck] = []

        required_methods = ["ask", "step", "create", "from_workspace", "to_workspace"]
        missing_methods = [
            method for method in required_methods if not hasattr(cls, method)
        ]
        checks.append(
            self._check(
                "required_methods",
                not missing_methods,
                (
                    "Agent 必需方法检查通过"
                    if not missing_methods
                    else f"缺少必需方法: {missing_methods}"
                ),
                missing_methods=missing_methods,
            )
        )
        if missing_methods:
            output_lines.append(f"✗ 缺少必需方法: {', '.join(missing_methods)}")
            return self._finalize_result(
                name=class_name,
                module_kind="agent",
                output_lines=output_lines,
                checks=checks,
                error=f"缺少必需方法: {missing_methods}",
            )

        try:
            agent = cls(id=0, profile={"name": "测试", "personality": "友好"})
            output_lines.append("✓ 创建成功")
            checks.append(self._check("instantiation", True, "Agent 实例化成功"))
        except Exception as exc:
            output_lines.append(f"✗ 创建实例失败: {exc}")
            checks.append(
                self._check("instantiation", False, f"Agent 实例化失败: {exc}")
            )
            return self._finalize_result(
                name=class_name,
                module_kind="agent",
                output_lines=output_lines,
                checks=checks,
                error=str(exc),
            )

        if hasattr(agent, "description"):
            try:
                description = agent.description()
                output_lines.append(f"✓ description() 返回 {len(description)} 字符")
                checks.append(
                    self._check(
                        "description",
                        bool(description),
                        "description() 可调用",
                        length=len(description),
                    )
                )
            except Exception as exc:
                output_lines.append(f"✗ description() 调用失败: {exc}")
                checks.append(
                    self._check("description", False, f"description() 调用失败: {exc}")
                )

        if hasattr(agent, "init_description"):
            try:
                init_description = agent.init_description()
                output_lines.append(
                    f"✓ init_description() 返回 {len(init_description)} 字符"
                )
                checks.append(
                    self._check(
                        "init_description",
                        bool(init_description),
                        "init_description() 可调用",
                        length=len(init_description),
                    )
                )
            except Exception as exc:
                output_lines.append(f"✗ init_description() 调用失败: {exc}")
                checks.append(
                    self._check(
                        "init_description", False, f"init_description() 调用失败: {exc}"
                    )
                )

        for method in required_methods:
            exists = hasattr(agent, method)
            checks.append(
                self._check(
                    f"method_{method}",
                    exists,
                    f"{method}() 方法存在" if exists else f"{method}() 方法不存在",
                )
            )
            output_lines.append(
                f"{'✓' if exists else '✗'} {method}() 方法{'存在' if exists else '不存在'}"
            )

        return self._finalize_result(
            name=class_name,
            module_kind="agent",
            output_lines=output_lines,
            checks=checks,
        )

    def _test_env_class(self, cls: type, class_name: str) -> TestResult:
        output_lines = [f"--- 测试 {class_name} ---"]
        checks: list[ValidationCheck] = []
        metadata: dict[str, Any] = {}

        try:
            env = cls()
            output_lines.append("✓ 创建成功")
            checks.append(self._check("instantiation", True, "cls() 实例化成功"))
        except Exception as exc:
            output_lines.append(f"✗ 创建实例失败: {exc}")
            checks.append(
                self._check("instantiation", False, f"cls() 实例化失败: {exc}")
            )
            return self._finalize_result(
                name=class_name,
                module_kind="env_module",
                output_lines=output_lines,
                checks=checks,
                error=str(exc),
            )

        if hasattr(env, "description"):
            try:
                description = env.description()
                output_lines.append(f"✓ description() 返回 {len(description)} 字符")
                checks.append(
                    self._check(
                        "description",
                        bool(description),
                        "description() 可调用",
                        length=len(description),
                    )
                )
                metadata["description_length"] = len(description)
            except Exception as exc:
                output_lines.append(f"✗ description() 调用失败: {exc}")
                checks.append(
                    self._check("description", False, f"description() 调用失败: {exc}")
                )

        if hasattr(env, "init_description"):
            try:
                init_description = env.init_description()
                output_lines.append(
                    f"✓ init_description() 返回 {len(init_description)} 字符"
                )
                checks.append(
                    self._check(
                        "init_description",
                        bool(init_description),
                        "init_description() 可调用",
                        length=len(init_description),
                    )
                )
                metadata["init_description_length"] = len(init_description)
            except Exception as exc:
                output_lines.append(f"✗ init_description() 调用失败: {exc}")
                checks.append(
                    self._check(
                        "init_description", False, f"init_description() 调用失败: {exc}"
                    )
                )

        tool_names = get_registered_tool_names(env)
        metadata["tool_names"] = tool_names
        metadata["tool_count"] = len(tool_names)
        output_lines.append(f"✓ 已注册 {len(tool_names)} 个工具")
        checks.append(
            self._check(
                "registered_tools",
                len(tool_names) > 0,
                f"已注册 {len(tool_names)} 个工具" if tool_names else "未注册任何工具",
                tool_names=tool_names,
            )
        )

        has_step = overrides_base_method(cls, EnvBase, "step")
        metadata["has_step"] = has_step
        checks.append(
            self._check(
                "step",
                has_step,
                "step() 方法已覆写" if has_step else "step() 方法未覆写 EnvBase.step",
            )
        )
        output_lines.append(
            f"{'✓' if has_step else '✗'} step() 方法{'已覆写' if has_step else '未覆写 EnvBase.step'}"
        )

        try:
            from agentsociety2.env.router_codegen import CodeGenRouter

            router = CodeGenRouter(env_modules=[env])
            tool_schemas = getattr(router, "_tool_manager", None)
            metadata["router_tool_manager"] = tool_schemas is not None
            output_lines.append("✓ router smoke test 成功")
            checks.append(
                self._check(
                    "router_smoke",
                    True,
                    "CodeGenRouter 可正常挂载该环境",
                )
            )
        except Exception as exc:
            output_lines.append(f"✗ router smoke test 失败: {exc}")
            checks.append(
                self._check("router_smoke", False, f"router smoke test 失败: {exc}")
            )

        return self._finalize_result(
            name=class_name,
            module_kind="env_module",
            output_lines=output_lines,
            checks=checks,
            metadata=metadata,
        )

    def _test_integration(
        self,
        agent_cls: type,
        agent_name: str,
        env_cls: type,
        env_name: str,
    ) -> TestResult:
        output_lines = ["--- 集成测试 ---"]
        checks: list[ValidationCheck] = []

        try:
            from agentsociety2.env.router_codegen import CodeGenRouter
        except ImportError:
            output_lines.append("⚠ 无法导入 CodeGenRouter，跳过集成测试")
            checks.append(
                self._check("router_import", True, "CodeGenRouter 不可用，跳过集成测试")
            )
            return self._finalize_result(
                name=f"{agent_name}+{env_name}",
                module_kind="integration",
                output_lines=output_lines,
                checks=checks,
            )

        try:
            env = env_cls()
            router = CodeGenRouter(env_modules=[env])
            output_lines.append("✓ 环境路由创建成功")
            checks.append(self._check("router_creation", True, "环境路由创建成功"))

            agent = agent_cls(
                id=0,
                profile={"name": "集成测试", "personality": "测试"},
            )
            output_lines.append("✓ Agent 创建成功")
            checks.append(self._check("agent_creation", True, "Agent 创建成功"))

            # Agents bind shared services instead of init(env).
            if hasattr(agent, "_bind_services"):
                try:
                    from agentsociety2.agent.service_proxy import build_service_proxy

                    proxy = build_service_proxy(router, trace=False, replay=False)
                    agent._bind_services(proxy)
                    output_lines.append("✓ Agent 环境初始化成功")
                    checks.append(
                        self._check("agent_init", True, "Agent 环境初始化成功")
                    )
                except Exception as exc:
                    output_lines.append(f"✗ Agent 环境初始化失败: {exc}")
                    checks.append(
                        self._check("agent_init", False, f"Agent 环境初始化失败: {exc}")
                    )
        except Exception as exc:
            output_lines.append(f"✗ 集成测试失败: {exc}")
            checks.append(self._check("integration", False, f"集成测试失败: {exc}"))
            return self._finalize_result(
                name=f"{agent_name}+{env_name}",
                module_kind="integration",
                output_lines=output_lines,
                checks=checks,
                error=str(exc),
            )

        return self._finalize_result(
            name=f"{agent_name}+{env_name}",
            module_kind="integration",
            output_lines=output_lines,
            checks=checks,
        )

    async def run_target_test(
        self,
        *,
        module_kind: str,
        module_path: str,
        class_name: str | None,
    ) -> dict[str, Any]:
        """Test a single target module regardless of scan outcome."""

        if not class_name:
            return {
                "success": False,
                "error": "必须提供 class_name 才能执行目标测试",
                "stdout": "",
                "stderr": "",
                "returncode": -1,
                "results": [],
                "total_tests": 0,
                "passed_tests": 0,
                "failed_tests": 0,
            }

        try:
            cls = self._safe_import_class(module_path, class_name)
            if cls is None:
                raise ValueError(f"无法导入类 {class_name}")
            result = (
                self._test_env_class(cls, class_name)
                if module_kind == "env_module"
                else self._test_agent_class(cls, class_name)
            )
            results = [result]
            return self._serialize_results(results)
        except Exception as exc:
            failed = TestResult(
                name=class_name,
                module_kind=module_kind,
                success=False,
                output=f"✗ {class_name}",
                error=str(exc),
            )
            return self._serialize_results([failed], error=str(exc))

    def _serialize_results(
        self,
        results: list[TestResult],
        *,
        stdout: str = "",
        stderr: str = "",
        error: str | None = None,
    ) -> dict[str, Any]:
        passed = sum(1 for result in results if result.success)
        failed = sum(1 for result in results if not result.success)
        return {
            "success": failed == 0,
            "stdout": stdout,
            "stderr": stderr,
            "returncode": 0 if failed == 0 else 1,
            "results": [
                {
                    "name": result.name,
                    "module_kind": result.module_kind,
                    "success": result.success,
                    "output": result.output,
                    "error": result.error,
                    "checks": [
                        check.model_dump(mode="json") for check in result.checks
                    ],
                    "metadata": result.metadata,
                }
                for result in results
            ],
            "total_tests": len(results),
            "passed_tests": passed,
            "failed_tests": failed,
            "error": (
                error
                if error is not None
                else (None if failed == 0 else f"{failed} 个测试失败")
            ),
        }

    async def run_test(self, scan_result: dict[str, Any]) -> dict[str, Any]:
        """执行测试。"""

        agents = scan_result.get("agents", [])
        envs = scan_result.get("envs", [])
        if not agents and not envs:
            return {
                "success": False,
                "error": "未发现任何自定义模块",
                "stdout": "",
                "stderr": "",
                "returncode": -1,
                "results": [],
                "total_tests": 0,
                "passed_tests": 0,
                "failed_tests": 0,
            }

        stdout_buffer = io.StringIO()
        stderr_buffer = io.StringIO()
        results: list[TestResult] = []
        all_output: list[str] = []

        try:
            with redirect_stdout(stdout_buffer), redirect_stderr(stderr_buffer):
                all_output.extend(["=" * 50, "开始测试自定义模块", "=" * 50])

                if agents:
                    all_output.extend(["", "测试 Agent", "-" * 30])
                    for agent_info in agents:
                        module_path = agent_info.get("module_path", "")
                        class_name = agent_info.get("class_name", "")
                        if not module_path or not class_name:
                            continue
                        try:
                            cls = self._safe_import_class(module_path, class_name)
                            if cls is None:
                                raise ValueError(f"无法导入类 {class_name}")
                            result = self._test_agent_class(cls, class_name)
                        except Exception as exc:
                            result = TestResult(
                                name=class_name,
                                module_kind="agent",
                                success=False,
                                output=f"✗ {class_name}",
                                error=str(exc),
                            )
                        results.append(result)
                        all_output.append(result.output)

                if envs:
                    all_output.extend(["", "测试环境模块", "-" * 30])
                    for env_info in envs:
                        module_path = env_info.get("module_path", "")
                        class_name = env_info.get("class_name", "")
                        if not module_path or not class_name:
                            continue
                        try:
                            cls = self._safe_import_class(module_path, class_name)
                            if cls is None:
                                raise ValueError(f"无法导入类 {class_name}")
                            result = self._test_env_class(cls, class_name)
                        except Exception as exc:
                            result = TestResult(
                                name=class_name,
                                module_kind="env_module",
                                success=False,
                                output=f"✗ {class_name}",
                                error=str(exc),
                            )
                        results.append(result)
                        all_output.append(result.output)

                if agents and envs:
                    all_output.extend(["", "集成测试", "-" * 30])
                    try:
                        agent_info = agents[0]
                        env_info = envs[0]
                        agent_cls = self._safe_import_class(
                            agent_info.get("path", "")
                            or agent_info.get("module_path", ""),
                            agent_info.get("class_name", ""),
                        )
                        env_cls = self._safe_import_class(
                            env_info.get("path", "") or env_info.get("module_path", ""),
                            env_info.get("class_name", ""),
                        )
                        if agent_cls is None or env_cls is None:
                            raise ValueError("无法导入 Agent 或环境类")
                        result = self._test_integration(
                            agent_cls,
                            agent_info.get("class_name", ""),
                            env_cls,
                            env_info.get("class_name", ""),
                        )
                        results.append(result)
                        all_output.append(result.output)
                    except Exception as exc:
                        all_output.append(f"✗ 集成测试: {exc}")

                all_output.extend(["", "=" * 50, "测试完成", "=" * 50])
            return self._serialize_results(
                results,
                stdout="\n".join(all_output),
                stderr=stderr_buffer.getvalue(),
            )
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "stdout": "\n".join(all_output),
                "stderr": stderr_buffer.getvalue(),
                "returncode": -1,
                "results": [],
                "total_tests": 0,
                "passed_tests": 0,
                "failed_tests": 0,
            }
