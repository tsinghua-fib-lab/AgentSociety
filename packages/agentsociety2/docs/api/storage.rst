存储模块
========

先用 ``ReplayReader`` 查看 dataset catalog，再按 dataset 查询数据。目录布局与 JSONL 示例见 :doc:`/storage`；下方历史 SQLModel 只用于兼容读取旧数据库。

.. py:module:: agentsociety2.storage

ReplayWriter
------------

.. autoclass:: agentsociety2.storage.ReplayWriter
   :members:
   :undoc-members:
   :show-inheritance:

ReplaySink
----------

.. autoclass:: agentsociety2.storage.ReplaySink
   :members:
   :undoc-members:
   :show-inheritance:

ReplayDatasetSpec
-----------------

.. autoclass:: agentsociety2.storage.ReplayDatasetSpec
   :members:
   :undoc-members:

ReplayReader
------------

.. autoclass:: agentsociety2.storage.ReplayReader
   :members:
   :undoc-members:

ColumnDef
---------

.. autoclass:: agentsociety2.storage.ColumnDef
   :members:
   :undoc-members:

TableSchema
-----------

.. autoclass:: agentsociety2.storage.TableSchema
   :members:
   :undoc-members:

分布式 Replay Proxy
-------------------

大规模仿真下，``ReplayProxy`` 只携带 ``replay_dir`` 与启用标志。各 agent / env /
society 进程收到 proxy 后在本地懒加载 ``ReplaySink``，并直接 append sharded JSONL。

ReplayProxy
~~~~~~~~~~~

.. autoclass:: agentsociety2.storage.replay_proxy.ReplayProxy
   :members:
   :undoc-members:

.. autofunction:: agentsociety2.storage.build_replay_sink

.. autofunction:: agentsociety2.storage.workspace_state.atomic_write_text

兼容数据模型
-------------

以下模型仅用于兼容读取历史 SQLite 数据库；新实验默认不再写入这些 agent 表。

AgentProfile
~~~~~~~~~~~~

.. autoclass:: agentsociety2.storage.models.AgentProfile
   :members:
   :undoc-members:

AgentStatus
~~~~~~~~~~~

.. autoclass:: agentsociety2.storage.models.AgentStatus
   :members:
   :undoc-members:

AgentDialog
~~~~~~~~~~~

.. autoclass:: agentsociety2.storage.models.AgentDialog
   :members:
   :undoc-members:
   :exclude-members: type
