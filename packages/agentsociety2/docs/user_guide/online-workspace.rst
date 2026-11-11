.. _online-workspace:

在线工作空间
==============================

我们推荐使用在线平台进行实验，平台已预装 agentsociety2 库、AI Social Scientist 插件和 Claude Code CLI。

平台地址：https://agentsociety2.fiblab.net/

注册与登录
----------

1. 打开平台主页，点击"登录"。

2. 如果没有账号，点击"注册"完成注册流程。已有 FIBLAB 账号的用户可直接登录。

.. note::

   登录成功后，您可能需要联系平台管理员审批账号权限，审批通过后刷新页面即可。

创建工作空间
------------

1. 进入工作区管理页面，点击"创建工作空间"，输入名称后确认。

.. figure:: ../_static/images/user_guide/workspace_create.png
   :alt: 创建工作空间
   :width: 80%
   :align: center
   :class: doc-figure

   在平台中创建开发环境；进入 IDE 后，还需要打开具体的研究项目文件夹。

2. 等待工作空间状态从"创建中"变为"运行中"。

3. 点击工作空间可查看 **Coder 账号密码**、 **平台提供的 LLM API 端点**和 **API Key** 等信息，请妥善保存。

4. 复制页面上方的 Coder 账号信息，点击"打开"进入开发环境。

5. 在 Coder 页面中选择 **code-server** （推荐）或 **VS Code Desktop** 打开开发环境。

.. figure:: ../_static/images/user_guide/coder_open.png
   :alt: 选择 code-server 或 VSCode Desktop
   :width: 80%
   :align: center
   :class: doc-figure

   选择打开开发环境的客户端。code-server 是浏览器工作台，后端 API 是另一项服务。

.. figure:: ../_static/images/user_guide/codeserver_interface.png
   :alt: code-server 工作台
   :width: 100%
   :align: center
   :class: doc-figure

   打开工作台后，选择具体的研究项目文件夹。
