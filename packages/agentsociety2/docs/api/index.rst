API 参考
=========

本节汇集常用公开接口。Python SDK 参考由 Sphinx autodoc 从当前源码生成；后端接口的访问与调试见 :doc:`http`。首次运行请先读 :doc:`/quickstart`；查实验配置字段用 :doc:`config`。

按使用场景选择
--------------

.. grid:: 1 1 2 2
   :gutter: 3
   :class-container: reference-links

   .. grid-item-card:: 编排仿真实验
      :link: society
      :link-type: doc
      :class-card: doc-card

      创建仿真、推进时间、查询与干预，以及向智能体发放问卷。

   .. grid-item-card:: 扩展智能体与环境
      :link: env
      :link-type: doc
      :class-card: doc-card

      实现环境工具、选择路由器，并接入自定义行为。

   .. grid-item-card:: 配置与读取数据
      :link: config
      :link-type: doc
      :class-card: doc-card

      查阅配置模型与字段，读取回放数据和元信息。

   .. grid-item-card:: 集成 HTTP 接口
      :link: http
      :link-type: doc
      :class-card: doc-card

      使用后端接口，打开 Swagger，查看请求参数与响应结构。

常用公开入口
------------

以下入口均来自当前包的公开导出。完整签名、参数与返回值见对应参考页。

.. list-table::
   :header-rows: 1
   :widths: 40 35 25

   * - 导入位置
     - 对象
     - 参考
   * - ``agentsociety2.society``
     - ``AgentSociety``、``AgentSocietyHelper``
     - :doc:`society`
   * - ``agentsociety2``
     - ``AgentBase``、``PersonAgent``
     - :doc:`agent`
   * - ``agentsociety2``
     - ``EnvBase``、``RouterBase``、``tool`` 与各路由器
     - :doc:`env`
   * - ``agentsociety2.society``
     - ``InitConfig``、``StepsConfig``
     - :doc:`config`
   * - ``agentsociety2.storage``
     - ``ReplayReader``、``ReplayWriter``、``TableSchema``
     - :doc:`storage`

SDK 参考
--------

.. toctree::
   :maxdepth: 1

   agent
   memory
   skills
   env
   society
   storage
   config
   registry

集成与扩展参考
--------------

.. toctree::
   :maxdepth: 1

   http
   backend
   runtime

.. note::

   API 文档从代码中的 docstring 自动生成。如果发现文档不完整或有误，请直接修改源代码中的注释。
