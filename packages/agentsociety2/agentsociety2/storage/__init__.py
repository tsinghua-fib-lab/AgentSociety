"""存储模块 — 回放数据写入（分布式 JSONL）与 schema 元数据。

本模块包含：

**ReplaySink / ReplayWriter** — 回放数据写入器（分布式、append-only JSONL，
每个 writer 进程一个实例，直接 ``os.write(O_APPEND)`` ，无中心 actor）。
``ReplayWriter`` 是向后兼容别名（legacy 公共 API，构造时传 ``.db`` 路径会被
映射为 replay 目录）。

**Schema 元数据**：

- ``ColumnDef``: 列定义与语义元数据
- ``TableSchema``: 表结构定义
- ``ReplayDatasetSpec``: 数据集级 replay 元数据

写入示例::

    import asyncio
    from agentsociety2.storage import ReplayWriter, ColumnDef, TableSchema

    writer = ReplayWriter("replay")          # replay 目录
    asyncio.run(writer.init())
    asyncio.run(writer.register_table(TableSchema(
        name="custom_data",
        columns=[ColumnDef(name="key", type="TEXT")],
    )))
    asyncio.run(writer.write("custom_data", {"key": "value"}))
"""

from .replay_metadata import ReplayDatasetSpec
from .replay_proxy import ReplayProxy
from .replay_reader import ReplayReader
from .replay_sink import ReplaySink, ReplayWriter, build_replay_sink
from .table_schema import ColumnDef, TableSchema

__all__ = [
    "ColumnDef",
    "ReplayDatasetSpec",
    "ReplayProxy",
    "ReplayReader",
    "ReplaySink",
    "ReplayWriter",
    "TableSchema",
    "build_replay_sink",
]
