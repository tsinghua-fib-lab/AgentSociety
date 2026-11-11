安装与使用研究助手技能
======================

.. _skills-workspace-2:

选择技能入口
------------

* **推进文献、假设、实验和分析**：在插件技能管理的 **Claude** 标签页，将研究助手技能同步到工作区，再交给 Claude Code / Codex 使用。
* **扩展仿真参与者的行为**：在 **运行时** 标签页管理 Agent 技能，原理与编写方法见 :doc:`/agent_skills`、:doc:`/skill_guide`。
* **连接外部工具或安装第三方技能**：使用 **MCP**、**市场** 标签页，配置对应的服务与来源。

.. _skills-workspace-1:

研究助手技能
------------

研究工作流主要通过 Claude Code 的“skills-first”方式提供：

- AgentSociety 内置研究 skills：随 VSCode 插件打包，在技能管理页查看并同步到工作区。
- Agent 运行时技能：由后端 ``/api/v1/agent-skills/*`` 发现、扫描和导入，供仿真参与者按需激活；不是研究助手的 Claude 技能。

* **agentsociety-literature-search** - 学术文献检索
* **agentsociety-hypothesis** - 假设管理（add, get, list, delete）
* **agentsociety-experiment-config** - 实验配置生成与验证
* **agentsociety-run-experiment** - 实验执行与监控
* **agentsociety-analysis** - 数据分析与跨实验综合
* **agentsociety-scan-modules** - 查找可用模块、查看参数并校验自定义模块是否可加载
* **agentsociety-paper-review** - 对已有稿件进行内部模拟评审，给出证据与研究阶段回访建议
* **agentsociety-create-agent** - 自定义 Agent 生成与校验
* **agentsociety-create-env-module** - 自定义环境模块生成与校验
* **agentsociety-use-dataset / agentsociety-create-dataset** - 使用或整理研究数据集
* **agentsociety-research-pipeline** - 按研究阶段组织任务与产物
* **paper-toolkit** - 独立论文写作工具链入口

.. note::

   本页中的 ``.agentsociety/bin/ags.py`` 命令面向**已初始化的工作区**。运行这些命令还需要将对应研究技能同步到 ``.claude/skills/``，并使用已安装 SDK 的 Python 环境。如果当前目录尚未生成 ``.agentsociety/``，请先执行：

   .. code-block:: bash

      agentsociety-workspace init --target-dir .

   等价入口是 ``python -m agentsociety2.society.workspace init --target-dir .``。

.. _skills-workspace-0:

create-agent 技能
~~~~~~~~~~~~~~~~~

``agentsociety-create-agent`` 用于创建或修订工作区里的自定义 Agent 类型。它不是 PersonAgent 内置认知技能，而是研究工作流中的开发辅助 skill：当实验需要一个当前不存在的 Agent class 时，通常由 ``agentsociety-experiment-config`` 分支调用。

**文件位置与扫描规则**:

- 新 Agent 模块应放在 ``custom/agents/`` 下，例如 ``custom/agents/research/lab_agent.py``。
- 扫描器会读取该目录下的 ``*.py``，但跳过路径片段包含 ``examples/`` 的文件。
- 推荐一个文件一个主要 Agent class；一个文件中存在多个 ``AgentBase`` 子类时，扫描器也能发现。

**基类选择**:

.. list-table::
   :widths: 25 75
   :header-rows: 1

   * - 基类
     - 适用场景
   * - ``AgentBase``
     - 简单实验、博弈/基准场景，开发者自行管理状态。
   * - ``PersonAgent``
     - 需要现有工具决策循环、技能运行时与持久化记忆。

**本地校验**:

.. code-block:: bash

   agentsociety-workspace init --target-dir .
   python .agentsociety/bin/ags.py create-agent --file custom/agents/my_agent.py
   python .agentsociety/bin/ags.py create-agent --file custom/agents/my_agent.py --json

以下命令使用已安装 ``agentsociety2`` 的 Python 环境；若工作区配置了独立解释器，请用该解释器替换 ``python``。

校验器会检查：目标文件为 Python 文件、至少有一个直接继承 ``AgentBase`` 或 ``PersonAgent`` 的类、``ask`` / ``step`` / ``to_workspace`` 均为 ``async def``（同时保持继承的 ``create`` / ``from_workspace`` 工作区契约可用）、模块可动态导入、目标类不是 abstract class。创建完成后，在 VS Code 扩展中执行 **Scan Custom Modules** 让后端重新发现模块。

按任务选择辅助技能
------------------

不知道可用的类名或参数时，先用 ``agentsociety-scan-modules``；已有合适模块时直接配置实验。只有模块能力不足，才进入 ``agentsociety-create-agent`` 或 ``agentsociety-create-env-module``，生成后再扫描与验证。

已有稿件时，可用 ``agentsociety-paper-review`` 检查论点、证据与呈现方式，输出内部模拟评审和建议。它不会自动改稿、重跑实验或更新研究进度；研究者确认后，再由相应研究技能处理需要回访的阶段。写作与排版继续通过独立的 ``paper-toolkit`` 完成。
