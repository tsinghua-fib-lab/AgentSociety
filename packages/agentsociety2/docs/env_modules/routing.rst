环境模块与路由器
================

模块保存状态，路由器组织调用
----------------------------

``EnvBase`` 模块描述世界的一部分，例如社交关系、天气或公共资源。一个实验可以挂载多个模块；智能体通过同一个环境入口使用它们。

.. graphviz::
   :caption: 智能体通过环境路由器调用多个环境模块的工具
   :alt: 智能体通过环境路由器调用多个环境模块的工具
   :class: doc-figure
   :align: center

   digraph environment {
      rankdir=LR;
      node [shape=box, style="rounded", fontname="sans-serif"];
      agent [label="PersonAgent"];
      router [label="ask_env / Router"];
      social [label="Social tools"];
      resources [label="Resource tools"];
      agent -> router;
      router -> social;
      router -> resources;
   }

模块定义状态、工具和每步更新规则；``RouterBase`` 聚合工具、处理请求并返回结果。Ray 运行模式中的 ``EnvRouterProxy`` 连接智能体任务与共享的环境服务，避免每个智能体各自持有一份互不一致的世界状态。

选择路由策略
------------

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - 路由器
     - 调用方式
   * - ``CodeGenRouter``
     - 生成代码来组合环境工具，适合需要多步查询、计算或批量操作的请求。
   * - ``ReActRouter`` / ``PlanExecuteRouter``
     - 通过工具决策循环，或先规划再执行，组织对模块工具的调用。
   * - ``TwoTierReActRouter`` / ``TwoTierPlanExecuteRouter``
     - 分层组织模块选择与工具执行，用于工具集合较大的环境。
   * - ``SearchToolRouter``
     - 先检索相关工具，再组织调用。

先使用实验已有的策略，确认工具接口与结果可用后再比较其他路由器。代码执行后端、期限与模板复用见 :doc:`/codegen_execution`，系统执行模型见 :doc:`/architecture`。

查询、干预与时间推进
--------------------

* **查询**：工具使用 ``readonly=True``；只读请求只允许查询类工具。
* **干预**：修改资源、关系或规则的工具使用 ``readonly=False``；允许写入的请求才可调用。
* **时间推进**：模块的 ``step(tick, t)`` 更新随时间变化的状态，工具调用本身不会替代实验时钟推进。

只读限制取决于工具声明和实现是否一致。一个标记为只读的方法也应避免在内部修改实验状态。工具返回“已成功”之前，应完成必要的状态更新与输入校验。

检查请求走到了哪里
------------------

先直接调用模块方法，确认输入和返回值；再挂载到路由器，检查工具是否被发现、只读属性是否正确。最后通过小规模实验检查智能体是否能使用工具，并核对 trace 与 replay 中的结果。

模块未出现时检查挂载列表和自定义模块扫描结果；工具未出现时检查 ``@tool``、类型注解与签名；结果能返回但恢复后丢失时，继续检查 :doc:`persistence`。
