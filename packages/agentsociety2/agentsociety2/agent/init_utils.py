"""PersonAgent 初始化辅助工具（用于测试/脚手架）。

该模块为 `agentsociety2.agent.tests` 提供最小的初始化能力：构造 init_state（workspace seed），
并创建可被 :class:`~agentsociety2.agent.person.PersonAgent` 消费的配置对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agentsociety2.agent.person import PersonAgent


@dataclass
class PersonInitConfig:
    """PersonAgent 初始化配置（workspace seed）。"""

    agent_id: int
    name: str = ""
    profile: dict[str, Any] = field(default_factory=dict)
    force_overwrite: bool = False
    _seed: dict[str, Any] = field(default_factory=dict, repr=False)

    def set_state(self, _: str, rel_path: str, value: Any) -> "PersonInitConfig":
        """写入一个将被 seed 到 workspace 的文件。"""
        self._seed[str(rel_path).strip()] = value
        return self

    def to_init_state(self) -> dict[str, Any]:
        return {
            "init_state_force": bool(self.force_overwrite),
            "workspace_seed": dict(self._seed),
        }


def init_needs_state(*, satiety: float = 0.5, energy: float = 0.5) -> dict[str, Any]:
    """生成 needs.json 的最小结构（用于测试）。

    :param satiety: 饱腹度（0~1）。
    :param energy: 精力（0~1）。
    :returns: needs.json 对象。
    """
    current_need = "satiety" if satiety < energy else "energy"
    return {
        "satiety": float(satiety),
        "energy": float(energy),
        "current_need": current_need,
        "thresholds": {"satiety": 0.3, "energy": 0.3},
        "can_interrupt": True,
    }


def init_personality_state(
    *, extraversion: float = 0.5, neuroticism: float = 0.5
) -> dict[str, Any]:
    """生成 personality.json 的最小结构（用于测试）。

    :param extraversion: 外向性（0~1）。
    :param neuroticism: 神经质（0~1）。
    :returns: personality.json 对象。
    """
    return {
        "traits": {
            "extraversion": float(extraversion),
            "neuroticism": float(neuroticism),
        },
        "personality_description": "test personality",
    }


def init_emotion_state(
    *, primary: str = "Hope", valence: float = 0.0, arousal: float = 0.5
) -> dict[str, Any]:
    """生成 emotion.json 的最小结构（用于测试）。

    :param primary: 主导情绪标签。
    :param valence: 效价（-1~1）。
    :param arousal: 唤醒度（0~1）。
    :returns: emotion.json 对象。
    """
    return {
        "primary": str(primary),
        "valence": float(valence),
        "arousal": float(arousal),
        "mood": {
            "valence": float(valence),
            "arousal": float(arousal),
            "stability": 0.7,
        },
        "intensities": {
            "joy": 3,
            "sadness": 3,
            "fear": 3,
            "disgust": 3,
            "anger": 3,
            "surprise": 3,
        },
    }


def discover_skill_schemas() -> dict[str, list[str]]:
    """返回测试用的“技能输出文件约定”。

    注：真实系统的技能输出由 SKILL.md 定义并由 skill 脚本生成。测试仅需要一个稳定集合
    来验证 workspace seed/目录创建是否正常。
    """
    return {
        "needs": ["needs.json"],
        "personality": ["personality.json"],
        "cognition": ["emotion.json"],
    }


def create_person_agent(config: PersonInitConfig) -> PersonAgent:
    """基于配置创建 PersonAgent（不初始化 env）。"""
    agent = PersonAgent(
        id=int(config.agent_id),
        profile=config.profile,
        name=config.name or None,
        init_state=config.to_init_state(),
    )
    return agent
