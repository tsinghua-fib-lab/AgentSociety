#!/usr/bin/env python3
"""Validate an Agent class implementation against the current AgentBase contract.

Checks that an Agent file:
- subclasses ``AgentBase`` (or ``PersonAgent``) directly (AST rule),
- implements the three required abstracts: ``to_workspace``, ``ask``, ``step`` (async),
- does not use unsupported legacy lifecycle, state, prompt, or LLM-role APIs,
- imports and is not abstract at runtime.

Usage:
    $PYTHON_PATH .agentsociety/bin/ags.py create-agent --file custom/agents/my_agent.py
    $PYTHON_PATH .agentsociety/bin/ags.py create-agent --file custom/agents/my_agent.py --json
"""

from __future__ import annotations

import argparse
import ast
import importlib.util
import inspect
import json
import sys
from pathlib import Path
from typing import Any


# Required abstract methods on AgentBase subclasses.
REQUIRED_METHODS = ["to_workspace", "ask", "step"]

# Public override hooks / utilities the skill recognizes (informational only).
OPTIONAL_METHODS = [
    "restore",
    "create",
    "from_workspace",
    "build_react_messages",
    "build_agent_json",
    "dispatch_react_tool",
    "description",
    "init_description",
    "close",
]

# Subclass either one directly (PersonAgent subclasses AgentBase).
ALLOWED_DIRECT_BASES = frozenset({"AgentBase", "PersonAgent"})


def _base_names_from_expr(expr: ast.expr) -> set[str]:
    names: set[str] = set()
    if isinstance(expr, ast.Name):
        names.add(expr.id)
    elif isinstance(expr, ast.Attribute):
        names.add(expr.attr)
    elif isinstance(expr, ast.Subscript):
        names |= _base_names_from_expr(expr.value)
    return names


def _class_direct_agent_bases(class_def: ast.ClassDef) -> set[str]:
    out: set[str] = set()
    for base in class_def.bases:
        out |= _base_names_from_expr(base)
    return out & ALLOWED_DIRECT_BASES


def _method_names_in_class(class_def: ast.ClassDef) -> dict[str, ast.AsyncFunctionDef | ast.FunctionDef]:
    methods: dict[str, ast.AsyncFunctionDef | ast.FunctionDef] = {}
    for node in class_def.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            methods[node.name] = node
    return methods


def _audit_constructor_contract(class_def: ast.ClassDef) -> list[str]:
    """Detect constructor signatures that do not match the current contract."""
    out: list[str] = []
    methods = _method_names_in_class(class_def)
    # __init__ must be arg-less (only self).
    init = methods.get("__init__")
    if init is not None:
        params = [a for a in init.args.args if a.arg != "self"]
        # Allow variadic/keyword args but flag positional params beyond self.
        extra_positional = [
            a.arg for a in params if a.arg not in {"kwargs", "args"}
        ]
        if extra_positional:
            out.append(
                f"__init__ at line {init.lineno} takes positional args "
                f"{extra_positional}. AgentBase.__init__ is arg-less. "
                "Put state setup in restore()."
            )
    return out


def _audit_ask_env_calls(tree: ast.AST) -> list[str]:
    """Detect `ask_env(..., readonly=False, ..., template_mode=True)` (Pitfall P3).

    Stateful writes that engage the template cache (keyed on instruction-text
    similarity + variable names, NOT tool name) and can collide silently across
    writes. See references/pitfalls.md P3.
    """
    warnings_out: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "ask_env"):
            continue
        kw = {k.arg: k.value for k in node.keywords if k.arg}
        readonly_val = kw.get("readonly")
        template_val = kw.get("template_mode")
        if (
            isinstance(readonly_val, ast.Constant)
            and readonly_val.value is False
            and isinstance(template_val, ast.Constant)
            and template_val.value is True
        ):
            warnings_out.append(
                f"ask_env at line {node.lineno}: readonly=False with template_mode=True. "
                "This pattern caches a closure keyed on instruction-text similarity + "
                "argument names (NOT tool name) and can silently collide between writes. "
                "Default to template_mode=False for writes. See references/pitfalls.md P3."
            )
    return warnings_out


def validate_file(file_path: Path) -> dict[str, Any]:
    """Validate an Agent Python file.

    Returns a dict with:
    - valid: bool
    - errors: list of error messages
    - warnings: list of warning messages
    - class_name: str or None
    - has_init_description: bool
    - methods: list of method names found
    """
    result: dict[str, Any] = {
        "valid": True,
        "errors": [],
        "warnings": [],
        "class_name": None,
        "has_init_description": False,
        "methods": [],
    }

    if not file_path.exists():
        result["valid"] = False
        result["errors"].append(f"File not found: {file_path}")
        return result

    if file_path.suffix != ".py":
        result["valid"] = False
        result["errors"].append(f"Not a Python file: {file_path}")
        return result

    if "examples" in file_path.parts:
        result["warnings"].append(
            "File is in 'examples' directory and will not be scanned for registration. "
            "Move it to custom/agents/ directly."
        )

    try:
        source = file_path.read_text(encoding="utf-8")
        tree = ast.parse(source)
    except SyntaxError as e:
        result["valid"] = False
        result["errors"].append(f"Syntax error: {e}")
        return result

    # Find classes that directly extend AgentBase or PersonAgent.
    agent_classes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and _class_direct_agent_bases(node)
    ]

    if not agent_classes:
        result["valid"] = False
        result["errors"].append(
            "No class inheriting from AgentBase or PersonAgent found "
            "(AST only recognizes direct bases named AgentBase or PersonAgent; "
            "if you use an alias, ensure the module imports and MRO still includes AgentBase)"
        )
        return result

    if len(agent_classes) > 1:
        result["warnings"].append(
            f"Multiple AgentBase subclasses found: {[c.name for c in agent_classes]}. "
            "Only the first will be validated."
        )

    agent_class = agent_classes[0]
    result["class_name"] = agent_class.name

    methods = _method_names_in_class(agent_class)
    result["methods"] = list(methods.keys())

    # Required abstract methods.
    for method in REQUIRED_METHODS:
        node = methods.get(method)
        if node is None:
            result["valid"] = False
            result["errors"].append(f"Missing required method: {method}")
        elif not isinstance(node, ast.AsyncFunctionDef):
            result["valid"] = False
            result["errors"].append(f"Method '{method}' should be async")

    # Constructor contract audit.
    for issue in _audit_constructor_contract(agent_class):
        result["valid"] = False
        result["errors"].append(issue)

    # description / init_description
    if "description" not in methods:
        result["warnings"].append(
            "No description() method. Agent will use AgentBase generic short description."
        )
    if "init_description" in methods:
        result["has_init_description"] = True
    else:
        result["warnings"].append(
            "No init_description() method. Agent will use generic initialization guidance."
        )

    # If the class reuses run_react_loop, build_react_messages must be overridden.
    uses_react_loop = "run_react_loop" in source and "run_react_loop" in methods or _calls_self_attr(tree, "run_react_loop")
    if uses_react_loop and "build_react_messages" not in methods:
        result["warnings"].append(
            "Class calls self.run_react_loop(...) but does not override build_react_messages. "
            "The base implementation raises NotImplementedError — override it to provide "
            "ReAct prompt messages."
        )

    # Pitfall P3 audit (warnings).
    for warn in _audit_ask_env_calls(tree):
        result["warnings"].append(warn)

    # Import + abstractness check.
    try:
        module_name = f"validate_module_{id(file_path)}"
        spec = importlib.util.spec_from_file_location(module_name, file_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            for name, obj in inspect.getmembers(module, inspect.isclass):
                if obj.__module__ == module_name and hasattr(obj, "__mro__"):
                    mro_names = [c.__name__ for c in obj.__mro__]
                    if "AgentBase" in mro_names and obj.__name__ == agent_class.name:
                        if inspect.isabstract(obj):
                            result["valid"] = False
                            result["errors"].append(
                                f"Class '{obj.__name__}' is abstract. "
                                "Implement to_workspace / ask / step."
                            )
                        break

            del sys.modules[module_name]
    except Exception as e:
        result["valid"] = False
        result["errors"].append(f"Could not import module: {e}")

    return result


def _calls_self_attr(tree: ast.AST, attr_name: str) -> bool:
    """Return True if the AST contains a `self.<attr_name>(...)` call."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == attr_name
            and isinstance(func.value, ast.Name)
            and func.value.id == "self"
        ):
            return True
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Agent implementation")
    parser.add_argument(
        "--file", "-f", type=str, required=True, help="Path to the Agent Python file"
    )
    parser.add_argument("--json", action="store_true", help="Output result as JSON")
    args = parser.parse_args()

    file_path = Path(args.file)
    result = validate_file(file_path)

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"\n{'='*60}")
        print(f"Validation: {file_path}")
        print(f"{'='*60}")

        if result["class_name"]:
            print(f"\nClass: {result['class_name']}")

        if result["errors"]:
            print(f"\nErrors ({len(result['errors'])}):")
            for err in result["errors"]:
                print(f"  ✗ {err}")

        if result["warnings"]:
            print(f"\nWarnings ({len(result['warnings'])}):")
            for warn in result["warnings"]:
                print(f"  ⚠ {warn}")

        if result["valid"]:
            print("\n✓ Agent validation passed!")
            print("\nNext steps:")
            print("  1. Run VSCode command 'Scan Custom Modules'")
            print("  2. Run VSCode command 'Test Custom Modules'")
        else:
            print("\n✗ Validation failed. Fix the errors above.")

        print()

    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
