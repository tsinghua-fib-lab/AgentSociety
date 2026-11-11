.. _local-setup:

本地安装与助手配置
==============================

前置条件
--------

- **操作系统**：macOS 或 Linux（Windows 用户建议使用 WSL）
- **Python**：3.11–3.13，推荐使用 `uv <https://docs.astral.sh/uv/>`_ 管理

.. code-block:: bash

   # 安装 uv（macOS/Linux）
   curl -LsSf https://astral.sh/uv/install.sh | sh

安装 agentsociety2
------------------

.. code-block:: bash

   # 使用 uv
   uv venv && source .venv/bin/activate
   uv pip install agentsociety2

   # 或使用 pip
   pip install agentsociety2

.. important::

   请确保安装的是最新版本。查看当前最新版本：https://pypi.org/project/agentsociety2/

安装 AI Social Scientist 插件
--------------------------------

1. 从 `Release <https://github.com/tsinghua-fib-lab/AgentSociety/releases>`_ 下载最新版本的 VSIX 文件。
2. 在 VSCode 中按 ``Cmd/Ctrl + Shift + P``，输入 ``Extensions: Install from VSIX...``。
3. 选择下载的 VSIX 文件完成安装。

配置 Coding Agent
-----------------

插件初始化工作区时会自动同步 AI Social Scientist 的技能到 ``.claude/skills/`` 目录下。您也可以打开技能管理的 **Claude** 标签页手动同步：卡片上的「同步到工作区」按钮按需同步单个技能，页头「更多」菜单中的「将内置模板复制到当前项目」则一次性同步全部内置模板。

.. figure:: ../_static/images/user_guide/sync_skills.png
   :alt: 技能管理 Claude 标签页的同步入口
   :width: 100%
   :align: center
   :class: doc-figure

   Claude 标签页管理研究助手技能。卡片“同步到工作区”只同步选中项；“更多”菜单可复制全部内置模板。

Claude Code（推荐）：

.. code-block:: bash

   npm install -g @anthropic-ai/claude-code

配置第三方中转服务时，创建 ``~/.claude/settings.json``：

.. code-block:: json

   {
     "env": {
       "ANTHROPIC_AUTH_TOKEN": "YOUR_API_KEY",
       "ANTHROPIC_BASE_URL": "YOUR_BASE_URL",
       "ANTHROPIC_MODEL": "claude-sonnet-4-6"
     }
   }

也可以通过扩展的 **Claude / Codex** 区域打开配置页，按 :doc:`/user_guide/cli-gateway` 配置本地网关。

可从扩展侧边栏的“AI 对话”进入协作界面，也可在工作区终端启动 Claude Code。首次使用时按当前客户端提示完成登录。

.. note::

   同步到 ``.claude/skills/`` 的技能可被 Claude Code 和 Cursor 自动识别。插件会尝试为 Codex 建立 ``.codex/skills`` 链接。是否同步成功可在技能页和工作区目录中核对。

客户端官方文档
--------------

客户端的安装、登录与设置语法可查阅以下官方文档。本项目的供应商路由配置见 :doc:`/user_guide/cli-gateway`。

* `Claude Code 入门 <https://code.claude.com/docs/en/overview>`_
* `Claude Code 设置文件 <https://code.claude.com/docs/en/settings>`_
* `Codex CLI <https://developers.openai.com/codex/cli>`_
* `Codex 配置入门 <https://developers.openai.com/codex/config-basic>`_
