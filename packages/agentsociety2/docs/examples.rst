示例
========

本部分包含演示 AgentSociety 2 功能的示例代码。

先离线检查配置
--------------

下面的示例验证初始化配置和时间步参数，不启动 Ray 或调用模型。配置校验能发现缺失字段和无效步数；模块是否可用、模型能否连接仍需运行时检查。

.. testcode:: configuration

   from pydantic import ValidationError
   from agentsociety2.society import InitConfig, RunStep

   config = InitConfig.model_validate({
       "env_modules": [{"module_type": "SimpleSocialSpace"}],
       "agents": [{
           "agent_id": 1,
           "agent_type": "PersonAgent",
           "kwargs": {"id": 1, "profile": {"name": "Alice"}},
       }],
   })
   step = RunStep(num_steps=2, tick=600)
   assert config.agents[0].kwargs["id"] == 1
   assert step.num_steps * step.tick == 1200
   try:
       RunStep(num_steps=0)
   except ValidationError:
       print("Invalid step count rejected.")
   else:
       raise AssertionError("Expected a validation error")

.. testoutput:: configuration

   Invalid step count rejected.

这个代码块由文档 CI 直接执行。需要付费模型的完整仿真另见 :doc:`quickstart`；记录输入、模型与结果的建议见下方复现说明。

离线回放示例
------------

只想先确认回放写入、目录元数据和读取接口是否可用时，可运行 :doc:`storage` 中的独立脚本。该示例不需要模型凭据，也不会访问网络。

.. code-block:: bash

   python packages/agentsociety2/examples/offline/replay_round_trip.py

记录可复现的实验
----------------

分享示例时，一起提供配置文件、输入数据来源、随机种子（适用时）、模型供应商与模型 ID、关键参数、SDK 版本和代码提交。结果中保留运行日志、回放目录及评价方法，避免只有一张结论截图。

LLM 采样、服务端模型更新和并发调度都可能影响行为结果；固定配置有助于比较，但不保证逐字或逐步相同。比较实验应说明重复次数、测量口径与差异范围。工作区产物见 :doc:`results`，外部数据说明见 :doc:`datasets`。

运行示例
----------------

示例位于 ``packages/agentsociety2/examples/``。``offline/`` 中的示例无需模型凭据；以下涉及智能体决策的示例需要配置模型服务。

**前提条件：**

1. 安装 AgentSociety 2: ``pip install agentsociety2``
2. 配置 LLM API 凭证（参见 :doc:`installation`）
3. 导航到示例目录

.. code-block:: bash

   cd packages/agentsociety2/examples
   python basics/01_hello_agent.py

基本示例
--------------

这些示例演示 AgentSociety 2 的基本概念：

**Hello Agent** (``basics/01_hello_agent.py``)

一个最小示例，展示：

* 创建具有个性配置文件的单个智能体
* 设置 SimpleSocialSpace 环境
* 使用 AgentSociety 协调智能体-环境交互

.. literalinclude:: ../examples/basics/01_hello_agent.py
   :language: python
   :start-at:     agent_specs = [
   :end-at:     await society.init()
   :dedent: 4
   :caption: ``basics/01_hello_agent.py``

**自定义环境模块** (``basics/02_custom_env_module.py``)

演示用 contrib 环境模块跑通 Ray 发现与干预：

* 使用内置 ``WeatherEnvironment``（``agentsociety2.contrib.env``），无需手写注册
* 通过 ``create_env_router_proxy`` 挂载环境（与 CLI / 生产路径一致）
* ``intervene`` 改天气后 ``ask`` 读回温度

**回放系统** (``basics/03_replay_system.py``)

展示 replay 数据记录与读取：

* 为环境模块启用 ReplayWriter
* 生成 replay catalog 和环境 replay dataset
* 结合 agent workspace 文件检查本地 thread / 工具日志

博弈论示例
---------------------

这些示例使用 contrib 下的博弈 agent / env，并通过 ``society.step()`` 推进回合。需要配置 LLM 凭证（参见 :doc:`installation`）。

**囚徒困境** (``games/01_prisoners_dilemma.py``)

* ``PrisonersDilemmaAgent`` + ``PrisonersDilemmaEnv``
* 多轮同时决策（Cooperate / Defect）
* 结果写入 ``run_dir`` （含 env state 与 replay）

**公共物品博弈** (``games/02_public_goods.py``)

* ``PublicGoodsAgent`` + ``PublicGoodsEnv``
* 多名智能体多轮贡献决策

**声誉博弈** (``games/reputation_game.py``)

* ``LLMDonorAgent`` + ``ReputationGameEnv``
* 基于声誉的捐赠决策短跑示例

完整批量实验脚本见 ``packages/agentsociety2/experiments/env_main_*_v2.py``。

高级示例
-----------------

**自定义智能体** (``advanced/01_custom_agent.py``)

使用 contrib 智能体类型扩展 AgentSociety 2：

* 使用内置 ``SpecialistAgent``（``agentsociety2.contrib.agent``），Ray worker 可自动发现
* 以 ``agent_class_name="SpecialistAgent"`` 交给 ``AgentSociety``（无需手写 ``register_agent_module``）
* 通过 ``AgentSocietyHelper`` 的 ``get_agent_profile`` / ``ask_agents`` 查询与提问

**多路由器比较** (``advanced/02_multi_router.py``)

比较不同的推理策略：

* ReActRouter: 迭代推理和行动
* PlanExecuteRouter: 计划优先执行
* CodeGenRouter: 生成代码执行（推荐）
