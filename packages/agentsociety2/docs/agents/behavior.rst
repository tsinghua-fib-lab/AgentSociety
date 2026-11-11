决策、交互与记忆
================

.. _agents-behavior-6:

ReAct 工具循环
--------------

``PersonAgent.step()`` / ``ask()`` 的核心是基类提供的 ``run_react_loop``：每轮让模型提交一个结构化工具决策，运行时校验、执行并把结果写回上下文，循环直至 ``finish`` 或回合上限。这把 LLM 的自由生成限制在可审计的工具结果里，也方便 replay 复盘。

基类 ``dispatch_react_tool`` 处理以下工具（``PersonAgent`` 在此之上按需追加 ``memory_*`` 等前缀）：

.. list-table::
   :widths: 26 74
   :header-rows: 1

   * - 工具
     - 说明
   * - ``read`` / ``write`` / ``append`` / ``list`` / ``grep``
     - 读写 agent 工作区文件（带越界保护）。
   * - ``activate_skill`` / ``deactivate_skill``
     - 把某 skill 的 ``SKILL.md`` 注入 / 移出上下文。
   * - ``read_skill_file``
     - 读取 skill 目录内文件（渐进式披露）。
   * - ``execute_skill_script``
     - 执行 skill 脚本（内置技能进程内直调，自定义技能在子进程执行，见 :doc:`/agent_skills` ）。
   * - ``ask_env``
     - 向环境 router 发请求（查询或修改环境），返回 ``(ctx, answer)`` 二元组。
   * - ``finish``
     - 结束当前仿真步（可附 summary）。

模型每轮的输出被解析为一个结构化决策（工具名 + 参数 + 是否结束）。无效工具名会被纠正或返回可恢复错误，不会直接崩溃。

一次 ``run_react_loop`` 只构建**一个** thread：首条消息由 ``build_react_messages`` 产出（system +
含各上下文档的 user），之后每轮的 assistant 工具调用与其结果**追加**到末尾，不再重建。这样每个请求都是上一个的严格前缀扩展，provider 的 prompt 前缀缓存能随轮次增长而不是每轮归零。实际缓存命中取决于模型服务与请求内容；在轮内重建或从头部截断 thread 会破坏已有前缀。工具结果以 ``role: "tool"`` 消息返回（失败时带 ``ERROR:`` 前缀）；模型若以文本而非原生 tool call
发起调用，结果则作为 ``<recent_observations>`` user 块追加。步内改动了
``<todo_context>`` / 激活 skill 时，会追加一条刷新块而不是重渲染（见
``AgentBase.build_context_refresh_message``）。工具结果同时写入磁盘 JSONL 供 replay 复盘。

.. note::

   agent 层**没有** ``bash`` / ``glob`` / ``codegen`` / ``batch`` 这类工具。环境交互统一走
   ``ask_env``，由环境侧的 router（如 ``CodeGenRouter``）决定如何调用环境模块工具（见 :doc:`/env_modules`）。


.. _agents-behavior-5:

TODO 状态
~~~~~~~~~

基类内置一组 TODO 工具（``todo_list`` / ``todo_add`` / ``todo_update`` / ``todo_start`` /
``todo_complete`` / ``todo_defer`` / ``todo_clear_completed``），让 agent 可以显式维护待办清单。
TODO 条目用 UUID 标识，自动归档，可通过 ``dispatch_todo_tool`` 分发；目的是让多步计划在跨 tick 之间可追踪、可恢复。


.. _agents-behavior-4:

工作区布局
~~~~~~~~~~

每个 agent 拥有独立工作区，是它的唯一持久状态来源：

.. code-block:: text

   <run_dir>/agents/agent_XXXX/
   ├── config.json            # 静态配置（create 时写一次，不再重写）
   ├── AGENT.json             # 动态自描述快照（每步 to_workspace 时更新）
   ├── state/                 # 技能与自定义状态文件（如 daily_guidance/）
   ├── TODO.json              # 跨步待办清单
   ├── MEMORY.md              # 跨 step 运行时记忆摘要
   ├── memory/
   │   ├── episodes.jsonl     # 事件记忆
   │   └── state.json         # 记忆运行时状态
   └── custom/skills/         # 自定义技能目录（热加载）

``config.json`` 是静态的；``AGENT.json`` 由 ``persist_agent_json``（调 ``build_agent_json``）在
``to_workspace`` 时写回，是 agent 对自己的自描述快照（含 ``world_description`` 等字段，供 Ray
重建时从磁盘恢复；注入 prompt 的 ``<agent>`` 视图会剥离该字段以免与 ``<world>`` 重复）。工具、技能脚本与 LLM 调用日志写入 ``<run_dir>/trace/trace_<xx>.jsonl`` 分片。跨 step 的运行时摘要见 ``MEMORY.md``。

.. _agents-behavior-9:

与智能体交互
------------

.. _agents-behavior-8:

``ask()`` 方法
~~~~~~~~~~~~~~

.. code-block:: python

   response = await agent.ask(
       "What's your opinion on renewable energy?",
       readonly=True,   # 仅查询，不允许写环境工具
   )

``ask`` 通过 ReAct 循环回答问题。``readonly=True`` 时只暴露查询工具，并限制工作区写入、待办变更和修改环境的工具；``False`` 允许使用对应的修改工具。只读问答仍可能记录 trace、更新对话上下文或保存运行时快照。


.. _agents-behavior-7:

``step()`` 方法
~~~~~~~~~~~~~~~

``AgentSociety`` 在仿真期间自动调用（``tick`` 为本步时间跨度秒，``t`` 为本步开始时的仿真时间）：

.. code-block:: python

   action_description = await agent.step(tick=3600, t=datetime.now())

在编排器层面，``AgentSociety.step(tick)`` / ``run(num_steps, tick)`` 会驱动所有 agent 的 ``step``，并支持以 Ray Task 批式并行（见 :doc:`/architecture`）。外部问答/干预则经 ``AgentSociety.ask(question)``
与 ``AgentSociety.intervene(instruction)``。

.. _agents-behavior-11:

智能体记忆
----------

``PersonAgent`` 的记忆分几层：

1. **Thread（对话线程）**：短期上下文，维护最近工具调用与 LLM 交互，过长时压缩。
2. **AgentMemory（运行时持久化记忆）**：跨 step 的运行时摘要，位于 ``MEMORY.md``，由 thread
   压缩与显式 handoff 更新，主要服务长线程压缩、恢复与错误连续性。
3. **Event memory**：``PersonMemoryRuntime`` 根据 step-mode ``finish`` 携带的 ``memories`` 写入
   ``memory/episodes.jsonl`` ，保存社会关系、地点、承诺、计划结果等可检索事实（是否写入由工具循环决定，不是每步固定）。
4. Workspace 状态文件：skill 脚本写入的 ``state/*.json``，例如情绪、意图、计划等。

``MEMORY.md`` 与 ``memory/episodes.jsonl`` 不是一回事：前者是压缩后的长期背景摘要，后者是 append-only
事件流。要替换/扩展记忆策略，优先扩展 ``PersonMemoryRuntime`` 或相关工具边界，而不是恢复旧的
``memory`` 内置 skill。


.. _agents-behavior-10:

参考
----

* :doc:`/agent_skills` - Agent Skills 子系统（发现、entrypoint 执行、生命周期 hook）
* :doc:`/architecture` - Ray 执行模型、``ServiceProxy``、trace、路由器
* :doc:`/api/agent` - ``AgentBase`` / ``PersonAgent`` API 参考
* 源码 ``agentsociety2/agent/base/README.md`` - AgentBase 子类开发指南（最权威）
