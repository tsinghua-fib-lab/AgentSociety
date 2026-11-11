实验执行与分析
==============

.. _skills-experiments-analysis-7:

实验工作流
~~~~~~~~~~

研究 pipeline 的主干是：

``literature-search → hypothesis → experiment-config → run-experiment → analysis → paper-toolkit``

实验相关的两个核心 skill 是：

.. list-table::
   :widths: 30 35 35
   :header-rows: 1

   * - Skill
     - 主要输入
     - 主要输出
   * - ``agentsociety-experiment-config``
     - ``SIM_SETTINGS.json``、已有 Agent/Env/Dataset 信息
     - ``init_config.json``、``steps.yaml``、``config_params.py``
   * - ``agentsociety-run-experiment``
     - ``init_config.json`` + ``steps.yaml``
     - ``run/replay/``、日志、artifacts、``pid.json``

推荐流程：

1. 先确认工作区中已经具备 ``init_config.json``、``steps.yaml`` 与所需模块信息。
2. 在 ``experiment-config`` 阶段先扫描模块；如果缺少 Agent 或 Env，先补充对应自定义模块，再重新扫描。
3. 运行 ``experiment-config check`` 或等价校验，确认配置和步骤文件可用。
4. 启动实验时使用 ``run-experiment``；后台执行必须指定日志文件，避免丢失 verbose 输出。
5. 实验完成后检查 ``run/replay/_schema.json``、日志与 artifacts，再进入分析阶段。


.. _skills-experiments-analysis-6:

分析工作流
~~~~~~~~~~

``agentsociety-analysis`` 面向已完成实验的数据解释、图表和报告生成。当前 replay 数据位于
``run/replay/``，可通过 ``ReplayReader`` / DuckDB 读取；如果 ``_schema.json`` 不存在，应回到 ``run-experiment`` 或配置修复阶段。

推荐流程：

1. **加载上下文**：读取 hypothesis、experiment config、steps 和 run 元数据。
2. **确认问题**：明确本次分析是验证假设、解释异常、比较组间差异，还是生成报告。
3. **探索数据**：列出 replay dataset，查看 schema、行数、关键字段和缺失情况。
4. **提出发现**：先给出可检验发现，再决定需要哪些图表。
5. **生成图表**：单实验默认最多 5 张图；每张图在报告中必须有一句说明。
6. **写报告**：单实验输出到 ``presentation/hypothesis_{id}/``，跨实验综合输出到 ``synthesis/``。

报告与状态目录约定：用户可见报告写在 ``presentation/`` 与 ``synthesis/``；harness 机器状态在 ``.agentsociety/analysis/``；不要在 ``presentation/`` 下再建旧式 ``analysis/`` 目录。

常用命令：

.. code-block:: bash

   python .agentsociety/bin/ags.py analysis load-context --workspace . --hypothesis-id 1 --experiment-id 1
   python - <<'PY'
   from agentsociety2.storage import ReplayReader
   reader = ReplayReader("hypothesis_1/experiment_1/run/replay")
   for dataset in reader.load_dataset_catalog():
       print(dataset["dataset_id"], dataset["table_name"])
   reader.close()
   PY

.. _skills-experiments-analysis-12:

实验技能 (experiment)
~~~~~~~~~~~~~~~~~~~~~

.. figure:: /_static/images/experiment_workflow.svg
   :alt: 实验设计、配置与执行：工作区文件到运行产物
   :width: 90%
   :align: center
   :class: doc-figure

   实验设计、配置与执行：工作区文件到运行产物

左侧是研究设计，中间是可执行配置，右侧是运行产物。新实验的时序数据写入 JSONL replay，恢复状态写入 checkpoint；二者用途不同，具体布局见 :doc:`/storage`。

.. code-block:: python

   from pathlib import Path
   from agentsociety2.skills.experiment import (
       start_experiment, get_experiment_status,
       get_available_env_modules, get_available_agent_modules
   )

   # 获取可用模块
   env_modules = get_available_env_modules()
   agent_modules = get_available_agent_modules()

   # 启动实验
   await start_experiment(
       workspace_path=Path("./workspace"),
       hypothesis_id="1",
       experiment_id="1"
   )

.. _skills-experiments-analysis-11:

分析技能 (analysis)
~~~~~~~~~~~~~~~~~~~

.. figure:: /_static/images/analysis_workflow.svg
   :alt: 分析工作流：数据核验、发现、资源与报告
   :width: 90%
   :align: center
   :class: doc-figure

   分析工作流：数据核验、发现、资源与报告

从 replay 读取数据并生成图表，报告写入 ``presentation/``，跨实验综合写入 ``synthesis/``；harness 状态保存在 ``.agentsociety/analysis/``。

.. code-block:: python

   from pathlib import Path

   from agentsociety2.storage import ReplayReader
   from agentsociety2.skills.analysis import ContextLoader

   workspace = Path("./workspace")
   context = ContextLoader(workspace).load_context("1", "1")
   reader = ReplayReader(workspace / "hypothesis_1" / "experiment_1" / "run" / "replay")
   datasets = reader.load_dataset_catalog()
   rows = reader.fetch_dataset_rows(
       reader.get_dataset_by_id("core.agent_profile"),
       limit=5,
   )
   reader.close()

跨实验对比不再使用独立综合 skill，而是作为
``agentsociety-analysis`` 的 Stage 5 在 Claude Code 中完成。

.. _skills-experiments-analysis-10:

论文写作
~~~~~~~~

完成分析报告、核对图表与证据后，可通过 ``paper-toolkit`` 继续论文写作。研究技能负责文献、假设、实验与分析，各阶段的产物可供写作流程继续使用。

.. _skills-experiments-analysis-9:

完整工作流示例
--------------

下面是一个使用 Claude Code Skills 的典型研究工作流：

1. **定义研究话题** - 编辑 ``TOPIC.md``
2. **文献检索** - 使用 ``/agentsociety-literature-search``
3. **创建假设** - 使用 ``/agentsociety-hypothesis add``
4. **配置实验** - 使用 ``/agentsociety-experiment-config validate/prepare/run``
5. **执行实验** - 使用 ``/agentsociety-run-experiment start``
6. **分析结果** - 使用 ``/agentsociety-analysis``
7. **生成论文** - 使用独立 ``paper-toolkit`` 工作流

.. _skills-experiments-analysis-8:

配置
----

研究技能使用相同的 LLM 配置。可以通过环境变量为特定技能配置不同的模型：

.. code-block:: bash

   # 默认 LLM
   export AGENTSOCIETY_LLM_MODEL="gpt-5.5"

   # 代码生成（实验设计、分析）
   export AGENTSOCIETY_CODER_LLM_MODEL="gpt-5.5"
