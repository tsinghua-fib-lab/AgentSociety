与 AgentSociety 交互
==============================

使用 ``society.ask()`` 查询状态，使用 ``society.intervene()`` 调用写工具，使用 ``step()`` 或 ``run()`` 推进模拟时间。初始化流程见 :doc:`quickstart`。

交互入口
--------

.. graphviz::
   :caption: 查询使用只读工具，干预可以调用写工具
   :alt: 查询使用只读工具，干预可以调用写工具
   :class: doc-figure

   digraph interaction_modes {
       rankdir=TB;
       graph [bgcolor="#ffffff", pad="0.2"];
       node [shape=box, style="rounded,filled", fillcolor="#f4f7fc", color="#9dafc9", fontname="Arial"];
       edge [color="#64748b", fontname="Arial", fontsize=10];

       Society [label="AgentSociety"];
       Ask [label="ask()", shape=ellipse];
       Intervene [label="intervene()", shape=ellipse];

       subgraph cluster_ask {
           label = "Read-only query";
           style=filled;
           color=lightgreen;
           Query [label="Inspect state"];
           Read [label="Read-only tools"];
           NoModify [label="No write tools"];
       }

       subgraph cluster_intervene {
           label = "Intervention";
           style=filled;
           color=lightcoral;
           Modify [label="Update state"];
           Write [label="Read / write tools"];
           Change [label="Apply intervention"];
       }

       Society -> Ask;
       Society -> Intervene;
       Ask -> Query;
       Ask -> Read;
       Ask -> NoModify;
       Intervene -> Modify;
       Intervene -> Write;
       Intervene -> Change;
   }

查询、修改与推进
----------------

下面使用内置天气环境演示完整调用顺序：

.. code-block:: python

   import asyncio
   from datetime import datetime
   from pathlib import Path

   from agentsociety2.contrib.env import WeatherEnvironment
   from agentsociety2.env import CodeGenRouter
   from agentsociety2.society import AgentSociety

   async def main():
       society = AgentSociety(
           agent_specs=[{"id": 1, "profile": {"name": "Demo Agent"}, "config": {}}],
           agent_class_name="PersonAgent",
           env_router=CodeGenRouter(env_modules=[WeatherEnvironment()]),
           start_t=datetime(2026, 1, 1),
           run_dir=Path("run"),
       )
       try:
           await society.init()
           print(await society.ask("What is the current weather?"))
           print(await society.intervene("Change the weather to rainy at 15 degrees Celsius"))
           print(await society.ask("What is the current weather now?"))
           await society.run(num_steps=2, tick=600)
       finally:
           await society.close()

   asyncio.run(main())

``ask`` 使用只读环境工具；``intervene`` 可调用环境公开的写工具。可用操作取决于挂载的模块，工具定义见 :doc:`env_modules`。

按时间点读取状态
----------------

在已初始化的 ``society`` 上逐步运行：

.. code-block:: python

   for step_number in range(3):
       print(step_number, await society.ask("Describe the current environment state"))
       await society.step(tick=600)

``tick`` 的单位是秒。每步先推进智能体，再推进环境，最后更新模拟时钟；返回值与状态记录可配合查看。

查看输出
--------

* 当前问答结果：读取 ``ask`` / ``intervene`` 的返回值。
* 时序状态：使用 ``ReplayReader`` 读取 ``run/replay/``，见 :doc:`storage`。
* 工具与模型调用：查看 ``run/trace/``。
* 保存问答产物：CLI 的 ``ask`` / ``intervene`` 步骤自动写入 ``run/artifacts/``，见 :doc:`cli`。

更多接口见 :doc:`api/society`；定向查询智能体的方法见 ``AgentSocietyHelper``。

结构化问卷
----------

需要向多个参与者发放同一组问题时，使用 ``society.run_questionnaire(questionnaire, target_agent_ids=...)``。``Questionnaire`` 指定问卷编号和题目列表，``QuestionnaireResponse`` 保留目标 Agent、原始回答、解析值与解析是否成功等结果；输入与返回类型见 :doc:`api/society`，题目字段见 :doc:`api/config`。

CLI 的 ``questionnaire`` 步骤会把问卷产物写入 ``run/artifacts/``，适合在模拟的指定时点收集结构化响应，配置方式见 :doc:`cli`。直接调用 SDK 时，调用方负责保存返回结果；检查 ``parse_success`` 和原始回答后再汇总指标。
