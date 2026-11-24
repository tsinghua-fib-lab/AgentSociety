#!/usr/bin/env python3
"""实验配置生成脚本

提供实验配置的验证、准备、信息查询、运行和检查功能。

Usage:
    $PYTHON_PATH .agentsociety/bin/ags.py experiment-config validate --hypothesis-id 1 --experiment-id 1
    $PYTHON_PATH .agentsociety/bin/ags.py experiment-config prepare --hypothesis-id 1 --experiment-id 1
    $PYTHON_PATH .agentsociety/bin/ags.py experiment-config info --hypothesis-id 1 --experiment-id 1
    $PYTHON_PATH .agentsociety/bin/ags.py experiment-config run --hypothesis-id 1 --experiment-id 1
    $PYTHON_PATH .agentsociety/bin/ags.py experiment-config check --hypothesis-id 1 --experiment-id 1
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any


def _workspace_root() -> Path:
    """解析工作区根目录（优先 AGENTSOCIETY_WORKSPACE）。"""
    raw = os.environ.get("AGENTSOCIETY_WORKSPACE")
    if raw:
        return Path(raw).expanduser().resolve()
    # 向上查找工作区标记（.env / .agentsociety），不依赖固定目录深度。
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".env").exists() or (candidate / ".agentsociety").exists():
            return candidate
    return here.parents[4]


workspace_root = _workspace_root()
env_file = workspace_root / ".env"
if env_file.exists():
    from dotenv import load_dotenv

    load_dotenv(env_file, override=True)

sys.path.insert(0, str(workspace_root / "packages" / "agentsociety2"))

get_registered_env_modules: Any = None
get_registered_agent_modules: Any = None
get_agent_module_class: Any = None
resolve_env_module_key: Any = None
get_registry: Any = None
split_agent_kwargs: Any = None
InitConfig: Any = None
StepsConfig: Any = None
_AGENTSOCIETY2_LOADED = False


def _ensure_agentsociety2() -> None:
    """按需导入 agentsociety2，保证未安装时仍能解析 --help。"""
    global _AGENTSOCIETY2_LOADED
    if _AGENTSOCIETY2_LOADED:
        return
    try:
        from agentsociety2.registry import (
            get_agent_module_class,
            get_registered_env_modules,
            get_registered_agent_modules,
            get_registry,
            resolve_env_module_key,
        )
        from agentsociety2.skills.experiment.models import split_agent_kwargs
        from agentsociety2.society.models import InitConfig, StepsConfig
    except ImportError as exc:
        raise SystemExit(
            "agentsociety2 is not available in the current Python interpreter. "
            "Install it (e.g. `uv sync` from the workspace root) and retry. "
            f"Original error: {exc}"
        )
    globals().update({
        "get_registered_env_modules": get_registered_env_modules,
        "get_registered_agent_modules": get_registered_agent_modules,
        "get_agent_module_class": get_agent_module_class,
        "resolve_env_module_key": resolve_env_module_key,
        "get_registry": get_registry,
        "split_agent_kwargs": split_agent_kwargs,
        "InitConfig": InitConfig,
        "StepsConfig": StepsConfig,
    })
    _AGENTSOCIETY2_LOADED = True


def _safe_segment(value: str, label: str) -> str:
    """Validate an id used as one path segment."""
    text = str(value)
    if not text or text in {".", ".."} or "/" in text or "\\" in text or "\0" in text:
        raise ValueError(f"Invalid {label}: {value!r}")
    return text


def get_experiment_paths(
    workspace_path: Path, hypothesis_id: str, experiment_id: str
) -> dict[str, Path]:
    """获取实验相关路径"""
    hypothesis_id = _safe_segment(hypothesis_id, "hypothesis_id")
    experiment_id = _safe_segment(experiment_id, "experiment_id")
    hyp_dir = workspace_path / f"hypothesis_{hypothesis_id}"
    exp_dir = hyp_dir / f"experiment_{experiment_id}"
    init_dir = exp_dir / "init"

    return {
        "workspace": workspace_path,
        "hypothesis": hyp_dir,
        "experiment": exp_dir,
        "init": init_dir,
        "hypothesis_md": hyp_dir / "HYPOTHESIS.md",
        "experiment_md": exp_dir / "EXPERIMENT.md",
        "sim_settings": hyp_dir / "SIM_SETTINGS.json",
        "config_params": init_dir / "config_params.py",
        "init_config": init_dir / "init_config.json",
        "steps_yaml": init_dir / "steps.yaml",
        "validation_report": init_dir / "validation_report.json",
        "user_data": workspace_path / "user_data",
    }


def read_sim_settings(hyp_dir: Path) -> dict[str, Any]:
    """读取 SIM_SETTINGS.json"""
    sim_settings_file = hyp_dir / "SIM_SETTINGS.json"
    if sim_settings_file.exists():
        try:
            return json.loads(sim_settings_file.read_text(encoding="utf-8"))
        except Exception as e:
            print(f"解析 SIM_SETTINGS.json 失败: {e}", file=sys.stderr)
    return {}


def action_validate(
    workspace_path: Path, hypothesis_id: str, experiment_id: str
) -> dict[str, Any]:
    """验证实验设置"""
    result = {
        "success": True,
        "errors": [],
        "warnings": [],
        "info": {},
    }

    paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id)

    # 检查假设目录
    if not paths["hypothesis"].exists():
        result["success"] = False
        result["errors"].append(f"假设目录不存在: {paths['hypothesis']}")
        return result

    # 检查实验目录
    if not paths["experiment"].exists():
        result["success"] = False
        result["errors"].append(f"实验目录不存在: {paths['experiment']}")
        return result

    # 检查 SIM_SETTINGS.json
    sim_settings = read_sim_settings(paths["hypothesis"])
    if not sim_settings:
        result["success"] = False
        result["errors"].append("SIM_SETTINGS.json 不存在或为空")
        return result

    agent_classes = sim_settings.get("agentClasses", [])
    env_modules = sim_settings.get("envModules", [])

    result["info"]["agent_classes"] = agent_classes
    result["info"]["env_modules"] = env_modules

    if not agent_classes:
        result["success"] = False
        result["errors"].append("SIM_SETTINGS.json 中未选择 agent 类型")
    if not env_modules:
        result["success"] = False
        result["errors"].append("SIM_SETTINGS.json 中未选择环境模块")

    # 验证模块在注册表中存在
    available_agents = dict(get_registered_agent_modules())
    available_envs = dict(get_registered_env_modules())

    for agent_type in agent_classes:
        if agent_type not in available_agents:
            result["warnings"].append(
                f"Agent 类型 '{agent_type}' 未在注册表中找到。"
                f"可用类型: {list(available_agents.keys())}"
            )

    for env_type in env_modules:
        if env_type not in available_envs:
            result["warnings"].append(
                f"环境模块 '{env_type}' 未在注册表中找到。"
                f"可用类型: {list(available_envs.keys())}"
            )

    # 检查 user_data 目录
    user_data_dir = paths["user_data"]
    if user_data_dir.exists():
        data_files = list(user_data_dir.iterdir())
        result["info"]["user_data_files"] = [f.name for f in data_files if f.is_file()]
    else:
        result["warnings"].append("user_data/ 目录不存在")

    return result


def action_prepare(
    workspace_path: Path, hypothesis_id: str, experiment_id: str
) -> dict[str, Any]:
    """准备 init/ 目录"""
    paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id)

    # 创建 init 目录
    paths["init"].mkdir(parents=True, exist_ok=True)

    # 创建示例 config_params.py 模板
    if not paths["config_params"].exists():
        sim_settings = read_sim_settings(paths["hypothesis"])
        agent_classes = sim_settings.get("agentClasses", ["person_agent"])
        env_modules = sim_settings.get("envModules", ["simple_social_space"])

        template = f'''"""配置参数生成脚本

此脚本由 Claude Code 生成，用于生成实验配置文件。
运行后将生成 init_config.json 和 steps.yaml。
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

# 输出目录：从 init/ 向上查找工作区标记，默认 <workspace>/hypothesis_N/experiment_N/init
script_dir = Path(__file__).parent
workspace_root = script_dir.parents[3]
for _candidate in (script_dir, *script_dir.parents):
    if (_candidate / ".agentsociety").exists() or (_candidate / ".env").exists():
        workspace_root = _candidate
        break
user_data_dir = workspace_root / "user_data"

# ============================================
# 1. 读取 SIM_SETTINGS.json 确定的模块类型
# ============================================
AGENT_TYPES = {agent_classes}
ENV_MODULE_TYPES = {env_modules}

# ============================================
# 2. 读取 user_data/ 中的额外数据（如果存在）
# ============================================
# TODO: 从 user_data/ 读取数据文件
# 例如:
# profiles = []
# if (user_data_dir / "profiles.csv").exists():
#     import csv
#     with open(user_data_dir / "profiles.csv") as f:
#         reader = csv.DictReader(f)
#         profiles = list(reader)

# ============================================
# 3. 生成 init_config.json
# ============================================

config = {{
    "env_modules": [
        {{
            "module_type": "{env_modules[0] if env_modules else 'SimpleSocialSpace'}",
            "kwargs": {{
                # TODO: 根据模块要求添加参数
                # 使用 scan_modules skill 查看所需参数:
                # $PYTHON_PATH .agentsociety/bin/ags.py scan-modules info --type env --name SimpleSocialSpace
            }}
        }}
    ],
    "agents": [
        {{
            "agent_id": i + 1,
            "agent_type": "{agent_classes[0] if agent_classes else 'person_agent'}",
            "kwargs": {{
                "id": i + 1,
                "profile": {{
                    # TODO: 设置 agent profile
                    "name": f"Agent {{i + 1}}",
                }}
            }}
        }}
        for i in range(10)  # TODO: 设置 agent 数量
    ]
}}

# 保存 init_config.json
init_config_file = script_dir / "init_config.json"
init_config_file.write_text(json.dumps(config, ensure_ascii=False, indent=2))
print(f"✓ 已生成 init_config.json")

# ============================================
# 4. 生成 steps.yaml
# ============================================

start_time = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

steps_config = {{
    "start_t": start_time.isoformat(),
    "steps": [
        # TODO: 根据实验需求配置步骤
        # 支持的步骤类型:
        # - run: 运行仿真
        # - ask: 对当前状态提问
        # - intervene: 施加干预
        # - questionnaire: 向 agent 发放结构化问卷
        {{"type": "run", "num_steps": 100, "tick": 1}},
        # 示例问卷步骤（按需启用/修改）:
        # {{
        #     "type": "questionnaire",
        #     "questionnaire_id": "post_run_survey",
        #     "title": "Post-run survey",
        #     "description": "Collect agent feedback after the simulation",
        #     "target_agent_ids": [1, 2, 3],  # 可选；为空则发给全部 agents
        #     "questions": [
        #         {{
        #             "id": "mood",
        #             "prompt": "How do you feel about the outcome?",
        #             "response_type": "choice",
        #             "choices": ["positive", "neutral", "negative"],
        #         }},
        #         {{
        #             "id": "reason",
        #             "prompt": "Please explain your answer briefly.",
        #             "response_type": "text",
        #         }},
        #     ],
        # }},
    ]
}}

# 保存 steps.yaml
try:
    import yaml
    steps_file = script_dir / "steps.yaml"
    steps_file.write_text(yaml.dump(steps_config, allow_unicode=True, default_flow_style=False))
    print(f"✓ 已生成 steps.yaml")
except ImportError:
    # 如果没有 yaml 模块，手动写入
    steps_file = script_dir / "steps.yaml"
    with open(steps_file, "w") as f:
        f.write(f"start_t: {{steps_config['start_t']}}\\n")
        f.write("steps:\\n")
        for step in steps_config["steps"]:
            f.write(f"  - type: {{step['type']}}\\n")
            if step['type'] == 'run':
                f.write(f"    num_steps: {{step['num_steps']}}\\n")
                f.write(f"    tick: {{step['tick']}}\\n")
            elif step['type'] == 'ask':
                f.write(f"    question: {{json.dumps(step['question'], ensure_ascii=False)}}\\n")
            elif step['type'] == 'intervene':
                f.write(f"    instruction: {{json.dumps(step['instruction'], ensure_ascii=False)}}\\n")
            elif step['type'] == 'questionnaire':
                f.write(f"    questionnaire_id: {{json.dumps(step['questionnaire_id'], ensure_ascii=False)}}\\n")
                if step.get('title') is not None:
                    f.write(f"    title: {{json.dumps(step['title'], ensure_ascii=False)}}\\n")
                if step.get('description') is not None:
                    f.write(f"    description: {{json.dumps(step['description'], ensure_ascii=False)}}\\n")
                if step.get('target_agent_ids') is not None:
                    f.write(f"    target_agent_ids: {{json.dumps(step['target_agent_ids'], ensure_ascii=False)}}\\n")
                f.write("    questions:\\n")
                for question in step['questions']:
                    f.write(f"      - id: {{json.dumps(question['id'], ensure_ascii=False)}}\\n")
                    f.write(f"        prompt: {{json.dumps(question['prompt'], ensure_ascii=False)}}\\n")
                    f.write(
                        f"        response_type: "
                        f"{{json.dumps(question.get('response_type', 'text'), ensure_ascii=False)}}\\n"
                    )
                    if question.get('choices'):
                        f.write(
                            f"        choices: "
                            f"{{json.dumps(question['choices'], ensure_ascii=False)}}\\n"
                        )
    print(f"✓ 已生成 steps.yaml")

print("\\n配置文件生成完成！")
print(f"- init_config.json: {{init_config_file}}")
print(f"- steps.yaml: {{steps_file}}")
'''

        paths["config_params"].write_text(template, encoding="utf-8")

    return {
        "success": True,
        "message": "已创建 init/ 目录",
        "config_params": str(paths["config_params"]),
        "init_config": str(paths["init_config"]),
        "steps_yaml": str(paths["steps_yaml"]),
    }


def action_info(
    workspace_path: Path, hypothesis_id: str, experiment_id: str
) -> dict[str, Any]:
    """显示选中模块的信息"""
    paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id)

    sim_settings = read_sim_settings(paths["hypothesis"])
    agent_classes = sim_settings.get("agentClasses", [])
    env_modules = sim_settings.get("envModules", [])

    result = {
        "agent_classes": [],
        "env_modules": [],
    }

    # 获取 agent 信息
    agent_type_map = dict(get_registered_agent_modules())
    for agent_type in agent_classes:
        if agent_type in agent_type_map:
            agent_class = agent_type_map[agent_type]
            info = {
                "type": agent_type,
                "class": agent_class.__name__,
                "description": getattr(agent_class, "description", lambda: "N/A")(),
                "init_description": getattr(
                    agent_class, "init_description", lambda: "N/A"
                )(),
            }
            # 新 API：__init__ 是无参的；真正的初始化参数在 init_description() 里
            # 文档化（profile 字段 + config 键）。这里展示标准 config 键集合 + init_description。
            info["parameters"] = [
                {"name": "id", "type": "int", "purpose": "unique agent id (in kwargs/profile)"},
                {"name": "name", "type": "str", "purpose": "display name (in kwargs/profile)"},
                {"name": "max_react_turns", "type": "int", "default": "10",
                 "purpose": "runtime config key (split into config record by CLI)"},
                {"name": "enable_memory", "type": "bool", "default": "True",
                 "purpose": "runtime config key (PersonAgent)"},
                {"name": "enable_todo_list", "type": "bool", "default": "True",
                 "purpose": "runtime config key"},
            ]
            info["construction_note"] = (
                "New API: agents are created via AgentBase.create(workspace_path, profile, config) "
                "and reconstructed via from_workspace(...). __init__ is arg-less; the CLI splits "
                "agent kwargs into profile (id + persona) + config (runtime keys). See "
                "references/config-structure.md."
            )
            result["agent_classes"].append(info)

    # 获取 env 模块信息
    env_type_map = dict(get_registered_env_modules())
    for env_type in env_modules:
        if env_type in env_type_map:
            env_class = env_type_map[env_type]
            info = {
                "type": env_type,
                "class": env_class.__name__,
                "description": getattr(env_class, "description", lambda: "N/A")(),
                "init_description": getattr(
                    env_class, "init_description", lambda: "N/A"
                )(),
            }
            # 尝试获取参数信息
            try:
                import inspect
                sig = inspect.signature(env_class.__init__)
                params = []
                for name, param in list(sig.parameters.items())[1:]:  # 跳过 self
                    param_info = {"name": name}
                    if param.annotation != inspect.Parameter.empty:
                        param_info["type"] = str(param.annotation)
                    if param.default != inspect.Parameter.empty:
                        param_info["default"] = str(param.default)
                    params.append(param_info)
                info["parameters"] = params
            except Exception:
                pass
            result["env_modules"].append(info)

    return result


def _has_unresolved_placeholders(path: Path) -> bool:
    """检查 ``config_params.py`` 是否仍保留模板占位。

    :param path: 脚本路径。
    :returns: 仍包含 ``# TODO:`` 占位时返回 True。
    """
    try:
        return "# TODO:" in path.read_text(encoding="utf-8")
    except OSError:
        return False


def action_run(
    workspace_path: Path, hypothesis_id: str, experiment_id: str
) -> dict[str, Any]:
    """运行 config_params.py 生成配置文件"""
    paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id)

    if not paths["config_params"].exists():
        return {
            "success": False,
            "error": f"config_params.py 不存在: {paths['config_params']}",
        }
    if _has_unresolved_placeholders(paths["config_params"]):
        return {
            "success": False,
            "error": (
                "config_params.py 仍包含模板 TODO 占位，拒绝生成占位实验。"
                "请先按研究设计填写参数。"
            ),
        }

    try:
        # 运行 config_params.py
        result = subprocess.run(
            [sys.executable, str(paths["config_params"])],
            capture_output=True,
            text=True,
            cwd=str(paths["init"]),
        )

        output = result.stdout
        if result.stderr:
            output += "\n" + result.stderr

        # 检查输出文件
        init_config_exists = paths["init_config"].exists()
        steps_yaml_exists = paths["steps_yaml"].exists()

        return {
            "success": result.returncode == 0 and init_config_exists and steps_yaml_exists,
            "returncode": result.returncode,
            "output": output,
            "init_config_exists": init_config_exists,
            "steps_yaml_exists": steps_yaml_exists,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
        }


def action_check(
    workspace_path: Path, hypothesis_id: str, experiment_id: str
) -> dict[str, Any]:
    """验证生成的配置文件"""
    paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id)

    result = {
        "success": True,
        "errors": [],
        "warnings": [],
        "details": {},
    }

    # 检查 init_config.json
    if not paths["init_config"].exists():
        result["success"] = False
        result["errors"].append(f"init_config.json 不存在: {paths['init_config']}")
        return result

    # 检查 steps.yaml
    if not paths["steps_yaml"].exists():
        result["success"] = False
        result["errors"].append(f"steps.yaml 不存在: {paths['steps_yaml']}")
        return result

    # 检查 config_params.py 是否仍是模板
    if paths["config_params"].exists() and _has_unresolved_placeholders(
        paths["config_params"]
    ):
        result["success"] = False
        result["errors"].append(
            "config_params.py 仍包含模板 TODO 占位；请先填写实验参数再运行。"
        )

    # 验证 init_config.json 格式
    try:
        config_data = json.loads(paths["init_config"].read_text(encoding="utf-8"))
        init_config = InitConfig.model_validate(config_data)
        result["details"]["init_config"] = {
            "env_modules_count": len(init_config.env_modules),
            "agents_count": len(init_config.agents),
            "env_module_types": [m.module_type for m in init_config.env_modules],
            "agent_types": list(set(a.agent_type for a in init_config.agents)),
        }
    except Exception as e:
        result["success"] = False
        result["errors"].append(f"init_config.json 验证失败: {e}")
        return result

    # 验证 steps.yaml 格式
    try:
        import yaml
        steps_data = yaml.safe_load(paths["steps_yaml"].read_text(encoding="utf-8"))
        steps_config = StepsConfig.model_validate(steps_data)
        result["details"]["steps_config"] = {
            "start_t": steps_config.start_t,
            "steps_count": len(steps_config.steps),
            "step_types": [s.type for s in steps_config.steps],
        }
    except Exception as e:
        result["success"] = False
        result["errors"].append(f"steps.yaml 验证失败: {e}")
        return result

    # 尝试实例化模块（严格验证）
    env_type_map = dict(get_registered_env_modules())
    agent_type_map = dict(get_registered_agent_modules())

    # 验证环境模块
    for module_config in init_config.env_modules:
        module_type = module_config.module_type
        canonical_key = resolve_env_module_key(module_type)
        if canonical_key is None:
            result["errors"].append(
                f"环境模块类型 '{module_type}' 未注册。"
                f"可用: {list(env_type_map.keys())}"
            )
            result["success"] = False
            continue

        env_class = env_type_map[canonical_key]
        try:
            _ = env_class(**module_config.kwargs)
            result["details"][f"env_{module_type}"] = "实例化成功"
        except Exception as e:
            result["errors"].append(f"环境模块 '{module_type}' 实例化失败: {e}")
            result["success"] = False

    # 验证 agent（抽样验证第一个）—— 使用新的 workspace 契约
    if init_config.agents:
        agent_config = init_config.agents[0]
        agent_type = agent_config.agent_type
        agent_class = get_agent_module_class(agent_type)
        if agent_class is None:
            result["errors"].append(
                f"Agent 类型 '{agent_type}' 未注册。可用: {list(agent_type_map.keys())}"
            )
            result["success"] = False
        else:
            try:
                profile, agent_config_dict = split_agent_kwargs(
                    agent_config.agent_id, agent_config.kwargs
                )
                # 验证 AgentBase 契约：arg-less __init__ + create 可写入 workspace。
                import tempfile
                # 新契约 __init__ 无参；真正的状态在 restore() 里设置。
                _ = agent_class()
                with tempfile.TemporaryDirectory() as tmp_ws:
                    agent_class.create(Path(tmp_ws), profile, agent_config_dict)
                result["details"][f"agent_{agent_type}"] = "create() 写入 workspace 成功"
            except Exception as e:
                result["errors"].append(f"Agent '{agent_type}' create() 失败: {e}")
                result["success"] = False

    return result


def main():
    parser = argparse.ArgumentParser(
        description="实验配置生成和验证工具"
    )
    parser.add_argument("--workspace", default=".", help="工作空间路径")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")

    subparsers = parser.add_subparsers(dest="command", help="子命令")
    subparsers.required = True

    # 通用参数
    common_parser = argparse.ArgumentParser(add_help=False)
    common_parser.add_argument("--hypothesis-id", required=True, help="假设 ID")
    common_parser.add_argument("--experiment-id", required=True, help="实验 ID")

    # validate 子命令
    subparsers.add_parser(
        "validate",
        parents=[common_parser],
        help="验证实验设置和模块选择",
        description="检查 SIM_SETTINGS.json 和实验目录结构，验证模块是否已注册"
    )

    # prepare 子命令
    subparsers.add_parser(
        "prepare",
        parents=[common_parser],
        help="创建 init/ 目录结构",
        description="创建 init/ 目录并生成 config_params.py 模板"
    )

    # info 子命令
    subparsers.add_parser(
        "info",
        parents=[common_parser],
        help="显示选中模块的信息",
        description="显示 SIM_SETTINGS.json 中选中的 agent 和环境模块的详细信息"
    )

    # run 子命令
    subparsers.add_parser(
        "run",
        parents=[common_parser],
        help="运行 config_params.py 生成配置",
        description="执行 config_params.py 生成 init_config.json 和 steps.yaml"
    )

    # check 子命令
    subparsers.add_parser(
        "check",
        parents=[common_parser],
        help="验证生成的配置文件",
        description="验证 init_config.json 和 steps.yaml 的格式和内容"
    )

    args = parser.parse_args()
    _ensure_agentsociety2()
    workspace_path = Path(args.workspace).resolve()

    action_map = {
        "validate": action_validate,
        "prepare": action_prepare,
        "info": action_info,
        "run": action_run,
        "check": action_check,
    }

    action_func = action_map[args.command]
    result = action_func(workspace_path, args.hypothesis_id, args.experiment_id)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("success") else 1
    else:
        if args.command == "validate":
            if result["success"]:
                print("✓ 验证通过")
                print(f"  Agent 类型: {result['info'].get('agent_classes', [])}")
                print(f"  环境模块: {result['info'].get('env_modules', [])}")
                user_files = result['info'].get('user_data_files', [])
                if user_files:
                    print(f"  user_data/ 文件: {user_files}")
                if result["warnings"]:
                    print("\n⚠ 警告:")
                    for w in result["warnings"]:
                        print(f"  - {w}")
            else:
                print("✗ 验证失败")
                for e in result["errors"]:
                    print(f"  ✗ {e}")
                return 1

        elif args.command == "prepare":
            print(result["message"])
            print(f"  config_params.py: {result['config_params']}")

        elif args.command == "info":
            print("Agent 类型:")
            for a in result["agent_classes"]:
                print(f"  - {a['type']} ({a['class']})")
                print(f"    {a['description']}")
                if "parameters" in a:
                    print("    参数:")
                    for p in a["parameters"]:
                        default = f" = {p['default']}" if "default" in p else ""
                        print(f"      - {p['name']}: {p.get('type', 'Any')}{default}")
            print("\n环境模块:")
            for m in result["env_modules"]:
                print(f"  - {m['type']} ({m['class']})")
                print(f"    {m['description']}")
                if "parameters" in m:
                    print("    参数:")
                    for p in m["parameters"]:
                        default = f" = {p['default']}" if "default" in p else ""
                        print(f"      - {p['name']}: {p.get('type', 'Any')}{default}")

        elif args.command == "run":
            if result["success"]:
                print("✓ 配置生成成功")
                if result.get("output"):
                    print(result["output"])
            else:
                print("✗ 配置生成失败")
                if result.get("error"):
                    print(f"  错误: {result['error']}")
                elif result.get("output"):
                    print(result["output"])
                return 1

        elif args.command == "check":
            if result["success"]:
                print("✓ 配置验证通过")
                details = result.get("details", {})
                if "init_config" in details:
                    ic = details["init_config"]
                    print(f"  环境模块: {ic['env_modules_count']} ({', '.join(ic['env_module_types'])})")
                    print(f"  Agents: {ic['agents_count']} ({', '.join(ic['agent_types'])})")
                if "steps_config" in details:
                    sc = details["steps_config"]
                    print(f"  开始时间: {sc['start_t']}")
                    print(f"  步骤数: {sc['steps_count']}")
                for k, v in details.items():
                    if k not in ["init_config", "steps_config"]:
                        print(f"  {k}: {v}")
            else:
                print("✗ 配置验证失败")
                for e in result["errors"]:
                    print(f"  ✗ {e}")
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
