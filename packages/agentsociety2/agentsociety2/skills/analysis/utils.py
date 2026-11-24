"""
分析模块工具：路径、replay schema 与实验文件发现。

行为与目录约定见同包 `README.md` 。
"""

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from agentsociety2.storage.replay_metadata import (
    COLUMN_CATALOG_TABLE,
    DATASET_CATALOG_TABLE,
)
from agentsociety2.storage.replay_reader import ReplayReader

from .models import (
    DIR_ARTIFACTS,
    DIR_CHARTS,
    DIR_DATA,
    DIR_EXPERIMENT_PREFIX,
    DIR_HYPOTHESIS_PREFIX,
    DIR_REPLAY,
    DIR_REPORT_ASSETS,
    DIR_RUN,
    DIR_SYNTHESIS,
    FILE_ANALYSIS_SUMMARY_JSON,
    FILE_PID,
    FILE_README_MD,
    FILE_REPORT_EN_HTML,
    FILE_REPORT_EN_MD,
    FILE_REPORT_ZH_HTML,
    FILE_REPORT_ZH_MD,
    FILE_SQLITE,
    FILE_SYNTHESIS_REPORT_EN_SUFFIX,
    FILE_SYNTHESIS_REPORT_PREFIX,
    FILE_SYNTHESIS_REPORT_ZH_SUFFIX,
    ExperimentPaths,
    PresentationPaths,
    SynthesisPaths,
)


def _sanitize_id(raw: str) -> str:
    """仅保留安全字符，防止路径穿越。"""
    s = (raw or "").strip()
    s = re.sub(r"[^a-zA-Z0-9_-]", "", s)
    return s or "unknown"


def _resolve_replay_dir(path: Path) -> Path | None:
    """返回 ``run``/``replay``/``sqlite.db`` 兼容路径对应的 replay 目录。"""
    p = Path(path)
    candidates = []
    if p.is_dir():
        candidates.extend([p, p / DIR_REPLAY])
    else:
        candidates.append(p.parent / DIR_REPLAY)
    for candidate in candidates:
        if (candidate / "_schema.json").exists():
            return candidate
    return None


def experiment_paths(
    workspace_path: Path,
    hypothesis_id: str,
    experiment_id: str,
) -> ExperimentPaths:
    """按约定聚合单实验路径；id 会做安全清洗。"""
    wp = Path(workspace_path).resolve()
    hid = _sanitize_id(hypothesis_id)
    eid = _sanitize_id(experiment_id)
    base = wp / f"{DIR_HYPOTHESIS_PREFIX}{hid}"
    exp = base / f"{DIR_EXPERIMENT_PREFIX}{eid}"
    run = exp / DIR_RUN
    replay = run / DIR_REPLAY
    legacy_sqlite = run / FILE_SQLITE
    data_path = (
        legacy_sqlite if legacy_sqlite.exists() and not replay.exists() else replay
    )
    return ExperimentPaths(
        hypothesis_base=base,
        experiment_path=exp,
        run_path=run,
        db_path=data_path,
        pid_path=run / FILE_PID,
        assets_path=run / DIR_ARTIFACTS,
    )


def presentation_paths(
    presentation_root: Path,
    hypothesis_id: str,
    experiment_id: str,
) -> PresentationPaths:
    """单实验分析产物路径：按 hypothesis 聚合，实验 id 仅保留接口兼容。"""
    root = Path(presentation_root).resolve()
    hid = _sanitize_id(hypothesis_id)
    _sanitize_id(experiment_id)
    output_dir = root / f"{DIR_HYPOTHESIS_PREFIX}{hid}"
    charts_dir = output_dir / DIR_CHARTS
    report_assets_dir = output_dir / DIR_REPORT_ASSETS
    data_dir = output_dir / DIR_DATA
    return PresentationPaths(
        output_dir=output_dir,
        charts_dir=charts_dir,
        report_assets_dir=report_assets_dir,
        report_zh_md=output_dir / FILE_REPORT_ZH_MD,
        report_zh_html=output_dir / FILE_REPORT_ZH_HTML,
        report_en_md=output_dir / FILE_REPORT_EN_MD,
        report_en_html=output_dir / FILE_REPORT_EN_HTML,
        result_json=data_dir / FILE_ANALYSIS_SUMMARY_JSON,
        readme=output_dir / FILE_README_MD,
    )


def synthesis_paths(
    workspace_path: Path,
) -> SynthesisPaths:
    """综合报告路径：写入独立的 synthesis/ 根目录。"""

    wp = Path(workspace_path).resolve()
    output_dir = wp / DIR_SYNTHESIS
    return SynthesisPaths(
        output_dir=output_dir,
        report_assets_dir=output_dir / DIR_REPORT_ASSETS,
        report_zh_md=output_dir
        / f"{FILE_SYNTHESIS_REPORT_PREFIX.rstrip('_')}{FILE_SYNTHESIS_REPORT_ZH_SUFFIX}.md",
        report_en_md=output_dir
        / f"{FILE_SYNTHESIS_REPORT_PREFIX.rstrip('_')}{FILE_SYNTHESIS_REPORT_EN_SUFFIX}.md",
    )



# ---------- 先读结构再处理：DB schema 与实验文件 ----------


def _quote_identifier(name: str) -> str:
    """安全引用 SQLite 标识符（表名、列名）。"""
    return '"' + str(name).replace('"', '""') + '"'


def extract_database_schema(db_path: Path) -> dict[str, Any]:
    """从 metadata catalog 表提取 replay schema。"""
    if not db_path or not db_path.exists():
        return {}
    replay_dir = _resolve_replay_dir(db_path)
    if replay_dir is not None:
        reader = ReplayReader(replay_dir)
        try:
            schema: dict[str, Any] = {}
            for dataset in reader.load_dataset_catalog():
                meta = {
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
                columns = []
                pk_columns = {
                    key
                    for key in (dataset.get("entity_key"), dataset.get("step_key"))
                    if key
                }
                for column in dataset.get("columns", []):
                    name = column.get("column_name")
                    columns.append(
                        {
                            "name": name,
                            "type": column.get("sqlite_type", "TEXT"),
                            "logical_type": column.get("logical_type"),
                            "analysis_role": column.get("analysis_role"),
                            "title": column.get("title"),
                            "description": column.get("description"),
                            "unit": column.get("unit"),
                            "enum_values": column.get("enum_values"),
                            "example": column.get("example"),
                            "notnull": not bool(column.get("nullable", True)),
                            "pk": name in pk_columns,
                            "tags": list(column.get("tags") or []),
                            "dataset": meta,
                        }
                    )
                schema[dataset["table_name"]] = columns
            return schema
        finally:
            reader.close()
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = {row[0] for row in cursor.fetchall()}
        if DATASET_CATALOG_TABLE not in tables or COLUMN_CATALOG_TABLE not in tables:
            # Fallback to PRAGMA-based schema extraction when catalog tables are absent
            schema = {}
            for table_name in tables:
                cursor.execute(f"PRAGMA table_info({_quote_identifier(table_name)})")
                columns = cursor.fetchall()
                schema[table_name] = [
                    {
                        "name": col[1],
                        "type": col[2],
                        "notnull": bool(col[3]),
                        "pk": bool(col[5]),
                    }
                    for col in columns
                ]
            conn.close()
            return schema

        cursor.execute(
            f"SELECT dataset_id, table_name, kind, title, description, entity_key, step_key, time_key, default_order_json, capabilities_json "
            f"FROM {DATASET_CATALOG_TABLE} ORDER BY dataset_id"
        )
        dataset_rows = cursor.fetchall()
        dataset_meta_by_table: dict[str, dict[str, Any]] = {}
        for row in dataset_rows:
            default_order = json.loads(row[8]) if row[8] else []
            capabilities = json.loads(row[9]) if row[9] else []
            dataset_meta_by_table[row[1]] = {
                "dataset_id": row[0],
                "kind": row[2],
                "title": row[3],
                "description": row[4],
                "entity_key": row[5],
                "step_key": row[6],
                "time_key": row[7],
                "default_order": (
                    default_order if isinstance(default_order, list) else []
                ),
                "capabilities": capabilities if isinstance(capabilities, list) else [],
            }

        cursor.execute(
            f"SELECT dataset_id, column_name, sqlite_type, logical_type, analysis_role, title, description, unit, enum_json, example_json, nullable, tags_json "
            f"FROM {COLUMN_CATALOG_TABLE} ORDER BY dataset_id, column_name"
        )
        column_rows = cursor.fetchall()
        columns_by_dataset: dict[str, list[dict[str, Any]]] = {}
        for row in column_rows:
            enum_values = json.loads(row[8]) if row[8] else None
            example = json.loads(row[9]) if row[9] else None
            tags = json.loads(row[11]) if row[11] else []
            columns_by_dataset.setdefault(row[0], []).append(
                {
                    "name": row[1],
                    "type": row[2],
                    "logical_type": row[3],
                    "analysis_role": row[4],
                    "title": row[5],
                    "description": row[6],
                    "unit": row[7],
                    "enum_values": enum_values,
                    "example": example,
                    "notnull": not bool(row[10]),
                    "pk": False,
                    "tags": tags if isinstance(tags, list) else [],
                }
            )

        schema: dict[str, Any] = {}
        for table_name, meta in dataset_meta_by_table.items():
            dataset_columns = columns_by_dataset.get(meta["dataset_id"], [])
            pk_columns = {
                key for key in (meta.get("entity_key"), meta.get("step_key")) if key
            }
            schema[table_name] = []
            for column in dataset_columns:
                column = dict(column)
                column["pk"] = column["name"] in pk_columns
                column["dataset"] = meta
                schema[table_name].append(column)
        return schema
    finally:
        conn.close()


def format_database_schema_markdown(
    schema: dict[str, Any],
    include_row_counts: bool = False,
    db_path: Path | None = None,
) -> str:
    """将 replay metadata schema 格式化为 Markdown，可选行数。"""
    if not schema:
        return "Schema not available"
    lines = []
    for table_name, columns in schema.items():
        dataset = columns[0].get("dataset") if columns else None
        dataset_id = (
            dataset.get("dataset_id") if isinstance(dataset, dict) else table_name
        )
        lines.append(f"### Dataset: `{dataset_id}`")
        lines.append(f"- Table: `{table_name}`")
        if isinstance(dataset, dict):
            lines.append(f"- Kind: `{dataset.get('kind', '')}`")
            capabilities = dataset.get("capabilities") or []
            if capabilities:
                lines.append(
                    f"- Capabilities: {', '.join(f'`{cap}`' for cap in capabilities)}"
                )
            description = dataset.get("description")
            if description:
                lines.append(f"- Description: {description}")
        lines.append(f"Columns: {', '.join([col['name'] for col in columns])}")
        for col in columns:
            pk_marker = " (PRIMARY KEY)" if col.get("pk") else ""
            extras = []
            if col.get("logical_type"):
                extras.append(f"logical_type={col['logical_type']}")
            if col.get("analysis_role"):
                extras.append(f"analysis_role={col['analysis_role']}")
            if col.get("unit"):
                extras.append(f"unit={col['unit']}")
            extra_text = f" [{' ; '.join(extras)}]" if extras else ""
            lines.append(f"  - {col['name']} ({col['type']}){pk_marker}{extra_text}")
            if col.get("description"):
                lines.append(f"    description: {col['description']}")
        lines.append("")
    if include_row_counts and db_path:
        lines.append("### Table Row Counts")
        replay_dir = _resolve_replay_dir(db_path)
        if replay_dir is not None:
            reader = ReplayReader(replay_dir)
            try:
                datasets_by_table = {
                    dataset["table_name"]: dataset
                    for dataset in reader.load_dataset_catalog()
                }
                for table_name in schema:
                    dataset = datasets_by_table.get(table_name)
                    count = reader.count_dataset_rows(dataset) if dataset else 0
                    lines.append(f"- `{table_name}`: {count} rows")
            finally:
                reader.close()
        else:
            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            for table_name in schema:
                cursor.execute(f"SELECT COUNT(*) FROM {_quote_identifier(table_name)}")
                count = cursor.fetchone()[0]
                lines.append(f"- `{table_name}`: {count} rows")
            conn.close()
    return "\n".join(lines)


def collect_experiment_files(db_path: Path) -> list[str]:
    """收集 run 目录下可供执行器使用的文件路径（含 replay/、同级文件、run/artifacts）。"""
    if not db_path:
        return []
    files: list[str] = [str(db_path)]
    if not db_path.exists():
        return files
    run_dir = db_path.parent
    if db_path.is_dir() and db_path.name != DIR_REPLAY:
        run_dir = db_path
    if run_dir.exists():
        for p in run_dir.glob("*"):
            if p.is_file() and p != db_path:
                files.append(str(p))
            elif p.is_dir() and p.name == DIR_REPLAY:
                for replay_file in p.glob("*"):
                    if replay_file.is_file():
                        files.append(str(replay_file))
        artifacts_dir = run_dir / DIR_ARTIFACTS
        if artifacts_dir.exists():
            for p in artifacts_dir.rglob("*"):
                if p.is_file():
                    files.append(str(p))
    return files
