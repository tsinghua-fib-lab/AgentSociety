组织一次研究
============

本页说明怎样把研究问题推进到实验和报告。工作台安装见 :doc:`user_guide`，具体技能与 Python 接口见 :doc:`skills`。

协作角色
--------

AgentSociety 2 将研究助手、仿真参与者与研究者连接在同一个研究工作区中：研究助手组织任务，仿真参与者产生行为响应，研究者审阅关键决策与证据。

.. list-table::
   :widths: 25 75
   :header-rows: 1

   * - 角色
     - 在工作区中做什么
   * - 人类研究者
     - 明确研究问题，确认假设、实验设计与结论；检查中间产物并决定如何修订。
   * - AI Social Scientist
     - 通过研究技能整理文献、准备数据、配置和执行实验、分析结果并整理报告。
   * - Silicon Participants
     - 仿真中的 Agent；按画像、技能与环境规则行动，留下可检查的运行记录。

从问题到产物
------------

.. list-table::
   :widths: 20 40 40
   :header-rows: 1

   * - 阶段
     - 核对内容
     - 工作区入口
   * - 界定范围
     - 研究对象、比较目标、数据来源，以及人数、步数和运行预算
     - ``TOPIC.md``
   * - 文献与假设
     - 理论依据、可检验关系、对照与处理条件
     - ``papers/``、``hypothesis_*/HYPOTHESIS.md``
   * - 设计实验
     - 变量、测量方式、干预与所需 Agent / 环境模块
     - ``SIM_SETTINGS.json``、``EXPERIMENT.md``
   * - 配置仿真
     - 数据到画像或状态的映射、模块参数与执行步骤
     - ``init/init_config.json``、``init/steps.yaml``
   * - 执行实验
     - 运行状态、失败步骤、数据是否写出
     - ``run/pid.json``、``run/output.log``、``run/replay/``
   * - 分析结果
     - 发现与证据的对应关系、图表、局限与跨实验比较
     - ``presentation/``、``synthesis/``
   * - 整理论文
     - 已核对的结论、引用及报告资源
     - 外部 ``paper-toolkit`` 的 ``paper/``

研究过程中可以回到先前阶段修订。范围记录在 ``TOPIC.md``，进度由研究管线管理。修改假设、数据或配置后，检查并重新生成受影响的运行记录与报告。

在工作台中推进
--------------

1. 打开具体研究文件夹，完成模型配置并初始化工作区。
2. 在技能管理的 **Claude** 标签页同步研究管线及所需技能；在 **AI 对话** 中说明当前任务，并附带相关文件。
3. 助手提出下一步方案后，核对输入和目标，再执行对应研究步骤。
4. 在项目树检查产物；需要更改研究方向时，从相关假设或配置阶段修订。

使用外部数据时，先阅读 :doc:`datasets`；执行方法见 :doc:`cli`；结果检查见 :doc:`results`。

继续已有工作
------------

在已初始化且同步了 ``agentsociety-research-pipeline`` 的工作区根目录，使用安装 SDK 的 Python 环境查看当前位置：

.. code-block:: bash

   python .agentsociety/bin/ags.py research-pipeline where-am-i --json

管线状态保存在 ``.agentsociety/progress.json``。研究技能脚本通过 ``.agentsociety/bin/ags.py`` 启动；该入口不会替代技能同步或 Python 依赖安装。缺少脚本时，回到技能管理页同步对应技能，再按 :doc:`user_guide` 检查 Python 配置。

衔接分析与写作
--------------

实验完成后，使用分析技能整理数据、图表与结论，并检查每项结论对应的证据。确认分析结果后，可通过 ``paper-toolkit`` 继续组织引用、撰写稿件和排版。分析产物与报告入口见 :doc:`results`；需要扩展参与者行为时，阅读 :doc:`agent_skills`。
