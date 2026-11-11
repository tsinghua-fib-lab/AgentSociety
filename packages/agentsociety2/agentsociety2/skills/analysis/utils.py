"""
分析模块工具：路径、`instruction_md` 发现、replay schema、LLM XML/报告解析。

行为与目录约定见同包 `README.md` 。
"""

import json
import re
import sqlite3
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from agentsociety2.agent.json_utils import loads_llm_json
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

# 进度回调类型，供 service/agents 等使用
AnalysisProgressCallback = Callable[[str], Awaitable[None]] | None


class XmlParseError(Exception):
    """LLM 返回的 XML 解析失败，供调用方捕获并触发 LLM 重试。"""

    def __init__(self, message: str, raw_content: str = ""):
        super().__init__(message)
        self.raw_content = raw_content


_INSTRUCTION_MD_DIR = Path(__file__).resolve().parent / "instruction_md"
T = TypeVar("T", bound=BaseModel)


@dataclass(frozen=True)
class AnalysisSkillMeta:
    """`instruction_md/*.md` 条目的元数据（供按名筛选并注入 LLM 系统上下文）。"""

    name: str
    priority: int
    description: str
    path: Path
    required: bool = False  # If True, always loaded regardless of selection


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


def _parse_skill_frontmatter(path: Path) -> dict[str, Any]:
    """从 Markdown 技能文件解析类 YAML frontmatter。

    支持的键：``name`` 、``priority`` 、``description`` 、``required`` 。
    """
    if not path.exists():
        return {}
    try:
        content = path.read_text(encoding="utf-8")
    except Exception:
        return {}

    lines = content.splitlines()
    if len(lines) < 3 or lines[0].strip() != "---":
        return {}

    result: dict[str, Any] = {}
    for line in lines[1:]:
        s = line.strip()
        if s == "---":
            break
        if not s or ":" not in s:
            continue
        key, value = s.split(":", 1)
        k = key.strip()
        v = value.strip().strip('"').strip("'")
        if k == "priority":
            try:
                result[k] = int(v)
            except ValueError:
                continue
        elif k == "required":
            result[k] = v.lower() in ("true", "yes", "1")
        else:
            result[k] = v
    return result


def _strip_md_frontmatter(text: str) -> str:
    """去掉 YAML frontmatter，只保留注入 LLM 的正文。"""
    lines = text.strip().splitlines()
    if not lines or lines[0].strip() != "---":
        return text.strip()
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return "\n".join(lines[i + 1 :]).strip()
    return text.strip()


def list_analysis_skills() -> list[AnalysisSkillMeta]:
    """扫描 `instruction_md/` 下 Markdown，返回元数据（不读取正文）。"""
    result: list[AnalysisSkillMeta] = []
    if not _INSTRUCTION_MD_DIR.exists():
        return result

    for idx, path in enumerate(sorted(_INSTRUCTION_MD_DIR.glob("*.md"))):
        meta = _parse_skill_frontmatter(path)
        name = meta.get("name") or path.stem
        priority = int(meta.get("priority", idx + 1))
        description = meta.get("description", "")
        required = meta.get("required", False)
        result.append(
            AnalysisSkillMeta(
                name=name,
                priority=priority,
                description=description,
                path=path,
                required=required,
            )
        )

    result.sort(key=lambda x: (x.priority, x.name))
    return result


def get_analysis_skills(
    selected_names: list[str] | None = None,
    strict_selection: bool = True,
) -> str:
    """加载选中的 `instruction_md/*.md` 全文并拼接为 LLM 上下文片段。

    strict_selection=True：仅加载 required 条目 + 显式点名的条目。
    标记为 required 的片段始终会加载。
    """
    metas = list_analysis_skills()
    if not metas:
        return ""

    # Always include required skills
    required_skills = [m for m in metas if m.required]
    selected_set = set(selected_names or [])

    if strict_selection:
        # In strict mode: load required + explicitly selected
        targets = required_skills + [
            m for m in metas if m.name in selected_set and not m.required
        ]
    else:
        # In non-strict mode: load all if no selection, or required + selected
        if not selected_set:
            targets = metas
        else:
            targets = required_skills + [
                m for m in metas if m.name in selected_set and not m.required
            ]

    # Remove duplicates while preserving order
    seen = set()
    unique_targets: list[AnalysisSkillMeta] = []
    for m in targets:
        if m.name not in seen:
            seen.add(m.name)
            unique_targets.append(m)

    # Sort by priority
    unique_targets.sort(key=lambda x: (x.priority, x.name))

    parts: list[str] = []
    for m in unique_targets:
        raw = m.path.read_text(encoding="utf-8")
        body = _strip_md_frontmatter(raw).strip()
        if body:
            parts.append(body)
    return "\n\n---\n\n".join(parts).strip()


def _extract_xml_from_content(content: str) -> str:
    """从 LLM 输出中提取 XML。支持整段或 ```xml ... ``` 代码块。"""
    raw = (content or "").strip()
    if not raw:
        return ""
    if raw.startswith("<"):
        return raw
    if "```" in raw:
        for part in raw.split("```"):
            s = part.strip().lstrip("xml").strip()
            if s.startswith("<"):
                return s
    return raw


def _xml_element_to_value(el: ET.Element) -> Any:
    """将 XML 元素转为 Python 值。"""
    children = list(el)
    if not children:
        text = (el.text or "").strip()
        if text.lower() in ("true", "false"):
            return text.lower() == "true"
        return text
    # 有子元素：若全为同标签且多个，直接返回列表；否则返回 dict
    tags = [c.tag for c in children]
    if len(set(tags)) == 1 and len(children) > 1:
        return [_xml_element_to_value(c) for c in children]
    result: dict[str, Any] = {}
    for c in children:
        val = _xml_element_to_value(c)
        if c.tag in result:
            if not isinstance(result[c.tag], list):
                result[c.tag] = [result[c.tag]]
            result[c.tag].append(val)
        else:
            result[c.tag] = val
    return result


def _parse_xml_to_root(xml_str: str) -> ET.Element:
    """解析 XML 字符串为 Element，使用 elemental-xenon 修复 LLM 生成的畸形 XML。"""
    from xenon import TrustLevel, repair_xml_safe

    # 使用 xenon 修复 XML（专为 LLM 输出设计）
    repaired = repair_xml_safe(xml_str, trust=TrustLevel.UNTRUSTED)

    try:
        return ET.fromstring(repaired)
    except ET.ParseError as e:
        raise XmlParseError(
            f"XML parse failed even after repair: {e}", raw_content=repaired
        ) from e


def parse_llm_xml_response(content: str, root_tag: str = "result") -> dict[str, Any]:
    """解析 LLM 返回的 XML 为字典。

    :param content: LLM 返回的原始内容（可包含 ```xml 代码块）
    :param root_tag: 根标签名，用于提取顶层 dict

    :returns: 解析后的字典
    :raises XmlParseError: XML 解析失败
    """
    xml_str = _extract_xml_from_content(content)
    if not xml_str:
        raise XmlParseError("No XML content extracted", raw_content=content)
    root = _parse_xml_to_root(xml_str)
    if root.tag == root_tag:
        return {c.tag: _xml_element_to_value(c) for c in root}
    # 根为 root_tag 的包装
    inner = root.find(root_tag)
    if inner is None:
        inner = root.find(f".//{root_tag}")
    if inner is not None:
        return {c.tag: _xml_element_to_value(c) for c in inner}
    return {c.tag: _xml_element_to_value(c) for c in root}


def parse_llm_xml_to_model(
    content: str, model_class: type[T], root_tag: str = "result"
) -> T:
    """解析 LLM 返回的 XML 并验证为 Pydantic 模型。"""
    data = parse_llm_xml_response(content, root_tag)
    # 处理 item 包装：<insights><item>a</item></insights> -> insights: ["a"]
    for k, v in list(data.items()):
        if isinstance(v, dict) and "item" in v and len(v) == 1:
            items = v["item"]
            data[k] = items if isinstance(items, list) else [items]
    return model_class.model_validate(data)


def _take_json_string(content: str) -> str:
    """从约定格式中取出 JSON 字符串：整段即 JSON，或 ```json ... ``` 中唯一一段。"""
    raw = (content or "").strip()
    if not raw:
        return ""
    if raw.startswith("```"):
        parts = raw.split("```")
        for i, p in enumerate(parts):
            s = p.strip()
            if i == 0:
                s = s.lstrip("json").strip()
            if s and (s.startswith(("{", "["))):
                return s
        return ""
    return raw


def parse_llm_json_response(content: str) -> dict[str, Any]:
    """解析 LLM 返回的 JSON，约定为单段 JSON 或 ```json ... ```。

    - 提取不到 JSON 或 JSON 根不是 object：抛出 ValueError。
    """
    json_str = _take_json_string(content)
    if not json_str:
        raise ValueError("No JSON content extracted")
    data = loads_llm_json(json_str, expect="object")
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data


def parse_llm_report_response(content: str) -> dict[str, str]:
    """解析报告类 LLM 输出（XML 格式，双语）。

    格式::
        <report>
          <markdown_zh><![CDATA[...]]></markdown_zh>
          <html_zh><![CDATA[...]]></html_zh>
          <markdown_en><![CDATA[...]]></markdown_en>
          <html_en><![CDATA[...]]></html_en>
        </report>

    返回字典，键为：``markdown_zh`` 、``html_zh`` 、``markdown_en`` 、
    ``html_en`` 、``markdown`` 、``html`` 。

    - 缺少必须的字段（至少 markdown_zh/markdown_en + html_zh/html_en）：抛出 XmlParseError。
    """
    raw = (content or "").strip()
    if not raw:
        raise XmlParseError("Empty report content", raw_content=content)
    xml_str = raw
    if "```" in raw:
        for part in raw.split("```"):
            s = part.strip().lstrip("xml").strip()
            if "<report" in s or s.startswith("<report"):
                xml_str = s
                break
    root = _parse_xml_to_root(xml_str)

    def _text(tag: str) -> str:
        el = root.find(f".//{tag}")
        if el is None:
            el = root.find(tag)
        return "".join(el.itertext()).strip() if el is not None else ""

    md_zh = _text("markdown_zh")
    html_zh = _text("html_zh")
    md_en = _text("markdown_en")
    html_en = _text("html_en")

    if not md_zh and not md_en:
        raise XmlParseError(
            "Report must include markdown_zh or markdown_en", raw_content=content
        )
    if not html_zh and not html_en:
        raise XmlParseError(
            "Report must include html_zh or html_en", raw_content=content
        )

    return {
        "markdown_zh": md_zh,
        "html_zh": html_zh,
        "markdown_en": md_en,
        "html_en": html_en,
        "markdown": md_zh or md_en,
        "html": html_zh or html_en,
    }


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
