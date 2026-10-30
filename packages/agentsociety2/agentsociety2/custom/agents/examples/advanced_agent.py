"""
高级 Agent 示例

展示带有记忆、情绪等高级功能的 Agent（workspace 契约）。
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from agentsociety2.agent.base import AgentBase


class AdvancedAgent(AgentBase):
    """
    高级 Agent 示例

    展示如何添加记忆、情绪等高级功能。
    """

    @classmethod
    def description(cls) -> str:
        """返回 Agent 短说明。"""
        return "带有记忆和情绪状态的高级 Agent 示例。"

    @classmethod
    def init_description(cls) -> str:
        return """AdvancedAgent: 带有记忆和情绪的高级 Agent 示例

展示如何实现带记忆、情绪等高级功能的 Agent（workspace 契约）。

**Profile 字段:**
- name (str): Agent 名称
- personality (str): 个性特征
- occupation (str): 职业

**自定义属性:**
- memories: 记忆列表
- mood: 当前情绪（平静、开心、悲伤等）

**初始化配置示例:**
```json
{
  "id": 0,
  "profile": {
    "name": "李华",
    "personality": "理性、深思熟虑",
    "occupation": "研究员"
  },
  "config": {}
}
```
"""

    # ==================== Workspace 契约 ====================

    @classmethod
    def create(cls, workspace_path: Path, profile: dict, config: dict) -> None:
        """Create the initial agent workspace."""
        workspace_path = Path(workspace_path)
        workspace_path.mkdir(parents=True, exist_ok=True)
        (workspace_path / "config.json").write_text(
            json.dumps(config or {}, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        agent_id = int(profile.get("id", 0))
        name = str(profile.get("name")) if profile.get("name") else f"Agent_{agent_id}"
        (workspace_path / "AGENT.json").write_text(
            json.dumps(
                {
                    "id": agent_id,
                    "name": name,
                    "profile": profile,
                    "step_count": 0,
                    "memories": [],
                    "mood": "平静",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    @classmethod
    async def from_workspace(
        cls, workspace_path: Path, service_proxy: Any
    ) -> "AdvancedAgent":
        """Reconstruct a ready AdvancedAgent from its workspace."""
        agent = cls()
        await agent.restore(workspace_path, service_proxy)
        return agent

    async def restore(self, workspace_path: Path, service_proxy: Any) -> None:
        """Restore agent state from AGENT.json (no super() — example agents
        don't use the skill/workspace runtime that AgentBase.restore binds)."""
        workspace_path = Path(workspace_path)
        meta = json.loads((workspace_path / "AGENT.json").read_text(encoding="utf-8"))
        self._id = int(meta.get("agent_id", meta.get("id", 0)))
        self._profile = meta.get("profile", {"name": meta.get("name")})
        self._name = meta.get("name") or f"Agent_{self._id}"
        self._config = {}
        self._bind_services(service_proxy)
        self._step_count = int(meta.get("step_count", 0))
        # 自定义属性
        self._memories: list[str] = list(meta.get("memories", []))
        self._mood: str = str(meta.get("mood", "平静"))

    async def to_workspace(self, workspace_path: Path) -> None:
        """Write current dynamic state (memories + mood) back to the workspace."""
        workspace_path = Path(workspace_path)
        (workspace_path / "AGENT.json").write_text(
            json.dumps(
                {
                    "id": self._id,
                    "name": self._name,
                    "profile": self.get_profile(),
                    "step_count": self._step_count,
                    "memories": self._memories,
                    "mood": self._mood,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    async def ask(self, message: str, readonly: bool = True) -> str:
        """回答问题，结合记忆和情绪"""
        # 构建包含记忆和情绪的提示词
        memory_text = "\n".join(self._memories[-5:]) if self._memories else "暂无记忆"

        prompt = f"""你是一个真实的人。

**你的资料:**
{self.get_profile()}

**当前情绪:** {self._mood}

**最近的记忆:**
{memory_text}

问题：{message}

请根据你的资料、记忆和当前情绪来回答这个问题。"""

        try:
            response = await self.acompletion([{"role": "user", "content": prompt}])

            answer = response.choices[0].message.content or ""

            # 记录这次交互
            memory = f"Q: {message}\nA: {answer[:100]}..."
            self._memories.append(memory)

            return answer
        except Exception as e:
            return f"抱歉，我无法回答这个问题：{e!s}"

    async def step(self, tick: int, t: datetime) -> str:
        """执行仿真步骤，更新情绪"""
        self._step_count += 1
        try:
            _, observation = await self.ask_env(
                {"variables": {}}, "当前环境状态是什么？", readonly=True
            )
        except Exception:
            observation = "环境正常"

        # 根据观察更新情绪（简单逻辑）
        if "好" in observation or "顺利" in observation:
            self._mood = "开心"
        elif "坏" in observation or "困难" in observation:
            self._mood = "沮丧"
        else:
            self._mood = "平静"

        action = f"Agent {self.name}（情绪：{self._mood}）观察到：{observation}"
        return action
