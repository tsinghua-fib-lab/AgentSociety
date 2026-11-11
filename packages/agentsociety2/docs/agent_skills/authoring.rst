技能扩展与调试
==============

.. _agent-skills-authoring-15:

环境类 Skill（``env:`` 前缀）
-----------------------------

以 ``env:`` 开头的 ``skill_id`` 会被 ``execute_skill_script`` 重定向到 ``ask_env``（走环境路由
``RouterBase``），而非执行脚本。用于把“查询/操作仿真环境”包装成 skill 暴露给 LLM。这类 skill 不需要
``entrypoint``。


.. _agent-skills-authoring-14:

SkillRegistry API
-----------------

``SkillRegistry`` 是技能的发现中心（位于 :mod:`agentsociety2.agent.base.skill_registry`）。在大规模仿真下它是共享只读单例（不再每 agent 复制）。

.. list-table::
   :widths: 38 62
   :header-rows: 1

   * - 方法
     - 说明
   * - ``scan_builtin(root=None)``
     - 扫描内置技能。
   * - ``scan_custom(skills_root, namespace="custom")``
     - 扫描自定义技能。
   * - ``scan_env(skills_dir, env_name)``
     - 扫描环境模块提供的技能。
   * - ``list_all()``
     - 返回所有 ``SkillDescriptor``。
   * - ``get(skill_id)`` / ``find_by_name(name)``
     - 按 id / 名称查询。
   * - ``read_skill_doc(skill_id)`` / ``read_skill_file(skill_id, relative_path)``
     - 读取 ``SKILL.md`` 正文 / skill 内文件。
   * - ``list_hooks(hook_type)``
     - 返回声明了某 hook 的技能。

``SkillDescriptor`` 是每个 skill 的元数据（``skill_id`` / ``name`` / ``description`` / ``script`` /
``hooks`` / 来源路径等）。激活、脚本执行与 hook 调度由 ``AgentSkillRuntime``（见 :doc:`/api/skills`）负责，``AgentBase`` 持有其实例 ``self.skill_runtime``。


.. _agent-skills-authoring-13:

自定义 Skill 最小示例
---------------------

目录：

.. code-block:: text

   {workspace}/custom/skills/hello-skill/
   ├── SKILL.md
   └── scripts/
       └── hello_skill.py

``SKILL.md``：

.. code-block:: markdown

   ---
   name: hello-skill
   description: Add a short greeting into the step log when greeting is relevant
   script: scripts/hello_skill.py
   ---

   # Hello Skill

   Write a greeting to the workspace.

``scripts/hello_skill.py``（``entrypoint`` + CLI 共用派发）：

.. code-block:: python

   import contextvars
   import json
   from pathlib import Path
   from typing import Any

   _WORKSPACE_ROOT: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
       "hello_workspace_root", default=None
   )

   def entrypoint(argv: list[str], ctx: Any) -> str:
       root = Path(str(getattr(ctx, "workspace_root"))).resolve()
       _WORKSPACE_ROOT.set(root)
       (root / "hello.txt").write_text("hello-skill: greeted", encoding="utf-8")
       return json.dumps({"ok": True, "summary": "greeted"}, ensure_ascii=False)

   if __name__ == "__main__":
       # 手动 CLI 运行仍可用（运行时经 skill_worker.py 调用 entrypoint）
       raise SystemExit(0 if entrypoint([], type("C", (), {"workspace_root": "."})()) else 1)

放进 ``custom/skills/`` 即被热加载；激活后主 LLM 会在合适上下文选择它执行。


.. _agent-skills-authoring-12:

编写 Skill 的检查清单
---------------------

* 内置目录放在 ``agent/skills/<name>/``；自定义目录放在工作区 ``custom/skills/<name>/``。
* 有 ``SKILL.md``：frontmatter 含 ``name``、精炼可操作的 ``description``、可选 ``script`` / ``hooks``。
* 若有脚本：提供 ``def entrypoint(argv, ctx) -> str`` 并接受 ``ctx``；工作区根取自
  ``ctx.workspace_root``；结果用 ``return`` 返回；用 ``contextvars`` 承载调用状态；CLI 派发与
  ``entrypoint`` 共用同一函数。
* 若声明 ``pre_step`` hook，输出要自包含、可直接作为 agent 指引（会被包进 ``<skill_hooks>``）。
* 参考资料放 ``references/``，``SKILL.md`` 里点名引用，按需被读取。


.. _agent-skills-authoring-11:

参考
----

* :doc:`/agents` - ``PersonAgent`` 使用说明
* :doc:`/architecture` - Ray 执行模型与 ``ServiceProxy``
* :doc:`/api/skills` - ``SkillRegistry`` / ``AgentSkillRuntime`` API
* 源码 ``agentsociety2/agent/skills/README.md`` - 技能子系统最权威说明
* ReAct: Yao et al. (2022), https://arxiv.org/abs/2210.03629
