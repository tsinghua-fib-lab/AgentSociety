"""数据层：replay/SQLite 读取（`DataReader` ）、实验目录上下文（`ContextLoader` ）。"""

import json
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from agentsociety2.logger import get_logger
from agentsociety2.storage.replay_reader import ReplayReader

from .models import (
    DIR_ARTIFACTS,
    DIR_REPLAY,
    FILE_EXPERIMENT_MD,
    FILE_HYPOTHESIS_MD,
    FILE_PID,
    FILE_SQLITE,
    ExperimentContext,
    ExperimentDesign,
    ExperimentStatus,
)

logger = get_logger()


def _quote_identifier(name: str) -> str:
    """安全引用 SQLite 标识符（表名、列名）。"""
    return '"' + str(name).replace('"', '""') + '"'


def _sanitize_id(raw: str) -> str:
    """仅保留安全字符，防止路径穿越。"""
    s = (raw or "").strip()
    import re

    s = re.sub(r"[^a-zA-Z0-9_-]", "", s)
    return s or "unknown"


def _resolve_replay_dir(path: Path) -> Path | None:
    p = Path(path)
    candidates: list[Path] = []
    if p.is_dir():
        candidates.extend([p, p / DIR_REPLAY])
    else:
        candidates.append(p.parent / DIR_REPLAY)
    for candidate in candidates:
        if (candidate / "_schema.json").exists():
            return candidate
    return None


# ─────────────────────────────────────────────────────────────────────────
# 数据结构
# ─────────────────────────────────────────────────────────────────────────


@dataclass
class DatabaseSchema:
    """数据库 Schema 信息"""

    tables: list[str]
    columns: dict[str, list[dict[str, Any]]]  # table_name -> [{name, type, ...}]
    row_counts: dict[str, int]
    markdown: str = ""


@dataclass
class DataStats:
    """数据统计摘要"""

    numeric_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    categorical_stats: dict[str, dict[str, Any]] = field(default_factory=dict)
    sample_data: dict[str, list[dict]] = field(default_factory=dict)
    quick_stats_md: str = ""


@dataclass
class DataSummary:
    """完整数据摘要"""

    db_path: str | None = None
    schema: DatabaseSchema | None = None
    stats: DataStats | None = None

    @property
    def tables(self) -> list[str]:
        return self.schema.tables if self.schema else []

    @property
    def row_counts(self) -> dict[str, int]:
        return self.schema.row_counts if self.schema else {}

    @property
    def schema_markdown(self) -> str:
        return self.schema.markdown if self.schema else ""

    @property
    def quick_stats(self) -> str:
        return self.stats.quick_stats_md if self.stats else ""

    @property
    def numeric_stats(self) -> dict[str, dict[str, Any]]:
        return self.stats.numeric_stats if self.stats else {}

    @property
    def categorical_stats(self) -> dict[str, dict[str, Any]]:
        return self.stats.categorical_stats if self.stats else {}

    @property
    def sample_data(self) -> dict[str, list[dict]]:
        return self.stats.sample_data if self.stats else {}


# ─────────────────────────────────────────────────────────────────────────
# DataReader: 数据库读取和理解
# ─────────────────────────────────────────────────────────────────────────


class DataReader:
    """Replay/数据库读取和理解"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.replay_dir = _resolve_replay_dir(self.db_path)
        self.logger = logger

    def _read_replay_schema(self) -> DatabaseSchema:
        if self.replay_dir is None:
            return DatabaseSchema(tables=[], columns={}, row_counts={})
        reader = ReplayReader(self.replay_dir)
        try:
            columns_by_table: dict[str, list[dict[str, Any]]] = {}
            row_counts: dict[str, int] = {}
            for dataset in reader.load_dataset_catalog():
                table = dataset["table_name"]
                dataset_meta = {
                    key: dataset.get(key)
                    for key in (
                        "dataset_id",
                        "kind",
                        "title",
                        "description",
                        "entity_key",
                        "step_key",
                        "time_key",
                        "default_order",
                        "capabilities",
                    )
                }
                pk_columns = {
                    key
                    for key in (dataset.get("entity_key"), dataset.get("step_key"))
                    if key
                }
                columns_by_table[table] = [
                    {
                        "name": column.get("column_name"),
                        "type": column.get("sqlite_type", "TEXT"),
                        "logical_type": column.get("logical_type"),
                        "analysis_role": column.get("analysis_role"),
                        "title": column.get("title"),
                        "description": column.get("description"),
                        "unit": column.get("unit"),
                        "enum_values": column.get("enum_values"),
                        "example": column.get("example"),
                        "notnull": not bool(column.get("nullable", True)),
                        "pk": column.get("column_name") in pk_columns,
                        "tags": list(column.get("tags") or []),
                        "dataset": dataset_meta,
                    }
                    for column in dataset.get("columns", [])
                ]
                row_counts[table] = reader.count_dataset_rows(dataset)
            markdown = self._format_schema_markdown(columns_by_table, row_counts)
            return DatabaseSchema(
                tables=list(columns_by_table.keys()),
                columns=columns_by_table,
                row_counts=row_counts,
                markdown=markdown,
            )
        finally:
            reader.close()

    def read_schema(self) -> DatabaseSchema:
        """读取数据库 Schema"""
        if self.replay_dir is not None:
            return self._read_replay_schema()
        if not self.db_path.exists():
            return DatabaseSchema(tables=[], columns={}, row_counts={})

        from .utils import extract_database_schema, format_database_schema_markdown

        schema_dict = extract_database_schema(self.db_path)
        if not schema_dict:
            return DatabaseSchema(tables=[], columns={}, row_counts={})

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        row_counts = {}
        tables = list(schema_dict.keys())
        try:
            for table in tables:
                try:
                    cursor.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}")
                    row_counts[table] = cursor.fetchone()[0]
                except sqlite3.Error:
                    row_counts[table] = 0
        finally:
            conn.close()

        markdown = format_database_schema_markdown(
            schema_dict,
            include_row_counts=True,
            db_path=self.db_path,
        )

        return DatabaseSchema(
            tables=tables,
            columns=schema_dict,
            row_counts=row_counts,
            markdown=markdown,
        )

    def read_sample_data(
        self,
        tables: list[str] | None = None,
        limit: int = 5,
    ) -> dict[str, list[dict]]:
        """读取样本数据"""
        if self.replay_dir is not None:
            reader = ReplayReader(self.replay_dir)
            try:
                datasets_by_table = {
                    dataset["table_name"]: dataset
                    for dataset in reader.load_dataset_catalog()
                }
                if tables is None:
                    tables = list(datasets_by_table.keys())
                result: dict[str, list[dict]] = {}
                for table in tables:
                    dataset = datasets_by_table.get(table)
                    if dataset is None:
                        continue
                    rows = reader.fetch_dataset_rows(dataset, limit=limit)["rows"]
                    if rows:
                        result[table] = rows
                return result
            finally:
                reader.close()
        if not self.db_path.exists():
            return {}

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        # 获取要读取的表
        if tables is None:
            tables = self.read_schema().tables

        result = {}
        for table in tables:
            try:
                cursor.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table)}")
                if cursor.fetchone()[0] == 0:
                    continue
                cursor.execute(
                    f"SELECT * FROM {_quote_identifier(table)} LIMIT {limit}"
                )
                cols = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                result[table] = [dict(zip(cols, row, strict=False)) for row in rows]
            except sqlite3.Error:
                continue

        conn.close()
        return result

    def compute_stats(self, schema: DatabaseSchema) -> DataStats:
        """计算统计摘要"""
        if self.replay_dir is not None:
            numeric_stats = self._compute_replay_numeric_stats(schema)
            categorical_stats = self._compute_replay_categorical_stats(schema)
            sample_data = self.read_sample_data(schema.tables)
            quick_stats_md = self._format_quick_stats(
                schema, numeric_stats, categorical_stats, sample_data
            )
            return DataStats(
                numeric_stats=numeric_stats,
                categorical_stats=categorical_stats,
                sample_data=sample_data,
                quick_stats_md=quick_stats_md,
            )
        if not self.db_path.exists():
            return DataStats()

        conn = sqlite3.connect(str(self.db_path))

        numeric_stats = self._compute_numeric_stats(conn, schema)
        categorical_stats = self._compute_categorical_stats(conn, schema)
        conn.close()

        sample_data = self.read_sample_data(schema.tables)
        quick_stats_md = self._format_quick_stats(
            schema, numeric_stats, categorical_stats, sample_data
        )

        return DataStats(
            numeric_stats=numeric_stats,
            categorical_stats=categorical_stats,
            sample_data=sample_data,
            quick_stats_md=quick_stats_md,
        )

    def read_full_summary(self) -> DataSummary:
        """读取完整数据摘要"""
        schema = self.read_schema()
        stats = self.compute_stats(schema)

        return DataSummary(
            db_path=str(self.db_path),
            schema=schema,
            stats=stats,
        )

    # ─────────────────────────────────────────────────────────────────────
    # 私有方法
    # ─────────────────────────────────────────────────────────────────────

    def _format_schema_markdown(
        self,
        schema: dict[str, list[dict[str, Any]]],
        row_counts: dict[str, int],
    ) -> str:
        if not schema:
            return "Schema not available"
        lines: list[str] = []
        for table_name, columns in schema.items():
            dataset = columns[0].get("dataset") if columns else None
            dataset_id = (
                dataset.get("dataset_id") if isinstance(dataset, dict) else table_name
            )
            lines.append(f"### Dataset: `{dataset_id}`")
            lines.append(f"- Table: `{table_name}`")
            lines.append(f"- Rows: {row_counts.get(table_name, 0)}")
            if isinstance(dataset, dict):
                if dataset.get("kind"):
                    lines.append(f"- Kind: `{dataset['kind']}`")
                if dataset.get("description"):
                    lines.append(f"- Description: {dataset['description']}")
            for col in columns:
                extras = []
                if col.get("logical_type"):
                    extras.append(f"logical_type={col['logical_type']}")
                if col.get("analysis_role"):
                    extras.append(f"analysis_role={col['analysis_role']}")
                extra_text = f" [{' ; '.join(extras)}]" if extras else ""
                lines.append(f"  - {col['name']} ({col['type']}){extra_text}")
            lines.append("")
        return "\n".join(lines)

    def _datasets_by_table(self) -> dict[str, dict[str, Any]]:
        if self.replay_dir is None:
            return {}
        reader = ReplayReader(self.replay_dir)
        try:
            return {
                dataset["table_name"]: dataset
                for dataset in reader.load_dataset_catalog()
            }
        finally:
            reader.close()

    def _compute_replay_numeric_stats(
        self,
        schema: DatabaseSchema,
    ) -> dict[str, dict[str, Any]]:
        if self.replay_dir is None:
            return {}
        reader = ReplayReader(self.replay_dir)
        try:
            datasets_by_table = {
                dataset["table_name"]: dataset
                for dataset in reader.load_dataset_catalog()
            }
            result: dict[str, dict[str, Any]] = {}
            for table in schema.tables:
                dataset = datasets_by_table.get(table)
                if dataset is None or schema.row_counts.get(table, 0) == 0:
                    continue
                table_stats: dict[str, Any] = {}
                for col in schema.columns.get(table, []):
                    if col.get("type", "").upper() not in (
                        "INTEGER",
                        "REAL",
                        "FLOAT",
                        "DOUBLE",
                        "NUMERIC",
                    ):
                        continue
                    name = col["name"]
                    table_stats[name] = {
                        "min": reader.min_value(dataset, name),
                        "max": reader.max_value(dataset, name),
                        "avg": None,
                        "count": schema.row_counts.get(table, 0),
                    }
                if table_stats:
                    result[table] = table_stats
            return result
        finally:
            reader.close()

    def _compute_replay_categorical_stats(
        self,
        schema: DatabaseSchema,
    ) -> dict[str, dict[str, Any]]:
        if self.replay_dir is None:
            return {}
        reader = ReplayReader(self.replay_dir)
        try:
            datasets_by_table = {
                dataset["table_name"]: dataset
                for dataset in reader.load_dataset_catalog()
            }
            result: dict[str, dict[str, Any]] = {}
            for table in schema.tables:
                dataset = datasets_by_table.get(table)
                if dataset is None or schema.row_counts.get(table, 0) == 0:
                    continue
                table_stats: dict[str, Any] = {}
                for col in schema.columns.get(table, []):
                    if col.get("type", "").upper() not in (
                        "TEXT",
                        "VARCHAR",
                        "CHAR",
                        "STRING",
                    ):
                        continue
                    name = col["name"]
                    values = reader.distinct_values(dataset, name)[:5]
                    table_stats[name] = {
                        "unique_count": reader.count_distinct(dataset, name),
                        "top_values": [(value, None) for value in values],
                    }
                if table_stats:
                    result[table] = table_stats
            return result
        finally:
            reader.close()

    def _compute_numeric_stats(
        self,
        conn,
        schema: DatabaseSchema,
    ) -> dict[str, dict[str, Any]]:
        """计算数值列统计"""
        cursor = conn.cursor()
        result = {}

        for table in schema.tables:
            if schema.row_counts.get(table, 0) == 0:
                continue

            numeric_cols = [
                col["name"]
                for col in schema.columns.get(table, [])
                if col.get("type", "").upper()
                in ("INTEGER", "REAL", "FLOAT", "DOUBLE", "NUMERIC")
            ]
            if not numeric_cols:
                continue

            t = _quote_identifier(table)
            table_stats = {}
            for col in numeric_cols:
                try:
                    c = _quote_identifier(col)
                    cursor.execute(
                        f"SELECT MIN({c}), MAX({c}), AVG({c}), COUNT({c}) FROM {t}"
                    )
                    row = cursor.fetchone()
                    if row and row[3] > 0:
                        table_stats[col] = {
                            "min": row[0],
                            "max": row[1],
                            "avg": round(row[2], 4) if row[2] is not None else None,
                            "count": row[3],
                        }
                except sqlite3.Error:
                    logger.debug(
                        "Failed to compute aggregate stats for table %s",
                        table,
                        exc_info=True,
                    )
            if table_stats:
                result[table] = table_stats

        return result

    def _compute_categorical_stats(
        self,
        conn,
        schema: DatabaseSchema,
    ) -> dict[str, dict[str, Any]]:
        """计算分类列统计"""
        cursor = conn.cursor()
        result = {}

        for table in schema.tables:
            if schema.row_counts.get(table, 0) == 0:
                continue

            text_cols = [
                col["name"]
                for col in schema.columns.get(table, [])
                if col.get("type", "").upper() in ("TEXT", "VARCHAR", "CHAR", "STRING")
            ]
            if not text_cols:
                continue

            t = _quote_identifier(table)
            table_stats = {}
            for col in text_cols:
                try:
                    c = _quote_identifier(col)
                    cursor.execute(f"SELECT COUNT(DISTINCT {c}) FROM {t}")
                    unique_count = cursor.fetchone()[0]

                    cursor.execute(
                        f"SELECT {c}, COUNT(*) as cnt FROM {t} "
                        f"WHERE {c} IS NOT NULL GROUP BY {c} ORDER BY cnt DESC LIMIT 5"
                    )
                    top_values = cursor.fetchall()

                    if unique_count > 0:
                        table_stats[col] = {
                            "unique_count": unique_count,
                            "top_values": [(v[0], v[1]) for v in top_values]
                            if top_values
                            else [],
                        }
                except sqlite3.Error:
                    logger.debug(
                        "Failed to compute column stats for table %s",
                        table,
                        exc_info=True,
                    )
            if table_stats:
                result[table] = table_stats

        return result

    def _format_quick_stats(
        self,
        schema: DatabaseSchema,
        numeric_stats: dict,
        categorical_stats: dict,
        sample_data: dict[str, list[dict]] | None = None,
    ) -> str:
        """格式化快速统计为 Markdown"""
        sample_data = sample_data or {}
        lines = ["## Data Overview\n"]
        lines.append(f"- **Data path**: {self.db_path}")
        lines.append(f"- **Tables**: {len(schema.tables)}")
        lines.append(f"- **Total Rows**: {sum(schema.row_counts.values())}")
        lines.append("")

        for table in schema.tables:
            rows = schema.row_counts.get(table, 0)
            cols = schema.columns.get(table, [])
            dataset = cols[0].get("dataset") if cols else None
            dataset_id = (
                dataset.get("dataset_id") if isinstance(dataset, dict) else table
            )
            title = dataset.get("title") if isinstance(dataset, dict) else None
            description = (
                dataset.get("description") if isinstance(dataset, dict) else None
            )
            lines.append(f"### Dataset: `{dataset_id}` ({rows} rows)")
            lines.append(f"- Table: `{table}`")
            if title:
                lines.append(f"- Title: {title}")
            if description:
                lines.append(f"- Description: {description}")

            if sample_data.get(table):
                lines.append("Sample data (first rows):")
                for i, row in enumerate(sample_data[table][:3], 1):
                    items = [f"  - {k}: {v}" for k, v in list(row.items())[:5]]
                    lines.append(f"  Row {i}:")
                    lines.extend(items)
                lines.append("")

            if table in numeric_stats:
                lines.append("**Numeric Stats**:")
                col_meta = {col["name"]: col for col in cols}
                for col, stats in numeric_stats[table].items():
                    label = col_meta.get(col, {}).get("title") or col
                    detail = col_meta.get(col, {}).get("description")
                    lines.append(
                        f"  - `{label}` (`{col}`): min={stats.get('min')}, max={stats.get('max')}, avg={stats.get('avg')}"
                    )
                    if detail:
                        lines.append(f"    meaning: {detail}")

            if table in categorical_stats:
                lines.append("**Categorical Stats**:")
                col_meta = {col["name"]: col for col in cols}
                for col, stats in categorical_stats[table].items():
                    top = stats.get("top_values", [])[:3]
                    top_str = ", ".join(
                        [f"'{v[0]}'({v[1]})" for v in top if v[0] is not None]
                    )
                    label = col_meta.get(col, {}).get("title") or col
                    detail = col_meta.get(col, {}).get("description")
                    lines.append(
                        f"  - `{label}` (`{col}`): {stats.get('unique_count')} unique, top: {top_str}"
                    )
                    if detail:
                        lines.append(f"    meaning: {detail}")

            lines.append("")

        return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────
# ContextLoader: 实验上下文加载
# ─────────────────────────────────────────────────────────────────────────


class ContextLoader:
    """实验上下文加载"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)
        self.logger = logger

    def load_context(
        self,
        hypothesis_id: str,
        experiment_id: str,
    ) -> ExperimentContext:
        """加载完整实验上下文"""
        hid = _sanitize_id(hypothesis_id)
        eid = _sanitize_id(experiment_id)

        base = self.workspace_path / f"hypothesis_{hid}"
        exp = base / f"experiment_{eid}"
        run = exp / "run"

        if not exp.exists():
            raise ValueError(f"Experiment path not found: {exp}")

        design = self.load_design(base, exp)
        duration = self._load_duration(run)
        status, completion, errors = self._analyze_status(run)

        return ExperimentContext(
            experiment_id=eid,
            hypothesis_id=hid,
            design=design,
            duration_seconds=duration,
            execution_status=status,
            completion_percentage=completion,
            error_messages=errors,
        )

    def load_design(
        self,
        hypothesis_base: Path,
        experiment_path: Path,
    ) -> ExperimentDesign:
        """加载实验设计"""
        design_data = {
            "hypothesis": "Hypothesis not specified",
            "objectives": [],
            "variables": {},
            "methodology": "",
            "success_criteria": [],
            "hypothesis_markdown": None,
            "experiment_markdown": None,
        }

        # 加载 HYPOTHESIS.md
        hyp_path = hypothesis_base / FILE_HYPOTHESIS_MD
        if hyp_path.exists():
            content = hyp_path.read_text(encoding="utf-8")
            design_data["hypothesis_markdown"] = content
            for line in content.splitlines():
                s = line.strip()
                if s and not s.startswith("#"):
                    design_data["hypothesis"] = s[:500]
                    break

        # 加载 EXPERIMENT.md
        exp_path = experiment_path / FILE_EXPERIMENT_MD
        if exp_path.exists():
            design_data["experiment_markdown"] = exp_path.read_text(encoding="utf-8")

        return ExperimentDesign(**design_data)

    def _load_duration(self, run_path: Path) -> float | None:
        """从 pid.json 读取运行时长"""
        pid_file = run_path / FILE_PID
        if not pid_file.exists():
            return None

        try:
            data = json.loads(pid_file.read_text(encoding="utf-8"))
            start_s = data.get("start_time")
            end_s = data.get("end_time")
            if start_s and end_s:
                start = datetime.fromisoformat(start_s)
                end = datetime.fromisoformat(end_s)
                return (end - start).total_seconds()
        except Exception:
            logger.debug("Failed to parse simulation duration", exc_info=True)
        return None

    def _analyze_status(
        self,
        run_path: Path,
    ) -> tuple[ExperimentStatus, float, list[str]]:
        """分析实验状态"""
        replay_dir = run_path / DIR_REPLAY
        legacy_db_path = run_path / FILE_SQLITE
        pid_file = run_path / FILE_PID
        errors: list[str] = []
        status = ExperimentStatus.UNKNOWN
        completion = 0.0

        if not (replay_dir / "_schema.json").exists() and not legacy_db_path.exists():
            return ExperimentStatus.FAILED, 0.0, ["Replay data not found"]

        # 从 pid.json 读取状态
        if pid_file.exists():
            try:
                data = json.loads(pid_file.read_text(encoding="utf-8"))
                pid_status = (data.get("status") or "").strip().lower()
                if pid_status in ("completed", "success", "done"):
                    status = ExperimentStatus.SUCCESSFUL
                elif pid_status in ("failed", "error"):
                    status = ExperimentStatus.FAILED
            except Exception as e:
                errors.append(f"Failed to read pid.json: {e}")

        # 从 run 目录收集运行时错误
        runtime_errors = self._collect_runtime_failures(run_path)
        errors.extend(runtime_errors)
        if runtime_errors and status == ExperimentStatus.SUCCESSFUL:
            status = ExperimentStatus.PARTIAL_SUCCESS

        return status, completion, errors

    def _collect_runtime_failures(self, run_path: Path) -> list[str]:
        """收集运行时失败信号"""
        import re

        failures: list[str] = []

        # 检查 artifacts 目录
        artifacts_dir = run_path / DIR_ARTIFACTS
        if artifacts_dir.exists():
            for md_path in artifacts_dir.glob("*.md"):
                try:
                    txt = md_path.read_text(encoding="utf-8")
                    lowered = txt.lower()
                    if (
                        "planning failed" in lowered
                        or "invalid json response" in lowered
                    ):
                        failures.append(f"Artifact failure in {md_path.name}")
                except OSError:
                    continue

        # 检查 output.log
        log_path = run_path / "output.log"
        if log_path.exists():
            try:
                tail = log_path.read_text(encoding="utf-8", errors="ignore")[-8000:]
                if "traceback" in tail.lower():
                    failures.append("Runtime log contains traceback")
                error_lines = [
                    ln.strip()
                    for ln in tail.splitlines()
                    if re.search(r"\bERROR\b|\bCRITICAL\b", ln)
                ]
                non_ignorable = [
                    ln
                    for ln in error_lines
                    if "litellm" not in ln.lower() and "deprecation" not in ln.lower()
                ]
                if non_ignorable:
                    failures.append("Runtime log contains ERROR/CRITICAL entries")
            except OSError:
                logger.debug("Failed to read log file", exc_info=True)

        return failures
