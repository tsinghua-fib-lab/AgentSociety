.. _env-config:

模型与后端配置
==============================

新建工作区
----------

在线工作空间中，在左侧文件树新建一个文件夹作为工作区（如 ``demo``），然后通过 ``File → Open Folder`` 打开。

配置向导
--------

首次打开尚未配置的项目文件夹时，扩展会打开配置向导。推荐顺序是：保存仿真 LLM → 初始化研究工作区 → 按需启动后端。向导包含以下步骤，可选项可以跳过：

**步骤 1：一键导入（可选）** — 从 AgentSociety Web 一键导入配置：登录后自动拉取 LiteLLM Key、默认模型与文献 MCP，并创建 Gateway 供应商 Fiblab。不需要可点「跳过」，改为手动逐步填写。

**步骤 2：仿真 LLM** — 填写默认大模型 API 信息并点击验证：

.. list-table::
   :widths: 25 50 25
   :header-rows: 1

   * - 参数
     - 说明
     - 是否必填
   * - LLM API 密钥
     - 大模型服务的 API Key，用于默认对话、分析等核心功能
     - 是
   * - LLM API 基础 URL
     - API 的 base URL，如 ``https://api.openai.com/v1``
     - 是
   * - LLM 模型名称
     - 使用的模型名称，默认 ``gpt-5.5``
     - 是
   * - 推理（thinking）
     - 配置页下拉：跟随网关默认 / 开 / 关；写入 ``AGENTSOCIETY_LLM_THINKING``（``on`` / ``off``）。留空则不发送该参数
     - 否

验证通过后进入下一步。使用兼容接口时仍需核对服务商提供的模型名称、访问权限和参数支持；更多环境变量见 :doc:`/installation`。

**步骤 3：保存配置** — 查看摘要并保存到工作区 ``.env``。保存前应完成密钥与服务地址检查。此时可以先从侧边栏初始化研究工作区，再按需继续启动后端。

**步骤 4：启动后端** — 选择或自动检测 ``PYTHON_PATH``，点击「保存并启动后端」。成功后状态栏显示 Backend 端口；向导会自动进入可选步骤。

.. list-table::
   :widths: 25 50 25
   :header-rows: 1

   * - 参数
     - 说明
     - 推荐值
   * - Python 路径
     - Python 运行环境路径，留空则自动检测已安装 ``agentsociety2`` 的环境
     - ``uv sync`` 后的 ``.venv/bin/python``

**步骤 5：文献检索（可选）** — 配置学术文献 MCP 网关，可跳过。

**步骤 6：EasyPaper（可选）** — 使用 ``/easypaper`` 生成论文时需配置 LLM 与可选 VLM，保存后写入工作区 ``easypaper_config.yaml``；可从仿真 LLM 一键复制，可跳过。

**步骤 7：CLI 网关（可选）** — 配置 Claude Code / Codex 本地 AI Gateway 供应商与路由，可跳过。

完成或退出向导后，可随时通过配置页「打开向导」重新进入。

高级配置
--------

在配置页切换到完整模式后，可展开 **专用与运行** 标签页，按需填写（均可留空，沿用默认 LLM）：

- **专用模型**：代码生成（Coder）、Embedding；Coder 也可单独设置推理开关（``AGENTSOCIETY_CODER_LLM_THINKING``）
- **Python 环境**：扫描并选择解释器
- **文献检索**：MCP URL 与 API Key
- **Claude / Codex 路由**：本地 AI Gateway 供应商池
- **EasyPaper**：``/easypaper`` 论文生成所用的 LLM 与可选 VLM（保存后写入 ``easypaper_config.yaml``）

.. list-table::
   :widths: 25 50 25
   :header-rows: 1

   * - 参数
     - 说明
     - 推荐值
   * - Embedding 模型
     - 文本嵌入模型
     - ``text-embedding-3-large``（维度 ``1024``）
   * - 学术文献检索
     - 学术文献检索 MCP 网关地址
     - ``https://llmapi.fiblab.net/mcp/``

状态栏与输出
------------

- **状态栏**：Backend（端口）、Gateway（路由状态/成功率）、LLM（验证通过时显示模型名）
- **输出通道**：``AI Social Scientist``（主通道，含 ``[API]``、``[Chat]`` 等前缀）、``AI Social Scientist Backend`` 与 ``AI CLI Gateway``
- 扩展默认启用 ``python.terminal.useEnvFile``，集成终端会自动加载工作区 ``.env``

启动后端
--------

配置向导第 4 步或配置页中的「保存并启动后端」会自动保存配置并启动后端服务。也可通过状态栏 Backend 菜单或命令面板启动。

右下角状态栏显示后端运行状态（含端口号）表示启动成功。
