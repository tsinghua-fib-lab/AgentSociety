AgentSociety 2
==============

**AgentSociety 2** 是面向计算社会科学的现代化、LLM 原生智能体模拟与科研平台：在统一的异步框架中创建与管理智能体、环境模块与研究技能，并支持从 CLI、REST API 到集成研究环境的多入口协作。

.. container:: project-links

   * `PyPI <https://pypi.org/project/agentsociety2/>`_

   * Python 3.11–3.13

   * `Apache 2.0 <https://github.com/tsinghua-fib-lab/AgentSociety/blob/main/LICENSE>`_

从这里开始
----------

.. grid:: 1 1 2 2
   :gutter: 3
   :class-container: start-links

   .. grid-item-card:: 使用科研工作台
      :link: user_guide
      :link-type: doc
      :class-card: doc-card

      配置工作区、模型与后端，开始交互式研究。

   .. grid-item-card:: 运行 Python 示例
      :link: quickstart
      :link-type: doc
      :class-card: doc-card

      从最小仿真开始，了解智能体与环境的交互。

   .. grid-item-card:: 创建环境模块
      :link: custom_modules
      :link-type: doc
      :class-card: doc-card

      定义实验规则与工具，扩展自己的仿真环境。

   .. grid-item-card:: 理解运行架构
      :link: architecture
      :link-type: doc
      :class-card: doc-card

      查看执行、恢复、追踪与存储的工作方式。

研究工作区
------------------

平台把两类智能体放进同一个研究工作区：AI Social Scientist 协调文献、假设、实验和分析，硅基参与者在可配置环境中产生行为反馈。研究者负责明确问题、审阅设计并判断证据能支持哪些结论。

工作从 ``TOPIC.md`` 开始，逐步形成假设、可执行配置、运行记录和报告。CLI、Python API 与工作台共享核心仿真能力；运行架构见 :doc:`architecture`，智能体与技能见 :doc:`agents`、:doc:`agent_skills`。论文撰写通过外部 ``paper-toolkit`` 接续分析结果。

完整步骤见 :doc:`research_workflow`；准备输入数据见 :doc:`datasets`；查看回放与研究产物见 :doc:`results`。

----

功能与文档
------------

.. list-table::
   :widths: 30 45 25
   :header-rows: 1

   * - 想做什么
     - 功能
     - 阅读入口
   * - 使用研究工作台
     - 配置模型、管理文献与数据、组织假设和实验、分享工作区
     - :doc:`user_guide`
   * - 配置参与者与环境
     - 人物画像、行为技能、环境工具与自定义模块
     - :doc:`agents`、:doc:`env_modules`
   * - 执行与干预实验
     - Python 交互、CLI 执行、进度日志与中断恢复
     - :doc:`interaction`、:doc:`cli`
   * - 检查数据与结果
     - 时间步回放、数据集读取、分析与图表报告
     - :doc:`storage`、:doc:`skills`
   * - 扩展研究能力
     - 研究助手技能、Agent 技能与自定义环境
     - :doc:`agent_skills`、:doc:`custom_modules`
   * - 集成自己的工具
     - Python 接口、独立后端与配置模型
     - :doc:`api/index`

安装
------------

.. code-block:: bash

   pip install agentsociety2

详细安装说明请参见 :doc:`installation`。

快速开始
-----------

与智能体交互通过 :class:`~agentsociety2.society.AgentSociety` 的异步 API（如 ``ask`` / ``intervene``）完成，需使用 ``asyncio``。最小示意见 :doc:`quickstart`。

文档
-------------

.. toctree::
   :maxdepth: 1
   :caption: 入门指南:

   user_guide
   research_workflow
   installation
   quickstart
   examples

.. toctree::
   :maxdepth: 1
   :caption: 仿真与数据:

   concepts
   agents
   env_modules
   interaction
   cli
   results
   storage
   codegen_execution

.. toctree::
   :maxdepth: 1
   :caption: 研究与扩展:

   skills
   datasets
   agent_skills
   skill_guide
   custom_modules

.. toctree::
   :maxdepth: 1
   :caption: 开发与参考:

   architecture
   development
   module_and_parameter_management
   contributing
   api/index

引用
----

如果您在研究中使用了 AgentSociety 2，请引用：

.. code-block:: bibtex

   @misc{piao2026agentsociety2,
     title        = {{AgentSociety} 2: An Integrated Research Environment for Executable Social Science},
     author       = {Jinghua Piao and Jun Zhang and Haoyu Huang and Keming Zhang and Jing Yi Wang and Xinran Zhao and Songwei Li and Boyuan Sun and Jiayi Chang and Fengli Xu and Chunyan Wang and Fang Zhang and Ke Rong and Jun Su and Tianguang Meng and Yi Liu and Qingguo Meng and Yu Wang and Yong Li},
     year         = {2026},
     eprint       = {2607.11895},
     archiveprefix= {arXiv},
     primaryclass = {cs.CY},
     doi          = {10.48550/arXiv.2607.11895},
     url          = {https://arxiv.org/abs/2607.11895},
   }

论文：https://arxiv.org/abs/2607.11895

仓库级引用文件：

* ``CITATION.cff``: https://github.com/tsinghua-fib-lab/AgentSociety/blob/main/CITATION.cff
* ``citations.bib``: https://github.com/tsinghua-fib-lab/AgentSociety/blob/main/citations.bib

链接
-----

* **GitHub**: https://github.com/tsinghua-fib-lab/AgentSociety
* **PyPI**: https://pypi.org/project/agentsociety2/
* **Issues**: https://github.com/tsinghua-fib-lab/AgentSociety/issues

搜索
------

* :ref:`search`
