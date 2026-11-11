Skills 模块
============

本页分为两部分：

* **Research Skills**：``agentsociety2.skills`` 下的科研工作流模块。
* **Agent Skills**：``agentsociety2.agent.base`` 下的技能注册与运行时机制；
  ``agent/skills/`` 目录只承载技能内容（如内置的 ``daily-guidance/``）。

Research Skills（研究技能）
---------------------------

总入口
~~~~~~

.. automodule:: agentsociety2.skills
   :members:

analysis
~~~~~~~~

.. automodule:: agentsociety2.skills.analysis
   :members:

experiment
~~~~~~~~~~

.. automodule:: agentsociety2.skills.experiment
   :members:

hypothesis
~~~~~~~~~~

.. automodule:: agentsociety2.skills.hypothesis
   :members:

literature
~~~~~~~~~~

.. automodule:: agentsociety2.skills.literature
   :members:

.. note::

   当前仓库中可公开使用的 research skills 模块为 ``analysis``、``experiment``、
   ``hypothesis``、``literature``。

Agent Skills（智能体技能）
--------------------------

技能基础设施（发现、可见性/激活、脚本执行、生命周期 hook）已从 ``agent/skills/`` 下沉到
:mod:`agentsociety2.agent.base`。``agent/skills/`` 目录现在只承载技能**内容**（如内置的
``daily-guidance/``）。设计说明见 :doc:`/agent_skills`。

.. py:module:: agentsociety2.agent.base.skill_registry

SkillRegistry
~~~~~~~~~~~~~

.. autoclass:: agentsociety2.agent.base.skill_registry.SkillRegistry
   :members:
   :undoc-members:
   :show-inheritance:

SkillDescriptor
~~~~~~~~~~~~~~~

.. autoclass:: agentsociety2.agent.base.skill_registry.SkillDescriptor
   :members:
   :undoc-members:

AgentSkillRuntime
~~~~~~~~~~~~~~~~~

.. autoclass:: agentsociety2.agent.base.skill_runtime.AgentSkillRuntime
   :members:
   :undoc-members:
   :show-inheritance:

SkillScriptContext
~~~~~~~~~~~~~~~~~~

.. autoclass:: agentsociety2.agent.base.skill_runtime.SkillScriptContext
   :members:
   :undoc-members:

脚本返回类型与注册表协议
~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: agentsociety2.agent.base.skill_runtime.ScriptRunResult
   :members: as_dict
   :no-special-members:

.. autoclass:: agentsociety2.agent.base.skill_runtime.SkillRegistryLike
   :no-members:
   :no-special-members:

SKILL.md Frontmatter
~~~~~~~~~~~~~~~~~~~~

SKILL.md 文件使用 YAML frontmatter 声明 skill 元信息：

.. code-block:: yaml

   ---
   name: my-skill
   description: 触发条件 + 输出结果，选择阶段 LLM 唯一可见的文本
   script: scripts/my_skill.py
   hooks:
     pre_step: scripts/my_skill.py
   ---

frontmatter 之后识别的字段：``name``、``description``（选择阶段唯一可见，决定是否激活）、可选的 ``script``（默认脚本相对路径）与 ``hooks``（生命周期脚本映射，键如 ``pre_step`` /
``post_step``）。Skill 注册 id 形如 ``namespace@name``（内置 ``built-in@``、自定义 ``custom@``）。内置脚本在 agent 进程内经 ``entrypoint(argv, ctx)`` 执行，自定义脚本经 ``skill_worker.py``
隔离子进程执行（详见 :doc:`/agent_skills`）；以
``env:`` 开头的 skill id 会被重定向到 ``ask_env``，走环境路由而非脚本。
