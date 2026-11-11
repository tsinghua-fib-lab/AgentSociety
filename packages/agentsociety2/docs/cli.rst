命令行界面
========================================

CLI 从配置文件启动实验，记录进度与日志，并支持从 checkpoint 恢复。首次运行可从下方最小配置开始，再根据实验规模调整批大小与回放设置。

概述
------------

CLI 是运行 AgentSociety 2 实验的主要方式。它提供：

* 实验配置加载和验证
* 步骤化执行跟踪
* 进度持久化（pid.json）
* 灵活的日志配置
* 后台运行支持

基本用法
------------

.. code-block:: bash

   python -m agentsociety2.society.cli [OPTIONS]

必需参数
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - 参数
     - 说明
   * - ``--config`` <PATH>
     - 初始化配置文件路径（``init_config.json``）
   * - ``--steps`` <PATH>
     - 步骤配置文件路径（steps.yaml）

可选参数
~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - 参数
     - 默认值
     - 说明
   * - ``--run-dir`` <PATH>
     - 当前目录
     - 运行输出目录路径
   * - ``--experiment-id`` <TEXT>
     - 无
     - 实验标识符
   * - ``--log-level``
     - INFO
     - 日志级别：DEBUG, INFO, WARNING, ERROR, CRITICAL
   * - ``--log-file`` <PATH>
     - 无
     - 日志文件路径（**后台运行必需**）
   * - ``--batch-size`` <INT>
     - ``AGENTSOCIETY_BATCH_SIZE`` 或 256
     - 每个 ``step_agent_batch`` Ray Task 处理的 agent 数
   * - ``--replay-disable``
     - false
     - 禁用回放写入；需要后续回放或时序分析时应保留回放数据
   * - ``--resume``
     - false
     - 从 ``run_dir/SOCIETY.json`` 和 ``SOCIETY_STEP.json`` 恢复中断的实验。CLI 会恢复
       society 的时钟、步数和各 env 模块状态，并跳过已经完成的 ``RunStep``。``Ask``、
       ``Intervene`` 和 ``Questionnaire`` 会重新执行，产物时间戳也会随之更新；如果
       ``steps.yaml`` 与 checkpoint 不一致，CLI 会给出告警。

运行实验
------------

前台运行（调试模式）
~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   python -m agentsociety2.society.cli \
       --config hypothesis_1/experiment_1/init/init_config.json \
       --steps hypothesis_1/experiment_1/init/steps.yaml \
       --run-dir hypothesis_1/experiment_1/run \
       --log-level DEBUG

日志输出到控制台。

后台运行
~~~~~~~~~~~~~~~~~~~~~~~~~~

**重要**: 后台运行时必须指定 ``--log-file`` 以捕获日志。

.. code-block:: bash

   python -m agentsociety2.society.cli \
       --config hypothesis_1/experiment_1/init/init_config.json \
       --steps hypothesis_1/experiment_1/init/steps.yaml \
       --run-dir hypothesis_1/experiment_1/run \
       --experiment-id "1_1" \
       --log-level INFO \
       --log-file hypothesis_1/experiment_1/run/output.log &

检查实验状态
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: bash

   # 检查 pid.json 查看运行状态
   cat hypothesis_1/experiment_1/run/pid.json

   # 查看日志
   tail -f hypothesis_1/experiment_1/run/output.log

停止实验
~~~~~~~~~~~~~

.. code-block:: bash

   # 查找进程 ID
   pid=$(jq -r '.pid' hypothesis_1/experiment_1/run/pid.json)

   # 发送 SIGTERM 信号
   kill -TERM "$pid"

恢复中断的实验
~~~~~~~~~~~~~~~~~~~~~

实验会在每步结束时原子地写出 checkpoint。即使进程在写入过程中崩溃，已有 checkpoint 也不会被破坏：

* ``run_dir/SOCIETY.json`` —— 初始化时写一次，保存不可变的全量配置，例如 ``agent_specs``、
  env 模块类型和 kwargs、``batch_size``、``steps_hash``。
* ``run_dir/SOCIETY_STEP.json`` —— 每步标量：当前时间、步数、已完成的顶层步数、``terminated``。
* 各 env 模块的状态写到 ``run_dir/env/{module_type}/state/ENV_STATE.json``，具体格式由模块自定。

用 ``--resume`` 从最后完成的步续跑：

.. code-block:: bash

   python -m agentsociety2.society.cli \
       --config hypothesis_1/experiment_1/init/init_config.json \
       --steps hypothesis_1/experiment_1/init/steps.yaml \
       --run-dir hypothesis_1/experiment_1/run \
       --resume \
       --log-file hypothesis_1/experiment_1/run/output.log &

恢复时以 checkpoint 中的 env 模块类型和 kwargs、时钟、步数为准，而不是重新读取 config 文件中的这些值，这可以避免配置漂移。``RunStep`` 会根据游标跳过已完成的部分；``Ask``、``Intervene`` 和
``Questionnaire`` 会重新执行。如果 ``steps.yaml`` 的 hash 与 checkpoint 不一致，CLI 会输出
WARNING。可以用下面的命令校验恢复点：

.. code-block:: bash

   cat hypothesis_1/experiment_1/run/SOCIETY_STEP.json   # step_count / completed_step_count

.. note::

   只有覆盖了 ``to_workspace()`` 和 ``restore()`` 的 env 模块才能在 resume 时恢复动态状态（见 :doc:`env_modules`）。未覆盖的模块 resume 后会回到 fresh 态。

配置文件
------------

``init_config.json``
~~~~~~~~~~~~~~~~~~~~

初始化配置文件定义实验的基本设置：

.. code-block:: json

   {
       "agents": [
           {
               "agent_id": 1,
               "agent_type": "PersonAgent",
               "kwargs": {
                   "id": 1,
                   "profile": {"name": "Alice", "personality": "friendly"}
               }
           }
       ],
       "env_modules": [
           {
               "module_type": "SimpleSocialSpace",
               "kwargs": {
                   "agent_id_name_pairs": [[1, "Alice"]]
               }
           }
       ],
       "codegen_router": {
           "final_summary_enabled": false
       }
   }

``codegen_router`` 块可选。``final_summary_enabled`` 自 v2.10.0 起**默认关闭**：关闭时 env
``ask`` 的最终应答由确定性拼装生成；开启后每次 ask 额外产生一次 LLM summary 调用，会增加调用开销；是否开启取决于是否需要自然语言总结。

steps.yaml
~~~~~~~~~~~~~

步骤配置文件定义实验的执行步骤：

.. code-block:: yaml

   start_t: "2026-01-01T00:00:00"
   steps:
     - type: ask
       question: "Introduce yourself to the group"

     - type: run
       num_steps: 1
       tick: 3600

     - type: intervene
       instruction: "Make everyone feel better"

步骤类型
~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1

   * - 类型
     - 说明
   * - ``run``
     - 运行 ``num_steps`` 个模拟步，每步时长 ``tick`` 秒
   * - ``ask``
     - 只读查询，不修改环境
   * - ``intervene``
     - 读写操作，可以修改环境
   * - ``questionnaire``
     - 向目标 agent 发放问卷（``questionnaire_id``、``questions`` 题目列表，可选
       ``target_agent_ids``），收集结构化回答

输出文件
------------

运行实验后，``run-dir`` 目录将包含：

.. code-block:: text

   hypothesis_1/experiment_1/run/
   ├── pid.json              # 进程信息（PID、启动时间、状态）
   ├── output.log            # 日志文件（如果指定了 --log-file）
   ├── replay/               # _schema.json + sharded JSONL replay datasets
   ├── trace/                # sharded JSONL trace spans
   ├── SOCIETY.json          # 初始化配置 checkpoint
   ├── SOCIETY_STEP.json     # 最近完成步骤 checkpoint
   ├── env/                  # 环境模块状态
   ├── agents/               # agent workspaces
   └── artifacts/            # ask / intervene / questionnaire 产物
       ├── ask_step_0_<timestamp>.md
       ├── intervene_step_2_<timestamp>.md
       └── ...

pid.json 格式
~~~~~~~~~~~~~~~~~~~~~

.. code-block:: json

   {
       "pid": 12345,
       "status": "running",
       "start_time": "2026-03-20T10:30:00",
       "experiment_id": "1_1",
       "simulation_time": "2026-01-01T02:00:00",
       "step_count": 2
   }

``status`` 为 ``running`` / ``completed`` / ``completed_with_errors`` / ``failed``；每个步骤结束时会更新进度字段（``simulation_time`` / ``step_count``），完成或失败时追加 ``end_time``，失败时附带
``error``；``--resume`` 续跑时附带 ``resumed`` / ``resumed_from_step``。

日志级别
------------

可选的日志级别：

.. list-table::
   :header-rows: 1
   :widths: 20 80

   * - 级别
     - 用途
   * - ``DEBUG``
     - 详细的调试信息，包括 LLM 调用
   * - ``INFO``
     - 常规运行信息（默认）
   * - ``WARNING``
     - 警告信息
   * - ``ERROR``
     - 错误信息
   * - ``CRITICAL``
     - 严重错误

示例：完整工作流
------------------------

.. code-block:: bash

   # 1. 准备配置文件
   mkdir -p my_experiment/init my_experiment/run
   # ... 创建 init_config.json 和 steps.yaml ...

   # 2. 前台测试运行
   python -m agentsociety2.society.cli \
       --config my_experiment/init/init_config.json \
       --steps my_experiment/init/steps.yaml \
       --run-dir my_experiment/run \
       --log-level DEBUG

   # 3. 后台生产运行
   python -m agentsociety2.society.cli \
       --config my_experiment/init/init_config.json \
       --steps my_experiment/init/steps.yaml \
       --run-dir my_experiment/run \
       --experiment-id "exp_001" \
       --log-level INFO \
       --log-file my_experiment/run/output.log &

   # 4. 监控运行
   tail -f my_experiment/run/output.log

   # 5. 完成后检查 replay catalog
   python - <<'PY'
   from agentsociety2.storage import ReplayReader
   reader = ReplayReader("my_experiment/run/replay")
   print([d["dataset_id"] for d in reader.load_dataset_catalog()])
   reader.close()
   PY
