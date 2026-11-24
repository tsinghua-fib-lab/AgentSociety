#!/usr/bin/env python3
"""Local validation entrypoint for the create-env skill."""

from __future__ import annotations

import argparse
import ast
import importlib.util
import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


TRACE_NAMESPACE = "custom_env_skill"
TRACE_ROOT = Path(".agentsociety") / TRACE_NAMESPACE
RUNS_ROOT = TRACE_ROOT / "runs"


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""

    parser = argparse.ArgumentParser(description="Validate a custom env module.")
    parser.add_argument("--file", required=True, help="Path to custom/envs/<module>.py")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--class-name", default=None, help="Target class name")
    parser.add_argument(
        "--run-id",
        default=None,
        help="Optional run id used only for organizing validation artifacts",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    parser.add_argument(
        "--no-refresh-metadata",
        action="store_true",
        help="Skip .agentsociety/env_modules metadata refresh",
    )
    return parser.parse_args()


def now_iso() -> str:
    """Return a UTC timestamp for artifacts."""

    return datetime.now(timezone.utc).isoformat()


def setup_sys_path(workspace_path: Path) -> None:
    """Ensure the workspace and package root are importable."""

    workspace_str = str(workspace_path.resolve())
    if workspace_str not in sys.path:
        sys.path.insert(0, workspace_str)

    package_root = workspace_path / "packages" / "agentsociety2"
    if package_root.exists():
        package_root_str = str(package_root.resolve())
        if package_root_str not in sys.path:
            sys.path.insert(0, package_root_str)


def ensure_workspace_layout(workspace_path: Path) -> None:
    """Ensure artifact directories exist."""

    (workspace_path / RUNS_ROOT).mkdir(parents=True, exist_ok=True)
    (workspace_path / ".agentsociety" / "env_modules").mkdir(
        parents=True,
        exist_ok=True,
    )


def run_dir(workspace_path: Path, run_id: str) -> Path:
    """Return the run directory."""

    return workspace_path / RUNS_ROOT / run_id


def write_json(path: Path, payload: Any) -> None:
    """Write JSON with UTF-8 indentation."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def write_markdown(path: Path, text: str) -> None:
    """Write markdown text."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def read_json(path: Path) -> Any | None:
    """Read JSON when present."""

    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def append_log(workspace_path: Path, run_id: str, message: str) -> None:
    """Append one line to the run log."""

    log_path = run_dir(workspace_path, run_id) / "run.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{now_iso()}] {message}\n")


def normalize_module_path(workspace_path: Path, module_path: str) -> str:
    """Normalize to a workspace-relative path."""

    path = Path(module_path)
    if path.is_absolute():
        return str(path.resolve().relative_to(workspace_path.resolve()))
    return module_path


def build_request_payload(user_request: str) -> dict[str, Any]:
    """Build the request payload stored with a run."""

    return {
        "user_request": user_request,
        "metadata": {"invoked_from": "skill_validate_script"},
    }


def create_validation_run(
    workspace_path: Path,
    *,
    user_request: str,
    run_id: str | None,
) -> tuple[str, dict[str, Any]]:
    """Create or reuse a lightweight run used only to organize validation artifacts."""

    ensure_workspace_layout(workspace_path)
    actual_run_id = run_id or uuid4().hex[:12]
    current_run_dir = run_dir(workspace_path, actual_run_id)
    request_path = current_run_dir / "request.json"
    run_state_path = current_run_dir / "run_state.json"
    existing_request = read_json(request_path)
    request = (
        existing_request
        if isinstance(existing_request, dict)
        else build_request_payload(user_request)
    )
    if not request_path.exists():
        write_json(request_path, request)

    existing_run_state = read_json(run_state_path)
    existing_artifacts = (
        existing_run_state.get("artifacts", {})
        if isinstance(existing_run_state, dict)
        and isinstance(existing_run_state.get("artifacts", {}), dict)
        else {}
    )
    existed_before = run_state_path.exists()
    run_state = {
        "run_id": actual_run_id,
        "workspace_path": str(workspace_path.resolve()),
        "status": "active",
        "stage": "validate",
        "created_at": (
            existing_run_state.get("created_at")
            if isinstance(existing_run_state, dict)
            else None
        ) or now_iso(),
        "updated_at": now_iso(),
        "request": request,
        "module_path": (
            existing_run_state.get("module_path")
            if isinstance(existing_run_state, dict)
            else None
        ),
        "class_name": (
            existing_run_state.get("class_name")
            if isinstance(existing_run_state, dict)
            else None
        ),
        "last_error": None,
        "artifacts": {
            **existing_artifacts,
            "request": str(request_path.relative_to(workspace_path)),
        },
    }
    write_json(run_state_path, run_state)
    append_log(
        workspace_path,
        actual_run_id,
        "reused validation run" if existed_before else "created validation run",
    )
    return actual_run_id, run_state


def mark_run_failed(
    workspace_path: Path,
    *,
    run_id: str,
    user_request: str,
    error: str,
    module_path: str | None = None,
) -> None:
    """Persist failure metadata for a run even when validation exits early."""

    current_run_dir = run_dir(workspace_path, run_id)
    run_state_path = current_run_dir / "run_state.json"
    request_path = current_run_dir / "request.json"
    existing_run_state = read_json(run_state_path)
    request = (
        existing_run_state.get("request")
        if isinstance(existing_run_state, dict)
        and isinstance(existing_run_state.get("request"), dict)
        else build_request_payload(user_request)
    )
    artifacts = (
        existing_run_state.get("artifacts", {})
        if isinstance(existing_run_state, dict)
        and isinstance(existing_run_state.get("artifacts", {}), dict)
        else {}
    )
    if request_path.exists():
        artifacts = {
            **artifacts,
            "request": str(request_path.relative_to(workspace_path)),
        }

    run_state = {
        "run_id": run_id,
        "workspace_path": str(workspace_path.resolve()),
        "status": "failed",
        "stage": "failed",
        "created_at": (
            existing_run_state.get("created_at")
            if isinstance(existing_run_state, dict)
            else None
        ) or now_iso(),
        "updated_at": now_iso(),
        "request": request,
        "module_path": module_path,
        "class_name": (
            existing_run_state.get("class_name")
            if isinstance(existing_run_state, dict)
            else None
        ),
        "last_error": error,
        "artifacts": artifacts,
    }
    write_json(run_state_path, run_state)
    append_log(workspace_path, run_id, f"validation failed early: {error}")


def _import_compat_helpers():
    """Lazily import shared helpers from the agentsociety2 backend compatibility module.

    These functions must be imported after setup_sys_path() has been called,
    since agentsociety2 is not on sys.path at script startup.
    """
    from agentsociety2.backend.services.custom.compatibility import (
        get_registered_tool_names,
        is_no_arg_constructible,
        overrides_base_method,
    )

    return get_registered_tool_names, is_no_arg_constructible, overrides_base_method


def _decorator_is_tool(dec: ast.expr) -> tuple[bool, dict[str, Any]]:
    """Return (is_tool, kwargs_constants) for @tool / @tool(...) decorators."""

    if isinstance(dec, ast.Name) and dec.id == "tool":
        return True, {}
    if isinstance(dec, ast.Attribute) and dec.attr == "tool":
        return True, {}
    if isinstance(dec, ast.Call):
        f = dec.func
        name: str | None = None
        if isinstance(f, ast.Name):
            name = f.id
        elif isinstance(f, ast.Attribute):
            name = f.attr
        if name == "tool":
            kw: dict[str, Any] = {}
            for kwarg in dec.keywords:
                if kwarg.arg and isinstance(kwarg.value, ast.Constant):
                    kw[kwarg.arg] = kwarg.value.value
            return True, kw
    return False, {}


def _return_is_bool_literal(val: ast.expr) -> bool:
    return isinstance(val, ast.Constant) and isinstance(val.value, bool)


def _return_is_success_bool_dict(val: ast.expr) -> bool:
    if not isinstance(val, ast.Dict):
        return False
    for key, value in zip(val.keys, val.values):
        if (
            isinstance(key, ast.Constant)
            and key.value == "success"
            and isinstance(value, ast.Constant)
            and isinstance(value.value, bool)
        ):
            return True
    return False


def _return_dict_has_status(val: ast.expr) -> bool:
    if not isinstance(val, ast.Dict):
        return False
    for key in val.keys:
        if isinstance(key, ast.Constant) and key.value == "status":
            return True
    return False


def _return_annotation_is_bool(node: ast.AsyncFunctionDef | ast.FunctionDef) -> bool:
    ann = node.returns
    return isinstance(ann, ast.Name) and ann.id == "bool"


def static_audit_tool_returns(file_path: Path, target_class: str) -> list[dict[str, Any]]:
    """Static AST audit of `@tool` method return shapes (Pitfall P1).

    Detects:
    - `@tool(readonly=False)` methods returning a bool literal (`return True`)
    - methods returning `{"success": True/False}` (wrong field; status must be a string)
    - methods annotated `-> bool` (smell, not strict error for readonly tools)
    - `readonly=False` methods returning a dict literal without a `status` key (WARNING)

    Args:
        file_path: source file containing the env class.
        target_class: class name to audit (siblings are ignored).
    """

    issues: list[dict[str, Any]] = []
    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except (OSError, SyntaxError):
        return issues

    for cls_node in ast.walk(tree):
        if not isinstance(cls_node, ast.ClassDef) or cls_node.name != target_class:
            continue
        for item in cls_node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            tool_kwargs: dict[str, Any] | None = None
            for dec in item.decorator_list:
                ok, kw = _decorator_is_tool(dec)
                if ok:
                    tool_kwargs = kw
                    break
            if tool_kwargs is None:
                continue
            readonly = tool_kwargs.get("readonly", True)
            severity_write = "error" if readonly is False else "warning"
            location = f"{cls_node.name}.{item.name} (line {item.lineno})"

            if _return_annotation_is_bool(item):
                issues.append(
                    {
                        "code": "tool_return_annotation_bool",
                        "severity": severity_write,
                        "message": (
                            f"{location} has return annotation `-> bool`. "
                            "Framework expects a dict / Pydantic model with `status: str`. "
                            "See references/pitfalls.md P1."
                        ),
                        "check": "tool_return_shape",
                        "details": {"line": item.lineno, "readonly": readonly},
                    }
                )

            for sub in ast.walk(item):
                if not isinstance(sub, ast.Return) or sub.value is None:
                    continue
                if _return_is_bool_literal(sub.value):
                    issues.append(
                        {
                            "code": "tool_returns_bool_literal",
                            "severity": severity_write,
                            "message": (
                                f"{location} returns a bool literal at line "
                                f"{sub.lineno}. Framework expects "
                                "{'status': 'success'|'fail'|'in_progress'|'error', ...}. "
                                "See references/pitfalls.md P1."
                            ),
                            "check": "tool_return_shape",
                            "details": {"line": sub.lineno, "readonly": readonly},
                        }
                    )
                elif _return_is_success_bool_dict(sub.value):
                    issues.append(
                        {
                            "code": "tool_returns_success_bool_dict",
                            "severity": severity_write,
                            "message": (
                                f"{location} returns {{'success': bool}} at line "
                                f"{sub.lineno}. Use {{'status': 'success'|'fail'|...}} "
                                "(string, not bool). See references/pitfalls.md P1."
                            ),
                            "check": "tool_return_shape",
                            "details": {"line": sub.lineno, "readonly": readonly},
                        }
                    )
                elif (
                    readonly is False
                    and isinstance(sub.value, ast.Dict)
                    and not _return_dict_has_status(sub.value)
                ):
                    issues.append(
                        {
                            "code": "tool_dict_missing_status",
                            "severity": "warning",
                            "message": (
                                f"{location} (readonly=False) returns a dict literal "
                                f"without a 'status' key at line {sub.lineno}. "
                                "Writes should include `status: str`. "
                                "See references/pitfalls.md P1."
                            ),
                            "check": "tool_return_shape",
                            "details": {"line": sub.lineno, "readonly": readonly},
                        }
                    )

    return issues


def load_env_class(
    workspace_path: Path,
    module_path: str,
    class_name: str | None = None,
) -> tuple[type[Any], Path]:
    """Load the target env class from a workspace file."""

    setup_sys_path(workspace_path)
    file_path = workspace_path / normalize_module_path(workspace_path, module_path)
    if not file_path.exists():
        raise FileNotFoundError(f"target file does not exist: {file_path}")

    module_name = f"_skill_env_{file_path.stem}_{uuid4().hex[:8]}"
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot create spec for {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)

    from agentsociety2.env.base import EnvBase

    candidates = [
        obj
        for _, obj in inspect.getmembers(module, inspect.isclass)
        if issubclass(obj, EnvBase)
        and obj is not EnvBase
        and obj.__module__ == module_name
    ]
    if class_name is not None:
        candidates = [obj for obj in candidates if obj.__name__ == class_name]
    if len(candidates) != 1:
        raise ValueError(
            f"expected exactly one EnvBase subclass in {file_path}, found {len(candidates)}"
        )
    return candidates[0], file_path


def build_scan_diagnostic(module_path: str, file_path: Path, cls: type[Any]) -> dict[str, Any]:
    """Build local compatibility diagnostics for one env class."""

    get_registered_tool_names, is_no_arg_constructible, overrides_base_method = (
        _import_compat_helpers()
    )
    issues: list[dict[str, Any]] = []
    tool_names = get_registered_tool_names(cls)
    from agentsociety2.env.base import EnvBase

    has_step = overrides_base_method(cls, EnvBase, "step")
    is_no_arg, required_params = is_no_arg_constructible(cls)

    if not has_step:
        issues.append(
            {
                "code": "missing_step",
                "message": f"{cls.__name__} 缺少 step() 方法",
                "severity": "error",
                "check": "step_method",
                "details": {},
            }
        )
    if not tool_names:
        issues.append(
            {
                "code": "missing_tools",
                "message": f"{cls.__name__} 没有注册任何 @tool 方法",
                "severity": "error",
                "check": "registered_tools",
                "details": {},
            }
        )
    if not is_no_arg:
        issues.append(
            {
                "code": "non_default_constructor",
                "message": (
                    f"{cls.__name__} 不能直接通过 cls() 实例化，"
                    f"缺少默认值的参数: {required_params}"
                ),
                "severity": "error",
                "check": "default_constructor",
                "details": {"required_parameters": required_params},
            }
        )

    # Direct-base check: EnvMeta collects @tool methods from the class's own
    # namespace only and overwrites the registry on every subclass, so an env
    # that inherits from another env (instead of EnvBase directly) silently
    # drops every inherited tool. Require EnvBase as a direct base.
    direct_bases = [b for b in cls.__bases__]
    if EnvBase not in direct_bases:
        other_env_bases = [b.__name__ for b in direct_bases if b is not EnvBase]
        issues.append(
            {
                "code": "indirect_env_base",
                "message": (
                    f"{cls.__name__} 必须直接继承 EnvBase（当前直接基类: "
                    f"{', '.join(other_env_bases) or 'none'}）。EnvMeta 元类只收集"
                    f"类自身 namespace 内的 @tool 方法并在子类上覆盖注册表，因此"
                    f"继承自其它 env 类会导致基类的 @tool 装饰器不被识别、工具静默"
                    f"丢失。请参照该类作为参考，在本文件中重新实现所需的 @tool 方法。"
                ),
                "severity": "error",
                "check": "direct_env_base",
                "details": {"direct_bases": [b.__name__ for b in direct_bases]},
            }
        )

    issues.extend(static_audit_tool_returns(file_path, cls.__name__))

    accepted = not any(issue["severity"] == "error" for issue in issues)
    return {
        "module_kind": "env_module",
        "module_path": module_path,
        "file_path": str(file_path),
        "class_name": cls.__name__,
        "accepted": accepted,
        "issues": issues,
        "metadata": {
            "tool_names": tool_names,
            "tool_count": len(tool_names),
            "has_step": has_step,
            "default_constructible": is_no_arg,
            "type": cls.__name__,
            "class_name": cls.__name__,
            "workspace_module_path": module_path,
        },
    }


def build_test_report(cls: type[Any]) -> tuple[bool, dict[str, Any]]:
    """Run local runtime checks for the env class."""

    get_registered_tool_names, is_no_arg_constructible, overrides_base_method = (
        _import_compat_helpers()
    )
    checks: list[dict[str, Any]] = []
    output_lines = [f"--- 测试 {cls.__name__} ---"]
    metadata: dict[str, Any] = {}

    is_no_arg, _ = is_no_arg_constructible(cls)
    if is_no_arg:
        env = cls()
        output_lines.append("✓ 创建成功")
        checks.append(
            {
                "name": "instantiation",
                "passed": True,
                "message": "cls() 实例化成功",
                "details": {},
            }
        )
    else:
        env = None
        output_lines.append("✗ 无法无参创建")
        checks.append(
            {
                "name": "instantiation",
                "passed": False,
                "message": "cls() 无法无参实例化",
                "details": {},
            }
        )

    try:
        description = cls.description()
        metadata["description_length"] = len(description)
        output_lines.append(f"✓ description() 返回 {len(description)} 字符")
        checks.append(
            {
                "name": "description",
                "passed": bool(description),
                "message": "description() 可调用",
                "details": {"length": len(description)},
            }
        )
    except Exception as exc:
        output_lines.append(f"✗ description() 调用失败: {exc}")
        checks.append(
            {
                "name": "description",
                "passed": False,
                "message": f"description() 调用失败: {exc}",
                "details": {},
            }
        )

    try:
        init_description = cls.init_description()
        metadata["init_description_length"] = len(init_description)
        output_lines.append(f"✓ init_description() 返回 {len(init_description)} 字符")
        checks.append(
            {
                "name": "init_description",
                "passed": bool(init_description),
                "message": "init_description() 可调用",
                "details": {"length": len(init_description)},
            }
        )
    except Exception as exc:
        output_lines.append(f"✗ init_description() 调用失败: {exc}")
        checks.append(
            {
                "name": "init_description",
                "passed": False,
                "message": f"init_description() 调用失败: {exc}",
                "details": {},
            }
        )

    tool_names = get_registered_tool_names(cls)
    metadata["tool_names"] = tool_names
    metadata["tool_count"] = len(tool_names)
    output_lines.append(f"✓ 已注册 {len(tool_names)} 个工具")
    checks.append(
        {
            "name": "registered_tools",
            "passed": len(tool_names) > 0,
            "message": f"已注册 {len(tool_names)} 个工具" if tool_names else "未注册任何工具",
            "details": {"tool_names": tool_names},
        }
    )

    from agentsociety2.env.base import EnvBase

    has_step = overrides_base_method(cls, EnvBase, "step")
    metadata["has_step"] = has_step
    checks.append(
        {
            "name": "step",
            "passed": has_step,
            "message": "step() 方法已覆写" if has_step else "step() 方法未覆写 EnvBase.step",
            "details": {},
        }
    )
    output_lines.append("✓ step() 方法已覆写" if has_step else "✗ step() 方法未覆写 EnvBase.step")

    try:
        from agentsociety2.env.router_codegen import CodeGenRouter

        if env is None:
            raise RuntimeError("env instance not available")
        CodeGenRouter(env_modules=[env])
        metadata["router_tool_manager"] = True
        output_lines.append("✓ router smoke test 成功")
        checks.append(
            {
                "name": "router_smoke",
                "passed": True,
                "message": "CodeGenRouter 可正常挂载该环境",
                "details": {},
            }
        )
    except Exception as exc:
        metadata["router_tool_manager"] = False
        output_lines.append(f"✗ router smoke test 失败: {exc}")
        checks.append(
            {
                "name": "router_smoke",
                "passed": False,
                "message": f"router smoke test 失败: {exc}",
                "details": {},
            }
        )

    success = all(check["passed"] for check in checks)
    return success, {
        "module_kind": "env_module",
        "name": cls.__name__,
        "success": success,
        "output": "\n".join(output_lines),
        "error": None,
        "checks": checks,
        "metadata": metadata,
    }


def refresh_env_metadata(
    workspace_path: Path,
    *,
    module_path: str,
    file_path: Path,
    cls: type[Any],
) -> str:
    """Write local env metadata for the generated module."""

    metadata_path = (
        workspace_path / ".agentsociety" / "env_modules" / f"{cls.__name__.lower()}.json"
    )
    try:
        description = cls.description()
    except Exception:
        description = f"{cls.__name__}: {cls.__doc__ or 'No description available'}"
    try:
        init_description = cls.init_description()
    except Exception:
        init_description = ""
    write_json(
        metadata_path,
        {
            "type": cls.__name__,
            "class_name": cls.__name__,
            "description": description,
            "init_description": init_description,
            "is_custom": True,
            "module_path": module_path,
            "file_path": str(file_path),
        },
    )
    return str(metadata_path.relative_to(workspace_path))


def build_validation_summary(
    *,
    module_path: str,
    class_name: str,
    diagnostic: dict[str, Any],
    test_report: dict[str, Any],
    registry_validation: dict[str, Any],
    success: bool,
) -> str:
    """Build a human-readable validation summary."""

    lines = [
        f"# Validation Summary: {class_name}",
        "",
        f"- Module path: `{module_path}`",
        f"- Scanner accepted: `{diagnostic['accepted']}`",
        f"- Tester success: `{test_report['success']}`",
        f"- Registry visible: `{registry_validation['visible_in_registry']}`",
        f"- Overall success: `{success}`",
        "",
        "## Scanner Diagnostics",
        f"- {diagnostic['class_name']}: {'accepted' if diagnostic['accepted'] else 'rejected'}",
    ]
    for issue in diagnostic["issues"]:
        lines.append(f"  - [{issue['severity']}] {issue['message']}")

    lines.append("")
    lines.append("## Tester Checks")
    lines.append(f"- {test_report['name']}: {'passed' if test_report['success'] else 'failed'}")
    lines.append("")
    lines.append("## Registry")
    lines.append(f"- {registry_validation['message']}")
    if registry_validation["metadata_file"]:
        lines.append(f"- Metadata file: `{registry_validation['metadata_file']}`")
    return "\n".join(lines)


def validate_module(
    workspace_path: Path,
    *,
    run_id: str,
    module_path: str,
    class_name: str | None = None,
    refresh_metadata: bool = True,
) -> dict[str, Any]:
    """Validate one env module and persist the report."""

    normalized_module_path = normalize_module_path(workspace_path, module_path)
    cls, file_path = load_env_class(workspace_path, normalized_module_path, class_name)

    diagnostic = build_scan_diagnostic(normalized_module_path, file_path, cls)
    test_success, test_report = build_test_report(cls)

    from agentsociety2.registry import get_registry

    registry = get_registry()
    registry.clear_custom_modules()
    cls._is_custom = True
    registry.register_env_module(cls.__name__, cls, is_custom=True)
    visible_in_registry = registry.get_env_module(cls.__name__) is not None
    metadata_file = None
    metadata_refreshed = False
    if refresh_metadata:
        metadata_file = refresh_env_metadata(
            workspace_path,
            module_path=normalized_module_path,
            file_path=file_path,
            cls=cls,
        )
        metadata_refreshed = True

    registry_validation = {
        "registered": visible_in_registry,
        "visible_in_registry": visible_in_registry,
        "metadata_refreshed": metadata_refreshed,
        "metadata_file": metadata_file,
        "message": (
            f"{cls.__name__} 已注册并可见"
            if visible_in_registry
            else f"{cls.__name__} 未出现在 registry"
        ),
    }

    errors: list[str] = []
    if not diagnostic["accepted"]:
        errors.append("scanner 兼容检查未通过")
    if not test_success:
        errors.append("tester 运行检查未通过")
    if not visible_in_registry:
        errors.append("registry 可见性检查未通过")

    success = diagnostic["accepted"] and test_success and visible_in_registry
    summary = build_validation_summary(
        module_path=normalized_module_path,
        class_name=cls.__name__,
        diagnostic=diagnostic,
        test_report=test_report,
        registry_validation=registry_validation,
        success=success,
    )
    report = {
        "success": success,
        "workspace_path": str(workspace_path.resolve()),
        "module_path": normalized_module_path,
        "class_name": cls.__name__,
        "scanner_diagnostics": [diagnostic],
        "test_reports": [test_report],
        "registry": registry_validation,
        "errors": errors,
        "summary": summary,
    }

    report_path = run_dir(workspace_path, run_id) / "validation_report.json"
    summary_path = run_dir(workspace_path, run_id) / "validation_summary.md"
    write_json(report_path, report)
    write_markdown(summary_path, summary)

    existing_run_state = read_json(run_dir(workspace_path, run_id) / "run_state.json")
    existing_artifacts = (
        existing_run_state.get("artifacts", {})
        if isinstance(existing_run_state, dict)
        and isinstance(existing_run_state.get("artifacts", {}), dict)
        else {}
    )
    run_state = {
        "run_id": run_id,
        "workspace_path": str(workspace_path.resolve()),
        "status": "completed" if success else "failed",
        "stage": "completed" if success else "failed",
        "created_at": (
            existing_run_state.get("created_at")
            if isinstance(existing_run_state, dict)
            else None
        ) or now_iso(),
        "updated_at": now_iso(),
        "request": (
            existing_run_state.get("request")
            if isinstance(existing_run_state, dict)
            and isinstance(existing_run_state.get("request"), dict)
            else build_request_payload(f"validate {normalized_module_path}")
        ),
        "module_path": normalized_module_path,
        "class_name": cls.__name__,
        "last_error": None if success else "; ".join(errors),
        "artifacts": {
            **existing_artifacts,
            "validation_report": str(report_path.relative_to(workspace_path)),
            "validation_summary": str(summary_path.relative_to(workspace_path)),
        },
    }
    write_json(run_dir(workspace_path, run_id) / "run_state.json", run_state)
    append_log(workspace_path, run_id, f"validation finished: success={success}")
    return report


def main() -> int:
    """Validate a module and print the result."""

    args = parse_args()
    workspace_path = Path(args.workspace).resolve()
    setup_sys_path(workspace_path)

    run_id, _ = create_validation_run(
        workspace_path,
        user_request=f"validate {args.file}",
        run_id=args.run_id,
    )
    try:
        report = validate_module(
            workspace_path,
            run_id=run_id,
            module_path=args.file,
            class_name=args.class_name,
            refresh_metadata=not args.no_refresh_metadata,
        )
    except Exception as exc:
        mark_run_failed(
            workspace_path,
            run_id=run_id,
            user_request=f"validate {args.file}",
            error=str(exc),
            module_path=args.file,
        )
        print(f"Validation failed: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(report["summary"])
        if report["errors"]:
            print("")
            print("Errors:")
            for error in report["errors"]:
                print(f"- {error}")

    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
