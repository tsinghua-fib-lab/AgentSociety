#!/usr/bin/env python3
"""扫描和查询 AgentSociety2 工作区中的 agent 和 env 类

提供对已注册 agent 类和环境模块的扫描和查询功能。

Usage:
    $PYTHON_PATH .agentsociety/bin/ags.py scan-modules list [--type agent|env] [--custom-only]
    $PYTHON_PATH .agentsociety/bin/ags.py scan-modules info --type agent|env --name NAME
    $PYTHON_PATH .agentsociety/bin/ags.py scan-modules search --keyword KEYWORD
    $PYTHON_PATH .agentsociety/bin/ags.py scan-modules export --output modules.json
    $PYTHON_PATH .agentsociety/bin/ags.py scan-modules validate --type agent|env --name NAME
"""

from __future__ import annotations

import argparse
import importlib
import importlib.util
import inspect
import json
import sys
from pathlib import Path
from typing import Any, List, Optional, Tuple, Type


def setup_workspace(workspace_path: Path) -> Path:
    """设置工作区路径并验证

    Note: agentsociety2 是一个 Python 包，通过 import 使用，
    不需要在文件系统中查找。
    """
    workspace_path = workspace_path.resolve()

    # 添加工作区路径到 sys.path（用于加载自定义模块）
    if str(workspace_path) not in sys.path:
        sys.path.insert(0, str(workspace_path))

    return workspace_path


def load_env_file(workspace_path: Path) -> None:
    """加载工作区 ``.env``（覆盖已有 shell 值）。"""
    env_file = workspace_path / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(env_file, override=True)
        except ImportError:
            pass


def get_registry_and_modules(workspace_path: Path) -> Tuple[Any, List[Tuple], List[Tuple]]:
    """获取注册表和所有模块"""
    from agentsociety2.registry.base import get_registry
    from agentsociety2.registry.modules import (
        scan_and_register_custom_modules,
        discover_and_register_builtin_modules,
    )

    registry = get_registry()
    registry.set_workspace(workspace_path)

    # 加载内置模块
    discover_and_register_builtin_modules(registry)

    # 扫描并注册自定义模块
    try:
        scan_and_register_custom_modules(workspace_path, registry)
    except Exception as e:
        print(f"Warning: Failed to scan custom modules: {e}", file=sys.stderr)

    agents = registry.list_agent_modules()
    env_modules = registry.list_env_modules()

    return registry, agents, env_modules


def get_prefill_params(workspace_path: Path) -> dict:
    """从 .agentsociety/prefill_params.json 加载预填充参数"""
    prefill_file = workspace_path / ".agentsociety" / "prefill_params.json"
    if not prefill_file.exists():
        return {"version": "1.0", "env_modules": {}, "agents": {}}

    try:
        return json.loads(prefill_file.read_text(encoding="utf-8"))
    except Exception:
        return {"version": "1.0", "env_modules": {}, "agents": {}}


def get_module_info(
    module_class: Type,
    module_type: str,
    prefill_data: dict
) -> dict:
    """获取模块详细信息"""
    info = {
        "type": module_type,
        "class_name": module_class.__name__,
        "is_custom": getattr(module_class, "_is_custom", False),
    }

    # 获取描述
    try:
        if hasattr(module_class, "description"):
            info["description"] = module_class.description()
        else:
            info["description"] = module_class.__doc__ or f"{module_class.__name__}"
    except Exception:
        info["description"] = f"{module_class.__name__}"
    try:
        info["init_description"] = module_class.init_description()
    except Exception:
        info["init_description"] = ""

    # 获取文件位置
    try:
        module = importlib.import_module(module_class.__module__)
        info["file"] = getattr(module, "__file__", "Unknown")
        info["import_path"] = f"{module_class.__module__}.{module_class.__name__}"
    except Exception:
        info["file"] = "Unknown"
        info["import_path"] = module_class.__name__

    # 获取构造函数参数
    try:
        sig = inspect.signature(module_class.__init__)
        params = {}
        for name, param in list(sig.parameters.items())[1:]:  # 跳过 'self'
            params[name] = {
                "annotation": str(param.annotation)
                if param.annotation != inspect.Parameter.empty
                else "Any",
                "default": str(param.default)
                if param.default != inspect.Parameter.empty
                else None,
                "required": param.default == inspect.Parameter.empty,
            }
        info["parameters"] = params
    except Exception as e:
        info["parameters"] = {}
        info["parameter_error"] = str(e)

    # 检查是否有预填充参数
    prefill_key = module_type
    if prefill_key in prefill_data.get("env_modules", {}) or \
       prefill_key in prefill_data.get("agents", {}):
        env_prefill = prefill_data.get("env_modules", {}).get(prefill_key, {})
        agent_prefill = prefill_data.get("agents", {}).get(prefill_key, {})
        info["prefill_params"] = env_prefill or agent_prefill or None
        info["has_prefill"] = bool(info["prefill_params"])
    else:
        info["has_prefill"] = False

    return info


def format_module_list(
    agents: List[Tuple],
    env_modules: List[Tuple],
    prefill_data: dict,
    show_type: Optional[str] = None,
    custom_only: bool = False,
    detail_level: str = "medium"  # short, medium, full
) -> str:
    """格式化模块列表输出

    Args:
        agents: Agent 列表
        env_modules: 环境模块列表
        prefill_data: 预填充参数数据
        show_type: 显示类型过滤 (agent/env/None)
        custom_only: 仅显示自定义模块
        detail_level: 详细程度 (short/medium/full)
    """
    lines = []

    def _format_desc(desc: str, level: str) -> str:
        """根据详细程度格式化描述"""
        if level == "short":
            # 只显示第一行，截断到30字符
            first_line = desc.split('\n')[0] if desc else ""
            return first_line[:30] + "..." if len(first_line) > 30 else first_line
        elif level == "medium":
            # 截断到80字符
            return desc[:80] + "..." if len(desc) > 80 else desc
        else:  # full
            # 显示完整描述
            return desc

    # 处理 agents
    if show_type is None or show_type == "agent":
        filtered_agents = agents
        if custom_only:
            filtered_agents = [(t, c) for t, c in agents if getattr(c, "_is_custom", False)]

        if filtered_agents:
            agent_count = len(agents)
            custom_count = sum(1 for _, c in agents if getattr(c, "_is_custom", False))
            title = f"Available Agents ({agent_count}"
            if custom_count > 0:
                title += f", {custom_count} custom"
            title += ")"
            lines.append(title)
            lines.append("")

            for agent_type, agent_class in filtered_agents:
                try:
                    desc = getattr(agent_class, "description", lambda: "N/A")()
                except Exception:
                    desc = "N/A"

                desc_formatted = _format_desc(desc, detail_level)

                is_custom = " [CUSTOM]" if getattr(agent_class, "_is_custom", False) else ""
                has_prefill = " [PREFILL]" if prefill_data.get("agents", {}).get(agent_type) else ""

                if detail_level == "short":
                    lines.append(f"  - {agent_type}{is_custom}{has_prefill}")
                else:
                    lines.append(f"  - {agent_type}{is_custom}{has_prefill}: {desc_formatted}")

            if show_type is None:
                lines.append("")

    # 处理 env modules
    if show_type is None or show_type == "env":
        filtered_envs = env_modules
        if custom_only:
            filtered_envs = [(t, c) for t, c in env_modules if getattr(c, "_is_custom", False)]

        if filtered_envs:
            env_count = len(env_modules)
            custom_count = sum(1 for _, c in env_modules if getattr(c, "_is_custom", False))
            title = f"Available Environment Modules ({env_count}"
            if custom_count > 0:
                title += f", {custom_count} custom"
            title += ")"
            lines.append(title)
            lines.append("")

            for env_type, env_class in filtered_envs:
                try:
                    desc = getattr(env_class, "description", lambda: "N/A")()
                except Exception:
                    desc = "N/A"

                desc_formatted = _format_desc(desc, detail_level)

                is_custom = " [CUSTOM]" if getattr(env_class, "_is_custom", False) else ""
                has_prefill = " [PREFILL]" if prefill_data.get("env_modules", {}).get(env_type) else ""

                if detail_level == "short":
                    lines.append(f"  - {env_type}{is_custom}{has_prefill}")
                else:
                    lines.append(f"  - {env_type}{is_custom}{has_prefill}: {desc_formatted}")

    return "\n".join(lines)


def format_module_info(module_class: Type, module_type: str, prefill_data: dict) -> str:
    """格式化单个模块详细信息"""
    info = get_module_info(module_class, module_type, prefill_data)

    lines = [
        f"Module: {info['class_name']}",
        f"Type: {info['type']}",
        f"Class: {info['class_name']}",
        f"Description: {info['description']}",
        f"Location: {info.get('file', 'Unknown')}",
        f"Import: {info.get('import_path', info['class_name'])}",
    ]

    if info.get("is_custom"):
        lines.append("(Custom Module)")

    lines.append("")

    if "parameters" in info and info["parameters"]:
        lines.append("Parameters:")
        for name, param_info in info["parameters"].items():
            default = f" = {param_info['default']}" if param_info['default'] else ""
            required = " [REQUIRED]" if param_info.get('required') else ""
            lines.append(f"  - {name}: {param_info['annotation']}{default}{required}")
    else:
        lines.append("Parameters: None")

    if info.get("prefill_params"):
        lines.append("")
        lines.append("Prefill Parameters:")
        lines.append(f"  {json.dumps(info['prefill_params'], indent=2, ensure_ascii=False)}")

    return "\n".join(lines)


def cmd_list(args: argparse.Namespace, workspace_path: Path) -> int:
    """列出所有模块"""
    registry, agents, env_modules = get_registry_and_modules(workspace_path)
    prefill_data = get_prefill_params(workspace_path)

    # 确定详细程度
    detail_level = "medium"
    if args.short:
        detail_level = "short"
    elif args.full:
        detail_level = "full"

    if args.json:
        result = {
            "success": True,
            "detail_level": detail_level,
            "agents": [
                get_module_info(c, t, prefill_data)
                for t, c in agents
                if not args.custom_only or getattr(c, "_is_custom", False)
            ],
            "env_modules": [
                get_module_info(c, t, prefill_data)
                for t, c in env_modules
                if not args.custom_only or getattr(c, "_is_custom", False)
            ],
        }

        if args.type == "agent":
            result = {"success": True, "detail_level": detail_level, "agents": result["agents"]}
        elif args.type == "env":
            result = {"success": True, "detail_level": detail_level, "env_modules": result["env_modules"]}

        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        output = format_module_list(
            agents,
            env_modules,
            prefill_data,
            show_type=args.type,
            custom_only=args.custom_only,
            detail_level=detail_level
        )
        print(output)

    return 0


def cmd_info(args: argparse.Namespace, workspace_path: Path) -> int:
    """显示模块详细信息"""
    registry, agents, env_modules = get_registry_and_modules(workspace_path)
    prefill_data = get_prefill_params(workspace_path)

    # 查找模块
    module_class = None
    module_type = None

    if args.type == "agent":
        for t, c in agents:
            if t == args.name or c.__name__ == args.name:
                module_class = c
                module_type = t
                break
    else:  # env
        for t, c in env_modules:
            if t == args.name or c.__name__ == args.name:
                module_class = c
                module_type = t
                break

    if module_class is None:
        available = [t for t, _ in agents] if args.type == "agent" else [t for t, _ in env_modules]
        print(f"Error: {args.type.capitalize()} '{args.name}' not found.", file=sys.stderr)
        print(f"Available: {', '.join(available)}", file=sys.stderr)
        return 1

    if args.json:
        info = get_module_info(module_class, module_type, prefill_data)
        info["success"] = True
        print(json.dumps(info, indent=2, ensure_ascii=False))
    else:
        print(format_module_info(module_class, module_type, prefill_data))

    return 0


def cmd_search(args: argparse.Namespace, workspace_path: Path) -> int:
    """搜索模块"""
    registry, agents, env_modules = get_registry_and_modules(workspace_path)
    prefill_data = get_prefill_params(workspace_path)

    keyword = args.keyword.lower()
    results = {"agents": [], "env_modules": []}

    # 搜索 agents
    if args.type is None or args.type == "agent":
        for t, c in agents:
            info = get_module_info(c, t, prefill_data)
            if (keyword in t.lower() or
                keyword in c.__name__.lower() or
                keyword in info["description"].lower()):
                results["agents"].append(info)

    # 搜索 env modules
    if args.type is None or args.type == "env":
        for t, c in env_modules:
            info = get_module_info(c, t, prefill_data)
            if (keyword in t.lower() or
                keyword in c.__name__.lower() or
                keyword in info["description"].lower()):
                results["env_modules"].append(info)

    if args.json:
        results["success"] = True
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        if results["agents"]:
            print(f"Matching Agents ({len(results['agents'])}):")
            for info in results["agents"]:
                print(f"  - {info['class_name']}: {info['description'][:60]}...")

        if results["env_modules"]:
            if results["agents"]:
                print()
            print(f"Matching Environment Modules ({len(results['env_modules'])}):")
            for info in results["env_modules"]:
                print(f"  - {info['class_name']}: {info['description'][:60]}...")

        if not results["agents"] and not results["env_modules"]:
            print(f"No matches found for '{args.keyword}'")

    return 0


def cmd_export(args: argparse.Namespace, workspace_path: Path) -> int:
    """导出模块信息到 JSON"""
    registry, agents, env_modules = get_registry_and_modules(workspace_path)
    prefill_data = get_prefill_params(workspace_path)

    result = {
        "version": "1.0",
        "agents": {
            t: get_module_info(c, t, prefill_data)
            for t, c in agents
        },
        "env_modules": {
            t: get_module_info(c, t, prefill_data)
            for t, c in env_modules
        },
        "prefill_params": prefill_data,
    }

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)

    print(f"Exported {len(agents)} agents and {len(env_modules)} env modules to {output_path}")
    return 0


def cmd_validate(args: argparse.Namespace, workspace_path: Path) -> int:
    """验证模块可以导入"""
    registry, agents, env_modules = get_registry_and_modules(workspace_path)

    module_class = None

    if args.type == "agent":
        for t, c in agents:
            if t == args.name or c.__name__ == args.name:
                module_class = c
                break
    else:  # env
        for t, c in env_modules:
            if t == args.name or c.__name__ == args.name:
                module_class = c
                break

    if module_class is None:
        print(f"Error: {args.type.capitalize()} '{args.name}' not found.", file=sys.stderr)
        return 1

    # 验证导入路径
    try:
        module = importlib.import_module(module_class.__module__)
        cls = getattr(module, module_class.__name__)
        print(f"✓ Import path: {module_class.__module__}.{module_class.__name__}")
    except Exception as e:
        print(f"✗ Import failed: {e}", file=sys.stderr)
        return 1

    # 验证构造函数签名
    try:
        sig = inspect.signature(cls.__init__)
        params = list(sig.parameters.keys())[1:]  # 跳过 self
        print(f"✓ Constructor signature: {', '.join(params) if params else 'no parameters'}")
    except Exception as e:
        print(f"✗ Signature check failed: {e}", file=sys.stderr)
        return 1

    # 检查 description / init_description
    try:
        desc = cls.description()
        print(f"✓ description: {desc[:50]}...")
    except Exception:
        print("! description not available")

    try:
        desc = cls.init_description()
        print(f"✓ init_description: {desc[:50]}...")
    except Exception:
        print("! init_description not available")

    print(f"\n✓ {args.type.capitalize()} '{args.name}' is valid")
    return 0


def main():
    workspace_parent = argparse.ArgumentParser(add_help=False)
    workspace_parent.add_argument("--workspace", "-w", default=".", help="工作区路径")
    # Subparsers must not overwrite a top-level --workspace with their default.
    sub_workspace_parent = argparse.ArgumentParser(add_help=False)
    sub_workspace_parent.add_argument(
        "--workspace",
        "-w",
        default=argparse.SUPPRESS,
        help="工作区路径（可放在子命令前或后）",
    )

    parser = argparse.ArgumentParser(
        description="扫描和查询 AgentSociety2 工作区中的 agent 和 env 类",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        parents=[workspace_parent],
    )

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # list 命令
    list_parser = subparsers.add_parser(
        "list", help="列出所有可用模块", parents=[sub_workspace_parent]
    )
    list_parser.add_argument("--type", choices=["agent", "env"], help="过滤类型")
    list_parser.add_argument("--custom-only", action="store_true", help="仅显示自定义模块")
    list_parser.add_argument("--short", "-s", action="store_true",
                            help="简洁模式：仅显示模块名称，不显示描述")
    list_parser.add_argument("--full", "-f", action="store_true",
                            help="完整模式：显示完整描述信息")
    list_parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    # info 命令
    info_parser = subparsers.add_parser(
        "info", help="获取模块详细信息", parents=[sub_workspace_parent]
    )
    info_parser.add_argument("--type", choices=["agent", "env"], required=True,
                             help="模块类型")
    info_parser.add_argument("--name", "-n", required=True, help="模块名称")
    info_parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    # search 命令
    search_parser = subparsers.add_parser(
        "search", help="搜索模块", parents=[sub_workspace_parent]
    )
    search_parser.add_argument("--keyword", "-k", required=True, help="搜索关键词")
    search_parser.add_argument("--type", choices=["agent", "env"], help="过滤类型")
    search_parser.add_argument("--json", action="store_true", help="JSON 格式输出")

    # export 命令
    export_parser = subparsers.add_parser(
        "export", help="导出模块信息到 JSON", parents=[sub_workspace_parent]
    )
    export_parser.add_argument("--output", "-o", required=True, help="输出文件路径")

    # validate 命令
    validate_parser = subparsers.add_parser(
        "validate", help="验证模块可以导入", parents=[sub_workspace_parent]
    )
    validate_parser.add_argument("--type", choices=["agent", "env"], required=True,
                                help="模块类型")
    validate_parser.add_argument("--name", "-n", required=True, help="模块名称")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    # 设置工作区
    workspace_path = setup_workspace(Path(args.workspace))
    load_env_file(workspace_path)

    # 执行命令
    if args.command == "list":
        return cmd_list(args, workspace_path)
    elif args.command == "info":
        return cmd_info(args, workspace_path)
    elif args.command == "search":
        return cmd_search(args, workspace_path)
    elif args.command == "export":
        return cmd_export(args, workspace_path)
    elif args.command == "validate":
        return cmd_validate(args, workspace_path)

    return 0


if __name__ == "__main__":
    sys.exit(main())
