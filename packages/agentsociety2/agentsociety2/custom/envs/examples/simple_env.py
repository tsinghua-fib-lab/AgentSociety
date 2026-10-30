"""
简单环境模块示例

展示如何创建一个基础的环境模块。
"""

from datetime import datetime

from pydantic import BaseModel, Field

from agentsociety2.env import EnvBase, tool


class SimpleEnvConfig(BaseModel):
    """简单环境配置"""
    initial_value: int = Field(default=0, description="初始计数值")
    max_value: int = Field(default=100, description="最大值")


class SimpleEnv(EnvBase):
    """
    简单的计数器环境

    这是一个基础的环境模块示例，提供简单的计数器功能。
    """

    def __init__(self, config: SimpleEnvConfig | dict = None):
        super().__init__()
        if config is None:
            config = SimpleEnvConfig()
        elif isinstance(config, dict):
            config = SimpleEnvConfig(**config)
        self._config = config
        self._counter = config.initial_value

    @classmethod
    def description(cls) -> str:
        """返回环境模块短说明。"""
        return "简单计数器环境，提供计数观察和增减操作。"

    @classmethod
    def init_description(cls) -> str:
        """
        返回环境模块初始化参数说明
        """
        return """SimpleEnv: 简单的计数器环境示例

这是一个基础的环境模块，提供简单的计数器功能。

**配置参数:**
- initial_value (int): 初始计数值，默认 0
- max_value (int): 最大值，默认 100

**可用工具:**
- get_counter(agent_id): 获取当前计数值（观察）
- increment(agent_id, amount): 增加计数（操作）
- decrement(agent_id, amount): 减少计数（操作）
- reset_counter(agent_id): 重置计数（操作）

**初始化配置示例:**
```json
{
  "initial_value": 0,
  "max_value": 100
}
```
"""

    @tool(readonly=True, kind="observe")
    async def get_counter(self, agent_id: int) -> dict:
        """
        获取当前计数值

        :param agent_id: Agent ID

        :returns: 包含当前计数值的字典
        """
        return {
            "counter": self._counter,
            "max_value": self._config.max_value,
            "agent_id": agent_id
        }

    @tool(readonly=False)
    async def increment(self, agent_id: int, amount: int = 1) -> dict:
        """
        增加计数值

        :param agent_id: Agent ID
        :param amount: 增加的数量，默认 1

        :returns: 操作结果
        """
        old_value = self._counter
        self._counter = min(self._counter + amount, self._config.max_value)

        return {
            "agent_id": agent_id,
            "old_value": old_value,
            "new_value": self._counter,
            "amount_added": self._counter - old_value,
            "success": True
        }

    @tool(readonly=False)
    async def decrement(self, agent_id: int, amount: int = 1) -> dict:
        """
        减少计数值

        :param agent_id: Agent ID
        :param amount: 减少的数量，默认 1

        :returns: 操作结果
        """
        old_value = self._counter
        self._counter = max(self._counter - amount, 0)

        return {
            "agent_id": agent_id,
            "old_value": old_value,
            "new_value": self._counter,
            "amount_subtracted": old_value - self._counter,
            "success": True
        }

    @tool(readonly=False)
    async def reset_counter(self, agent_id: int) -> dict:
        """
        重置计数值为初始值

        :param agent_id: Agent ID

        :returns: 操作结果
        """
        old_value = self._counter
        self._counter = self._config.initial_value

        return {
            "agent_id": agent_id,
            "old_value": old_value,
            "new_value": self._counter,
            "success": True
        }

    async def step(self, tick: int, t: datetime):
        """
        环境步骤

        :param tick: 时间刻度
        :param t: 当前时间
        """
        self.t = t
        # 可以在这里添加定期事件
        # 例如：每段时间自动增加一些计数
