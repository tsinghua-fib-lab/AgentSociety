技能发现、激活与内置技能
========================

.. _agent-skills-usage-3:

设计目标
--------

* **按需加载**：降低每步不必要的上下文占用与执行开销。
* **可解释选择**：选择依据来自 catalog 中的简短描述，便于调试和复盘。
* **热更新友好**：支持运行时扫描、激活/停用与重载（自定义 skill 放进 ``custom/skills/`` 即被发现）。
* **文件约定解耦**：技能通过 workspace 文件交换状态，而不是互相直接调用。
* **分级执行**：内置技能的 ``entrypoint`` 进程内直调（避免子进程启动；脚本仍需满足并发安全约束）；自定义 /
  环境技能经 ``skill_worker.py`` 子进程隔离执行，隔离进程内状态；文件与环境工具的副作用仍需由技能自身管理。


.. _agent-skills-usage-2:

Skill 目录结构
--------------

内置技能位于 ``agentsociety2/agent/skills/``，自定义技能位于工作区 ``custom/skills/``，环境模块技能由环境提供。``SkillRegistry`` 按目录扫描，用 ``namespace@name`` 作为稳定 ``skill_id``。

.. code-block:: text

   # 内置技能（命名空间 built-in）
   agentsociety2/agent/skills/
   └── daily-guidance/
       ├── SKILL.md            # frontmatter（name/description/script/hooks）+ 行为说明
       ├── scripts/
       │   └── daily_guidance.py
       └── references/

   # 自定义技能（命名空间 custom，热加载）
   {workspace}/custom/skills/
   └── my-skill/
       ├── SKILL.md
       └── scripts/
           └── my_skill.py

   # 环境模块技能（命名空间 env）
   {env_module}/skills/
   └── weather-query/
       └── SKILL.md

扫描规则：每个子目录必须含 ``SKILL.md``，否则跳过；以 ``.`` 或 ``_`` 开头的目录被忽略；同名（同
``skill_id``）先到先得。agent 启动时通过 ``default_activated_skill_ids`` 配置默认激活哪些 skill。


.. _agent-skills-usage-1:

SKILL.md 格式
-------------

每个 skill 目录必须含 ``SKILL.md``，头部用 YAML frontmatter 描述元数据：

.. code-block:: markdown

   ---
   name: daily-guidance
   description: 强制使用：凡是时间尺度在小时及以下的日常行为模拟，必须使用本 Skill ...
   script: scripts/daily_guidance.py
   hooks:
     pre_step: scripts/daily_guidance.py
   ---

   # Daily Guidance

   （激活后被注入 system prompt 的行为说明……）

frontmatter 字段：

.. list-table::
   :widths: 22 78
   :header-rows: 1

   * - 字段
     - 说明
   * - ``name``
     - 显示名，与命名空间组合成 ``skill_id``（``namespace@name``）。
   * - ``description``
     - **目录描述**——选择阶段 LLM 唯一可见的文本，决定是否激活。务必精炼、可操作。
   * - ``script``
     - 可选，默认脚本相对路径（如 ``scripts/daily_guidance.py``）。
   * - ``hooks``
     - 可选，生命周期 hook 脚本映射，键为 hook 类型（``pre_step`` / ``post_step``），值为相对脚本路径。

.. note::

   frontmatter 之后的 Markdown 正文，是 skill 被 **激活后** 注入 system prompt 的行为说明（原样注入
   ``<skill_content>`` 块，不做任何占位符替换或命令注入）。未激活时不进上下文。


.. _agent-skills-usage-0:

可见性与激活
------------

* **可见（visible）**：skill 出现在目录里，LLM 能看到、能选择激活。
* **激活（activated）**：skill 的 ``SKILL.md`` 正文被注入 system prompt，其脚本 / hook 可被调用。

LLM 通过下列工具操作 skill：

.. list-table::
   :widths: 26 74
   :header-rows: 1

   * - 工具
     - 作用
   * - ``activate_skill``
     - 加载某 skill 的 ``SKILL.md`` 进上下文。
   * - ``deactivate_skill``
     - 从上下文移除某 skill。
   * - ``read_skill_file``
     - 读取 skill 内文件（渐进式披露）。
   * - ``execute_skill_script``
     - 执行 skill 脚本。

ReAct 主循环每个 ``step()`` 开始前会刷新可见 skill 集合；``ask`` 模式（外部问答）下只暴露只读工具子集。

.. _daily-guidance:

.. _agent-skills-usage-4:

内置技能：daily-guidance
------------------------

当前唯一内置技能是 ``daily-guidance``（``built-in@daily-guidance``），面向**时间尺度在小时及以下**的日常行为模拟。它让 agent 先形成一天的完整 Story（``state/daily_guidance/YYYY-MM-DD/story.yaml``），再按 Story 指导每个仿真步的行为：

* 用 ``plan --json`` 提交一天的安排：脚本校验后写入 story.yaml。
* **执行状态由时钟推导**：``completed_segments`` / ``current_segment_id`` 是 ``(segments, 当前仿真时间)``
  的函数，由脚本在读取时计算。
* ``pre_step`` hook 每步注入当前 segment：含 ``activity`` 和 ``location_policy``，agent 据此移动与回答问卷。
* 内含 needs-decay 模型与 story revision 能力，用于评估和修正每日安排。

daily-mobility 等实验默认激活该 skill。它也是“进程内 entrypoint + 原生 ``pre_step`` hook 函数（``async def pre_step()`` 快速路径）+ hook 注入”的参考实现（见
``agent/skills/daily-guidance/scripts/daily_guidance.py``）。

旧的 ``observation`` / ``cognition`` / ``plan`` / ``memory`` 四技能已被移除；这些认知/行为能力现在通过自定义 skill + workspace 状态文件 + ``ask_env`` 组合实现。
