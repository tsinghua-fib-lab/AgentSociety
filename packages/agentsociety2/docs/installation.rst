安装
============

系统要求
------------

AgentSociety 2 需要 Python 3.11–3.13。

从 PyPI 安装
-----------------

仅运行 SDK 示例时，安装核心包即可；文档、开发和分析依赖按需添加。工作台安装步骤见 :doc:`user_guide`。

.. code-block:: bash

   pip install agentsociety2

这将安装核心包。如果要安装开发依赖：

.. code-block:: bash

   pip install "agentsociety2[dev]"

对于文档依赖：

.. code-block:: bash

   pip install "agentsociety2[docs]"

分析技能与特定环境的可选依赖：

.. code-block:: bash

   pip install "agentsociety2[analysis]"   # EDA 报告与数据剖析（analysis 技能）
   pip install "agentsociety2[eda]"        # statsmodels 高级统计分析（analysis 技能）
   pip install "agentsociety2[ml]"         # torch 深度学习推荐算法（social_media 环境）

安装所有内容（含以上全部可选依赖）：

.. code-block:: bash

   pip install "agentsociety2[all]"

从源码安装
-------------------

要从最新的源代码安装：

.. code-block:: bash

   git clone https://github.com/tsinghua-fib-lab/agentsociety.git
   cd agentsociety/packages/agentsociety2
   pip install -e .

验证安装
-------------------

要验证您的安装，运行：

.. code-block:: python

   import agentsociety2
   print(agentsociety2.__version__)

您应该能看到版本号被打印出来。

配置
-------------

运行会调用模型的示例前，需要配置服务地址与 API Key。模型名可显式设置；未设置时使用框架默认值。下面使用占位密钥，请替换为自己的配置。

**默认模型配置**

.. code-block:: bash

   # Default LLM (Required - for most operations)
   export AGENTSOCIETY_LLM_API_KEY="your-api-key"
   export AGENTSOCIETY_LLM_API_BASE="https://api.openai.com/v1"
   export AGENTSOCIETY_LLM_MODEL="gpt-5.5"

**高级配置**

对于专门的任务，您可以配置单独的 LLM 实例。如果未设置这些选项，它们将回退到默认 LLM 配置：

.. code-block:: bash

   # Coder LLM (for code-related tasks)
   # Falls back to: AGENTSOCIETY_LLM_API_KEY, AGENTSOCIETY_LLM_API_BASE
   export AGENTSOCIETY_CODER_LLM_API_KEY="your-coder-api-key"      # Optional
   export AGENTSOCIETY_CODER_LLM_API_BASE="https://api.openai.com/v1"  # Optional
   export AGENTSOCIETY_CODER_LLM_MODEL="gpt-5.5"                    # Optional

   # Embedding model (for text embedding and semantic search)
   # Falls back to: AGENTSOCIETY_LLM_API_KEY, AGENTSOCIETY_LLM_API_BASE
   export AGENTSOCIETY_EMBEDDING_API_KEY="your-embedding-api-key"  # Optional
   export AGENTSOCIETY_EMBEDDING_API_BASE="https://api.openai.com/v1"  # Optional
   export AGENTSOCIETY_EMBEDDING_MODEL="text-embedding-3-large"   # Optional
   export AGENTSOCIETY_EMBEDDING_DIMS="1024"                      # Optional

**接口协议与推理（thinking）开关**

``AGENTSOCIETY_LLM_API_TYPE`` 选择接口协议：``openai`` 对应 Chat Completions（默认），
``anthropic`` 对应 Messages。推理控制项未设置时，不额外发送对应的推理参数。

.. code-block:: bash

   # openai（默认）使用 Chat Completions；anthropic 使用 Messages。
   # coder 角色可单独用 AGENTSOCIETY_CODER_LLM_API_TYPE 覆盖。
   export AGENTSOCIETY_LLM_API_TYPE="openai"

   # on / off (also accepts 1/0/true/false). Unset = send nothing.
   export AGENTSOCIETY_LLM_THINKING="off"

   # OpenAI 接口：off 发送 reasoning_effort="none"，on 默认 "medium"；
   # 显式设置本变量后按该值发送。
   # Anthropic Messages：发送显式 thinking 开关（off 为 disabled，on 默认预算 1024 tokens）。
   export AGENTSOCIETY_LLM_REASONING_EFFORT=""

   # 可选的显式控制字段：reasoning_effort / thinking / enable_thinking /
   # chat_template_kwargs / reasoning。未设时按接口协议自动选择。
   export AGENTSOCIETY_LLM_THINKING_FORMAT=""

   # Gateway-specific OpenAI-compatible switch, a JSON object merged into the
   # request's extra_body, e.g. {"enable_thinking": false} or
   # {"thinking": {"type": "disabled"}}. When set, thinking=off sends ONLY this
   # (no reasoning_effort), so the gateway never sees two conflicting switches.
   export AGENTSOCIETY_LLM_EXTRA_BODY=""

   # Per-role overrides for the coder model (env-router code generation);
   # each falls back to the corresponding AGENTSOCIETY_LLM_* value.
   export AGENTSOCIETY_CODER_LLM_THINKING=""            # Optional
   export AGENTSOCIETY_CODER_LLM_REASONING_EFFORT=""    # Optional
   export AGENTSOCIETY_CODER_LLM_EXTRA_BODY=""          # Optional

**数据目录**

.. code-block:: bash

   # Directory for storing agent data, memory and persistence files
   # Default: ./agentsociety_data
   export AGENTSOCIETY_HOME_DIR="/path/to/your/data"

**后端服务**

独立 FastAPI 后端（``python -m agentsociety2.backend.run``）的配置：

.. code-block:: bash

   export BACKEND_HOST="127.0.0.1"     # 监听地址
   export BACKEND_PORT="8001"          # 监听端口
   export WORKSPACE_PATH="/absolute/path/to/research-workspace"
   # 外部部署时显式设置可信 Host（逗号分隔）；后端本身不提供身份认证
   # export BACKEND_TRUSTED_HOSTS="example.com"
   # 跨域网页访问需要显式列出可信 Origin（逗号分隔的完整 URL）
   # export BACKEND_ALLOWED_ORIGINS="https://example.com"

**生成代码执行**

``CodeGenRouter`` 生成代码的执行后端与资源上限：

.. code-block:: bash

   # inprocess（默认）在环境进程内计算；process 开启独立计算进程与硬资源限制
   export AGENTSOCIETY_CODE_EXEC_BACKEND="inprocess"
   # export AGENTSOCIETY_CODE_EXEC_TIMEOUT=10       # 程序执行与工具等待期限（秒）
   # export AGENTSOCIETY_CODE_EXEC_MEMORY_MIB=512   # process 后端每 worker 地址空间上限
   # export AGENTSOCIETY_CODE_EXEC_WORKERS=4         # 共享数值工作进程数上限

详见 :doc:`codegen_execution`。

**工作区路径**

.. code-block:: bash

   # 后端服务工作区根目录（custom/ 文件夹所在位置），用于限制后端可访问的路径
   export WORKSPACE_PATH="/path/to/workspace"

**文献检索服务**

``literature`` 研究技能使用的外部服务（见 :doc:`skills`）：

.. code-block:: bash

   export LITERATURE_SEARCH_MCP_URL="https://llmapi.fiblab.net/mcp/"
   export LITERATURE_SEARCH_API_KEY="your-literature-search-key"

**使用 .env 文件**

您也可以在项目目录中创建 ``.env`` 文件：

.. code-block:: bash

   # 推荐：从仓库根目录复制模板（若你在源码仓库内）
   cp .env.example .env
   # 然后编辑 .env 填入 API Key

.. code-block:: bash

   # Required - LLM API Configuration
   AGENTSOCIETY_LLM_API_KEY=your-api-key
   AGENTSOCIETY_LLM_API_BASE=https://api.openai.com/v1
   AGENTSOCIETY_LLM_MODEL=gpt-5.5

   # Optional - Specialized LLM instances (fallback to default)
   AGENTSOCIETY_CODER_LLM_MODEL=gpt-5.5
   AGENTSOCIETY_EMBEDDING_MODEL=text-embedding-3-large
   AGENTSOCIETY_EMBEDDING_DIMS=1024
   AGENTSOCIETY_HOME_DIR=./agentsociety_data

.. note::

   ``AGENTSOCIETY_LLM_*`` 环境变量是全局 LLM API 配置，用于模型调用。智能体自身的行为（如 ``max_react_turns``、``enable_todo_list``、``disabled_skill_ids``）不通过环境变量设置，而是在实验配置的 ``AgentConfig.kwargs`` 中按智能体指定，见 :ref:`agent-config`。

LLM 调度与本地并发控制
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

LLM 调度由可序列化的 ``LLMClient`` 完成。每个 Ray task、env router actor 或 driver 进程在自己的事件循环中首次调用 LLM 时，本地创建 litellm Router 与 ``AdaptiveSemaphore``。
``AdaptiveSemaphore`` 基于近期延迟和 rate-limit 错误做 AIMD 自适应并发。

.. code-block:: bash

   # Ray CPU 预算（ray.init 的 num_cpus）：封顶每 tick 同时运行的 step_agent_batch
   # Ray Task 数。默认取机器 CPU 核数；调低可为 driver / env actor / trace 留出空间。
   # export AGENTSOCIETY_LLM_RAY_MAX_WORKERS=8

   # 每个本地 LLMClient 的 AIMD 初始并发；无人工上下限，由 AIMD 依延迟/限流自由自调节。
   export AGENTSOCIETY_LLM_RAY_CONCURRENCY=16

   # 每个 step_agent_batch Ray Task 处理的 agent 数；task 数 = ⌈N / BATCH_SIZE⌉，
   # 应 ≥ 同时运行的 worker 数才能打满 CPU（CLI --batch-size 可覆盖）。
   # export AGENTSOCIETY_BATCH_SIZE=256

   # AIMD “慢调用”判定
   export AGENTSOCIETY_LLM_LATENCY_DEGRADE_FACTOR=4.0   # 相对退避因子（相对健康基线的倍数）
   # export AGENTSOCIETY_LLM_SLOW_LATENCY_MS=8000       # 可选：绝对延迟 SLO（毫秒）

.. note::

   ``AGENTSOCIETY_LLM_RAY_CONCURRENCY`` 只是 AIMD 的起点，没有人工上下限——每进程并发会根据近期响应调整，并在延迟或限流恶化时回退。若网关有严格 QPS 上限可调低起点；实际总并发还取决于同时运行的 Ray task 数（``AGENTSOCIETY_LLM_RAY_MAX_WORKERS``）。

.. _standalone-backend:

独立启动后端
------------

插件可管理后端进程；使用 REST API 或自行排查时，也可在研究工作区根目录启动。使用安装了 SDK 的同一 Python 环境，并先按上文准备模型配置：

.. code-block:: bash

   export WORKSPACE_PATH="$PWD"
   export BACKEND_HOST="127.0.0.1"
   export BACKEND_PORT="8001"
   python -m agentsociety2.backend.run --log-level info

在另一个终端运行 ``curl http://127.0.0.1:8001/health`` 检查服务，再用浏览器打开 ``http://127.0.0.1:8001/docs`` 查看当前接口。前台进程用 ``Ctrl+C`` 停止。

``WORKSPACE_PATH`` 必须指向存在的研究根目录；请求中的 ``workspace_path`` 也必须解析到同一目录。切换项目后应重新配置或启动该项目的后端，不能只更换请求参数。

.. list-table::
   :widths: 25 45 30
   :header-rows: 1

   * - 服务
     - 用途
     - 访问入口
   * - 在线平台 / code-server
     - 创建开发环境、打开网页 IDE 与插件
     - 平台给出的工作区链接
   * - AgentSociety 后端
     - 模块、技能、实验和回放 API
     - 默认 ``127.0.0.1:8001``
   * - CLI Gateway
     - Claude / Codex 的可选供应商路由
     - 配置页显示的本地 Gateway 端口

三者分别运行；打开网页 IDE、启动后端或启用 Gateway 都不会自动执行实验。对外托管后端时，需要由部署层提供身份认证，并显式配置可信 Host 和浏览器 Origin。请求模型见 :doc:`api/backend`。

支持的 LLM 提供商
------------------------

AgentSociety 2 通过 LiteLLM 路由模型调用；文档中的默认示例使用 OpenAI 兼容的 Chat Completions 接口：

- ``AGENTSOCIETY_LLM_API_BASE=https://api.openai.com/v1``
- ``AGENTSOCIETY_LLM_MODEL=gpt-5.5``

如果你使用其它 LiteLLM 支持的 OpenAI 兼容网关，请保持同样的环境变量结构，并把 ``AGENTSOCIETY_LLM_API_BASE`` 与模型名替换为该网关提供的值。

.. _litellm: https://github.com/BerriAI/litellm
.. _litellm 文档: https://docs.litellm.ai/
