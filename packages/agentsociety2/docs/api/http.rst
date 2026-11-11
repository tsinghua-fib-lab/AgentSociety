HTTP API
========

后端为 AI Social Scientist 扩展与网页界面提供 HTTP 接口。需要通过程序读取实验、查询模块或集成回放时，可使用本页介绍的接口文档。直接编写 Python 仿真代码请查阅 :doc:`index` 中的 SDK 参考。

打开接口文档
------------

配置好 :doc:`/installation` 中的运行环境后，在研究工作区启动后端：

.. code-block:: bash

   uv run python -m agentsociety2.backend.run

默认地址为 ``http://127.0.0.1:8001``。扩展管理的后端或自定义部署可能使用其他端口，请以实际后端地址为准。

.. list-table::
   :header-rows: 1
   :widths: 22 23 55

   * - 文档
     - 路径
     - 用途
   * - Swagger UI
     - ``/docs``
     - 按标签浏览接口，查看参数、请求体和响应模型，发送请求。
   * - ReDoc
     - ``/redoc``
     - 连续阅读接口与模型说明。
   * - OpenAPI JSON
     - ``/openapi.json``
     - 导入 API 客户端或生成集成代码；内容由当前后端路由与模型生成。

例如，本地默认后端的 Swagger 地址是 ``http://127.0.0.1:8001/docs``。这些页面由运行中的后端提供；Read the Docs 展示使用说明，不会启动研究工作区或连接你的本地后端。

接口分组
--------

Swagger 中的标签与后端模块对应：

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * - 标签
     - 路径前缀
     - 主要功能
   * - ``experiments``
     - ``/api/v1/experiments``
     - 实验信息、日志与产物。
   * - ``replay``
     - ``/api/v1/replay``
     - 回放元信息与仿真数据查询。
   * - ``modules``
     - ``/api/v1/modules``
     - 可用智能体类与环境模块。
   * - ``custom``
     - ``/api/v1/custom``
     - 自定义模块的扫描、测试与管理。
   * - ``agent-skills``
     - ``/api/v1/agent-skills``
     - 行为技能的查询、导入、创建与上传。
   * - ``prefill-params``
     - ``/api/v1/prefill-params``
     - 工作区预填充参数。

具体 HTTP 方法、完整路径、必填参数和响应字段以所运行版本的 Swagger 或 OpenAPI 为准。后端模块的 Python 接口见 :doc:`backend`。

发送第一个请求
--------------

先检查服务状态，再查询可用模块：

.. code-block:: bash

   curl --fail http://127.0.0.1:8001/health
   # {"status":"healthy"}

   curl --fail 'http://127.0.0.1:8001/api/v1/modules/all?include_custom=false'

这两个请求只读取信息。在 Swagger 中展开接口后，可以用 **Try it out** 填写参数，再用 **Execute** 发送真实请求。导入、创建、清理等操作会修改对应工作区，请在测试工作区中调试。

工作区与访问配置
----------------

实验与回放接口需要 ``workspace_path`` 查询参数，值为后端可访问的研究工作区绝对路径。通过扩展操作时由扩展传入；手动调用时按 Swagger 填写。``WORKSPACE_PATH`` 配置后端允许访问的工作区范围，具体约束见 :doc:`/installation`。工作区目录及实验产物约定见 :doc:`/user_guide/research-project` 与 :doc:`/results`。

后端默认监听回环地址，当前没有内置用户登录认证。LLM 供应商的 API Key 用于调用模型，不是此后端的访问凭据。需要远程访问时，应配置访问认证的反向代理，并按 :doc:`/installation` 设置可信主机与浏览器来源。

无法访问 ``/docs`` 时，先确认后端地址和 ``/health``；页面打开后界面仍空白时，检查浏览器能否加载 Swagger 的外部静态资源。框架提供的文档方式见 `FastAPI 自动文档说明 <https://fastapi.tiangolo.com/features/#automatic-docs>`_。
