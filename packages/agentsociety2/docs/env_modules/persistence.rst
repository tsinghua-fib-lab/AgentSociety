环境状态与中断恢复
==================

.. _env-modules-persistence-10:

状态持久化与 resume
-------------------

如果模块带有动态内存态，例如计数器、收件箱或队列，可以实现 workspace 持久化，让仿真在中断后通过
``--resume`` 继续运行（详见 :doc:`/cli`）。基类提供一对可覆盖的钩子，但**不规定状态格式、文件名或目录**。模块可以自行选择布局；通常把状态写到 ``<workspace_root>/state/ENV_STATE.json``。

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - 方法
     - 作用
   * - ``async def to_workspace(self, workspace_path=None)``
     - 把动态状态写入 workspace。society 会在每步结束时通过 router 调用它。建议用
       ``agentsociety2.storage.workspace_state.atomic_write_text`` 原子写。
   * - ``async def restore(self, workspace_path) -> bool``
     - 从 workspace 恢复动态状态，用于 resume 路径。返回值表示是否加载到了快照，供 router 区分
       fresh 和 resume。该方法只会在 ``__init__`` 与 ``init()`` 之后调用，因此可以安全覆盖
       ``init()`` 里的重置。
   * - ``def _bind_workspace(self, workspace_path)``
     - 绑定到 workspace 目录（幂等），创建该目录。由 ``to_workspace``/``restore`` 自动调用。
   * - ``classmethod async def from_workspace(cls, workspace_path, **init_kwargs)``
     - 重建一个可用的模块：先执行 ``cls(**init_kwargs)``，再调用 ``restore``。resume 时，actor
       会从 ``SOCIETY.json`` 读取 ``init_kwargs``。

实现示例（参考 ``SimpleSocialSpace`` / ``EconomySpace`` / ``MobilitySpace``）：

.. testcode:: environment-state

   import json
   import asyncio
   from agentsociety2.env import EnvBase, tool
   from agentsociety2.storage.workspace_state import atomic_write_text

   _STATE_REL = "state/ENV_STATE.json"

   class MyPersistentEnv(EnvBase):
       def __init__(self, capacity: int = 100):
           super().__init__()
           self.capacity = capacity          # 构造配置（在 env_kwargs，不存盘）
           self._resources: dict[int, float] = {}  # 动态态（存盘）
           self._lock = asyncio.Lock()       # 不存盘（由 __init__ 重建）

       @tool(readonly=False)
       def allocate(self, agent_id: int, amount: float) -> str:
           """Allocate resources."""
           self._resources[agent_id] = amount
           return f"Allocated {amount} to agent {agent_id}"

       async def to_workspace(self, workspace_path=None) -> None:
           if workspace_path is not None:
               self._bind_workspace(workspace_path)
           atomic_write_text(
               self._workspace_root / _STATE_REL,
               json.dumps(
                   {"resources": {str(k): v for k, v in self._resources.items()}},
                   ensure_ascii=False,
                   indent=2,
                   default=str,
               ),
           )

       async def restore(self, workspace_path) -> bool:
           self._bind_workspace(workspace_path)
           state_path = self._workspace_root / _STATE_REL
           if not state_path.is_file():
               return False
           d = json.loads(state_path.read_text(encoding="utf-8"))
           self._resources = {int(k): v for k, v in d.get("resources", {}).items()}
           return True

约定：

* JSON 键只能是字符串。``dict[int, ...]`` 应使用 ``str(k)`` 存、``int(k)`` 读，或用
  ``agentsociety2.env.base.dump_int_map``/``load_int_map`` 辅助。
* pydantic 模型用 ``model_dump(mode="json")`` 和 ``model_validate``；datetime 用
  ``isoformat``/``fromisoformat``；``set`` 存 ``sorted(list)``。
* ``asyncio.Lock``、外部子进程、预训练模型权重等不可或不必序列化的对象不存盘，由
  ``__init__``/``init()`` 重建（如 ``MobilitySpace`` 的 routing server、``SocialMediaSpace``
  的推荐器）。
* 持久化与 replay 表（``_agent_state_columns`` 和 ``_env_state_columns``）相互独立。replay 面向分析，是 append-only 的时序数据；workspace 面向恢复，会覆写最新状态。详见 :doc:`/storage`。

验证保存与恢复
--------------

下面的离线检查复用上面的模块，在临时目录保存资源，再构造新实例恢复。断言同时检查整数键是否还原，以及构造配置是否被正确传入。整个过程不调用模型。

.. testcode:: environment-state

   from pathlib import Path
   from tempfile import TemporaryDirectory

   async def check_round_trip():
       with TemporaryDirectory() as directory:
           workspace = Path(directory)
           original = MyPersistentEnv(capacity=20)
           original.allocate(agent_id=7, amount=12.5)
           await original.to_workspace(workspace)
           restored = await MyPersistentEnv.from_workspace(workspace, capacity=20)
           assert restored._resources == {7: 12.5}
           assert restored.capacity == 20
           missing = MyPersistentEnv()
           assert await missing.restore(workspace / "new") is False
       print("Environment state restored")

   asyncio.run(check_round_trip())

.. testoutput:: environment-state

   Environment state restored
