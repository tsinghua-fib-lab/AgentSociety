开发指南
=================

只修改文档时，先运行中英文严格构建与图片引用检查；修改行为时，再运行对应 SDK、扩展或前端检查。具体步骤如下。

本指南面向 AgentSociety 2 的贡献者。仓库中的开发约定以 `CONTRIBUTING.md <https://github.com/tsinghua-fib-lab/agentsociety/blob/main/CONTRIBUTING.md>`_ 为准。

设置开发环境
------------------

在仓库根目录安装 SDK 的开发与文档依赖：

.. code-block:: bash

   uv sync
   cd packages/agentsociety2
   uv sync --extra dev --extra docs

运行测试与检查
------------------

在 ``packages/agentsociety2/`` 下执行：

.. code-block:: bash

   MEM0_TELEMETRY=False ANONYMIZED_TELEMETRY=False uv run pytest
   uv run ruff check .
   uv run ruff format --check .

扩展与前端的安装、检查及构建分别在各自目录运行：

.. code-block:: bash

   # From the repository root
   cd extension
   npm ci
   npm run check

   cd ../frontend
   npm ci
   npm run lint
   npm run build

扩展开发与截图说明见 `extension/docs/DEVELOPMENT.md <https://github.com/tsinghua-fib-lab/agentsociety/blob/main/extension/docs/DEVELOPMENT.md>`_；网页截图与浏览器回归说明见 `frontend/README.md <https://github.com/tsinghua-fib-lab/agentsociety/blob/main/frontend/README.md>`_。

启动后端
------------------

.. code-block:: bash

   uv run python -m agentsociety2.backend.run

默认监听 ``127.0.0.1:8001``，运行中的 API 文档位于 ``/docs``。HTTP 接口与调试示例见 :doc:`api/http`，后端模块与请求模型的 Python 接口见 :doc:`api/backend`。

构建文档
------------------

在 ``packages/agentsociety2/docs/`` 下执行：

.. code-block:: bash

   make html-zh SPHINXOPTS="-W --keep-going"
   make html-en SPHINXOPTS="-W --keep-going"

输出分别位于 ``_build/html/zh/`` 与 ``_build/html/en/``。修改正文后，使用 ``make update-po`` 更新英文目录，完成翻译后再执行 ``make html-en``。

实时预览与翻译检查
------------------

文档依赖已包含实时预览工具。从仓库根目录启动，修改正文、示例或 Python 文档字符串后，浏览器会自动刷新：

.. code-block:: bash

   make docs-live
   # English preview, using a separate port
   make docs-live DOCS_LANGUAGE=en DOCS_PORT=8002

默认中文预览地址是 ``http://127.0.0.1:8000``，仅监听本机。预览输出在 ``docs-preview/zh/`` 或 ``docs-preview/en/``；英文预览使用已维护的翻译目录，不会自动翻译新增文字。

提交前执行 ``make ci-docs-build`` 与 ``make ci-docs-browser``，分别检查中英文构建、翻译、真实离线脚本和页面交互。翻译目录中的缺失、模糊和未使用条目都会报错。需要测试网络或模型的示例应另外验收，不加入普通文档构建。

结构与扩展入口
------------------

* :doc:`architecture`：运行时架构、执行与恢复。
* :doc:`custom_modules`：新增智能体与环境模块。
* :doc:`module_and_parameter_management`：模块发现与预填充参数。
* :doc:`agent_skills`：技能运行时契约。
* :doc:`contributing`：报告问题与提交更改。

发布流程
------------------

版本号、变更日志、标签与发布检查统一遵循仓库 `CONTRIBUTING.md <https://github.com/tsinghua-fib-lab/agentsociety/blob/main/CONTRIBUTING.md>`_，避免各处文档维护不同的发布步骤。

规范参考
--------

* `Semantic Versioning <https://semver.org/>`_：版本号含义；本项目的组件版本与发布标签以仓库贡献指南为准。
* `Conventional Commits <https://www.conventionalcommits.org/en/v1.0.0/>`_：提交类型与标题格式。
* `reStructuredText 标记入门 <https://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html>`_：内联代码、加粗与列表的写法。
