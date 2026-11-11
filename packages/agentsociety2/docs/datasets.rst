数据集与输入数据
================

把数据用于实验前，先确认它的字段含义、单位、来源和版本。本页介绍数据资产的使用与打包；实验产生的 replay 数据见 :doc:`storage`。

三类数据放在哪里
----------------

.. list-table::
   :widths: 25 35 40
   :header-rows: 1

   * - 位置
     - 用途
     - 查看方式
   * - ``user_data/``
     - 研究者提供的原始资料或临时输入
     - 项目树的用户数据；CSV 可用表格查看器打开
   * - ``datasets/<id>/``
     - 带说明和元信息、可复用的数据集
     - 项目树的数据集；先打开 README，再查看数据文件
   * - ``hypothesis_*/experiment_*/run/replay/``
     - 仿真执行时记录的画像与时序状态
     - 回放或 ``ReplayReader``，见 :doc:`results`

发现与下载
----------

在已初始化并同步了 ``agentsociety-use-dataset`` 的工作区根目录，使用安装 SDK 的 Python 环境运行：

.. code-block:: bash

   python .agentsociety/bin/ags.py use-dataset list
   python .agentsociety/bin/ags.py use-dataset search --category agent_profiles --limit 10

``list`` 默认查看本地数据集；加 ``--all`` 合并本地与远程目录，加 ``--remote`` 只查看远程目录。搜索和下载访问平台数据服务，与本地仿真后端是不同服务。

选定实际数据集编号后，依次查看 ``info <id>``、``readme <id>``、``files <id>``，再执行 ``download <id>``。默认下载到 ``datasets/<id>/``；使用 ``cat <id> <path>`` 查看本地文件。命令参数可用相应子命令的 ``--help`` 查询。

README 应说明数据来源、采样范围、字段单位、缺失值与编码、文件之间的关联，以及必要的访问或处理方法。这些说明帮助研究助手理解数据的含义与使用条件，减少对缩写、单位和表间关系的误读。

如何用于实验
------------

1. 对照研究问题选择字段，记录筛选、清洗和抽样方法。
2. 将需要的字段映射为 Agent 画像、环境初始状态或结果比较指标。
3. 在实验说明中记录数据集编号、版本和处理产物路径，再生成或修改实验配置。
4. 先检查输入规模与配置是否一致，再按 :doc:`research_workflow` 推进实验。

下载不会自动修改 ``init_config.json`` 或启动仿真；数据如何进入模型，由实验配置和模块实现决定。

整理自己的数据集
----------------

在技能管理中同步 ``agentsociety-create-dataset`` 后，可将研究数据整理为以下结构：

.. code-block:: text

   <dataset-id>/
   ├── README.md
   ├── dataset.json
   └── data/

``dataset.json`` 的必填字段为 ``id``、``name``、``description``、``category``、``version``、``author``，还可记录 ``tags`` 和 ``license``。编号使用小写字母、数字、下划线或连字符；分类支持 ``agent_profiles``、``surveys``、``experiments``、``literature``、``simulation_results``、``other``。

使用 ``create-dataset init <name>`` 初始化，补齐说明与数据后，运行 ``create-dataset validate <path>``，再用 ``create-dataset pack <dir>`` 打包。校验器会报告缺失元信息和数据目录问题；通过校验不代表字段语义或研究适用性已获确认。

本地创建、校验与打包不要求平台登录。上传前运行 ``create-dataset login``，通过 ``upload <zip>`` 上传；需要公开流转时，再用 ``submit <dataset_id>`` 提交审核。平台权限与审核状态以当前服务返回为准。

下载后的 ``metadata.json`` 保存本地安装元信息，与上传包中的 ``dataset.json`` 用途不同；不要为了让项目树显示而改写数据来源或版本。共享整个研究项目的方法见 :doc:`user_guide`。
