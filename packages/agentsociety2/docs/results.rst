.. _workbench-results:

回放、分析与报告
================

本页按检查顺序介绍实验结果：先确认运行与数据，再查看回放，最后组织分析和报告。记录格式与读取 API 见 :doc:`storage`，研究流程见 :doc:`research_workflow`。

先确认实验已经运行
------------------

通过 CLI 或研究技能执行时，在实验的 ``run/`` 中检查 ``pid.json`` 与 ``output.log``；直接调用 SDK 时，检查终端输出与 ``SOCIETY_STEP.json``。然后核对 ``replay/_schema.json`` 和数据文件。后端启动成功只说明 API 可用；实验仍需另行执行。

``completed_with_errors`` 表示运行包含错误，应先定位失败步骤再解释结果。使用 ``--replay-disable`` 的运行不会生成可供此页面使用的 replay 数据；恢复文件也不能代替时序记录。

在工作台查看回放
----------------

在项目树展开 **研究话题 → 假设 → 实验 → 运行结果**，点击 **Replay 数据**；也可右键实验打开回放。

* 播放、暂停、调速或拖动时间轴，检查不同时间步。
* 点击 Agent 查看画像、当前状态与历史记录；原始表格用于核对具体数值。
* 在环境面板查看模块状态与原始数据；字段取决于该模块实际写入的数据集。

没有地理数据时，回放使用非地理布局；屏幕上人物的相对位置不代表真实坐标。地图、Agent 状态和环境面板是否可用，取决于 replay catalog 中的数据集及其 capability。

分析阶段
--------

运行研究助手的 ``agentsociety-analysis`` 技能前，确认它已同步到工作区。当前分析流程按以下阶段组织：

.. list-table::
   :widths: 22 48 30
   :header-rows: 1

   * - 阶段
     - 工作内容
     - 检查重点
   * - ``frame``
     - 明确分析问题与计划
     - 比较对象与证据来源
   * - ``explore``
     - 数据检查与按需 EDA
     - 字段、样本量与缺失值
   * - ``claims``
     - 记录发现及其证据
     - 发现是否由数据支持
   * - ``refine``
     - 完善分析、图表与图表说明
     - 图表与发现是否对应
   * - ``produce``
     - 生成并审阅双语报告
     - 结论、资源引用与局限
   * - ``synthesis``
     - 汇总工作区中的研究发现
     - 跨实验比较与一致性

前五个阶段按假设记录状态，``synthesis`` 单独记录工作区级状态。结构校验、阶段评议与研究者判断分别承担不同作用；门禁通过不等于结论已被科学验证。

在已初始化且同步分析技能的工作区，可查看分析状态：

.. code-block:: bash

   python .agentsociety/bin/ags.py analysis status --workspace . --hypothesis-id 1

将编号替换为实际假设编号。需要 EDA 时按 :doc:`installation` 安装相应可选依赖；不必为每张表生成完整剖析。分析命令与 Python 接口见 :doc:`skills`。

报告和过程文件
--------------

.. code-block:: text

   presentation/hypothesis_<id>/
   ├── report_zh.md / report_zh.html
   ├── report_en.md / report_en.html
   ├── charts/
   ├── assets/
   └── data/

``charts/`` 保存图表，``assets/`` 保存报告引用的资源，``data/`` 保存分析数据。综合报告位于 ``synthesis/``；分析计划、发现与阶段状态保存在 ``.agentsociety/analysis/``，不要混入用户报告目录。

在项目树打开报告后，核对图表、资源链接与证据引用。分析结论应说明对应实验、参数、数据版本和适用范围；仿真中的行为模式不能直接当作现实世界的因果结论。

继续写作或修订
--------------

报告确认后，外部 ``paper-toolkit`` 可读取研究产物继续论文写作，生成内容位于 ``paper/``。SDK 不内置论文生成器；需要在研究助手环境中安装并配置该工具链。

若分析发现输入、测量或设计有问题，应回到相应数据、假设或配置阶段，重新运行并更新报告。修改报告文字不会修复上游实验数据，操作入口见 :doc:`research_workflow`。
