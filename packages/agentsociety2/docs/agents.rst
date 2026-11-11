使用智能体
==========

智能体是仿真实验中的参与者。默认的 ``PersonAgent`` 将人物画像、记忆和技能接入工具决策循环；环境模块负责提供可查询、可修改的外部状态。

首次运行通常只需配置 ``PersonAgent``，由 :doc:`/quickstart` 中的编排器创建。需要增加行为时先考虑 :doc:`/agent_skills`；需要不同的决策流程时再编写自定义类。工作台研究助手的职责见 :doc:`/research_workflow`。

.. grid:: 1 1 3 3
   :gutter: 3
   :class-container: topic-links

   .. grid-item-card:: 智能体配置与构造
      :link: agents/configuration
      :link-type: doc
      :class-card: doc-card

      选择智能体类型，设置画像与参数，理解工作区和服务的绑定方式。

   .. grid-item-card:: 决策、交互与记忆
      :link: agents/behavior
      :link-type: doc
      :class-card: doc-card

      了解每步决策、环境交互、只读问答，以及记忆与状态的保存位置。

   .. grid-item-card:: 自定义智能体
      :link: agents/customization
      :link-type: doc
      :class-card: doc-card

      确定何时需要自定义类，并实现恢复、问答、仿真步和状态写回。

.. toctree::
   :hidden:
   :maxdepth: 1

   agents/configuration
   agents/behavior
   agents/customization

.. raw:: html

   <div class="guide-redirects" hidden>
   <span id="id2"></span><a data-legacy-fragment="id2" href="agents/configuration.html#agents-configuration-2">Moved section</a>
   <span id="workspace-record"></span><a data-legacy-fragment="workspace-record" href="agents/configuration.html#agents-configuration-1">Moved section</a>
   <span id="serviceproxy"></span><a data-legacy-fragment="serviceproxy" href="agents/configuration.html#agents-configuration-0">Moved section</a>
   <span id="react"></span><a data-legacy-fragment="react" href="agents/behavior.html#agents-behavior-6">Moved section</a>
   <span id="todo"></span><a data-legacy-fragment="todo" href="agents/behavior.html#agents-behavior-5">Moved section</a>
   <span id="id3"></span><a data-legacy-fragment="id3" href="agents/behavior.html#agents-behavior-4">Moved section</a>
   <span id="agentconfig"></span><a data-legacy-fragment="agentconfig" href="agents/configuration.html#agents-configuration-3">Moved section</a>
   <span id="id4"></span><a data-legacy-fragment="id4" href="agents/behavior.html#agents-behavior-9">Moved section</a>
   <span id="ask"></span><a data-legacy-fragment="ask" href="agents/behavior.html#agents-behavior-8">Moved section</a>
   <span id="step"></span><a data-legacy-fragment="step" href="agents/behavior.html#agents-behavior-7">Moved section</a>
   <span id="id5"></span><a data-legacy-fragment="id5" href="agents/customization.html#agents-customization-13">Moved section</a>
   <span id="agentbase"></span><a data-legacy-fragment="agentbase" href="agents/customization.html#agents-customization-12">Moved section</a>
   <span id="id6"></span><a data-legacy-fragment="id6" href="agents/behavior.html#agents-behavior-11">Moved section</a>
   <span id="id7"></span><a data-legacy-fragment="id7" href="agents/behavior.html#agents-behavior-10">Moved section</a>
   <span id="agent-config"></span><a data-legacy-fragment="agent-config" href="agents/configuration.html#agent-config">Moved section</a>
   </div>
