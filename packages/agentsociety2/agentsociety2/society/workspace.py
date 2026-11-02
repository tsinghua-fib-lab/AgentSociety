"""工作区管理 CLI - 用于初始化和管理 AgentSociety2 工作区

提供以下功能：
1. 初始化自定义模块模板 (custom/)
2. 创建用户数据目录 (user_data/)
3. 创建文献目录结构 (papers/)
4. 创建 .agentsociety 目录结构和配置文件
5. 下载必要的数据文件（地图等）
6. 生成模块描述 JSON 文件
"""

import argparse
import asyncio
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

import aiohttp

BEIJING_MAP_URL = "https://cloud.tsinghua.edu.cn/f/f5c777485d2748fa8535/?dl=1"


def get_custom_template_path() -> Path:
    """获取自定义模块模板路径"""
    # 从 agentsociety2.custom 包中获取路径
    from agentsociety2.custom import __file__ as custom_init

    return Path(custom_init).parent


def init_custom_modules(target_dir: Path, force: bool = False) -> dict:
    """
    初始化自定义模块目录，复制模板文件

    :param target_dir: 目标工作区根目录
    :param force: 是否强制覆盖已存在的文件

    :returns: 包含操作结果的字典
    """
    result = {
        "success": False,
        "message": "",
        "created": [],
        "skipped": [],
        "errors": [],
    }

    try:
        custom_dir = target_dir / "custom"
        template_path = get_custom_template_path()

        if not template_path.exists():
            result["errors"].append(f"Template path not found: {template_path}")
            result["message"] = f"Template not found at {template_path}"
            return result

        # 创建 custom 目录结构
        (custom_dir / "agents").mkdir(parents=True, exist_ok=True)
        result["created"].append("custom/agents/")

        (custom_dir / "envs").mkdir(parents=True, exist_ok=True)
        result["created"].append("custom/envs/")

        (custom_dir / "skills").mkdir(parents=True, exist_ok=True)
        result["created"].append("custom/skills/")

        # 复制示例文件到 custom/agents/ 和 custom/envs/
        # 这些是直接可用的示例，不是放在 examples 子目录中
        agents_src = template_path / "agents" / "examples"
        if agents_src.exists():
            for py_file in agents_src.glob("*.py"):
                dst = custom_dir / "agents" / py_file.name
                if not dst.exists() or force:
                    shutil.copy2(py_file, dst)
                    result["created"].append(f"custom/agents/{py_file.name}")

        envs_src = template_path / "envs" / "examples"
        if envs_src.exists():
            for py_file in envs_src.glob("*.py"):
                dst = custom_dir / "envs" / py_file.name
                if not dst.exists() or force:
                    shutil.copy2(py_file, dst)
                    result["created"].append(f"custom/envs/{py_file.name}")

        # 复制 skills 示例
        skills_src = template_path / "skills" / "examples"
        if skills_src.exists():
            for skill_dir in skills_src.iterdir():
                if skill_dir.is_dir():
                    dst = custom_dir / "skills" / skill_dir.name
                    if not dst.exists() or force:
                        shutil.copytree(str(skill_dir), str(dst), dirs_exist_ok=True)
                        result["created"].append(f"custom/skills/{skill_dir.name}/")

        # 复制 __init__.py 文件
        init_files = [
            (template_path / "__init__.py", custom_dir / "__init__.py"),
            (
                template_path / "agents" / "__init__.py",
                custom_dir / "agents" / "__init__.py",
            ),
            (
                template_path / "envs" / "__init__.py",
                custom_dir / "envs" / "__init__.py",
            ),
        ]

        for src, dst in init_files:
            if src.exists():
                if not dst.exists() or force:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
                    result["created"].append(str(dst.relative_to(target_dir)))
                else:
                    result["skipped"].append(
                        f"{dst.relative_to(target_dir)} (already exists)"
                    )

        # 创建 custom/README.md（工作区专用版本）
        custom_readme = custom_dir / "README.md"
        if not custom_readme.exists() or force:
            custom_readme_content = """# Custom Modules

本目录用于存放自定义的 Agent 和环境模块。

## 目录结构

- `agents/` - 自定义 Agent 类
- `envs/` - 自定义环境模块
- `skills/` - 自定义 Agent Skills（给 Agent 添加行为能力）

## 开发指南

### 创建自定义 Agent

1. 在 `agents/` 目录下创建新的 `.py` 文件
2. 继承自 `AgentBase`
3. 实现 `init_description()` 类方法
4. 实现 workspace 契约方法：`create()`, `from_workspace()`, `to_workspace()`
5. 实现必需方法：`ask()`, `step()`

```python
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from agentsociety2.agent.base import AgentBase
from agentsociety2.agent.service_proxy import ServiceProxy

class MyAgent(AgentBase):
    @classmethod
    def init_description(cls) -> str:
        return \"\"\"MyAgent: 我的自定义 Agent\"\"\"

    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (workspace_path / "AGENT.json").write_text(
            json.dumps({"id": profile["id"], "profile": profile, "step_count": 0}),
            encoding="utf-8",
        )

    @classmethod
    async def from_workspace(cls, workspace_path: Path, service_proxy: ServiceProxy) -> "MyAgent":
        # 构造契约：__init__ 无参，restore() 才是真正的初始化。
        agent = cls()
        await agent.restore(workspace_path, service_proxy)
        return agent

    async def to_workspace(self, workspace_path: Path) -> None:
        meta = json.loads((workspace_path / "AGENT.json").read_text(encoding="utf-8"))
        meta["step_count"] = self._step_count
        (workspace_path / "AGENT.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def ask(self, message: str, readonly: bool = True) -> str:
        return f"Answer to: {message}"

    async def step(self, tick: int, t: datetime) -> str:
        return f"Step {tick}"
```

### 创建自定义环境模块

1. 在 `envs/` 目录下创建新的 `.py` 文件
2. 继承自 `EnvBase`
3. 使用 `@tool` 装饰器注册工具方法

```python
from agentsociety2.env import EnvBase, tool

class MyEnv(EnvBase):
    @classmethod
    def init_description(cls) -> str:
        return \"\"\"MyEnv: 我的自定义环境\"\"\"

    @tool(readonly=True, kind="observe")
    async def get_state(self, agent_id: int) -> dict:
        return {"agent_id": agent_id}

    @tool(readonly=False)
    async def do_action(self, agent_id: int, action: str) -> dict:
        return {"agent_id": agent_id, "action": action}

    async def step(self, tick: int, t: datetime):
        self.t = t
```

### 创建自定义 Agent Skill

1. 在 `skills/` 目录下创建新目录（如 `my-skill/`）
2. 添加 `SKILL.md`（行为规范，必需）和可选的 `scripts/<skill_name>.py`（subprocess 模式）

```
skills/my-skill/
├── SKILL.md
├── _order.txt          # 可选，定义加载优先级
└── scripts/
    └── my-skill.py     # （可选）subprocess 脚本：--args-json + 写入 AGENT_WORK_DIR
```

```python
# skills/my-skill/scripts/my-skill.py
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--args-json", default="{}")
    ns = parser.parse_args()
    args = json.loads(ns.args_json or "{}")
    result = {"ok": True, "summary": f"MySkill: executed (tick={args.get('tick')})"}
    Path("my_skill_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

### 注册和测试

1. 在 VSCode 中运行"扫描自定义模块"命令
2. 运行"测试自定义模块"验证功能
3. 使用"扫描 Agent Skills"发现新的 skill

## 示例

本目录已包含示例文件：
- `agents/` 目录下有 Agent 示例
- `envs/` 目录下有环境模块示例
- `skills/` 目录用于放置自定义 Agent Skill

这些示例可以直接运行测试，也可以作为开发参考。
"""
            with open(custom_readme, "w", encoding="utf-8") as f:
                f.write(custom_readme_content)
            result["created"].append("custom/README.md")

        result["success"] = True
        result["message"] = f"Custom modules initialized at {custom_dir}"

    except Exception as e:
        result["errors"].append(str(e))
        result["message"] = f"Failed to initialize custom modules: {e}"

    return result


async def download_map_file(target_dir: Path, timeout: int = 300) -> dict:
    """
    下载地图文件到工作区

    :param target_dir: 目标工作区根目录
    :param timeout: 超时时间（秒）

    :returns: 包含操作结果的字典
    """
    result = {"success": False, "message": "", "file_path": "", "errors": []}

    data_dir = target_dir / ".agentsociety" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    map_file_path = data_dir / "beijing_map.pb"

    try:
        async with (
            aiohttp.ClientSession() as session,
            session.get(
                BEIJING_MAP_URL, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response,
        ):
            response.raise_for_status()

            with open(map_file_path, "wb") as f:
                async for chunk in response.content.iter_chunked(8192):
                    f.write(chunk)

        result["success"] = True
        result["message"] = f"Map file downloaded to {map_file_path}"
        result["file_path"] = str(map_file_path.resolve())

    except Exception as e:
        result["errors"].append(str(e))
        result["message"] = f"Failed to download map file: {e}"
        # 即使下载失败，也返回预期的文件路径
        result["file_path"] = str(map_file_path.resolve())

    return result


def create_module_info_files(target_dir: Path) -> dict:
    """
    创建模块描述 JSON 文件到 .agentsociety/ 目录

    :param target_dir: 目标工作区根目录

    :returns: 包含操作结果的字典
    """
    result = {"success": False, "message": "", "created": [], "errors": []}

    try:
        from agentsociety2.registry import (
            discover_and_register_builtin_modules,
            get_registry,
        )

        # 确保内置模块已加载
        registry = get_registry()
        if not registry._builtin_loaded:
            discover_and_register_builtin_modules(registry)

        # 创建目录
        agents_dir = target_dir / ".agentsociety" / "agent_classes"
        env_dir = target_dir / ".agentsociety" / "env_modules"
        agents_dir.mkdir(parents=True, exist_ok=True)
        env_dir.mkdir(parents=True, exist_ok=True)

        # 创建 agent_classes/*.json
        for module_type, agent_class in registry.list_agent_modules():
            try:
                description = agent_class.description()
            except Exception:
                description = agent_class.__doc__ or "No description available"
            try:
                init_description = agent_class.init_description()
            except Exception:
                init_description = ""

            agent_info = {
                "type": module_type,
                "class_name": agent_class.__name__,
                "description": description,
                "init_description": init_description,
                "is_custom": getattr(agent_class, "_is_custom", False),
            }

            with open(agents_dir / f"{module_type}.json", "w", encoding="utf-8") as f:
                json.dump(agent_info, f, ensure_ascii=False, indent=2)
            result["created"].append(f".agentsociety/agent_classes/{module_type}.json")

        # 创建 env_modules/*.json
        for module_type, env_class in registry.list_env_modules():
            try:
                description = env_class.description()
            except Exception:
                description = env_class.__doc__ or "No description available"
            try:
                init_description = env_class.init_description()
            except Exception:
                init_description = ""

            module_info = {
                "type": module_type,
                "class_name": env_class.__name__,
                "description": description,
                "init_description": init_description,
                "is_custom": getattr(env_class, "_is_custom", False),
            }

            with open(env_dir / f"{module_type}.json", "w", encoding="utf-8") as f:
                json.dump(module_info, f, ensure_ascii=False, indent=2)
            result["created"].append(f".agentsociety/env_modules/{module_type}.json")

        result["success"] = True
        result["message"] = "Module info files created"

    except Exception as e:
        result["errors"].append(str(e))
        result["message"] = f"Failed to create module info files: {e}"

    return result


def create_path_md(target_dir: Path) -> dict:
    """
    创建 .agentsociety/path.md 工作区路径记忆文件

    :param target_dir: 目标工作区根目录

    :returns: 包含操作结果的字典
    """
    result = {"success": False, "message": "", "errors": []}

    path_md_content = """# Workspace Path Memory

This file records descriptions of high-value file paths and their meanings to help the Agent run with long-term memory.

## High-Value Files

- `TOPIC.md`: The core research topic and goals for the current simulation experiment. Always read this file first to understand your mission.
- `.agentsociety/agent_classes/*.json`: JSON files containing detailed information about all supported agent classes, including their types and capabilities.
- `.agentsociety/env_modules/*.json`: JSON files containing detailed information about all supported environment modules that can be used to build simulation worlds.
- `.agentsociety/prefill_params.json`: Pre-filled parameters for modules to avoid repetitive input.

## Ignore Files

- `papers/`: The directory for storing literature search results or user-uploaded literature files. You SHOULD NOT read this directory directly, but use the `load_literature` tool to load the literature files.
- `paper/`: The external paper-toolkit workspace directory. It contains deterministic
  paper artifacts such as `paper.json`, section `.tex` files, evidence graph,
  check reports, compile runs, and the compiled deliverable.

## Progressive Context Loading

Instead of using specialized discovery tools, you should:
1. Read `.agentsociety/path.md` to understand the workspace structure.
2. List these directories to see available components.
3. Read specific JSON files as needed to gather detailed information about agent classes or environment modules.

## Custom Modules

- `custom/agents/`: Custom agent classes created by the user.
- `custom/envs/`: Custom environment modules created by the user.
"""

    dot_agentsociety_dir = target_dir / ".agentsociety"
    dot_agentsociety_dir.mkdir(parents=True, exist_ok=True)

    try:
        with open(dot_agentsociety_dir / "path.md", "w", encoding="utf-8") as f:
            f.write(path_md_content)
        result["success"] = True
        result["message"] = "path.md created"
    except Exception as e:
        result["errors"].append(str(e))
        result["message"] = f"Failed to create path.md: {e}"

    return result


def create_prefill_params(target_dir: Path, map_file_path: str) -> dict:
    """
    创建 .agentsociety/prefill_params.json 预填充参数文件

    :param target_dir: 目标工作区根目录
    :param map_file_path: 地图文件路径

    :returns: 包含操作结果的字典
    """
    result = {"success": False, "message": "", "errors": []}

    dot_agentsociety_dir = target_dir / ".agentsociety"
    data_dir = dot_agentsociety_dir / "data"

    prefill_data = {
        "version": "1.0",
        "env_modules": {
            "mobility_space": {
                "file_path": map_file_path,
                "home_dir": str(data_dir.resolve()),
            },
        },
        "agents": {},
    }

    try:
        with open(
            dot_agentsociety_dir / "prefill_params.json", "w", encoding="utf-8"
        ) as f:
            json.dump(prefill_data, f, ensure_ascii=False, indent=2)
        result["success"] = True
        result["message"] = "prefill_params.json created"
    except Exception as e:
        result["errors"].append(str(e))
        result["message"] = f"Failed to create prefill_params.json: {e}"

    return result


async def init_workspace(
    target_dir: Path,
    topic: str = "",
    components: list[str] | None = None,
    force: bool = False,
) -> dict:
    """
    初始化工作区，创建所需的目录结构

    :param target_dir: 目标工作区根目录
    :param topic: 研究主题
    :param components: 要创建的组件列表，可选值: "custom", "user_data", "papers", "agentsociety"
    :param force: 是否强制覆盖已存在的文件

    :returns: 包含操作结果的字典
    """
    if components is None:
        components = ["custom", "user_data", "papers", "agentsociety"]

    result = {
        "success": False,
        "message": "",
        "created": [],
        "skipped": [],
        "errors": [],
    }

    try:
        target_dir.mkdir(parents=True, exist_ok=True)

        # 创建 TOPIC.md
        if topic:
            topic_file = target_dir / "TOPIC.md"
            if not topic_file.exists() or force:
                topic_content = f"""# Research Topic

{topic}

## Description

[Describe your research topic here]

## Hypotheses

[Generated hypotheses will appear here]
"""
                with open(topic_file, "w", encoding="utf-8") as f:
                    f.write(topic_content)
                result["created"].append("TOPIC.md")

        # 创建 user_data 目录
        if "user_data" in components:
            user_data_dir = target_dir / "user_data"
            if not user_data_dir.exists():
                user_data_dir.mkdir(parents=True, exist_ok=True)
                result["created"].append("user_data/")
            else:
                result["skipped"].append("user_data/ (already exists)")

        # 创建 papers 目录
        if "papers" in components:
            papers_dir = target_dir / "papers"
            if not papers_dir.exists():
                papers_dir.mkdir(parents=True, exist_ok=True)

                # 创建 literature_index.json
                index_file = papers_dir / "literature_index.json"
                if not index_file.exists():
                    index_data = {
                        "version": "1.0",
                        "created_at": datetime.now(UTC).isoformat(),
                        "updated_at": datetime.now(UTC).isoformat(),
                        "entries": [],
                    }
                    index_file.write_text(
                        json.dumps(index_data, indent=2, ensure_ascii=False)
                    )
                    result["created"].append("papers/literature_index.json")
            else:
                result["skipped"].append("papers/ (already exists)")

        # 创建 custom 目录
        if "custom" in components:
            custom_result = init_custom_modules(target_dir, force=force)
            result["created"].extend(custom_result["created"])
            result["skipped"].extend(custom_result["skipped"])
            result["errors"].extend(custom_result["errors"])

        # 创建 .agentsociety 目录结构和文件
        if "agentsociety" in components:
            # 创建目录
            (target_dir / ".agentsociety" / "agent_classes").mkdir(
                parents=True, exist_ok=True
            )
            (target_dir / ".agentsociety" / "env_modules").mkdir(
                parents=True, exist_ok=True
            )
            (target_dir / ".agentsociety" / "data").mkdir(parents=True, exist_ok=True)
            (target_dir / ".agentsociety" / "custom_env_skill" / "runs").mkdir(
                parents=True, exist_ok=True
            )

            # 下载地图文件
            download_result = await download_map_file(target_dir)
            if download_result["success"]:
                result["created"].append(".agentsociety/data/beijing_map.pb")
            else:
                result["errors"].append(
                    f"Map download failed: {download_result['message']}"
                )
                # 即使下载失败也继续，创建空的 data 目录记录
                result["skipped"].append(
                    ".agentsociety/data/beijing_map.pb (download failed)"
                )

            map_file_path = download_result["file_path"]

            # 创建模块信息文件
            module_info_result = create_module_info_files(target_dir)
            result["created"].extend(module_info_result["created"])
            result["errors"].extend(module_info_result["errors"])

            # 创建 path.md
            path_md_result = create_path_md(target_dir)
            if path_md_result["success"]:
                result["created"].append(".agentsociety/path.md")
            result["errors"].extend(path_md_result["errors"])

            # 创建 prefill_params.json
            prefill_result = create_prefill_params(target_dir, map_file_path)
            if prefill_result["success"]:
                result["created"].append(".agentsociety/prefill_params.json")
            result["errors"].extend(prefill_result["errors"])

            # 创建过程持久化文件
            progress_file = target_dir / ".agentsociety" / "progress.json"
            if not progress_file.exists():
                progress_data = {
                    "version": "1.3",
                    "workspace": {
                        "topic": topic or "",
                        "created_at": datetime.now(UTC).isoformat(),
                        "current_stage": "literature_search",
                        "current_hypothesis_id": None,
                        "current_experiment_id": None,
                        "revision_round": 0,
                        "active_reroute": None,
                    },
                    "stages": {
                        stage: {
                            "status": "not_started",
                            "started_at": None,
                            "completed_at": None,
                            "attempts": 0,
                            "error": None,
                            "metadata": {},
                            "verification_status": "not_started",
                            "revision_round": 0,
                        }
                        for stage in (
                            "literature_search",
                            "hypothesis",
                            "experiment_config",
                            "run_experiment",
                            "analysis",
                            "generate_paper",
                        )
                    },
                    "hypotheses": {},
                    "transitions": [],
                }
                progress_file.write_text(
                    json.dumps(progress_data, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
                result["created"].append(".agentsociety/progress.json")

            keep_root_files = {"path.md", "prefill_params.json", "progress.json"}
            for existing_file in (target_dir / ".agentsociety").iterdir():
                if not existing_file.is_file():
                    continue
                if existing_file.name in keep_root_files:
                    continue
                if existing_file.suffix not in {".json", ".jsonl"}:
                    continue
                existing_file.unlink()

        if not result["errors"] or any("failed" in e.lower() for e in result["errors"]):
            # 只有没有严重错误时才标记为成功
            result["success"] = True
            result["message"] = f"Workspace initialized at {target_dir}"

    except Exception as e:
        result["errors"].append(str(e))
        result["message"] = f"Failed to initialize workspace: {e}"

    return result


def main():
    """工作区管理 CLI 入口"""
    parser = argparse.ArgumentParser(description="AgentSociety2 Workspace Management")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # init 命令
    init_parser = subparsers.add_parser("init", help="Initialize workspace components")
    init_parser.add_argument(
        "--target-dir",
        type=str,
        default=".",
        help="Target workspace directory (default: current directory)",
    )
    init_parser.add_argument("--topic", type=str, default="", help="Research topic")
    init_parser.add_argument(
        "--components",
        type=str,
        default="custom,user_data,papers,agentsociety",
        help="Components to create: custom, user_data, papers, agentsociety (default: all)",
    )
    init_parser.add_argument(
        "--force", action="store_true", help="Force overwrite existing files"
    )
    init_parser.add_argument(
        "--json", action="store_true", help="Output result as JSON"
    )

    # init-custom 命令
    custom_parser = subparsers.add_parser(
        "init-custom", help="Initialize custom modules only"
    )
    custom_parser.add_argument(
        "--target-dir",
        type=str,
        default=".",
        help="Target workspace directory (default: current directory)",
    )
    custom_parser.add_argument(
        "--force", action="store_true", help="Force overwrite existing files"
    )
    custom_parser.add_argument(
        "--json", action="store_true", help="Output result as JSON"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    target_dir = Path(args.target_dir).resolve()

    if args.command == "init":
        components = [c.strip() for c in args.components.split(",")]
        # 使用 asyncio 运行异步函数
        result = asyncio.run(
            init_workspace(
                target_dir, topic=args.topic, components=components, force=args.force
            )
        )
    elif args.command == "init-custom":
        result = init_custom_modules(target_dir, force=args.force)
    else:
        parser.print_help()
        return

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        if result["success"]:
            print(f"✓ {result['message']}")
            if result["created"]:
                print("\nCreated:")
                for item in result["created"]:
                    print(f"  - {item}")
            if result["skipped"]:
                print("\nSkipped:")
                for item in result["skipped"]:
                    print(f"  - {item}")
        else:
            print(f"✗ {result['message']}", file=__import__("sys").stderr)
            if result["errors"]:
                print("\nErrors:")
                for error in result["errors"]:
                    print(f"  - {error}")
            sys.exit(1)


if __name__ == "__main__":
    main()
