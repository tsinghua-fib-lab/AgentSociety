"""技能入口的轻量上下文，不依赖模型配置或仿真运行时。"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SkillScriptContext:
    """每次调用传给进程内 skill ``entrypoint`` 的上下文。

    取代 subprocess 路径依赖的进程级环境变量(``AGENT_WORK_DIR`` 等),
    使 50 个 agent 能在进程内并行运行各自的 hook,而不会在
    ``os.environ`` / ``cwd`` / ``sys.stdout`` 上竞争。

    :param workspace_root: 本 agent 的 workspace 根目录(原 ``AGENT_WORK_DIR``)。
    :param skill_dir: skill 包根目录(原 ``SKILL_DIR``)。
    :param skill_id: registry skill id(原 ``SKILL_ID``)。
    :param skill_name: 显示名(原 ``SKILL_NAME``)。
    :param env: subprocess 路径原本会设置的环境变量字典快照。
    """

    workspace_root: Path
    skill_dir: Path
    skill_id: str
    skill_name: str
    env: dict[str, str] = field(default_factory=dict)
