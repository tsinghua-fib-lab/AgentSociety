AgentSociety 2
==============

**AgentSociety 2** 是面向计算社会科学的现代化、LLM 原生智能体模拟与科研平台：在统一的异步框架中创建与管理智能体、环境模块与研究技能，并支持从 CLI、REST API 到集成研究环境的多入口协作。

.. image:: https://img.shields.io/pypi/v/agentsociety2.svg
   :target: https://pypi.org/project/agentsociety2/
   :alt: PyPI Version

.. image:: https://img.shields.io/pypi/pyversions/agentsociety2.svg
   :target: https://pypi.org/project/agentsociety2/
   :alt: Python Versions

.. image:: https://img.shields.io/badge/License-Apache%202.0-blue.svg
   :target: LICENSE
   :alt: License

研究背景与平台定位
------------------

科学探究在历史上依托 :strong:`经验、理论、计算与数据密集型` 等范式不断扩展问题的范围、规模与深度；数字时代以来，大语言模型与自主智能体正在系统性地重塑知识生产与协作方式。对社会科学而言，智能体至少可以承担两类互补角色：其一，作为 :strong:`智能体科学家`，参与文献整合、想法产生与实验编排等认知劳动；其二，作为可规模化、可重复的 :strong:`硅基被试`，在可控仿真环境中开展问卷、访谈与干预的试点研究，从而在成本与伦理约束下探索反事实与机制。

**AgentSociety 2** 将上述思路落实为 :strong:`端到端的智能体科研编排框架`：围绕四类范式组织协同工作的能力——面向经验范式的实验设计、执行与结果分析；面向理论范式的文献整合与假设构建（并可对接跨学科文献与结构化工作流）；面向计算范式的通用智能体–环境仿真（在 AgentSociety 1 的模拟传统上扩展为更灵活的模块化架构）；以及面向数据密集型范式的数据获取、整合与统计推断支持。多类研究技能与 **AgentSociety** 编排器共同构成从文献与假设、到数据与计算实验、再到分析与文稿准备的 :strong:`闭环流水线`。

与此同时，平台强调 :strong:`有意义的科学洞见仍源于人类研究者`；挑战在于如何在降低工程负担的同时，使人与智能体能力对齐、协作可控。**AgentSociety 2** 通过 **IDE 式集成研究环境（IRE）** 与可视化/扩展入口（如后端 API、CLI、前端与扩展）提供结构化工作区，支持研究者与多智能体团队持续协同，在透明可控的前提下将初步想法落实为可复现的仿真实验。系统架构、路由与存储等实现细节见 :doc:`concepts`；智能体与技能见 :doc:`agents` 与 :doc:`agent_skills`。

----

核心特性
------------

* **LLM 驱动的智能体**: 创建具有个性、记忆和推理能力的智能体，由大语言模型驱动。

* **灵活的环境模块**: 使用可组合的工具和状态管理构建自定义模拟环境。

* **异步优先设计**: 高性能异步架构，实现高效的多智能体模拟。

* **回放与分析**: append-only JSONL replay、``_schema.json`` catalog 与 DuckDB 读侧，用于实验跟踪和分析。

* **中断恢复**: agent、env 和 society 三层状态都会原子持久化，CLI ``--resume`` 可从中断处继续运行实验（见 :doc:`cli`）。

* **研究技能**: 内置文献检索、假设生成、实验设计与数据分析等 LLM 原生工作流；论文撰写由外部 ``paper-toolkit`` 承担。

* **REST API**: 基于 FastAPI 的独立后端服务，支持外部集成。

* **CLI 工具**: 强大的命令行界面，支持实验运行和进度跟踪。

* **可扩展**: 轻松扩展自定义智能体、环境和工具。

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
   :maxdepth: 2
   :caption: 入门指南:

   user_guide
   installation
   quickstart
   cli
   concepts
   architecture
   interaction

.. toctree::
   :maxdepth: 2
   :caption: 用户指南:

   agents
   agent_skills
   env_modules
   codegen_execution
   storage
   custom_modules
   skills

.. toctree::
   :maxdepth: 2
   :caption: 开发者指南:

   development
   module_and_parameter_management
   contributing

.. toctree::
   :maxdepth: 2
   :caption: 参考:

   api/index
   examples

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
