存储与结果访问
=========================

只想在工作台查看回放或分析报告时，先读 :doc:`results`。本页说明存储布局、写入格式与程序读取方式；外部输入数据见 :doc:`datasets`。

读取运行目录时，先区分三类产物：

* **Replay 目录**： ``<run_dir>/replay/``。``ReplaySink`` / ``ReplayWriter`` 以
  append-only JSONL 写入 replay 数据，并在 ``_schema.json`` 中保存 dataset catalog
  与列元数据。
* **本地工作目录**： ``<run_dir>/artifacts/``、``<run_dir>/agents/agent_<id>/``、
  ``<run_dir>/pid.json`` 等文件，存放 ``ask`` / ``intervene`` 产物、agent workspace
  与运行时元信息。
* **Workspace checkpoint（用于 resume）**：各 env 模块把动态状态写入
  ``<run_dir>/env/<module>/state/ENV_STATE.json``，society 把初始化时的不可变全量写入
  ``<run_dir>/SOCIETY.json``，并把每步标量写入 ``<run_dir>/SOCIETY_STEP.json``。这些文件都是原子 JSON 写入，仅供 ``--resume`` 使用，不进入 replay catalog。**Replay 面向分析，是
  append-only 的时序数据；workspace 面向恢复，会覆写最新状态**。

读取结果有三条路径：

* 后端 REST API ``/api/v1/replay/...``。推荐配合前端 / VSCode replay webview 使用。
* :class:`agentsociety2.storage.ReplayReader`，基于 DuckDB 读取 sharded JSONL。
* 直接读取 workspace 中的 ``*.json`` / ``*.jsonl``，用于 agent 行为分析、调试。

.. note::

   新实验不再写入 ``sqlite.db``，也不再写旧的 ``agent_profile``、``agent_status``、
   ``agent_dialog`` 三张框架表。``agentsociety2.storage.models`` 仅保留这些历史
   SQLModel 定义，供旧数据库兼容读取。

Run 目录布局
-----------------

CLI 入口 ``python -m agentsociety2.society.cli`` 以 ``--run-dir`` 指定的目录作为实验
HOME。``ExperimentRunner`` 会在其中创建以下结构：

.. code-block:: text

   <run_dir>/
   ├── replay/
   │   ├── _schema.json                 # dataset catalog + table/column metadata
   │   ├── core_agent_profile.<shard>.jsonl
   │   ├── <prefix>_agent_state.<shard>.jsonl
   │   └── <prefix>_env_state.<shard>.jsonl
   ├── trace/                           # 分布式 trace spans（工具/脚本/LLM 调用），trace_<xx>.jsonl 分片
   ├── pid.json                         # 进程信息与终止状态
   ├── artifacts/                       # ask / intervene / questionnaire 产物
   └── agents/
       └── agent_0001/
           ├── config.json              # 静态配置（create 时写一次）
           ├── AGENT.json               # 动态自描述快照（含 world_description；每步 to_workspace 更新）
           ├── TODO.json                # 跨步任务列表（todo_* 工具持有）
           ├── MEMORY.md                # 运行时记忆摘要（由 episodes 派生）
           ├── memory/
           │   ├── episodes.jsonl       # event-level memories
           │   └── state.json           # 记忆运行时状态
           └── state/                   # 技能/自定义状态文件（如 daily_guidance/）

当通过后端读取实验数据时，``run_dir`` 是从 ``workspace_path`` +
``hypothesis_<id>/experiment_<id>/run`` 组装得到的，后端会读取其中的
``replay/_schema.json`` 和 JSONL shard。

离线验证回放读写
----------------

以下脚本在临时目录注册数据集、写入一条记录，再通过 ``ReplayReader`` 读取。它不启动仿真或访问模型，不需要模型凭据；临时目录在结束后自动清理。

.. literalinclude:: ../examples/offline/replay_round_trip.py
   :language: python
   :caption: ``examples/offline/replay_round_trip.py``

:download:`下载可运行脚本 <../examples/offline/replay_round_trip.py>`，安装 SDK 后可直接执行。

在已安装 SDK 的环境中，从仓库根目录运行：

.. code-block:: bash

   python packages/agentsociety2/examples/offline/replay_round_trip.py

输出：

.. code-block:: text

   Replay round trip passed.

页面代码直接引用这份脚本。文档构建会执行它，pytest 还会检查数据集元信息、JSONL 文件和读取结果，避免示例与文档各维护一份。

Replay 写入格式
----------------

``ReplaySink`` 是每个进程本地持有的 append-only JSONL writer。``ReplayProxy`` 只携带
``replay_dir`` 与启用标志，可序列化穿过 Ray task / actor 边界；每个消费者在本进程内懒加载自己的 ``ReplaySink``，不再经过中心 SQLite actor。

``<run_dir>/replay/_schema.json`` 的顶层结构如下：

.. code-block:: json

   {
     "tables": {
       "core_agent_profile": {
         "columns": [{"name": "id", "type": "INTEGER"}],
         "primary_key": ["id"],
         "indexes": [["name"]]
       }
     },
     "datasets": {
       "core.agent_profile": {
         "dataset_id": "core.agent_profile",
         "table_name": "core_agent_profile",
         "module_name": "AgentSociety",
         "kind": "entity_static",
         "entity_key": "id",
         "step_key": null,
         "time_key": null,
         "default_order": ["id"],
         "capabilities": ["agent_profile", "entity_static"],
         "version": 1,
         "columns": [{"name": "id", "type": "INTEGER"}]
       }
     }
   }

每个物理表写成 ``<table_name>.<shard>.jsonl``。shard 由行内容的 CRC32 计算得到，因此跨 shard 的自然顺序不保证稳定；读取时应使用 dataset 的 ``default_order``、
``step_key`` 或 ``time_key`` 显式排序。

常见 capability：

* ``agent_profile``  — agent 静态档案。
* ``agent_snapshot`` — agent per-step 状态。
* ``env_snapshot``   — env per-step 状态。
* ``timeseries``     — 适合按时间轴展开。
* ``geo_point``      — 含 ``lng`` / ``lat``，可在地图上画。
* ``trajectory``     — 适合做轨迹回放。
* ``entity_static``  — 一次性静态实体表。
* ``event_stream``   — 事件流。

写入数据
-----------

环境模块的状态数据有两种写入路径： **声明式** （推荐）和 **手工注册** （事件流、自定义形状）。两条路径都调用同一个 replay writer，注入逻辑由
``AgentSociety`` / 环境 router 完成。

方式 A：声明式 ``_agent_state_columns`` / ``_env_state_columns``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

子类化 :class:`~agentsociety2.env.base.EnvBase` 时，把希望每步写入 replay 的列声明在
class var 里。``EnvBase`` 会在首次写入前自动：

1. 推导表名前缀（PascalCase → ``snake_case``，去 ``Space`` / ``Env`` / ``Module`` 后缀）。
2. 注册 ``{prefix}_agent_state`` 和 / 或 ``{prefix}_env_state`` 的 schema。
3. 调 ``register_dataset`` 写入 ``_schema.json``，capability 默认为
   ``["agent_snapshot", "timeseries"]`` / ``["env_snapshot", "timeseries"]``；如果
   ``_agent_state_columns`` 同时声明了 ``lng`` 和 ``lat``，会额外追加
   ``geo_point`` 和 ``trajectory``。

模块在 ``step()`` 中调用 ``EnvBase._write_agent_state()``、
``EnvBase._write_agent_state_batch()``、``EnvBase._write_env_state()`` 即可。

.. code-block:: python

   from typing import ClassVar
   from agentsociety2.env import EnvBase
   from agentsociety2.storage import ColumnDef


   class EconomySpace(EnvBase):
       _agent_state_columns: ClassVar[list[ColumnDef]] = [
           ColumnDef("currency", "REAL", analysis_role="measure"),
           ColumnDef("income", "REAL", analysis_role="measure"),
           ColumnDef("consumption", "REAL", analysis_role="measure"),
       ]
       _env_state_columns: ClassVar[list[ColumnDef]] = [
           ColumnDef("bank_interest_rate", "REAL", analysis_role="measure"),
       ]

       async def step(self, tick: int, t):
           records = [
               {"agent_id": p.id, "currency": p.currency,
                "income": p.income, "consumption": p.consumption}
               for p in self._persons.values()
           ]
           await self._write_agent_state_batch(self._step, t, records)
           await self._write_env_state(self._step, t,
                                       bank_interest_rate=self._bank_interest_rate)
           self._step += 1

方式 B：手工 ``register_table`` + ``register_dataset``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

事件流（``kind="event_stream"``）或形状不规则的数据，仍可手工注册：

.. code-block:: python

   from agentsociety2.storage import ColumnDef, ReplayDatasetSpec, TableSchema

   schema = TableSchema(
       name="social_media_event",
       columns=[
           ColumnDef("id", "INTEGER", nullable=False),
           ColumnDef("step", "INTEGER", nullable=False, logical_type="step"),
           ColumnDef("t", "TIMESTAMP", nullable=False, logical_type="timestamp"),
           ColumnDef("sender_id", "INTEGER", logical_type="identifier"),
           ColumnDef("event_type", "TEXT", logical_type="enum",
                     enum_values=["post", "follow", "like", "comment", "repost"]),
           ColumnDef("payload", "JSON"),
       ],
       primary_key=["id"],
       indexes=[["step"], ["sender_id"], ["event_type"]],
   )
   await self._replay_writer.register_table(schema)
   await self._replay_writer.register_dataset(
       ReplayDatasetSpec(
           dataset_id="social_media.event",
           table_name="social_media_event",
           module_name=self.name,
           kind="event_stream",
           title="Social Media Event Stream",
           entity_key="sender_id",
           step_key="step",
           time_key="t",
           default_order=["step", "id"],
           capabilities=["event_stream", "social_event"],
       ),
       schema.columns,
   )

   await self._replay_writer.write("social_media_event", {...})
   await self._replay_writer.write_batch("social_media_event", [{...}, {...}])

读取数据
-----------

方式 1：后端 REST API（推荐）
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

启动 ``python -m agentsociety2.backend.run`` 后，replay API 挂在
``/api/v1/replay``。所有请求都带 ``workspace_path`` query 参数，后端据此定位
``<workspace_path>/hypothesis_<id>/experiment_<id>/run/replay``。

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - 路径
     - 作用
   * - ``GET /info``
     - 实验摘要：``total_steps``、``start_time``、``end_time``、``agent_count``。
   * - ``GET /datasets``
     - 返回当前实验所有 dataset 及列元数据。
   * - ``GET /datasets/{dataset_id}``
     - 单个 dataset 详情。
   * - ``GET /datasets/{dataset_id}/rows``
     - 分页行查询。
   * - ``GET /panel-schema``
     - 前端 panel / 地图布局所需的 dataset 分组。
   * - ``GET /steps/{step}/bundle``
     - 某一步的合并快照：所有 agent 状态、env 状态、地理位置。
   * - ``GET /timeline``
     - ``step → t`` 映射，用于时间轴。
   * - ``GET /agents/profiles``
     - agent profile 列表（优先读 ``core.agent_profile``，否则从主 agent state dataset 推导）。

完整前缀为 ``/api/v1/replay/{hypothesis_id}/{experiment_id}/...``。

``/datasets/{dataset_id}/rows`` 支持 ``page``、``page_size``、``order_by``、
``desc_order``、``step``、``entity_id``、``start_step``、``end_step``、
``max_step``、``columns`` 和 ``latest_per_entity``。

方式 2：ReplayReader + DuckDB
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``ReplayReader`` 读取 ``_schema.json``，并把每个 dataset 的 JSONL shard 注册为
DuckDB view。它保留后端使用的 metadata-driven 查询语义：

.. code-block:: python

   from agentsociety2.storage import ReplayReader

   reader = ReplayReader("hypothesis_1/experiment_1/run/replay")
   datasets = reader.load_dataset_catalog()
   state = reader.get_dataset_by_id("economy.agent_state")
   rows = reader.query_dataset_rows(
       state,
       page=1,
       page_size=200,
       step=42,
       columns=["agent_id", "step", "currency"],
   )
   reader.close()

返回值约定：catalog 中标为 ``JSON`` 的列会被自动反序列化为 Python 对象；
``TIMESTAMP`` 列返回 ``datetime`` 对象，后端响应会编码为 ISO-8601 字符串。

方式 3：直接读 workspace 文件
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``<run_dir>/artifacts/`` 是 CLI 在 ``ask`` / ``intervene`` / ``questionnaire``
步骤上保存的 Markdown 产物，可直接展示给研究者。

``<run_dir>/agents/agent_<id>/`` 中常用文件：

* ``config.json`` — agent 静态配置。
* ``AGENT.json`` — 动态自描述快照（含 ``world_description``；每步 ``to_workspace`` 更新）。
* ``TODO.json`` — 跨步任务列表（``todo_*`` 工具读写）。
* ``MEMORY.md`` — 运行时记忆摘要。
* ``memory/episodes.jsonl`` — event-level memories。
* ``state/*.json`` — 技能与用户自定义状态文件（如 ``state/daily_guidance/`` 下的每日 Story）。

工具、技能脚本与 LLM 调用的过程日志以 trace span 形式写入共享的
``<run_dir>/trace/trace_<xx>.jsonl`` （按 ``trace_id`` 前缀分片的 JSONL），不在 agent
workspace 内。

这些文件适合调试 agent 行为、复现 thread 上下文、审视技能执行过程；它们不进入
replay dataset。

兼容旧数据库
----------------

旧版本（v1 或早期 v2）数据库里可能仍包含 ``agent_profile``、``agent_status``、
``agent_dialog`` 三张框架表。新 backend replay API 面向 ``run/replay`` 目录；如果需要读取历史 ``sqlite.db``，请使用 ``agentsociety2.storage.models`` 中保留的兼容模型或旧版分析脚本。
