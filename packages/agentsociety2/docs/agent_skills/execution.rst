技能脚本与生命周期
==================

.. _agent-skills-execution-9:

脚本执行模型（按信任级分流）
----------------------------

内置技能使用进程内调用，自定义技能使用独立 worker 子进程。两条路径共用 ``entrypoint(argv, ctx)`` 契约：

.. code-block:: text

   built-in 技能（可信，进程内热路径）:
     ① 原生 hook 函数              ← hook 脚本顶层定义同名无参函数（如 pre_step）时直接调用
     ② entrypoint(argv, ctx)       ← 缓存 import 后进程内调用；实现需自行保证并发安全
     ③ 子进程（python script.py）  ← 无 entrypoint 时的回退

   custom / env 技能（不可信，子进程隔离）:
     ① skill_worker.py 单次子进程  ← 提供 entrypoint 或原生 hook 函数时，worker 导入并只调用该函数
     ② 子进程（python script.py）  ← 无任何可调用函数时的回退，仅使用环境变量白名单

要点：

* ``entrypoint`` / hook 函数契约不变：无论进程内还是 worker 子进程，``entrypoint(argv, ctx)``
  的签名与 ``ctx.workspace_root`` 等上下文都保持一致，skill 作者按同一契约编写即可。
* **隔离而非就地执行**：自定义 / 环境技能即使提供 ``entrypoint`` 或原生 hook 函数，也在
  ``skill_worker.py`` 启动的**单次子进程**中执行——每次调用独立导入模块，启动和导入计入超时；跨调用状态应写入 workspace，不要依赖模块全局变量。该子进程保留宿主 ``os.environ`` （SDK、代理等配置可用）并叠加技能上下文（``SKILL_ID`` / ``SKILL_NAME`` / ``SKILL_DIR`` /
  ``AGENT_WORK_DIR``）。
* **结构化返回**：worker 把函数返回值按 stdout 约定结构化返回；技能自身的 ``print`` 输出转入
  stderr，不会污染结果。
* 旧的“动态包装器”（无 ``entrypoint`` 时以 ``__name__ == "__main__"``
  就地 ``exec`` 脚本）已在 v2.10.0 删除；无 ``entrypoint`` 的脚本一律走子进程，超时后可终止且不改变父进程状态。

.. _agent-skills-execution-8:

entrypoint 契约（推荐所有 skill 脚本遵循）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Skill 脚本可在模块顶层定义一个 ``entrypoint``，runtime（内置进程内直调；自定义经
``skill_worker.py``）会优先调用它：

.. code-block:: python

   def entrypoint(argv: list[str], ctx) -> str:
       """技能入口。

       Args:
           argv: 命令行参数（去掉脚本名之后的部分），与子进程方式的 sys.argv[1:] 一致。
           ctx:  SkillScriptContext，携带本 agent 的运行上下文。
       Returns:
           str: 脚本原本会打印到 stdout 的文本（通常是 YAML/JSON 结果块）。
       """

要点：

* **签名兼容**：runtime 检测形参数量，``entrypoint(argv)`` 与 ``entrypoint(argv, ctx)`` 都支持，强烈建议接受 ``ctx``。
* **返回 stdout**：不要依赖 ``print`` 被 capture；直接 ``return`` 结果字符串。
* **异常即失败**：``entrypoint`` 抛异常 → 记为失败（``exit_code=1``）。不要用 ``sys.exit()``；逻辑失败在返回文本里写 ``ok: false``。
* **幂等加载（内置技能）**：内置技能的进程内路径按 ``(路径, mtime)`` 缓存模块，模块顶层代码只执行一次；``skill_worker.py`` 子进程每次调用重新导入。

.. _agent-skills-execution-7:

SkillScriptContext
~~~~~~~~~~~~~~~~~~

上下文通过 ``ctx`` 显式传入（定义在 ``agent/base/skill_script_context.py``；内置技能进程内直调时由 runtime 构造，自定义技能在 ``skill_worker.py`` 子进程内构造）：

.. list-table::
   :widths: 28 72
   :header-rows: 1

   * - 字段
     - 说明
   * - ``ctx.workspace_root``
     - 本 agent 的工作区根目录（子进程时代对应环境变量 ``AGENT_WORK_DIR``）。
   * - ``ctx.skill_dir``
     - 本 skill 的包根目录。
   * - ``ctx.skill_id`` / ``ctx.skill_name``
     - 注册 id（``namespace@name``）/ 显示名。
   * - ``ctx.env``
     - 子进程方式本会设置的 env 快照（dict）。

.. _agent-skills-execution-6:

并发安全要求（重要）
~~~~~~~~~~~~~~~~~~~~

一次模拟里多个 agent 在**同一个进程**内并发跑各自**内置技能**的 ``entrypoint`` （自定义技能已由
worker 子进程按调用隔离）。下列进程级状态是**共享**的，绝不能在内置技能的 entrypoint 里直接读写，否则产生数据竞争：

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - ❌ 禁止
     - ✅ 替代方案
   * - ``os.environ["AGENT_WORK_DIR"] = ...``
     - 用 ``ctx.workspace_root``
   * - ``os.chdir(workspace)``
     - 用绝对路径（``ctx.workspace_root / ...``）
   * - ``print(...)`` 并依赖 stdout 捕获
     - 在 entrypoint 里 ``return`` 字符串
   * - 模块级可变全局当作“本次调用状态”
     - 用 ``contextvars.ContextVar`` （任务级隔离）

.. _agent-skills-execution-5:

原生 hook 函数快速路径
~~~~~~~~~~~~~~~~~~~~~~

v2.10.0 起，hook 脚本可在模块顶层定义一个与 hook 同名的**无参函数**（``def`` 或 ``async def``），
runtime 检测到后**直接调用该函数**——不打 argparse、不跑脚本其余部分、不阻塞事件循环：

.. code-block:: python

   async def pre_step() -> str:
       from agentsociety2.agent.base.skill_hook_context import get_hook_context

       ctx = get_hook_context()  # HookContext，见下表
       # ...按 ctx.payload["time"] 推导当前状态...
       return yaml_text

上下文不经过参数传入，而是经 contextvars 的 ``get_hook_context()`` 读取（定义在
``agent/base/skill_hook_context.py``）：

.. list-table::
   :widths: 28 72
   :header-rows: 1

   * - 字段
     - 说明
   * - ``ctx.workspace_root``
     - 本 agent 的工作区根目录。
   * - ``ctx.skill_dir``
     - 本 skill 的包根目录。
   * - ``ctx.skill_id``
     - 注册 id（``namespace@name``）。
   * - ``ctx.hook_type``
     - 生命周期 hook 名（``pre_step`` / ``post_step``）。
   * - ``ctx.payload``
     - 生命周期 payload dict（``hook_type`` / ``tick`` / ``time`` / ``agent_id`` / ``step_count``）。

内置技能的 hook 函数在 agent 进程内直调（异步函数用 ``asyncio.wait_for`` 加超时；同步函数保持内联热路径）；自定义技能的同名函数在 ``skill_worker.py`` 子进程内以相同的 ``HookContext`` 契约执行。函数返回值即 hook 输出（非字符串会序列化为 JSON）。这是热路径 hook（如 daily-guidance 的
``pre_step``）的推荐写法。

.. _agent-skills-execution-10:

生命周期 Hook（``pre_step`` / ``post_step``）
---------------------------------------------

在 ``SKILL.md`` 的 ``hooks:`` 里声明，每个仿真步自动触发：

* ``pre_step``：``agent.step()`` 开头、ReAct 循环之前运行。典型用途：根据仿真时钟推导当前状态，**注入到首轮上下文**。
* ``post_step``：ReAct 循环之后运行。典型用途：记录实际行为、收尾。

hook 脚本有两种形态：脚本形式以 ``--args-json`` 形式接收 payload（含 ``hook_type`` / ``tick`` /
``time`` / ``agent_id`` / ``step_count``）；**推荐**的函数形式则是在顶层定义同名无参函数、经
``get_hook_context()`` 读取 payload（见上文“原生 hook 函数快速路径”）。**改版后**，``pre_step``
的输出渲染为专用的 ``<skill_hooks>`` XML 分块，出现在
ReAct 首条 user 消息中——而不是被塞进通用 observation dump（那容易被 LLM 忽略）。例如：

.. code-block:: xml

   <skill_hooks>
   <skill_hook skill="built-in@daily-guidance" hook="pre_step" ok="true">
   active_segment:
     activity: sleep
     location_policy: home_aoi
   </skill_hook>
   </skill_hooks>

这样 agent 不必再花一轮观察去“重新发现”状态。
