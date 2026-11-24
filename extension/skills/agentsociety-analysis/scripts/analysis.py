#!/usr/bin/env python3
"""Core analysis CLI subcommands for context, schema, and query access."""

import argparse
import dataclasses
import inspect
import json
import os
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from pydantic import BaseModel


def _default_workspace() -> Path:
    raw_workspace = os.environ.get("AGENTSOCIETY_WORKSPACE")
    if raw_workspace:
        return Path(raw_workspace).expanduser().resolve()
    return Path.cwd().resolve()


def _load_workspace_env() -> None:
    env_file = _default_workspace() / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)


_load_workspace_env()

ContextLoader: type[Any] | None = None
DataReader: type[Any] | None = None
extract_database_schema: Any = None
EDAGenerator: type[Any] | None = None
AssetManager: type[Any] | None = None
ReportAsset: type[Any] | None = None
SUPPORTED_IMAGE_FORMATS: set[str] | None = None
_DEFAULT_IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".svg", ".pdf", ".webp"}


def _ensure_analysis_dependencies() -> None:
    """Load analysis dependencies from the active Python interpreter."""

    global ContextLoader
    global DataReader
    global extract_database_schema
    global EDAGenerator
    global AssetManager
    global ReportAsset
    global SUPPORTED_IMAGE_FORMATS
    if ContextLoader is not None:
        return

    try:
        from agentsociety2.skills.analysis import (
            AssetManager as _AssetManager,
            ContextLoader as _ContextLoader,
            DataReader as _DataReader,
            EDAGenerator as _EDAGenerator,
            extract_database_schema as _extract_database_schema,
        )
        from agentsociety2.skills.analysis.models import (
            ReportAsset as _ReportAsset,
            SUPPORTED_IMAGE_FORMATS as _SUPPORTED_IMAGE_FORMATS,
        )
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "agentsociety2 is not available in the current Python interpreter. "
            "Run this script with the workspace PYTHON_PATH from .env "
            "(for example: `$PYTHON_PATH .agentsociety/bin/ags.py analysis ...`)."
        ) from exc

    ContextLoader = _ContextLoader
    DataReader = _DataReader
    extract_database_schema = _extract_database_schema
    EDAGenerator = _EDAGenerator
    AssetManager = _AssetManager
    ReportAsset = _ReportAsset
    SUPPORTED_IMAGE_FORMATS = _SUPPORTED_IMAGE_FORMATS


class _ArgumentParseError(Exception):
    pass


class _ArgumentParseExit(Exception):
    pass


class _JsonArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _ArgumentParseError(message)

    def exit(self, status: int = 0, message: str | None = None) -> None:
        if status == 0 and not message:
            raise _ArgumentParseExit
        if message:
            raise _ArgumentParseError(message.strip())
        raise _ArgumentParseError(f"argument parsing exited with status {status}")


def _json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _emit(payload: dict[str, Any]) -> None:
    sys.stdout.write(
        json.dumps(
            payload, default=_json_default, ensure_ascii=False, separators=(",", ":")
        )
    )
    sys.stdout.write("\n")


def _ok(**payload: Any) -> int:
    _emit({"success": True, **payload})
    return 0


def _error(message: str, **payload: Any) -> int:
    _emit({"success": False, "error": message, **payload})
    return 1


def _blocked_result(message: str, **payload: Any) -> dict[str, Any]:
    return {"status": "BLOCKED", "error": message, **payload}


def _failed_result(message: str, **payload: Any) -> dict[str, Any]:
    return {"status": "FAILED", "error": message, **payload}


def _emit_local_result(result: dict[str, Any]) -> int:
    error = result.get("error")
    if error:
        return _error(
            str(error),
            **{key: value for key, value in result.items() if key != "error"},
        )
    return _ok(**result)


def _eda_profile_choices() -> list[str]:
    try:
        from agentsociety2.skills.analysis.harness.capabilities import (
            EDA_PROFILE_MODULES,
        )

        return list(EDA_PROFILE_MODULES)
    except ImportError:
        return [
            "quick-stats",
            "ydata",
            "sweetviz",
            "missingno",
            "correlation",
            "pygwalker",
            "datatable",
            "plotly-profile",
            "eda-hub",
            "bundle",
        ]


def _add_contract_input(
    container: Any,
    input_spec: Any,
    *,
    workspace_default: str,
    in_group: bool = False,
) -> None:
    kwargs: dict[str, Any] = {"dest": input_spec.name}
    if input_spec.action:
        kwargs["action"] = input_spec.action
    elif not in_group:
        kwargs["required"] = input_spec.cli_required
    if input_spec.default_source == "workspace":
        kwargs["default"] = workspace_default
    elif input_spec.default is not None:
        kwargs["default"] = input_spec.default
    if input_spec.choices:
        kwargs["choices"] = list(input_spec.choices)
    if input_spec.help:
        kwargs["help"] = input_spec.help
    container.add_argument(*input_spec.flags, **kwargs)


def _build_parser_from_registry() -> argparse.ArgumentParser:
    from agentsociety2.skills.analysis.harness.operations import operation_registry

    parser = _JsonArgumentParser(description="Analysis CLI tool layer")
    subparsers = parser.add_subparsers(dest="command", required=True)
    workspace_default = str(_default_workspace())

    for operation in operation_registry().values():
        command_parser = subparsers.add_parser(
            operation.id,
            help=operation.summary,
            description=operation.summary,
        )
        input_by_name = {input_spec.name: input_spec for input_spec in operation.inputs}
        grouped_inputs: set[str] = set()
        for input_group in operation.input_groups:
            argument_group = command_parser.add_mutually_exclusive_group(
                required=input_group.required
            )
            for member in input_group.members:
                _add_contract_input(
                    argument_group,
                    input_by_name[member],
                    workspace_default=workspace_default,
                    in_group=True,
                )
                grouped_inputs.add(member)
        for input_spec in operation.inputs:
            if input_spec.name in grouped_inputs:
                continue
            _add_contract_input(
                command_parser,
                input_spec,
                workspace_default=workspace_default,
            )
        command_parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Evaluate operation availability without executing the handler",
        )
    return parser


def _build_parser() -> argparse.ArgumentParser:
    return _build_parser_from_registry()


def _parse_csv_list(raw_value: str | None) -> list[str] | None:
    if raw_value is None:
        return None
    items = []
    seen = set()
    for item in raw_value.split(","):
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        items.append(normalized)
    return items or None


def _get_supported_image_formats() -> set[str]:
    return SUPPORTED_IMAGE_FORMATS or _DEFAULT_IMAGE_FORMATS


def _validate_read_only_sql(sql: str) -> str:
    normalized_sql = (sql or "").strip()
    if not normalized_sql:
        raise ValueError("query-data only supports read-only SQL queries")
    if ";" in normalized_sql.rstrip(";"):
        raise ValueError("query-data only supports a single read-only SQL statement")

    compact_sql = re.sub(r"\s+", " ", normalized_sql).strip().lower()
    if not (compact_sql.startswith("select ") or compact_sql.startswith("with ")):
        raise ValueError("query-data only supports read-only SELECT or WITH queries")

    blocked_tokens = (
        " insert ",
        " update ",
        " delete ",
        " drop ",
        " alter ",
        " attach ",
        " detach ",
        " create ",
        " replace ",
        " pragma ",
        " reindex ",
        " vacuum ",
    )
    scan_sql = f" {compact_sql} "
    if any(token in scan_sql for token in blocked_tokens):
        raise ValueError("query-data only supports read-only SQL queries")
    return normalized_sql


def _validate_plotting_conventions(code: str) -> None:
    """Require the publication plotting scaffold used by generated chart scripts."""

    text = code or ""
    compact = re.sub(r"\s+", "", text)
    missing: list[str] = []

    if not re.search(r"(?:matplotlib|mpl)\.use\(\s*['\"]Agg['\"]\s*\)", text):
        missing.append('matplotlib backend configured to "Agg"')

    has_font_family = (
        'rcParams["font.family"]' in text
        or "rcParams['font.family']" in text
        or '"font.family":' in text
        or "'font.family':" in text
    )
    if not has_font_family:
        missing.append('`font.family = "sans-serif"`')

    has_sans_serif = (
        'rcParams["font.sans-serif"]' in text
        or "rcParams['font.sans-serif']" in text
        or '"font.sans-serif":' in text
        or "'font.sans-serif':" in text
    )
    if not has_sans_serif:
        missing.append("`font.sans-serif` configured with readable fallbacks")

    has_svg_fonttype_none = (
        'rcParams["svg.fonttype"]="none"' in compact
        or "rcParams['svg.fonttype']='none'" in compact
        or '"svg.fonttype":"none"' in compact
        or "'svg.fonttype':'none'" in compact
    )
    if not has_svg_fonttype_none:
        missing.append('`svg.fonttype = "none"`')

    if missing:
        raise ValueError("Plotting script must include: " + "; ".join(missing))


def _filter_assets_with_companions(
    assets: list[Any],
    selected_names: set[str],
) -> list[Any]:
    if not selected_names:
        return assets

    selected_stems = {
        Path(name).stem
        for name in selected_names
        if Path(name).suffix.lower() in _get_supported_image_formats()
    }

    filtered_assets = []
    for asset in assets:
        asset_name = Path(asset.file_path).name
        asset_stem = Path(asset_name).stem
        if asset_name in selected_names or asset_stem in selected_stems:
            filtered_assets.append(asset)
    return filtered_assets


def _require_pillow() -> tuple[Any, Any, Any]:
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "compose-figure requires Pillow. Install it in the active Python "
            "environment, then rerun the command."
        ) from exc
    return Image, ImageDraw, ImageFont


def _ensure_positive_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _ensure_non_negative_int(value: Any, field_name: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _resolve_compose_path(raw_path: str, base_dir: Path) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = base_dir / path
    return path.resolve()


def _load_compose_font(image_font: Any, size: int) -> Any:
    candidates = (
        "DejaVuSans-Bold.ttf",
        "Arial Bold.ttf",
        "Arial.ttf",
    )
    for candidate in candidates:
        try:
            return image_font.truetype(candidate, size=size)
        except OSError:
            continue
    return image_font.load_default()


def _fit_image_to_box(
    image: Any,
    box_width: int,
    box_height: int,
    preserve_aspect: bool = True,
) -> tuple[Any, tuple[int, int]]:
    if preserve_aspect:
        resized = image.copy()
        resized.thumbnail((box_width, box_height))
        offset_x = (box_width - resized.width) // 2
        offset_y = (box_height - resized.height) // 2
        return resized, (offset_x, offset_y)

    return image.resize((box_width, box_height)), (0, 0)


def _grid_boxes(
    canvas_width: int,
    canvas_height: int,
    layout: dict[str, Any],
    panel_count: int,
) -> list[dict[str, int]]:
    rows = _ensure_positive_int(layout.get("rows"), "layout.rows")
    cols = _ensure_positive_int(layout.get("cols"), "layout.cols")
    capacity = rows * cols
    if panel_count > capacity:
        raise ValueError(
            f"layout grid capacity is {capacity}, but spec declares {panel_count} panels"
        )

    gap = _ensure_non_negative_int(layout.get("gap", 32), "layout.gap")
    padding = _ensure_non_negative_int(layout.get("padding", 72), "layout.padding")
    inner_width = canvas_width - padding * 2 - gap * (cols - 1)
    inner_height = canvas_height - padding * 2 - gap * (rows - 1)
    if inner_width <= 0 or inner_height <= 0:
        raise ValueError("layout padding and gap leave no drawable area on the canvas")

    cell_width = inner_width // cols
    cell_height = inner_height // rows
    boxes: list[dict[str, int]] = []
    for index in range(panel_count):
        row = index // cols
        col = index % cols
        x = padding + col * (cell_width + gap)
        y = padding + row * (cell_height + gap)
        boxes.append(
            {
                "x": x,
                "y": y,
                "width": cell_width,
                "height": cell_height,
            }
        )
    return boxes


def _manual_boxes(panels: list[dict[str, Any]]) -> list[dict[str, int]]:
    boxes: list[dict[str, int]] = []
    for index, panel in enumerate(panels):
        box = panel.get("box")
        if not isinstance(box, dict):
            raise ValueError(
                f'panel {index} requires a "box" object when layout.type is "manual"'
            )
        boxes.append(
            {
                "x": _ensure_non_negative_int(box.get("x"), f"panels[{index}].box.x"),
                "y": _ensure_non_negative_int(box.get("y"), f"panels[{index}].box.y"),
                "width": _ensure_positive_int(
                    box.get("width"), f"panels[{index}].box.width"
                ),
                "height": _ensure_positive_int(
                    box.get("height"), f"panels[{index}].box.height"
                ),
            }
        )
    return boxes


def _draw_panel_label(
    canvas: Any,
    image_draw: Any,
    image_font: Any,
    label: str,
    box: dict[str, int],
) -> None:
    font = _load_compose_font(image_font, size=42)
    draw = image_draw.Draw(canvas)
    text = label.strip()
    if not text:
        return

    left = box["x"] + 18
    top = box["y"] + 12
    draw.text((left, top), text, fill="#111111", font=font)


def _load_compose_spec(spec_path: Path) -> dict[str, Any]:
    """读取并校验 compose-figure 规格文件的最小结构。

    :param spec_path: 规格文件路径。
    :returns: 解析后的规格对象。
    :raises ValueError: 文件不可读、不是 JSON 对象或缺少必要字段时抛出。
    """

    try:
        raw_spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"cannot read compose-figure spec: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"compose-figure spec is not valid JSON: {exc}") from exc
    if not isinstance(raw_spec, dict):
        raise ValueError("compose-figure spec must be a JSON object")

    panels = raw_spec.get("panels")
    if not isinstance(panels, list) or not panels:
        raise ValueError("compose-figure spec must include a non-empty panels array")

    output_value = raw_spec.get("output")
    if not isinstance(output_value, str) or not output_value.strip():
        raise ValueError('compose-figure spec must include a non-empty "output" path')
    return raw_spec


def _compose_figure(spec_path: Path) -> dict[str, Any]:
    Image, ImageDraw, ImageFont = _require_pillow()

    raw_spec = _load_compose_spec(spec_path)
    panels = raw_spec["panels"]
    output_value = raw_spec["output"]
    canvas_spec = raw_spec.get("canvas") or {}
    if not isinstance(canvas_spec, dict):
        raise ValueError('"canvas" must be an object when provided')
    canvas_width = _ensure_positive_int(canvas_spec.get("width", 2400), "canvas.width")
    canvas_height = _ensure_positive_int(
        canvas_spec.get("height", 1400), "canvas.height"
    )
    background = canvas_spec.get("background", "#FFFFFF")
    if not isinstance(background, str) or not background.strip():
        raise ValueError("canvas.background must be a non-empty color string")

    layout = raw_spec.get("layout") or {"type": "grid", "rows": 1, "cols": len(panels)}
    if not isinstance(layout, dict):
        raise ValueError('"layout" must be an object when provided')
    layout_type = str(layout.get("type", "grid")).strip().lower()
    if layout_type not in {"grid", "manual"}:
        raise ValueError('layout.type must be either "grid" or "manual"')

    boxes = (
        _grid_boxes(canvas_width, canvas_height, layout, len(panels))
        if layout_type == "grid"
        else _manual_boxes(panels)
    )

    base_dir = spec_path.parent
    output_path = _resolve_compose_path(output_value, base_dir)
    if output_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        output_path = output_path.with_suffix(".png")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    canvas = Image.new("RGBA", (canvas_width, canvas_height), background)
    panel_summaries: list[dict[str, Any]] = []
    supported_suffixes = {".png", ".jpg", ".jpeg", ".webp"}

    for index, (panel, box) in enumerate(zip(panels, boxes)):
        if not isinstance(panel, dict):
            raise ValueError(f"panels[{index}] must be an object")

        source_value = panel.get("source")
        if not isinstance(source_value, str) or not source_value.strip():
            raise ValueError(f'panels[{index}] must include a non-empty "source" path')

        source_path = _resolve_compose_path(source_value, base_dir)
        if source_path.suffix.lower() not in supported_suffixes:
            raise ValueError(
                "compose-figure currently supports raster inputs only: "
                ".png, .jpg, .jpeg, .webp. Export a PNG companion first for "
                f"{source_path.name}."
            )
        if not source_path.exists():
            raise FileNotFoundError(str(source_path))

        preserve_aspect = bool(panel.get("preserve_aspect", True))
        with Image.open(source_path) as opened_image:
            fitted_image, offset = _fit_image_to_box(
                opened_image.convert("RGBA"),
                box["width"],
                box["height"],
                preserve_aspect=preserve_aspect,
            )

        paste_x = box["x"] + offset[0]
        paste_y = box["y"] + offset[1]
        canvas.alpha_composite(fitted_image, (paste_x, paste_y))

        label = str(panel.get("label", "")).strip()
        if label:
            _draw_panel_label(
                canvas,
                ImageDraw,
                ImageFont,
                label,
                box,
            )

        panel_summaries.append(
            {
                "label": label or None,
                "source": str(source_path),
                "box": box,
                "rendered_size": {
                    "width": fitted_image.width,
                    "height": fitted_image.height,
                },
            }
        )

    if output_path.suffix.lower() in {".jpg", ".jpeg"}:
        canvas.convert("RGB").save(output_path, quality=95)
    else:
        canvas.save(output_path)

    metadata_path = output_path.with_suffix(".json")
    metadata = {
        "output": str(output_path),
        "canvas": {
            "width": canvas_width,
            "height": canvas_height,
            "background": background,
        },
        "layout": {
            "type": layout_type,
            **{k: v for k, v in layout.items() if k != "type"},
        },
        "panels": panel_summaries,
    }
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {
        "output": str(output_path),
        "metadata": str(metadata_path),
        "panels": panel_summaries,
    }


def _experiment_data_paths(
    workspace: Path,
    hypothesis_id: str,
    experiment_id: str,
) -> dict[str, Path]:
    run_dir = (
        workspace
        / f"hypothesis_{hypothesis_id}"
        / f"experiment_{experiment_id}"
        / "run"
    )
    replay_path = run_dir / "replay"
    sqlite_path = run_dir / "sqlite.db"
    if (replay_path / "_schema.json").is_file():
        data_path = replay_path
    elif sqlite_path.is_file():
        data_path = sqlite_path
    elif replay_path.is_dir():
        data_path = replay_path
    else:
        data_path = replay_path
    return {
        "data_path": data_path,
        "db_path": data_path,
        "replay_path": replay_path,
        "sqlite_path": sqlite_path,
    }


def _run_load_context(args: argparse.Namespace) -> int:
    _ensure_analysis_dependencies()
    workspace = Path(args.workspace)
    context = ContextLoader(workspace).load_context(
        args.hypothesis_id, args.experiment_id
    )
    return _ok(
        context=context,
        paths=_experiment_data_paths(
            workspace,
            str(context.hypothesis_id),
            str(context.experiment_id),
        ),
    )


def _run_list_tables(args: argparse.Namespace) -> int:
    _ensure_analysis_dependencies()
    data_path = Path(args.data_path)
    schema = extract_database_schema(data_path)
    tables = [
        {"name": name, "column_count": len(columns)}
        for name, columns in sorted(schema.items())
    ]
    return _ok(tables=tables)


def _run_data_summary(args: argparse.Namespace) -> int:
    _ensure_analysis_dependencies()
    summary = DataReader(Path(args.data_path)).read_full_summary()
    return _ok(
        summary={
            "data_path": summary.db_path,
            "db_path": summary.db_path,
            "tables": summary.tables,
            "row_counts": summary.row_counts,
            "schema_markdown": summary.schema_markdown,
            "numeric_stats": summary.numeric_stats,
            "categorical_stats": summary.categorical_stats,
            "sample_data": summary.sample_data,
        }
    )


def _run_query_data(args: argparse.Namespace) -> int:
    db_path = Path(args.data_path).resolve()
    sql = _validate_read_only_sql(args.sql)
    replay_schema = db_path / "_schema.json" if db_path.is_dir() else None
    if replay_schema is not None and replay_schema.exists():
        from agentsociety2.storage import ReplayReader

        reader = ReplayReader(db_path)
        try:
            for dataset in reader.load_dataset_catalog():
                reader._ensure_view(dataset)
            cursor = reader._connection().execute(sql)
            columns = [column[0] for column in cursor.description or []]
            rows = [list(row) for row in cursor.fetchall()]
            return _ok(columns=columns, rows=rows, count=len(rows))
        finally:
            reader.close()
    db_uri = db_path.as_uri() + "?mode=ro"
    with sqlite3.connect(db_uri, uri=True) as conn:
        cursor = conn.execute(sql)
        columns = [column[0] for column in cursor.description or []]
        rows = [list(row) for row in cursor.fetchall()]
    return _ok(columns=columns, rows=rows, count=len(rows))


def _execute_eda(args: argparse.Namespace) -> dict[str, Any]:
    _ensure_analysis_dependencies()
    from agentsociety2.skills.analysis.harness.capabilities import (
        get_eda_capability_status,
    )

    capability = get_eda_capability_status(args.type)
    capability_data = capability.model_dump(mode="json")
    if capability.state != "available":
        return _blocked_result(
            f"run-eda --type {args.type} is {capability.state}: {capability.detail}",
            capability=capability_data,
        )

    db_path = Path(args.data_path)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    tables = _parse_csv_list(args.tables)
    generator = EDAGenerator()
    reader = DataReader(db_path)
    requested_tables, selected_tables, invalid_tables = (
        generator.resolve_table_selection(
            reader,
            tables,
        )
    )

    if requested_tables and not selected_tables:
        requested = ", ".join(requested_tables)
        return _blocked_result(
            f"run-eda: none of the requested tables are available: {requested}"
        )

    if args.type == "quick-stats":
        content = generator.generate_quick_stats(db_path, tables=selected_tables)
        quick_stats_path = output_dir / "eda_quick_stats.md"
        quick_stats_path.write_text(content or "", encoding="utf-8")
        files = [str(quick_stats_path)]
        _maybe_record_eda_artifacts(args, files)
        return {
            "type": args.type,
            "files": files,
            "content": content or "",
            "capability": capability_data,
            "requested_tables": requested_tables,
            "selected_tables": selected_tables,
            "invalid_tables": invalid_tables,
        }

    if args.type == "eda-hub":
        output_path = generator.generate_eda_hub(output_dir)
        files = [str(output_path)]
        _maybe_record_eda_artifacts(args, files)
        return {
            "type": args.type,
            "files": files,
            "capability": capability_data,
            "requested_tables": requested_tables,
            "selected_tables": selected_tables,
            "invalid_tables": invalid_tables,
        }

    if args.type == "bundle":
        profiles = _parse_csv_list(args.profiles)
        unknown_profiles = sorted(set(profiles or []) - set(_eda_profile_choices()))
        if unknown_profiles:
            return _blocked_result(
                "run-eda --profiles contains unknown profile(s): "
                + ", ".join(unknown_profiles),
                capability=capability_data,
            )
        files, hub = generator.generate_eda_bundle(
            db_path,
            output_dir,
            profiles=profiles,
            tables=selected_tables,
        )
        if not files:
            return _failed_result(
                "run-eda --type bundle did not produce any artifacts",
                capability={**capability_data, "state": "unhealthy"},
            )
        _maybe_record_eda_artifacts(args, files)
        return {
            "type": args.type,
            "files": files,
            "hub": str(hub) if hub else None,
            "profiles": profiles,
            "capability": capability_data,
            "requested_tables": requested_tables,
            "selected_tables": selected_tables,
            "invalid_tables": invalid_tables,
        }

    method_map = {
        "ydata": generator.generate_ydata_profile,
        "sweetviz": generator.generate_sweetviz_profile,
        "missingno": generator.generate_missingno_report,
        "correlation": generator.generate_correlation_report,
        "pygwalker": generator.generate_pygwalker_profile,
        "datatable": generator.generate_datatable_profile,
        "plotly-profile": generator.generate_plotly_profile,
    }
    output_path = method_map[args.type](db_path, output_dir, tables=selected_tables)
    if output_path is None:
        return _failed_result(
            f"run-eda --type {args.type} did not produce an artifact",
            capability={**capability_data, "state": "unhealthy"},
        )
    files = [str(output_path)] if output_path else []
    _maybe_record_eda_artifacts(args, files)
    return {
        "type": args.type,
        "files": files,
        "capability": capability_data,
        "requested_tables": requested_tables,
        "selected_tables": selected_tables,
        "invalid_tables": invalid_tables,
    }


def _run_eda(args: argparse.Namespace) -> int:
    return _emit_local_result(_execute_eda(args))


def _maybe_record_eda_artifacts(args: argparse.Namespace, files: list[str]) -> None:
    if not files or not getattr(args, "hypothesis_id", None):
        return
    workspace = Path(args.workspace).resolve()
    from agentsociety2.skills.analysis.harness import cli as harness_cli

    harness_cli.cmd_record_phase_artifacts(
        workspace,
        args.hypothesis_id,
        "explore",
        files,
        merge=True,
    )


def _execute_collect_assets(args: argparse.Namespace) -> dict[str, Any]:
    _ensure_analysis_dependencies()
    requested_output_dir = Path(args.output_dir)
    report_dir, assets_dir = _collect_assets_output_dirs(requested_output_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    asset_manager = AssetManager(Path(args.workspace))
    assets = asset_manager.discover_assets(args.experiment_id, args.hypothesis_id)

    if args.charts_dir:
        charts_dir = Path(args.charts_dir)
        for file_path in sorted(charts_dir.rglob("*")):
            if (
                not file_path.is_file()
                or file_path.suffix.lower() not in SUPPORTED_IMAGE_FORMATS
            ):
                continue
            relative_path = file_path.relative_to(charts_dir)
            assets.append(
                ReportAsset(
                    asset_id=asset_manager._build_asset_id("chart", relative_path),
                    asset_type="chart",
                    title=file_path.stem,
                    file_path=str(file_path),
                    description=f"Collected chart: {relative_path.as_posix()}",
                    file_size=file_path.stat().st_size,
                )
            )

    selected_names = set(_parse_csv_list(args.filter) or [])
    if selected_names:
        assets = _filter_assets_with_companions(assets, selected_names)

    include_embedded_data = bool(getattr(args, "include_embedded_data", False))
    processed = asset_manager.process_assets(
        assets,
        report_dir,
        include_embedded_data=include_embedded_data,
    )
    return {
        "assets": processed,
        "asset_count": len(processed),
        "assets_dir": str(assets_dir.resolve()),
        "embedded_data_included": include_embedded_data,
    }


def _collect_assets_output_dirs(output_dir: Path) -> tuple[Path, Path]:
    report_dir = output_dir.parent if output_dir.name == "assets" else output_dir
    return report_dir, report_dir / "assets"


def _run_collect_assets(args: argparse.Namespace) -> int:
    return _emit_local_result(_execute_collect_assets(args))


def _execute_compose_figure(args: argparse.Namespace) -> dict[str, Any]:
    spec_path = Path(args.spec).resolve()
    return _compose_figure(spec_path)


def _run_compose_figure(args: argparse.Namespace) -> int:
    return _emit_local_result(_execute_compose_figure(args))


def _load_strict_json(raw: str) -> Any:
    """按 JSON 字面量或文件路径解析命令行输入。

    :param raw: JSON 文本或文件路径。
    :returns: 解析后的 Python 对象。
    :raises ValueError: JSON 非法时抛出。
    """

    stripped = raw.lstrip()
    if stripped.startswith(("{", "[")):
        source = raw
    else:
        path = Path(raw)
        try:
            is_file = path.is_file()
        except OSError:
            is_file = False
        if not is_file:
            raise ValueError(f"JSON file not found: {raw}")
        source = path.read_text(encoding="utf-8")
    try:
        return json.loads(source)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON: {exc}") from exc


def _load_json_payload(raw: str) -> dict[str, Any]:
    value = _load_strict_json(raw)
    if not isinstance(value, dict):
        raise ValueError("payload must be a JSON object")
    return value


def _operation_preflight(args: argparse.Namespace):
    from agentsociety2.skills.analysis.harness import state as harness_state
    from agentsociety2.skills.analysis.harness.capabilities import capability_payload
    from agentsociety2.skills.analysis.harness.models import ReleaseStatus
    from agentsociety2.skills.analysis.harness.operations import get_operation_spec
    from agentsociety2.skills.analysis.harness.preflight import (
        OperationAvailability,
        evaluate_operation_availability,
    )

    operation = get_operation_spec(args.command)
    values = vars(args)
    input_errors = _operation_input_errors(operation, values)
    if input_errors:
        return OperationAvailability(
            operation_id=operation.id,
            status="INVALID_INPUT",
            reasons=input_errors,
        )
    phase = None
    current_gate_pass = False
    passed_gates: set[str] = set()
    workspace_value = values.get("workspace")
    hypothesis_id = values.get("hypothesis_id")
    if workspace_value and hypothesis_id:
        workspace = Path(workspace_value)
        state = harness_state.load_hypothesis_state(workspace, hypothesis_id)
        phase = state.current_phase.value
        passed_gates = {
            checkpoint_phase
            for checkpoint_phase, checkpoint in state.phase_checkpoints.items()
            if checkpoint.gate_pass
        }
        checkpoint = state.phase_checkpoints.get(phase)
        current_gate_pass = bool(checkpoint and checkpoint.gate_pass)
        if (
            state.hypothesis_release == ReleaseStatus.ready
            and "synthesis" in operation.phases
        ):
            phase = "synthesis"
    elif workspace_value and "synthesis" in operation.phases:
        workspace = Path(workspace_value)
        synthesis_state = harness_state.load_synthesis_state(workspace)
        scope = harness_state.resolve_synthesis_scope(workspace, synthesis_state)
        if scope and all(
            harness_state.load_hypothesis_state(
                workspace, hypothesis_id
            ).hypothesis_release
            == ReleaseStatus.ready
            for hypothesis_id in scope
        ):
            passed_gates.add("produce")
        phase = "synthesis"

    capability_states = {item["id"]: item["state"] for item in capability_payload()}
    return evaluate_operation_availability(
        operation,
        phase=phase,
        passed_gates=passed_gates,
        current_gate_pass=current_gate_pass,
        capability_states=capability_states,
        values=values,
    )


def _load_json_array(raw: str) -> list[Any]:
    value = _load_strict_json(raw)
    if not isinstance(value, list):
        raise ValueError("payload must be a JSON array")
    invalid = [item for item in value if not isinstance(item, str) or not item.strip()]
    if invalid:
        raise ValueError("JSON array items must be non-empty strings")
    return value


def _operation_input_errors(operation: Any, values: dict[str, Any]) -> tuple[str, ...]:
    """校验 dry-run 输入的可解析性，避免格式错误的输入被判为 AVAILABLE。

    :param operation: 操作规格。
    :param values: argparse 解析后的参数映射。
    :returns: 输入错误说明；为空表示输入可解析。
    """

    reasons: list[str] = []
    for input_spec in operation.inputs:
        raw = values.get(input_spec.name)
        if not isinstance(raw, str) or not raw.strip():
            continue
        try:
            if input_spec.kind == "json_object":
                _load_json_payload(raw)
            elif input_spec.kind == "json_array":
                _load_json_array(raw)
            elif input_spec.name == "spec":
                _load_compose_spec(Path(raw).resolve())
        except (OSError, ValueError) as exc:
            reasons.append(f"input {input_spec.name} is invalid: {exc}")
    return tuple(reasons)


def _handler_argument(
    parameter_name: str,
    args: argparse.Namespace,
) -> Any:
    source_name = "phase" if parameter_name == "target" else parameter_name
    if parameter_name == "include_recipes":
        return not args.skip_recipes
    if parameter_name == "include_lessons":
        return not args.skip_lessons
    value = getattr(args, source_name)
    if parameter_name == "workspace":
        return Path(value)
    if parameter_name == "payload":
        return _load_json_payload(value)
    if parameter_name == "artifacts":
        return _load_json_array(value)
    if parameter_name == "code" and value:
        path = Path(value)
        try:
            is_file = path.is_file()
        except OSError:
            is_file = False
        if is_file:
            return path.read_text(encoding="utf-8")
    return value


def _invoke_harness_from_registry(args: argparse.Namespace) -> dict[str, Any]:
    from agentsociety2.skills.analysis.harness import cli as harness_cli
    from agentsociety2.skills.analysis.harness.operations import get_operation_spec

    operation = get_operation_spec(args.command)
    handler_name = f"cmd_{operation.handler.replace('-', '_')}"
    handler = getattr(harness_cli, handler_name, None)
    if handler is None:
        raise RuntimeError(f"analysis handler is not registered: {operation.handler}")
    call_args: dict[str, Any] = {}
    for parameter in inspect.signature(handler).parameters.values():
        if parameter.kind in {
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        }:
            continue
        source_name = "phase" if parameter.name == "target" else parameter.name
        if parameter.name in {"include_recipes", "include_lessons"}:
            call_args[parameter.name] = _handler_argument(parameter.name, args)
            continue
        if not hasattr(args, source_name):
            if parameter.default is inspect.Parameter.empty:
                raise RuntimeError(
                    f"handler {handler_name} requires unmapped input: {parameter.name}"
                )
            continue
        call_args[parameter.name] = _handler_argument(parameter.name, args)
    return handler(**call_args)


def _invoke_local_mutating_from_registry(
    args: argparse.Namespace,
) -> dict[str, Any]:
    from agentsociety2.skills.analysis.harness.operations import get_operation_spec

    operation = get_operation_spec(args.command)
    handlers = {
        "eda": _execute_eda,
        "collect-assets": _execute_collect_assets,
        "compose-figure": _execute_compose_figure,
    }
    handler = handlers.get(operation.handler)
    if handler is None:
        raise RuntimeError(
            f"local mutating handler is not registered: {operation.handler}"
        )
    return handler(args)


def _emit_operation_outcome(outcome: Any) -> int:
    payload = {
        **outcome.result,
        "success": outcome.success,
        "outcome": outcome.model_dump(mode="json"),
    }
    if outcome.error is not None:
        payload["error"] = outcome.error.message
    _emit(payload)
    return outcome.exit_code


def _dispatch_operation(
    args: argparse.Namespace,
    *,
    invoke: Callable[[], dict[str, Any]],
    preflight: Any = None,
    persist_receipt: bool = False,
) -> int:
    from agentsociety2.skills.analysis.harness.execution import execute_operation
    from agentsociety2.skills.analysis.harness.operations import get_operation_spec

    operation = get_operation_spec(args.command)
    workspace_value = getattr(args, "workspace", None)
    workspace = Path(workspace_value) if workspace_value else None
    outcome = execute_operation(
        operation,
        workspace=workspace,
        values=vars(args),
        preflight=preflight,
        invoke=invoke,
        persist_receipt=persist_receipt,
    )
    return _emit_operation_outcome(outcome)


def _dispatch_harness_from_registry(
    args: argparse.Namespace,
    *,
    preflight: Any = None,
    persist_receipt: bool = False,
) -> int:
    return _dispatch_operation(
        args,
        invoke=lambda: _invoke_harness_from_registry(args),
        preflight=preflight,
        persist_receipt=persist_receipt,
    )


def _dispatch_local_mutating_from_registry(
    args: argparse.Namespace,
    *,
    preflight: Any = None,
    persist_receipt: bool = False,
) -> int:
    return _dispatch_operation(
        args,
        invoke=lambda: _invoke_local_mutating_from_registry(args),
        preflight=preflight,
        persist_receipt=persist_receipt,
    )


def _dispatch_harness(args: argparse.Namespace) -> int:
    return _dispatch_harness_from_registry(args)


def main() -> int:
    try:
        parser = _build_parser()
        args = parser.parse_args()
        from agentsociety2.skills.analysis.harness.operations import (
            get_operation_spec,
        )

        operation = get_operation_spec(args.command)
        preflight = _operation_preflight(args)
        preflight_payload = preflight.model_dump(mode="json")
        if args.dry_run:
            payload: dict[str, Any] = {
                "operation": operation.model_dump(mode="json"),
                "preflight": preflight_payload,
            }
            if preflight.available:
                from agentsociety2.skills.analysis.harness import cli as harness_cli

                handler = getattr(
                    harness_cli,
                    f"cmd_{operation.handler.replace('-', '_')}",
                    None,
                )
                if (
                    handler is not None
                    and "dry_run" in inspect.signature(handler).parameters
                ):
                    payload["execution_plan"] = _invoke_harness_from_registry(args)
            return _ok(**payload)
        read_only_local_handlers = {
            "load-context",
            "list-tables",
            "data-summary",
            "query-data",
        }
        mutating_local_handlers = {
            "eda",
            "collect-assets",
            "compose-figure",
        }
        if operation.handler in read_only_local_handlers:
            if not preflight.available:
                return _error(
                    f"operation {operation.id} is not available: {preflight.status}",
                    preflight=preflight_payload,
                )
            handler = globals()[f"_run_{operation.handler.replace('-', '_')}"]
            return handler(args)
        if operation.handler in mutating_local_handlers:
            return _dispatch_local_mutating_from_registry(
                args,
                preflight=preflight,
                persist_receipt=True,
            )
        return _dispatch_harness_from_registry(
            args,
            preflight=preflight,
            persist_receipt=True,
        )
    except _ArgumentParseError as exc:
        return _error(str(exc))
    except _ArgumentParseExit:
        return 0
    except FileNotFoundError as exc:
        return _error(str(exc))
    except sqlite3.Error as exc:
        return _error(f"sqlite error: {exc}")
    except Exception as exc:
        return _error(str(exc))


if __name__ == "__main__":
    sys.exit(main())
