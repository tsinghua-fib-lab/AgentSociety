"""分布式 JSONL 回放数据的 DuckDB 读取端。

回放写入器将数据行以分片换行分隔 JSON 文件的形式存储在 ``replay/`` 目录下，
并附带 ``_schema.json`` 伴随文件。``ReplayReader`` 提供与旧 SQLite catalog 表
等价的元数据驱动查询接口，只是改为在 JSONL 分片之上构建 DuckDB 视图。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import duckdb

_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _assert_sql_identifier(name: str) -> str:
    if not _SQL_IDENTIFIER_RE.fullmatch(name):
        raise ValueError(f"Invalid SQL identifier: {name}")
    return name


def _quote_identifier(name: str) -> str:
    return '"' + _assert_sql_identifier(name).replace('"', '""') + '"'


def _quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _duckdb_type(sqlite_type: str) -> str:
    kind = str(sqlite_type or "TEXT").upper()
    if kind == "INTEGER":
        return "BIGINT"
    if kind in ("REAL", "FLOAT", "DOUBLE", "NUMERIC"):
        return "DOUBLE"
    if kind == "BLOB":
        return "BLOB"
    if kind == "TIMESTAMP":
        return "TIMESTAMP"
    # JSON values are stored as JSON strings by ReplaySink normalization.
    return "VARCHAR"


def _loads_json(raw: Any, default: Any) -> Any:
    if raw is None:
        return default
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default
    return default


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="ignore")
    return value


class ReplayReader:
    """通过 DuckDB 读取回放 ``_schema.json`` 与分片 JSONL 行数据。"""

    def __init__(self, replay_dir: str | Path, *, threads: int | None = None) -> None:
        """绑定已有的回放目录，查询时再创建 DuckDB 内存连接。

        :param replay_dir: 含有 ``_schema.json`` 的回放目录。
        :param threads: 查询可使用的 DuckDB 线程数，省略时使用引擎默认值。
        :raises FileNotFoundError: 目录或元数据文件不存在。
        :raises ValueError: 路径包含空字节或父目录跳转。
        """
        self._threads = threads
        _path = Path(replay_dir)
        # Reject path traversal and null bytes
        if "\0" in str(_path):
            raise ValueError("Null byte in replay_dir")
        if ".." in _path.parts:
            raise ValueError("Path traversal in replay_dir")
        self.replay_dir = _path.expanduser().resolve()
        if not self.replay_dir.is_dir():
            raise FileNotFoundError(f"Replay directory not found: {self.replay_dir}")
        self.schema_path = self.replay_dir / "_schema.json"
        if not self.schema_path.is_file():
            raise FileNotFoundError(f"Replay schema not found: {self.schema_path}")
        self._schema: dict[str, Any] | None = None
        self._catalog: list[dict[str, Any]] | None = None
        self._schema_signature: tuple[int, int, int, int] | None = None
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._registered_tables: set[str] = set()

    def close(self) -> None:
        """释放当前 DuckDB 连接；重复调用是安全的。

        关闭后仍保留目录与元数据缓存，下次数据查询会重新建立连接。
        """
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            self._registered_tables.clear()

    def _connection(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            config = {} if self._threads is None else {"threads": self._threads}
            self._conn = duckdb.connect(database=":memory:", config=config)
        return self._conn

    def _load_schema(self) -> dict[str, Any]:
        stat = self.schema_path.stat()
        signature = (stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        if self._schema is None or self._schema_signature != signature:
            self._schema = json.loads(self.schema_path.read_text(encoding="utf-8"))
            self._schema_signature = signature
            # 目录与已注册视图都依赖 schema；schema 变化后必须重新构建，
            # 否则长生命周期 reader 看不到新增 dataset/列。
            self._catalog = None
            self._registered_tables.clear()
        return self._schema

    def _schema_mtime(self) -> datetime:
        return datetime.fromtimestamp(self.schema_path.stat().st_mtime)

    def load_dataset_catalog(self) -> list[dict[str, Any]]:
        """读取并缓存数据集目录，保留列定义、排序规则和能力标记。"""
        schema = self._load_schema()
        if self._catalog is not None:
            return self._catalog

        created_at = self._schema_mtime()
        catalog: list[dict[str, Any]] = []
        for dataset_id, raw in sorted((schema.get("datasets") or {}).items()):
            columns = []
            for col in raw.get("columns") or []:
                columns.append(
                    {
                        "column_name": col.get("name"),
                        "sqlite_type": col.get("type", "TEXT"),
                        "logical_type": col.get("logical_type"),
                        "analysis_role": col.get("analysis_role"),
                        "title": col.get("title"),
                        "description": col.get("description"),
                        "unit": col.get("unit"),
                        "enum_values": col.get("enum_values"),
                        "example": col.get("example"),
                        "nullable": bool(col.get("nullable", True)),
                        "tags": list(col.get("tags") or []),
                    }
                )
            catalog.append(
                {
                    "dataset_id": raw.get("dataset_id") or dataset_id,
                    "table_name": raw.get("table_name") or dataset_id.replace(".", "_"),
                    "module_name": raw.get("module_name") or "",
                    "kind": raw.get("kind") or "event_stream",
                    "title": raw.get("title") or "",
                    "description": raw.get("description") or "",
                    "entity_key": raw.get("entity_key"),
                    "step_key": raw.get("step_key"),
                    "time_key": raw.get("time_key"),
                    "default_order": list(raw.get("default_order") or []),
                    "capabilities": list(raw.get("capabilities") or []),
                    "version": int(raw.get("version") or 1),
                    "created_at": created_at,
                    "columns": columns,
                }
            )
        self._catalog = catalog
        return catalog

    def get_dataset_by_id(self, dataset_id: str) -> dict[str, Any]:
        """按稳定标识读取一个数据集的目录条目。

        :param dataset_id: 目录返回的完整标识，例如 ``core.agent_profile``。
        :returns: 可传给行查询方法的数据集元数据。
        :raises KeyError: 未找到该标识。
        """
        for dataset in self.load_dataset_catalog():
            if dataset["dataset_id"] == dataset_id:
                return dataset
        raise KeyError(dataset_id)

    def find_dataset_by_capability(
        self, capability: str, *, kind: str | None = None
    ) -> dict[str, Any]:
        """查找具有指定能力标记的数据集，可同时限制数据集类型。

        多个匹配项按 ``dataset_id`` 排序后返回第一个，便于确定性选择。

        :param capability: 能力标记，例如 ``agent_profile`` 或 ``timeseries``。
        :param kind: 可选的数据集类型，例如 ``entity_static``。
        :raises KeyError: 没有同时满足条件的数据集。
        """
        matches = []
        for dataset in self.load_dataset_catalog():
            if capability not in dataset.get("capabilities", []):
                continue
            if kind is not None and dataset.get("kind") != kind:
                continue
            matches.append(dataset)
        if not matches:
            raise KeyError(capability)
        matches.sort(key=lambda item: item["dataset_id"])
        return matches[0]

    def _get_column_map(self, dataset: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {column["column_name"]: column for column in dataset.get("columns", [])}

    def _get_column_names(self, dataset: dict[str, Any]) -> list[str]:
        return [column["column_name"] for column in dataset.get("columns", [])]

    def _ensure_view(self, dataset: dict[str, Any]) -> str:
        table_name = _assert_sql_identifier(str(dataset["table_name"]))
        if table_name in self._registered_tables:
            return table_name

        conn = self._connection()
        quoted_table = _quote_identifier(table_name)
        pattern = str(self.replay_dir / f"{table_name}.*.jsonl")
        # DuckDB 无法从空分片推断列，沿用目录中声明的空表结构。
        has_rows = any(
            path.stat().st_size
            for path in self.replay_dir.glob(f"{table_name}.*.jsonl")
        )
        if has_rows:
            conn.execute(
                f"""
                CREATE OR REPLACE VIEW {quoted_table} AS
                SELECT * FROM read_json_auto(
                    {_quote_literal(pattern)},
                    format='newline_delimited',
                    union_by_name=true
                )
                """
            )
        else:
            projections = []
            for column in dataset.get("columns", []):
                column_name = _quote_identifier(column["column_name"])
                column_type = _duckdb_type(column.get("sqlite_type", "TEXT"))
                projections.append(f"CAST(NULL AS {column_type}) AS {column_name}")
            select_list = ", ".join(projections) if projections else "1 AS __empty"
            conn.execute(
                f"CREATE OR REPLACE VIEW {quoted_table} AS SELECT {select_list} WHERE FALSE"
            )
        if has_rows:
            self._registered_tables.add(table_name)
        return table_name

    def _validate_selected_columns(
        self, dataset: dict[str, Any], columns: list[str] | None
    ) -> list[str]:
        available = self._get_column_names(dataset)
        selected = columns or available
        if not selected:
            raise ValueError(f"Dataset '{dataset['dataset_id']}' has no columns")
        invalid = [column for column in selected if column not in set(available)]
        if invalid:
            raise ValueError(
                f"Dataset '{dataset['dataset_id']}' received unknown columns: {invalid}"
            )
        return selected

    def _validate_order_columns(
        self, dataset: dict[str, Any], order_by: str | None
    ) -> list[str]:
        available = set(self._get_column_names(dataset))
        order_columns = (
            [order_by] if order_by else list(dataset.get("default_order") or [])
        )
        if not order_columns:
            return []
        invalid = [column for column in order_columns if column not in available]
        if invalid:
            raise ValueError(
                f"Dataset '{dataset['dataset_id']}' references unknown order columns: {invalid}"
            )
        return order_columns

    def _build_filter_sql(
        self,
        dataset: dict[str, Any],
        *,
        step: int | None = None,
        entity_id: int | None = None,
        start_step: int | None = None,
        end_step: int | None = None,
        max_step: int | None = None,
    ) -> tuple[list[str], list[Any]]:
        available = set(self._get_column_names(dataset))
        step_key = dataset.get("step_key")
        entity_key = dataset.get("entity_key")
        filters: list[str] = []
        params: list[Any] = []

        if entity_id is not None:
            if not entity_key or entity_key not in available:
                raise ValueError(
                    f"Dataset '{dataset['dataset_id']}' does not support entity_id filtering"
                )
            filters.append(f"{_quote_identifier(entity_key)} = ?")
            params.append(entity_id)

        def add_step_filter(operator: str, value: int | None) -> None:
            if value is None:
                return
            if not step_key or step_key not in available:
                raise ValueError(
                    f"Dataset '{dataset['dataset_id']}' does not support step filtering"
                )
            filters.append(f"{_quote_identifier(step_key)} {operator} ?")
            params.append(value)

        if step is not None:
            add_step_filter("=", step)
            return filters, params
        add_step_filter(">=", start_step)
        add_step_filter("<=", end_step)
        add_step_filter("<=", max_step)
        return filters, params

    def _normalize_value(self, column: dict[str, Any] | None, value: Any) -> Any:
        if value is None:
            return None
        if str((column or {}).get("sqlite_type") or "").upper() == "JSON":
            return _loads_json(value, value)
        return _json_safe(value)

    def normalize_row(
        self, dataset: dict[str, Any], row: dict[str, Any]
    ) -> dict[str, Any]:
        """根据列元数据解码 JSON，并将日期和字节转换为可序列化值。

        返回新的行字典，不修改传入的记录。
        """
        column_map = self._get_column_map(dataset)
        return {
            key: self._normalize_value(column_map.get(key), value)
            for key, value in row.items()
        }

    def _select_sql(
        self,
        dataset: dict[str, Any],
        *,
        selected_columns: list[str],
        order_by: str | None,
        desc: bool,
        latest_per_entity: bool,
        filters: list[str],
        with_total: bool = False,
    ) -> str:
        table_name = _quote_identifier(self._ensure_view(dataset))
        select_list = ", ".join(
            _quote_identifier(column) for column in selected_columns
        )
        if with_total:
            select_list += ", count(*) OVER ()"
        where_sql = f" WHERE {' AND '.join(filters)}" if filters else ""

        if latest_per_entity:
            entity_key = dataset.get("entity_key")
            step_key = dataset.get("step_key")
            if not entity_key or not step_key:
                raise ValueError(
                    f"Dataset '{dataset['dataset_id']}' does not support latest_per_entity"
                )
            entity_sql = _quote_identifier(entity_key)
            step_sql = _quote_identifier(step_key)
            return (
                f"SELECT {select_list} FROM ("
                f"SELECT * FROM {table_name}{where_sql} QUALIFY row_number() OVER "
                f"(PARTITION BY {entity_sql} ORDER BY {step_sql} DESC) = 1"
                f") ORDER BY {entity_sql} {'DESC' if desc else 'ASC'}"
            )

        sql = f"SELECT {select_list} FROM {table_name}{where_sql}"
        order_columns = self._validate_order_columns(dataset, order_by)
        if order_columns:
            direction = "DESC" if desc else "ASC"
            sql += " ORDER BY " + ", ".join(
                f"{_quote_identifier(column)} {direction}" for column in order_columns
            )
        return sql

    def fetch_dataset_rows(
        self,
        dataset: dict[str, Any],
        *,
        order_by: str | None = None,
        desc: bool = False,
        step: int | None = None,
        entity_id: int | None = None,
        start_step: int | None = None,
        end_step: int | None = None,
        max_step: int | None = None,
        columns: list[str] | None = None,
        latest_per_entity: bool = False,
        limit: int | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        """读取数据集记录，支持投影、排序和按步号或实体过滤。

        ``start_step``、``end_step`` 与 ``max_step`` 包含边界；省略排序列时使用数据集的 ``default_order``。
        ``latest_per_entity`` 需要数据集声明实体键和步号键。仅在提供 ``limit`` 时可使用非零 ``offset``。

        :returns: ``columns`` 列名列表与 ``rows`` 记录列表。
        :raises ValueError: 列名、排序或过滤条件不符合数据集定义。
        """
        selected_columns = self._validate_selected_columns(dataset, columns)
        filters, params = self._build_filter_sql(
            dataset,
            step=step,
            entity_id=entity_id,
            start_step=start_step,
            end_step=end_step,
            max_step=max_step,
        )
        sql = self._select_sql(
            dataset,
            selected_columns=selected_columns,
            order_by=order_by,
            desc=desc,
            latest_per_entity=latest_per_entity,
            filters=filters,
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
            if offset:
                sql += " OFFSET ?"
                params.append(offset)
        elif offset:
            raise ValueError("offset requires a finite limit")

        cursor = self._connection().execute(sql, params)
        names = [description[0] for description in cursor.description or []]
        rows = [
            self.normalize_row(dataset, dict(zip(names, row, strict=False)))
            for row in cursor.fetchall()
        ]
        return {"columns": selected_columns, "rows": rows}

    def count_dataset_rows(
        self,
        dataset: dict[str, Any],
        *,
        step: int | None = None,
        entity_id: int | None = None,
        start_step: int | None = None,
        end_step: int | None = None,
        max_step: int | None = None,
        latest_per_entity: bool = False,
    ) -> int:
        """统计符合步号与实体过滤条件的记录数。

        ``latest_per_entity=True`` 时按每个实体的最新记录计数；可用同一组过滤条件与行查询核对分页总数。
        """
        self._validate_selected_columns(dataset, None)
        filters, params = self._build_filter_sql(
            dataset,
            step=step,
            entity_id=entity_id,
            start_step=start_step,
            end_step=end_step,
            max_step=max_step,
        )
        table_name = _quote_identifier(self._ensure_view(dataset))
        where_sql = f" WHERE {' AND '.join(filters)}" if filters else ""
        if latest_per_entity:
            entity_key = dataset.get("entity_key")
            step_key = dataset.get("step_key")
            if not entity_key or not step_key:
                raise ValueError(
                    f"Dataset '{dataset['dataset_id']}' does not support latest_per_entity"
                )
            sql = (
                "SELECT count(*) FROM ("
                f"SELECT row_number() OVER (PARTITION BY {_quote_identifier(entity_key)} "
                f"ORDER BY {_quote_identifier(step_key)} DESC) AS __row_num "
                f"FROM {table_name}{where_sql}"
                ") WHERE __row_num = 1"
            )
        else:
            sql = f"SELECT count(*) FROM {table_name}{where_sql}"
        return int(self._connection().execute(sql, params).fetchone()[0] or 0)

    def query_dataset_rows(
        self,
        dataset: dict[str, Any],
        *,
        page: int,
        page_size: int,
        order_by: str | None = None,
        desc: bool = False,
        step: int | None = None,
        entity_id: int | None = None,
        start_step: int | None = None,
        end_step: int | None = None,
        max_step: int | None = None,
        columns: list[str] | None = None,
        latest_per_entity: bool = False,
    ) -> dict[str, Any]:
        """按页查询记录，并返回相同过滤条件下的总数。

        :param page: 从 1 开始的页码。
        :param page_size: 每页记录数，应为正整数。
        :returns: ``columns``、当前页 ``rows`` 与过滤后的 ``total``。
        """
        offset = (page - 1) * page_size
        selected = self._validate_selected_columns(dataset, columns)
        criteria = {
            "step": step,
            "entity_id": entity_id,
            "start_step": start_step,
            "end_step": end_step,
            "max_step": max_step,
        }
        filters, params = self._build_filter_sql(dataset, **criteria)
        count_first = offset > 0 or page_size == 0
        sql = self._select_sql(
            dataset,
            selected_columns=selected,
            order_by=order_by,
            desc=desc,
            latest_per_entity=latest_per_entity,
            filters=filters,
            with_total=not count_first,
        )
        total = 0
        if count_first:
            # 先判断后续页是否存在，避免为越界页排序和读取记录。
            total = self.count_dataset_rows(
                dataset, latest_per_entity=latest_per_entity, **criteria
            )
            if offset >= total or page_size == 0:
                return {"columns": selected, "rows": [], "total": total}
        records = (
            self._connection()
            .execute(sql + " LIMIT ? OFFSET ?", [*params, page_size, offset])
            .fetchall()
        )
        if not count_first and records:
            # 窗口计数在末列，不占用用户列名。
            total = int(records[0][-1])
        rows = [
            self.normalize_row(dataset, dict(zip(selected, row, strict=False)))
            for row in records
        ]
        return {"columns": selected, "rows": rows, "total": total}

    def distinct_values(
        self, dataset: dict[str, Any], column: str, *, order: bool = True
    ) -> list[Any]:
        """列出一列的非空去重值，默认按该列升序排列。

        :param column: 数据集定义中的列名。
        :param order: 是否排序；关闭后不保证返回顺序。
        :raises ValueError: 列名不属于该数据集。
        """
        if column not in set(self._get_column_names(dataset)):
            raise ValueError(
                f"Unknown column for dataset '{dataset['dataset_id']}': {column}"
            )
        table_name = _quote_identifier(self._ensure_view(dataset))
        column_sql = _quote_identifier(column)
        sql = f"SELECT DISTINCT {column_sql} FROM {table_name} WHERE {column_sql} IS NOT NULL"
        if order:
            sql += f" ORDER BY {column_sql}"
        return [row[0] for row in self._connection().execute(sql).fetchall()]

    def count_distinct(self, dataset: dict[str, Any], column: str) -> int:
        """统计一列的非空去重值数量。

        :param column: 数据集定义中的列名。
        :raises ValueError: 列名不属于该数据集。
        """
        if column not in set(self._get_column_names(dataset)):
            raise ValueError(
                f"Unknown column for dataset '{dataset['dataset_id']}': {column}"
            )
        table_name = _quote_identifier(self._ensure_view(dataset))
        row = (
            self._connection()
            .execute(
                f"SELECT count(DISTINCT {_quote_identifier(column)}) FROM {table_name}"
            )
            .fetchone()
        )
        return int(row[0] or 0)

    def timeline_summary(self, dataset: dict[str, Any]) -> tuple[int, Any, Any]:
        """一次扫描统计不同仿真步数、最早时间和最晚时间。

        :param dataset: 含有步号列和时间列的回放目录条目。
        :returns: 非空步号的去重计数与时间范围。空表的步数为零，两个时间均为空。
        """
        step, time = self._validate_selected_columns(
            dataset, [dataset["step_key"], dataset["time_key"]]
        )
        table = _quote_identifier(self._ensure_view(dataset))
        time_column = _quote_identifier(time)
        query = (
            f"SELECT count(DISTINCT {_quote_identifier(step)}), "
            f"min({time_column}), max({time_column}) FROM {table}"
        )
        count, first, last = self._connection().execute(query).fetchone()
        return int(count), first, last

    def value_counts(
        self,
        dataset: dict[str, Any],
        column: str,
        *,
        limit: int = 5,
    ) -> list[tuple[Any, int]]:
        """按出现次数降序返回一列的非空取值及计数。

        计数相同的取值按取值升序排列，保证同一份 replay 的输出稳定。

        :param dataset: 数据集定义。
        :param column: 数据集定义中的列名。
        :param limit: 最多返回的取值数量，必须为正整数。
        :returns: ``(value, count)`` 列表。
        :raises ValueError: 列名不属于该数据集，或 ``limit`` 非正。
        """
        if column not in set(self._get_column_names(dataset)):
            raise ValueError(
                f"Unknown column for dataset '{dataset['dataset_id']}': {column}"
            )
        if limit < 1:
            raise ValueError("limit must be a positive integer")
        table_name = _quote_identifier(self._ensure_view(dataset))
        column_sql = _quote_identifier(column)
        rows = (
            self._connection()
            .execute(
                f"SELECT {column_sql}, count(*) AS n FROM {table_name} "
                f"WHERE {column_sql} IS NOT NULL "
                f"GROUP BY {column_sql} ORDER BY n DESC, {column_sql} ASC LIMIT ?",
                [limit],
            )
            .fetchall()
        )
        return [(row[0], int(row[1])) for row in rows]

    def avg_value(self, dataset: dict[str, Any], column: str) -> float | None:
        """按声明的数值类型计算非空值的平均数，没有非空值时返回 ``None``。

        :param dataset: 数据集定义。
        :param column: 数据集定义中的数值列名。
        :returns: 平均数或 ``None``。
        :raises ValueError: 列名不属于该数据集，或该列未声明为数值类型。
        :raises duckdb.ConversionException: 非空值无法转换为声明的数值类型。
        """
        column_def = self._get_column_map(dataset).get(column)
        if column_def is None:
            raise ValueError(
                f"Unknown column for dataset '{dataset['dataset_id']}': {column}"
            )
        column_type = _duckdb_type(column_def["sqlite_type"])
        if column_type not in ("BIGINT", "DOUBLE"):
            raise ValueError(
                f"Column '{column}' in dataset '{dataset['dataset_id']}' is not numeric"
            )

        table_name = _quote_identifier(self._ensure_view(dataset))
        column_sql = _quote_identifier(column)
        # read_json_auto 可能将全为 NULL 的列推断为 JSON。
        sql = f"SELECT avg(CAST({column_sql} AS {column_type})) FROM {table_name}"
        return self._connection().execute(sql).fetchone()[0]

    def min_value(self, dataset: dict[str, Any], column: str) -> Any:
        """返回一列的最小非空值，无记录时返回 ``None``。

        比较方式由列的存储类型决定；列名必须来自数据集定义。
        """
        if column not in set(self._get_column_names(dataset)):
            raise ValueError(
                f"Unknown column for dataset '{dataset['dataset_id']}': {column}"
            )
        table_name = _quote_identifier(self._ensure_view(dataset))
        return (
            self._connection()
            .execute(f"SELECT min({_quote_identifier(column)}) FROM {table_name}")
            .fetchone()[0]
        )

    def max_value(self, dataset: dict[str, Any], column: str) -> Any:
        """返回一列的最大非空值，无记录时返回 ``None``。

        比较方式由列的存储类型决定；列名必须来自数据集定义。
        """
        if column not in set(self._get_column_names(dataset)):
            raise ValueError(
                f"Unknown column for dataset '{dataset['dataset_id']}': {column}"
            )
        table_name = _quote_identifier(self._ensure_view(dataset))
        return (
            self._connection()
            .execute(f"SELECT max({_quote_identifier(column)}) FROM {table_name}")
            .fetchone()[0]
        )


__all__ = ["ReplayReader"]
