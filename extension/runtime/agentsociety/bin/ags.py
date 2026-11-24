#!/usr/bin/env python3
"""Workspace-stable launcher for AgentSociety Claude skills.

This launcher lives under `<workspace>/.agentsociety/bin/ags.py` and dispatches
logical tool names to the synced skill scripts under `<workspace>/.claude/skills/`.
It keeps skill prompts independent from the physical installation layout.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

try:
    from dotenv import dotenv_values
except ModuleNotFoundError:  # pragma: no cover - optional dependency fallback
    dotenv_values = None


TOOL_SCRIPTS = {
    "literature-search": (
        "agentsociety-literature-search",
        "scripts/search.py",
    ),
    "literature-full-text": (
        "agentsociety-literature-search",
        "scripts/full_text.py",
    ),
    "scan-modules": (
        "agentsociety-scan-modules",
        "scripts/scan_modules.py",
    ),
    "hypothesis": (
        "agentsociety-hypothesis",
        "scripts/hypothesis.py",
    ),
    "experiment-config": (
        "agentsociety-experiment-config",
        "scripts/config.py",
    ),
    "run-experiment": (
        "agentsociety-run-experiment",
        "scripts/run.py",
    ),
    "research-pipeline": (
        "agentsociety-research-pipeline",
        "scripts/progress.py",
    ),
    "analysis": (
        "agentsociety-analysis",
        "scripts/analysis.py",
    ),
    "create-agent": (
        "agentsociety-create-agent",
        "scripts/validate.py",
    ),
    "create-env-module-validate": (
        "agentsociety-create-env-module",
        "scripts/validate.py",
    ),
    "create-env-module-resolve-sources": (
        "agentsociety-create-env-module",
        "scripts/resolve_sources.py",
    ),
    "use-dataset": (
        "agentsociety-use-dataset",
        "scripts/use.py",
    ),
    "create-dataset": (
        "agentsociety-create-dataset",
        "scripts/create.py",
    ),
}

ALIASES = {
    "literature_search": "literature-search",
    "literature_full_text": "literature-full-text",
    "scan_modules": "scan-modules",
    "experiment_config": "experiment-config",
    "run_experiment": "run-experiment",
    "research_pipeline": "research-pipeline",
    "create_agent": "create-agent",
    "create_env_module_validate": "create-env-module-validate",
    "create_env_module_resolve_sources": "create-env-module-resolve-sources",
    "use_dataset": "use-dataset",
    "create_dataset": "create-dataset",
}


def _normalize_tool(tool: str) -> str:
    lowered = tool.strip().lower()
    return ALIASES.get(lowered, lowered)


def _extract_workspace_and_passthrough_args(
    tool_args: list[str],
) -> tuple[Path, list[str]]:
    passthrough_args: list[str] = []
    workspace = Path.cwd().resolve()
    skip_next = False

    for index, token in enumerate(tool_args):
        if skip_next:
            skip_next = False
            continue
        if token in {"--workspace", "-w"} and index + 1 < len(tool_args):
            workspace = Path(tool_args[index + 1]).expanduser().resolve()
            skip_next = True
            continue
        if token.startswith("--workspace="):
            workspace = Path(token.split("=", 1)[1]).expanduser().resolve()
            continue
        if token.startswith("-w="):
            workspace = Path(token.split("=", 1)[1]).expanduser().resolve()
            continue
        passthrough_args.append(token)

    return workspace, passthrough_args


def _load_workspace_env(workspace: Path) -> dict[str, str]:
    """构造子进程环境：工作区 ``.env`` 覆盖已有 shell 变量。"""
    env = os.environ.copy()
    env_file = workspace / ".env"
    if dotenv_values is not None and env_file.exists():
        for key, value in dotenv_values(env_file).items():
            if value is not None:
                env[key] = value
    # The selected workspace also anchors backend path resolution.
    env["AGENTSOCIETY_WORKSPACE"] = str(workspace)
    env["WORKSPACE_PATH"] = str(workspace)
    return env


def _resolve_script(workspace: Path, tool: str) -> Path:
    skill_dir, relative_script = TOOL_SCRIPTS[tool]
    return workspace / ".claude" / "skills" / skill_dir / relative_script


def _available_tools_text() -> str:
    """返回可供 help/epilog 使用的工具清单。"""

    lines = ["Available tools:"]
    lines.extend(f"  - {name}" for name in sorted(TOOL_SCRIPTS))
    return "\n".join(lines)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Workspace-stable launcher for AgentSociety Claude skills.",
        epilog=_available_tools_text(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "tool",
        nargs="?",
        help="Logical tool name, e.g. run-experiment, research-pipeline, analysis",
    )
    parser.add_argument(
        "tool_args",
        nargs=argparse.REMAINDER,
        help="Arguments passed through to the selected tool script",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.tool:
        parser.print_help()
        return 0

    tool = _normalize_tool(args.tool)
    if tool not in TOOL_SCRIPTS:
        print(f"Unknown tool: {args.tool}", file=sys.stderr)
        print(_available_tools_text(), file=sys.stderr)
        return 2

    workspace, passthrough_args = _extract_workspace_and_passthrough_args(
        list(args.tool_args)
    )
    script_path = _resolve_script(workspace, tool)

    if not script_path.exists():
        print(
            "Skill script not found. Expected:\n"
            f"  {script_path}\n"
            "Resync the extension-bundled skills into the workspace `.claude/skills/` directory.",
            file=sys.stderr,
        )
        return 2

    env = _load_workspace_env(workspace)
    command = [sys.executable, str(script_path), *passthrough_args]

    result = subprocess.run(command, cwd=str(workspace), env=env, check=False)
    return int(result.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
