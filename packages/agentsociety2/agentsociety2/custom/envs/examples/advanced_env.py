"""
高级环境模块示例

展示带有资源管理、多 Agent 交互等高级功能的环境模块。
"""

from datetime import datetime

from pydantic import BaseModel, Field

from agentsociety2.env import EnvBase, tool


class AdvancedEnvConfig(BaseModel):
    """高级环境配置"""
    total_resources: int = Field(default=1000, description="总资源量")
    regeneration_rate: float = Field(default=0.1, description="资源再生率")


class AdvancedEnv(EnvBase):
    """
    高级资源管理环境

    展示如何实现带有资源管理、多 Agent 交互的环境。
    """

    def __init__(self, config: AdvancedEnvConfig | dict = None):
        super().__init__()
        if config is None:
            config = AdvancedEnvConfig()
        elif isinstance(config, dict):
            config = AdvancedEnvConfig(**config)
        self._config = config
        self._resources = config.total_resources
        self._agent_contributions: dict[int, float] = {}
        self._agent_consumptions: dict[int, float] = {}

    @classmethod
    def description(cls) -> str:
        """返回环境模块短说明。"""
        return "高级资源管理环境，支持多 Agent 资源消耗、贡献和统计。"

    @classmethod
    def init_description(cls) -> str:
        return """AdvancedEnv: 高级资源管理环境示例

展示带有资源管理、多 Agent 交互的环境模块。

**配置参数:**
- total_resources (int): 总资源量，默认 1000
- regeneration_rate (float): 资源再生率（每步），默认 0.1

**可用工具:**
- get_resources(agent_id): 获取当前资源量（观察）
- consume_resources(agent_id, amount): 消耗资源（操作）
- contribute_resources(agent_id, amount): 贡献资源（操作）
- get_agent_stats(agent_id): 获取 Agent 统计（观察）
- get_leaderboard(): 获取贡献排行榜（观察）

**初始化配置示例:**
```json
{
  "total_resources": 1000,
  "regeneration_rate": 0.1
}
```
"""

    @tool(readonly=True, kind="observe")
    async def get_resources(self, agent_id: int) -> dict:
        """获取当前资源量"""
        return {
            "current_resources": self._resources,
            "total_resources": self._config.total_resources,
            "utilization": f"{self._resources / self._config.total_resources * 100:.1f}%",
            "agent_id": agent_id
        }

    @tool(readonly=True, kind="observe")
    async def get_agent_stats(self, agent_id: int) -> dict:
        """获取 Agent 统计信息"""
        contribution = self._agent_contributions.get(agent_id, 0)
        consumption = self._agent_consumptions.get(agent_id, 0)
        net_contribution = contribution - consumption

        return {
            "agent_id": agent_id,
            "total_contributed": contribution,
            "total_consumed": consumption,
            "net_contribution": net_contribution,
            "status": "贡献者" if net_contribution >= 0 else "消费者"
        }

    @tool(readonly=True, kind="statistics")
    async def get_leaderboard(self) -> dict:
        """获取贡献排行榜"""
        # 计算净贡献
        net_contributions = {}
        for agent_id in set(list(self._agent_contributions.keys()) +
                           list(self._agent_consumptions.keys())):
            contribution = self._agent_contributions.get(agent_id, 0)
            consumption = self._agent_consumptions.get(agent_id, 0)
            net_contributions[agent_id] = contribution - consumption

        # 排序
        sorted_agents = sorted(
            net_contributions.items(),
            key=lambda x: x[1],
            reverse=True
        )

        return {
            "leaderboard": [
                {"agent_id": aid, "net_contribution": contrib}
                for aid, contrib in sorted_agents
            ],
            "total_agents": len(sorted_agents)
        }

    @tool(readonly=False)
    async def consume_resources(self, agent_id: int, amount: float = 10) -> dict:
        """消耗资源"""
        if amount > self._resources:
            return {
                "agent_id": agent_id,
                "success": False,
                "message": f"资源不足，当前: {self._resources:.1f}, 请求: {amount}"
            }

        self._resources -= amount

        # 记录消耗
        if agent_id not in self._agent_consumptions:
            self._agent_consumptions[agent_id] = 0
        self._agent_consumptions[agent_id] += amount

        return {
            "agent_id": agent_id,
            "success": True,
            "amount_consumed": amount,
            "remaining_resources": self._resources
        }

    @tool(readonly=False)
    async def contribute_resources(self, agent_id: int, amount: float = 10) -> dict:
        """贡献资源"""
        self._resources += amount

        # 记录贡献
        if agent_id not in self._agent_contributions:
            self._agent_contributions[agent_id] = 0
        self._agent_contributions[agent_id] += amount

        return {
            "agent_id": agent_id,
            "success": True,
            "amount_contributed": amount,
            "total_resources": self._resources
        }

    async def step(self, tick: int, t: datetime):
        """环境步骤 - 资源再生"""
        self.t = t

        # 资源自然再生
        regeneration = self._config.total_resources * self._config.regeneration_rate
        self._resources = min(
            self._resources + regeneration,
            self._config.total_resources
        )
