核心概念
=============

本部分说明 AgentSociety 2 的系统结构与术语；首页 :doc:`index` 中的「研究背景与平台定位」从范式与协作角度概括了平台动机，此处侧重实现层面的组件关系。

架构概述
---------------------

AgentSociety 2 围绕三个主要组件构建：

* **智能体 (Agents)**: 使用 LLM 与环境交互的自主实体（workspace 绑定的无状态 record，由 Ray Task 流式驱动）
* **环境模块 (Environment Modules)**: 定义模拟规则的可组合组件
* **AgentSociety**: 管理智能体和环境的协调器

智能体不直接持有 env / LLM / trace / replay 等运行时对象，而是经一个 ``ServiceProxy`` 容器接收共享服务句柄；环境路由跑在专用 Ray actor 里。详见 :doc:`architecture`。

**中断恢复**：agent、env 模块和 society 三层都会把恢复所需的状态原子写入 workspace。agent 使用
``AGENT.json``，env 模块通常使用 ``state/ENV_STATE.json``，society 使用不可变的
``SOCIETY.json`` 和每步更新的 ``SOCIETY_STEP.json``。CLI 的 ``--resume`` 可以从中断处继续运行实验（详见 :doc:`cli`）。这一机制与 replay 相互独立；replay 是面向分析的 append-only 时序数据（见 :doc:`storage`）。

研究问题通过实验配置进入仿真，产生行为轨迹与结果，再回到证据比较与机制评估。下面的调用图展示智能体、路由器与环境工具的连接：

.. graphviz::
   :caption: 智能体通过路由器调用环境工具
   :alt: 智能体通过路由器调用环境工具
   :class: doc-figure

   digraph agentsociety2 {
       rankdir=TB;
       graph [bgcolor="#ffffff", pad="0.2"];
       node [shape=box, style="rounded,filled", fillcolor="#f4f7fc", color="#9dafc9", fontname="Arial"];
       edge [color="#64748b", fontname="Arial", fontsize=10];

       Agent [label="Agent"];
       CodeGenRouter [label="CodeGenRouter"];
       EnvModule [label="Env Module"];
       Tool [label="@tool()"];

       Agent -> CodeGenRouter [label="ask_env"];
       CodeGenRouter -> EnvModule [label="calls tools"];
       EnvModule -> Tool [label="exposes methods"];
   }

完整系统架构
~~~~~~~~~~~~~~~~~

.. graphviz::
   :caption: 编排器、共享服务、智能体与环境模块的连接
   :alt: 编排器、共享服务、智能体与环境模块的连接
   :class: doc-figure

   digraph full_architecture {
       rankdir=TB;
       graph [bgcolor="#ffffff", pad="0.2"];
       node [shape=box, style="rounded,filled", fillcolor="#f4f7fc", color="#9dafc9", fontname="Arial"];
       edge [color="#64748b", fontname="Arial", fontsize=10];
       edge [fontsize=10];

       subgraph cluster_ui {
           label = "User interfaces";
           style=filled;
           color=lightgrey;
           CLI [label="CLI"];
           WebUI [label="Web dashboard"];
           API [label="REST API"];
       }

       subgraph cluster_core {
           label = "Simulation runtime";
           style=filled;
           color=lightblue;
           Society [label="AgentSociety\nCoordinator (driver)"];
           Router [label="Router\n(EnvRouterActor)"];
           Storage [label="ReplaySink (JSONL)\n/ Workspace state"];
           Trace [label="Sharded Trace Writer\n(per-process append)"];
       }

       subgraph cluster_agents {
           label = "Agents rebuilt in Ray tasks";
           style=filled;
           color=lightgreen;
           Proxy [label="ServiceProxy\n(env/llm/trace/replay)", shape=note];
           Agent1 [label="PersonAgent 1"];
           Agent2 [label="PersonAgent 2"];
           AgentN [label="... PersonAgent N"];
       }

       subgraph cluster_env {
           label = "Environment modules";
           style=filled;
           color=lightyellow;
           Env1 [label="SocialSpace"];
           Env2 [label="EconomySpace"];
           EnvN [label="... Custom modules"];
       }

       subgraph cluster_external {
           label = "Model access";
           style=filled;
           color=lavender;
           LLM [label="LLM Client\n(per-process dispatcher)"];
       }

       CLI -> Society;
       WebUI -> API;
       API -> Society;

       Society -> Router;
       Society -> Storage;
       Society -> Trace;
       Society -> Proxy;

       Proxy -> Agent1;
       Proxy -> Agent2;
       Proxy -> AgentN;

       Router -> Env1;
       Router -> Env2;
       Router -> EnvN;

       Agent1 -> Router [label="ask_env"];
       Agent2 -> Router;
       AgentN -> Router;

       Agent1 -> LLM [label="dispatcher"];
       Society -> LLM;
   }

Agent Skills 与研究技能
-------------------------------

平台上的「技能」分两层：

* **Agent Skills** （见 :doc:`agent_skills` ）——``PersonAgent`` 的能力组织方式，遵循
  **metadata-first、selected-only** 模型——LLM 先只看技能目录（``name`` / ``description``），仅被选中的技能才会加载执行。技能是自包含目录（``SKILL.md`` 与可选的 ``scripts/``、
  ``references/``），内置技能脚本在 agent 进程内经 ``entrypoint`` 执行，自定义技能经
  ``skill_worker.py`` 隔离子进程执行；内置技能只有
  ``daily-guidance``，自定义技能放入 ``custom/skills/`` 即可被发现与热加载。
* **研究技能** （见 :doc:`skills` ）——``agentsociety2.skills`` 下 LLM 原生的科研工作流模块，
  ``literature``（文献检索）、``hypothesis``（假设管理）、``experiment``（实验配置与执行）、
  ``analysis``（数据分析）；论文撰写由外部 ``paper-toolkit`` 承担。它们与 **AgentSociety**
  编排器一起构成从文献、假设、实验到分析与文稿准备的闭环流水线。

智能体-环境接口
----------------------------

对外部调用者（society / driver），``AgentSociety`` 提供 ``ask()``（只读查询）与 ``intervene()``
（可写干预）两个入口。智能体内部则经 ``ask_env()`` 访问环境：``ask_env`` 把请求交给环境 router 的
``ask(readonly=...)``，由路由器映射到环境模块的 ``@tool`` 方法。ReAct 工具循环的细节见
:doc:`architecture` 与 :doc:`agents`。

@tool 装饰器
-------------------

环境模块通过 ``@tool`` 装饰器公开其功能：

.. code-block:: python

   from agentsociety2.env import EnvBase, tool

   class MyEnvironment(EnvBase):
       @tool(readonly=True, kind="observe")
       def get_weather(self, agent_id: int) -> str:
           """Get current weather for agent."""
           return f"Weather for agent {agent_id}"

       @tool(readonly=False)
       def set_temperature(self, temp: int) -> str:
           """Set temperature."""
           self._temperature = temp
           return f"Temperature set to {temp}"

**参数：**

* ``readonly`` (bool): 函数是否修改状态
  * ``True`` = 只读观察
  * ``False`` = 修改环境

* ``kind`` (str): 用于优化的函数类别
  * ``"observe"``: 单参数观察
  * ``"statistics"``: 聚合查询（无参数）
  * ``None``: 常规工具

CodeGenRouter
-------------

CodeGenRouter 通过以下方式将智能体连接到环境模块：

1. 从环境模块中提取工具签名
2. 根据智能体输入生成调用适当工具的代码
3. 静态验证后，在配置的执行后端运行代码
4. 将结果返回给智能体

路由器只能调用已挂载模块公开的工具。执行权限、期限与写操作失败后的处理见 :doc:`codegen_execution`。

路由器选择
~~~~~~~~~~~~

``RouterBase`` 有多个实现，可按需替换：

* ``CodeGenRouter`` （默认）：生成调用代码，经静态验证与 AST 守卫后执行；
  FAISS 指令模板缓存**仅在** ``ask(..., template_mode=True)`` 时生效；若模块未声明 observe/statistics 工具，init 会跳过对应 LLM 代码生成。
* ``ReActRouter``：ReAct 式工具选择。
* ``PlanExecuteRouter``：先规划再执行。
* ``TwoTierReActRouter`` / ``TwoTierPlanExecuteRouter``：两级路由，适合大工具集。
* ``SearchToolRouter``：以检索方式选择工具。

生产环境下路由跑在专用 Ray actor（``EnvRouterProxy``）里；actor 并发由模块
``is_concurrency_safe()`` 决定，详见 :doc:`architecture` 与 :doc:`env_modules`。

工具类别
---------------

**观察工具** (``readonly=True``, ``kind="observe"``)

具有单个 ``agent_id`` 参数的智能体特定观察：

.. code-block:: python

   @tool(readonly=True, kind="observe")
   def get_agent_location(self, agent_id: int) -> str:
       """Get current location of agent."""
       return f"Agent {agent_id} is at location X"

**统计工具** (``readonly=True``, ``kind="statistics"``)

没有参数的聚合查询（除了 ``self``）：

.. code-block:: python

   @tool(readonly=True, kind="statistics")
   def get_average_happiness(self) -> str:
       """Get average happiness of all agents."""
       avg = sum(self.happiness.values()) / len(self.happiness)
       return f"Average happiness: {avg}"

**常规工具**

具有任何签名的通用工具：

.. code-block:: python

   @tool(readonly=False)
   def set_happiness(self, agent_id: int, value: float) -> str:
       """Set happiness level for agent."""
       self.happiness[agent_id] = value
       return f"Set agent {agent_id}'s happiness to {value}"

工具类别层次结构
~~~~~~~~~~~~~~~~~

.. graphviz::
   :caption: 工具的只读属性与类别分别约束用途
   :alt: 工具的只读属性与类别分别约束用途
   :class: doc-figure

   digraph tool_hierarchy {
       rankdir=TB;
       graph [bgcolor="#ffffff", pad="0.2"];
       node [shape=box, style="rounded,filled", fillcolor="#f4f7fc", color="#9dafc9", fontname="Arial"];
       edge [color="#64748b", fontname="Arial", fontsize=10];

       Root [label="@tool", shape=ellipse];

       Readonly [label="readonly=True", shape=diamond];
       Readwrite [label="readonly=False", shape=diamond];

       Observe [label="Observation (kind=observe)\nOne agent_id argument"];
       Statistics [label="Statistics (kind=statistics)\nNo arguments except self"];
       RegularRead [label="Regular read-only tool\nkind=None"] ;
       Regular [label="Regular write tool\nkind=None"];

       Root -> Readonly;
       Root -> Readwrite;

       Readonly -> Observe;
       Readonly -> Statistics;
       Readonly -> RegularRead;
       Readwrite -> Regular;
   }

智能体-环境交互流程
~~~~~~~~~~~~~~~~~~~~

.. graphviz::
   :caption: 一次环境请求的工具调用与响应路径
   :alt: 一次环境请求的工具调用与响应路径
   :class: doc-figure

   digraph interaction_flow {
       rankdir=TB;
       graph [bgcolor="#ffffff", pad="0.2"];
       node [shape=box, style="rounded,filled", fillcolor="#f4f7fc", color="#9dafc9", fontname="Arial"];
       edge [color="#64748b", fontname="Arial", fontsize=10];

       Agent [label="Agent"];
       Ask [label="ask_env()"];
       Router [label="Router"];
       Tools [label="Registered @tool methods"];
       Env [label="Environment state"];
       Response [label="Response"];

       Agent -> Ask;
       Ask -> Router;
       Router -> Tools [label="Select and call tools"];
       Tools -> Env [label="Apply tool"];
       Env -> Tools [label="Return result"];
       Tools -> Router;
       Router -> Response;
       Response -> Agent;
   }
