环境模块
========

环境模块保存仿真世界的状态，并通过 ``@tool`` 方法提供观察、查询和操作。智能体通过 ``ask_env`` 提出请求，由环境路由器选择并调用工具。

先阅读 :doc:`env_modules/routing` 理解模块与路由器的分工，再编写工具。带动态状态的模块还需要实现保存与恢复，才能在实验中断后继续运行。

.. grid:: 1 1 3 3
   :gutter: 3
   :class-container: topic-links

   .. grid-item-card:: 环境模块与路由器
      :link: env_modules/routing
      :link-type: doc
      :class-card: doc-card

      理解共享环境、工具路由、查询、干预与时间推进的关系。

   .. grid-item-card:: 创建环境模块与工具
      :link: env_modules/tools
      :link-type: doc
      :class-card: doc-card

      编写环境工具，区分观察、统计与状态修改，并挂载到路由器。

   .. grid-item-card:: 环境状态与中断恢复
      :link: env_modules/persistence
      :link-type: doc
      :class-card: doc-card

      保存动态状态，重建运行时对象，并检查中断恢复的结果。

.. toctree::
   :hidden:
   :maxdepth: 1

   env_modules/routing
   env_modules/tools
   env_modules/persistence

.. raw:: html

   <div class="guide-redirects" hidden>
   <span id="id2"></span><a data-legacy-fragment="id2" href="env_modules/tools.html#env-modules-tools-6">Moved section</a>
   <span id="envbase"></span><a data-legacy-fragment="envbase" href="env_modules/tools.html#env-modules-tools-5">Moved section</a>
   <span id="id3"></span><a data-legacy-fragment="id3" href="env_modules/tools.html#env-modules-tools-4">Moved section</a>
   <span id="id4"></span><a data-legacy-fragment="id4" href="env_modules/tools.html#env-modules-tools-3">Moved section</a>
   <span id="tool"></span><a data-legacy-fragment="tool" href="env_modules/tools.html#env-modules-tools-2">Moved section</a>
   <span id="id5"></span><a data-legacy-fragment="id5" href="env_modules/tools.html#env-modules-tools-1">Moved section</a>
   <span id="id6"></span><a data-legacy-fragment="id6" href="env_modules/tools.html#env-modules-tools-0">Moved section</a>
   <span id="resume"></span><a data-legacy-fragment="resume" href="env_modules/persistence.html#env-modules-persistence-10">Moved section</a>
   <span id="id7"></span><a data-legacy-fragment="id7" href="env_modules/tools.html#env-modules-tools-9">Moved section</a>
   <span id="id8"></span><a data-legacy-fragment="id8" href="env_modules/tools.html#env-modules-tools-8">Moved section</a>
   <span id="id9"></span><a data-legacy-fragment="id9" href="env_modules/tools.html#env-modules-tools-7">Moved section</a>
   </div>
