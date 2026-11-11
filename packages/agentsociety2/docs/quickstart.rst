快速入门
========

本页运行一个最小的 Python SDK 仿真。使用 VS Code / code-server 工作台时，可先阅读 :doc:`user_guide`；从配置文件运行实验时，阅读 :doc:`cli`。

前置条件
--------

先按 :doc:`installation` 安装 SDK 并配置模型。下面代码会访问模型服务；``python`` 应来自已安装 SDK 的环境。也可在项目目录准备 ``.env``，在导入 SDK 前用 ``load_dotenv()`` 加载。

创建并运行
----------

通过元数据声明一个参与者，创建共享环境路由，查询画像并推进两个时间步：

.. code-block:: python

   import asyncio
   from datetime import datetime
   from pathlib import Path

   from agentsociety2.env import create_env_router_proxy
   from agentsociety2.society import AgentSociety

   async def main():
       run_dir = Path("run_quickstart")
       agent_specs = [
           {
               "id": 1,
               "profile": {"name": "Alice", "age": 28, "bio": "Enjoys reading."},
               "config": {},
           }
       ]
       env_router = await create_env_router_proxy(
           ["SimpleSocialSpace"],
           {"SimpleSocialSpace": {"agent_id_name_pairs": [(1, "Alice")]}},
           run_dir=run_dir,
       )
       society = AgentSociety(
           agent_specs=agent_specs,
           agent_class_name="PersonAgent",
           env_router=env_router,
           start_t=datetime(2026, 1, 1, 8, 0),
           run_dir=run_dir,
       )
       try:
           await society.init()
           answer = await society.ask(
               "Use get_agent_profile for name=Alice. Summarize the profile."
           )
           print(answer)
           await society.run(num_steps=2, tick=600)
           print(society.all_token_stats())
       finally:
           await society.close()

   if __name__ == "__main__":
       asyncio.run(main())

``agent_specs`` 描述画像与配置，由 ``init()`` 创建 Agent 工作目录；不直接用画像参数构造 ``PersonAgent`` 实例。``create_env_router_proxy`` 让各 Ray worker 访问同一环境，使用方式与 CLI 一致。

``tick`` 的单位是秒，表示每步模拟时间跨度，不是等待的真实秒数。回答和 Agent 决策随模型与上下文变化；运行记录在 ``run_quickstart/``。再次独立运行时使用新的输出目录；恢复实验见 :doc:`cli`。

检查结果
--------

* 查看终端输出与 ``run_quickstart/SOCIETY_STEP.json`` 确认推进进度，结合调用记录检查错误。
* ``run_quickstart/replay/`` 保存 catalog 与时序数据；可用字段取决于实际写入的数据集。
* ``run_quickstart/agents/`` 保存人物的持久状态，``run_quickstart/trace/`` 保存调用记录。

回放与报告入口见 :doc:`results`；程序读取方法见 :doc:`storage`。SDK 直接运行的目录可用 ``ReplayReader`` 读取；插件回放默认从研究工作区的假设 / 实验目录读取数据。

查询、干预与推进
----------------

在已经初始化的 ``society`` 上，三个入口的用途分别是：

.. list-table::
   :widths: 32 68
   :header-rows: 1

   * - 方法
     - 用途
   * - ``society.ask(question)``
     - 通过辅助器规划只读查询，可检查画像、询问目标 Agent 或查询环境。
   * - ``society.intervene(instruction)``
     - 允许调用环境写工具，具体操作由挂载模块提供。
   * - ``society.step(tick)`` / ``run(num_steps, tick)``
     - 推进参与者、环境与仿真时钟。

查询画像中的已有字段时，可明确请求 ``get_agent_profile``；需要参与者作答时，明确 Agent 编号并请求 ``ask_agents``。只读查询仍可能留下日志；它不会自动推进仿真时钟。详细交互方法见 :doc:`interaction`。

扩展与后续步骤
--------------

* :doc:`research_workflow`：组织研究问题、假设与实验，保留可检查的中间产物。
* :doc:`datasets`：准备画像、环境输入或比较数据。
* :doc:`custom_modules`：实现自己的 Agent 或环境工具。
* :doc:`agent_skills`：扩展仿真参与者的行为能力。
* :doc:`examples`：查看仓库中的入门、博弈和进阶示例。

完整研究不要求手写全部编排代码；工作台与研究技能的使用方式见 :doc:`user_guide`、:doc:`skills`。
