"""动态回放表的 schema 定义（供环境模块注册）。

环境模块（例如 social_media、mobility_space）可通过 :class:`~agentsociety2.storage.table_schema.TableSchema`
与 :class:`~agentsociety2.storage.table_schema.ColumnDef` 声明自己的回放表结构，并在运行时调用
:meth:`agentsociety2.storage.replay_writer.ReplayWriter.register_table` 创建表、调用
:meth:`agentsociety2.storage.replay_writer.ReplayWriter.write` 写入行数据。

除 SQL 列定义外，``ColumnDef`` 还可携带语义元数据（描述、逻辑类型、分析角色等），
由 :class:`~agentsociety2.storage.ReplayWriter` 的 catalog 表单独持久化。
"""

from dataclasses import dataclass, field
from typing import Any, Literal

# SQLite column types
ColumnType = Literal["INTEGER", "REAL", "TEXT", "BLOB", "TIMESTAMP", "JSON"]


@dataclass
class ColumnDef:
    """表列定义（SQLite）。

    字段说明：

    - ``name`` ：列名。
    - ``type`` ：SQLite 列类型字符串，取值见 ``ColumnType`` 。
    - ``nullable`` ：是否允许 NULL。
    - ``default`` ：默认值表达式，例如 ``CURRENT_TIMESTAMP`` 。
    - ``title`` ：可选，人类可读的列标题。
    - ``description`` ：可选，语义描述，供回放、导出与分析使用。
    - ``logical_type`` ：可选，逻辑类型，例如 ``geo.lng`` 、``money`` 。
    - ``analysis_role`` ：可选，分析角色，例如 ``measure`` 。
    - ``unit`` ：可选，单位字符串，供分析与报告使用。
    - ``enum_values`` ：可选，离散列的枚举值列表。
    - ``example`` ：可选，示例值。
    - ``tags`` ：可选，自由标签列表。
    """

    name: str
    type: ColumnType
    nullable: bool = True
    default: str | None = None
    title: str | None = None
    description: str | None = None
    logical_type: str | None = None
    analysis_role: str | None = None
    unit: str | None = None
    enum_values: list[Any] | None = None
    example: Any | None = None
    tags: list[str] = field(default_factory=list)

    def to_sql(self) -> str:
        """:returns: 列定义的 SQL 片段。"""
        parts = [self.name, self.type]
        if not self.nullable:
            parts.append("NOT NULL")
        if self.default is not None:
            parts.append(f"DEFAULT {self.default}")
        return " ".join(parts)


@dataclass
class TableSchema:
    """数据库表结构定义（用于动态建表）。

    :param name: 表名。
    :param columns: 列定义列表。
    :param primary_key: 主键列名列表。
    :param indexes: 索引定义列表（每项为列名列表）。
    """

    name: str
    columns: list[ColumnDef]
    primary_key: list[str] = field(default_factory=list)
    indexes: list[list[str]] = field(default_factory=list)

    def to_create_sql(self) -> str:
        """:returns: ``CREATE TABLE`` SQL 语句。"""
        column_defs = [col.to_sql() for col in self.columns]

        # Add primary key constraint
        if self.primary_key:
            pk_cols = ", ".join(self.primary_key)
            column_defs.append(f"PRIMARY KEY ({pk_cols})")

        columns_sql = ",\n    ".join(column_defs)
        return f"CREATE TABLE IF NOT EXISTS {self.name} (\n    {columns_sql}\n)"

    def to_index_sql(self) -> list[str]:
        """:returns: ``CREATE INDEX`` SQL 语句列表。"""
        statements = []
        for idx_cols in self.indexes:
            idx_name = f"idx_{self.name}_{'_'.join(idx_cols)}"
            cols = ", ".join(idx_cols)
            statements.append(
                f"CREATE INDEX IF NOT EXISTS {idx_name} ON {self.name}({cols})"
            )
        return statements
