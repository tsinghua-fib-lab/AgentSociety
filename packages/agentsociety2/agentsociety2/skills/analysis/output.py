"""分析工具层的输出辅助模块。"""

from __future__ import annotations

import base64
import html as html_module
import mimetypes
import shutil
from dataclasses import dataclass
from hashlib import sha1
from pathlib import Path
from typing import Any

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover - optional dependency
    pd = None

from agentsociety2.logger import get_logger

from .chart_export import (
    EDA_HUB_ENTRIES,
    brand_header_html,
    eda_datatable_css,
    eda_hub_page_css,
    eda_index_page_css,
    ensure_brand_icon,
    export_plotly_html,
    html_font_links,
    html_tab_switcher_script,
)
from .models import (
    DIR_ARTIFACTS,
    DIR_EXPERIMENT_PREFIX,
    DIR_HYPOTHESIS_PREFIX,
    DIR_REPORT_ASSETS,
    DIR_RUN,
    SUPPORTED_IMAGE_FORMATS,
    ReportAsset,
)
from .utils import _sanitize_id

logger = get_logger()


@dataclass
class ReportPaths:
    """报告文件路径。"""

    markdown: Path
    html: Path
    markdown_zh: Path | None = None
    html_zh: Path | None = None
    markdown_en: Path | None = None
    html_en: Path | None = None
    assets_dir: Path | None = None


class AssetManager:
    """发现并归一化分析资产。"""

    def __init__(self, workspace_path: Path):
        self.workspace_path = Path(workspace_path)
        self.logger = logger

    def discover_assets(
        self,
        experiment_id: str,
        hypothesis_id: str,
    ) -> list[ReportAsset]:
        """发现 ``run/artifacts`` 下的图片资产。"""

        hid = _sanitize_id(hypothesis_id)
        eid = _sanitize_id(experiment_id)
        asset_path = (
            self.workspace_path
            / f"{DIR_HYPOTHESIS_PREFIX}{hid}"
            / f"{DIR_EXPERIMENT_PREFIX}{eid}"
            / DIR_RUN
            / DIR_ARTIFACTS
        )

        assets: list[ReportAsset] = []
        if not asset_path.exists():
            return assets

        for file_path in asset_path.rglob("*"):
            if file_path.suffix.lower() not in SUPPORTED_IMAGE_FORMATS:
                continue
            relative_path = file_path.relative_to(asset_path)
            assets.append(
                ReportAsset(
                    asset_id=self._build_asset_id("viz", relative_path),
                    asset_type="visualization",
                    title=self._format_title(file_path.stem),
                    file_path=str(file_path),
                    description=f"Generated visualization: {relative_path.as_posix()}",
                    file_size=file_path.stat().st_size,
                )
            )

        return assets

    def process_assets(
        self,
        assets: list[ReportAsset],
        output_dir: Path,
        *,
        include_embedded_data: bool = True,
    ) -> dict[str, Any]:
        """将资产复制到 ``assets/`` 下；可选生成 base64 内嵌数据。"""

        assets_dir = output_dir / DIR_REPORT_ASSETS
        assets_dir.mkdir(exist_ok=True)
        ensure_brand_icon(assets_dir)
        processed: dict[str, Any] = {}
        used_names: set[str] = set()

        for asset in assets:
            source_path = Path(asset.file_path)
            if not source_path.exists():
                continue

            dest_name = self._build_unique_dest_name(
                source_path, asset.asset_id, used_names
            )
            dest_path = assets_dir / dest_name
            if source_path.resolve() != dest_path.resolve():
                shutil.copy2(source_path, dest_path)

            embedded = None
            if (
                include_embedded_data
                and source_path.suffix.lower() in SUPPORTED_IMAGE_FORMATS
            ):
                with open(source_path, "rb") as file_handle:
                    encoded = base64.b64encode(file_handle.read()).decode("utf-8")
                    mime = (
                        mimetypes.guess_type(source_path.name) or ("image/png", None)
                    )[0]
                    embedded = f"data:{mime};base64,{encoded}"

            processed[asset.asset_id] = {
                "title": asset.title,
                "local_path": str(dest_path),
                "relative_path": f"{DIR_REPORT_ASSETS}/{dest_name}",
                "embedded_data": embedded,
                "description": asset.description,
            }

        return processed

    def _build_asset_id(self, prefix: str, relative_path: Path) -> str:
        normalized = relative_path.as_posix()
        digest = sha1(normalized.encode("utf-8")).hexdigest()[:10]
        return f"{prefix}_{relative_path.stem}_{digest}"

    def _build_unique_dest_name(
        self,
        source_path: Path,
        asset_id: str,
        used_names: set[str],
    ) -> str:
        candidate = source_path.name
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate

        suffix = source_path.suffix
        stem = source_path.stem
        unique_name = f"{stem}_{asset_id[-10:]}{suffix}"
        counter = 1
        while unique_name in used_names:
            unique_name = f"{stem}_{asset_id[-10:]}_{counter}{suffix}"
            counter += 1
        used_names.add(unique_name)
        return unique_name

    def _format_title(self, filename: str) -> str:
        title = filename.replace("_", " ").replace("-", " ")
        return " ".join(word.capitalize() for word in title.split())


AssetProcessor = AssetManager


class EDAGenerator:
    """生成探索性数据分析（EDA）产物。"""

    def __init__(self):
        self.logger = logger

    def resolve_table_selection(
        self,
        reader,
        tables: list[str] | None,
    ) -> tuple[list[str], list[str], list[str]]:
        """返回请求的、选中的与无效的表名。"""

        available_tables = reader.read_schema().tables
        if tables is None:
            return available_tables, available_tables, []

        requested_tables: list[str] = []
        seen = set()
        for table in tables:
            name = (table or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            requested_tables.append(name)

        available_set = set(available_tables)
        selected_tables = [
            table for table in requested_tables if table in available_set
        ]
        invalid_tables = [
            table for table in requested_tables if table not in available_set
        ]
        return requested_tables, selected_tables, invalid_tables

    def _resolve_tables(self, reader, tables: list[str] | None) -> list[str]:
        _, selected_tables, _ = self.resolve_table_selection(reader, tables)
        return selected_tables

    def generate_quick_stats(
        self,
        db_path: Path,
        max_rows: int = 5000,
        tables: list[str] | None = None,
    ) -> str | None:
        if not db_path.exists():
            return None

        from .data import DatabaseSchema, DataReader

        reader = DataReader(db_path)
        schema = reader.read_schema()
        selected_tables = self._resolve_tables(reader, tables)
        filtered_schema = DatabaseSchema(
            tables=selected_tables,
            columns={table: schema.columns.get(table, []) for table in selected_tables},
            row_counts={
                table: schema.row_counts.get(table, 0) for table in selected_tables
            },
            markdown=schema.markdown,
        )
        stats = reader.compute_stats(filtered_schema)

        return stats.quick_stats_md

    def generate_missingno_report(
        self,
        db_path: Path,
        output_dir: Path,
        max_rows: int = 50000,
        tables: list[str] | None = None,
    ) -> Path | None:
        """使用 missingno 生成缺失值报告。"""

        if not db_path.exists():
            return None

        from .data import DataReader

        reader = DataReader(db_path)
        selected_tables = self._resolve_tables(reader, tables)
        sample = reader.read_sample_data(tables=selected_tables, limit=max_rows)

        if not sample:
            return None
        if pd is None:
            self.logger.warning("pandas 未安装，跳过 missingno 报告生成")
            return None

        all_dfs = []
        for table_name, data in sample.items():
            if data and len(data) > 0:
                df = pd.DataFrame(data)
                df.columns = [f"{table_name}.{col}" for col in df.columns]
                all_dfs.append(df)

        if not all_dfs:
            return None

        combined_df = pd.concat(all_dfs, axis=1)
        if len(combined_df.columns) > 50:
            missing_counts = combined_df.isnull().sum()
            top_missing = missing_counts.nlargest(50).index.tolist()
            combined_df = combined_df[top_missing]

        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            import matplotlib.pyplot as plt
            import missingno as msno

            out_file = output_dir / "eda_missingno.html"

            _fig, axes = plt.subplots(2, 2, figsize=(16, 12))

            try:
                msno.matrix(combined_df, ax=axes[0, 0], fontsize=8)
                axes[0, 0].set_title("Missing Value Matrix", fontsize=12)
            except Exception:
                axes[0, 0].text(
                    0.5, 0.5, "Matrix plot failed", ha="center", va="center"
                )
                axes[0, 0].set_title("Missing Value Matrix (Error)")

            try:
                msno.bar(combined_df, ax=axes[0, 1], fontsize=8)
                axes[0, 1].set_title("Missing Value Bar Chart", fontsize=12)
            except Exception:
                axes[0, 1].text(0.5, 0.5, "Bar plot failed", ha="center", va="center")
                axes[0, 1].set_title("Missing Value Bar (Error)")

            try:
                if len(combined_df.columns) > 1:
                    msno.heatmap(combined_df, ax=axes[1, 0], fontsize=8)
                    axes[1, 0].set_title(
                        "Missing Value Correlation Heatmap", fontsize=12
                    )
                else:
                    axes[1, 0].text(
                        0.5, 0.5, "Need >1 columns", ha="center", va="center"
                    )
                    axes[1, 0].set_title("Correlation Heatmap (Skipped)")
            except Exception:
                axes[1, 0].text(0.5, 0.5, "Heatmap failed", ha="center", va="center")
                axes[1, 0].set_title("Correlation Heatmap (Error)")

            try:
                if len(combined_df.columns) > 1:
                    msno.dendrogram(combined_df, ax=axes[1, 1], fontsize=8)
                    axes[1, 1].set_title("Missing Value Dendrogram", fontsize=12)
                else:
                    axes[1, 1].text(
                        0.5, 0.5, "Need >1 columns", ha="center", va="center"
                    )
                    axes[1, 1].set_title("Dendrogram (Skipped)")
            except Exception:
                axes[1, 1].text(0.5, 0.5, "Dendrogram failed", ha="center", va="center")
                axes[1, 1].set_title("Dendrogram (Error)")

            plt.tight_layout()
            plt.savefig(
                str(out_file).replace(".html", ".png"), dpi=150, bbox_inches="tight"
            )
            plt.close()

            html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Missing Value Analysis (missingno)</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; }}
        h1 {{ color: #333; }}
        .summary {{ background: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0; }}
        .stats {{ margin-top: 10px; }}
        img {{ max-width: 100%; height: auto; margin: 20px 0; border: 1px solid #ddd; }}
    </style>
</head>
<body>
    <h1>Missing Value Analysis</h1>
    <div class="summary">
        <p><strong>Tool</strong>: missingno - Missing data visualization</p>
        <p><strong>Total Columns Analyzed</strong>: {len(combined_df.columns)}</p>
        <p><strong>Total Rows</strong>: {len(combined_df)}</p>
        <div class="stats">
            <p><strong>Total Missing Values</strong>: {combined_df.isnull().sum().sum()}</p>
            <p><strong>Columns with Missing</strong>: {(combined_df.isnull().sum() > 0).sum()}</p>
        </div>
    </div>
    <img src="eda_missingno.png" alt="Missing Value Visualization">
</body>
</html>"""
            out_file.write_text(html_content, encoding="utf-8")

            self.logger.info("生成 missingno 缺失值报告: %s", out_file)
            return out_file

        except ImportError:
            self.logger.warning("missingno 未安装，跳过缺失值可视化")
            return None
        except Exception as exc:
            self.logger.warning("missingno 生成失败: %s", exc)
            return None

    def generate_correlation_report(
        self,
        db_path: Path,
        output_dir: Path,
        max_rows: int = 50000,
        tables: list[str] | None = None,
    ) -> Path | None:
        """生成相关性报告。"""

        if not db_path.exists():
            return None

        from .data import DataReader

        reader = DataReader(db_path)
        selected_tables = self._resolve_tables(reader, tables)
        sample = reader.read_sample_data(tables=selected_tables, limit=max_rows)

        if not sample:
            return None
        if pd is None:
            self.logger.warning("pandas 未安装，跳过相关性报告生成")
            return None

        output_dir.mkdir(parents=True, exist_ok=True)

        generated_files = []
        for table_name, data in sample.items():
            if not data or len(data) < 2:
                continue

            df = pd.DataFrame(data)
            numeric_df = df.select_dtypes(include=["number"])

            if len(numeric_df.columns) < 2:
                continue

            try:
                import matplotlib.pyplot as plt
                import seaborn as sns

                corr_matrix = numeric_df.corr()

                _fig, ax = plt.subplots(figsize=(12, 10))
                sns.heatmap(
                    corr_matrix,
                    annot=True,
                    fmt=".2f",
                    cmap="RdBu_r",
                    center=0,
                    square=True,
                    linewidths=0.5,
                    ax=ax,
                )
                ax.set_title(f"Correlation Matrix: {table_name}", fontsize=14)

                safe_name = "".join(
                    c if c.isalnum() or c in "_-" else "_" for c in table_name
                )
                out_file = output_dir / f"correlation_{safe_name}.png"
                plt.tight_layout()
                plt.savefig(str(out_file), dpi=150, bbox_inches="tight")
                plt.close()

                generated_files.append((table_name, str(out_file)))
                self.logger.info(
                    "生成相关性矩阵: %s (表: %s, %d 列)",
                    out_file,
                    table_name,
                    len(numeric_df.columns),
                )

            except Exception as exc:
                self.logger.warning("生成表 %s 的相关性矩阵失败: %s", table_name, exc)

        if not generated_files:
            return None

        index_file = output_dir / "correlation_index.html"
        rows = "\n".join(
            f'<tr><td>{name}</td><td><img src="{Path(path).name}" style="max-width:800px"></td></tr>'
            for name, path in generated_files
        )
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Correlation Analysis</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 40px; }}
        h1 {{ color: #333; }}
        table {{ border-collapse: collapse; width: 100%; }}
        td {{ padding: 20px; border-bottom: 1px solid #ddd; }}
        img {{ max-width: 100%; }}
    </style>
</head>
<body>
    <h1>Correlation Analysis Report</h1>
    <table>
        <tr><th>Table</th><th>Correlation Matrix</th></tr>
        {rows}
    </table>
</body>
</html>"""
        index_file.write_text(html_content, encoding="utf-8")

        return index_file

    def generate_ydata_profile(
        self,
        db_path: Path,
        output_dir: Path,
        max_rows: int = 10000,
        tables: list[str] | None = None,
    ) -> Path | None:
        """生成 ydata-profiling 报告。"""

        if not db_path.exists():
            return None

        from .data import DataReader

        reader = DataReader(db_path)
        selected_tables = self._resolve_tables(reader, tables)
        sample = reader.read_sample_data(tables=selected_tables, limit=max_rows)

        if not sample:
            return None
        if pd is None:
            self.logger.warning("pandas 未安装，跳过 ydata-profiling 报告生成")
            return None

        non_empty_tables = {
            table_name: data
            for table_name, data in sample.items()
            if data and len(data) > 0
        }

        if not non_empty_tables:
            return None

        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            from ydata_profiling import ProfileReport

            if len(non_empty_tables) == 1:
                table_name = next(iter(non_empty_tables.keys()))
                df = pd.DataFrame(non_empty_tables[table_name])
                out_file = output_dir / "eda_profile.html"
                profile = ProfileReport(df, title=f"EDA: {table_name}", minimal=True)
                profile.to_file(str(out_file))
                self.logger.info(
                    "生成 ydata-profiling 报告: %s (表: %s, %d 行)",
                    out_file,
                    table_name,
                    len(df),
                )
                return out_file

            generated_files = []
            for table_name, data in non_empty_tables.items():
                df = pd.DataFrame(data)
                if df.empty:
                    continue
                safe_name = "".join(
                    c if c.isalnum() or c in "_-" else "_" for c in table_name
                )
                table_file = output_dir / f"eda_profile_{safe_name}.html"
                try:
                    profile = ProfileReport(
                        df, title=f"EDA: {table_name}", minimal=True
                    )
                    profile.to_file(str(table_file))
                    generated_files.append((table_name, table_file.name, len(df)))
                    self.logger.info(
                        "生成 ydata-profiling 表报告: %s (表: %s, %d 行)",
                        table_file,
                        table_name,
                        len(df),
                    )
                except Exception as exc:
                    self.logger.warning(
                        "生成表 %s 的 EDA 报告失败: %s", table_name, exc
                    )

            if not generated_files:
                return None

            index_file = output_dir / "eda_profile.html"
            index_content = self._build_eda_index_html(
                generated_files, "ydata-profiling"
            )
            index_file.write_text(index_content, encoding="utf-8")
            self.logger.info(
                "生成 EDA 索引页: %s (%d 张表)", index_file, len(generated_files)
            )
            return index_file

        except Exception as exc:
            self.logger.debug("ydata-profiling 生成失败: %s", exc)
            return None

    def _build_eda_index_html(
        self,
        table_files: list[tuple[str, str, int]],
        tool_name: str,
    ) -> str:
        rows = "\n".join(
            f'<tr><td><a href="{filename}">{name}</a></td><td class="num">{row_count}</td></tr>'
            for name, filename, row_count in table_files
        )
        subtitle = f"{tool_name} · 选择表打开完整画像"
        header = brand_header_html(
            "交互式 EDA 索引",
            subtitle,
            variant="hub",
            lang="zh",
        )
        return f"""<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>EDA Index ({tool_name})</title>
    {html_font_links()}
    <style>{eda_index_page_css()}</style>
</head>
<body>
    <div class="index-shell">
        {header}
        <div class="index-body">
            <p class="panel-intro">分析报告可通过 <code>iframe</code> 嵌入下方各表画像。</p>
            <table>
                <tr><th>表</th><th class="num">行数</th></tr>
{rows}
            </table>
        </div>
    </div>
</body>
</html>"""

    def generate_sweetviz_profile(
        self,
        db_path: Path,
        output_dir: Path,
        max_rows: int = 10000,
        tables: list[str] | None = None,
    ) -> Path | None:
        """生成 Sweetviz 报告。"""

        if not db_path.exists():
            return None

        from .data import DataReader

        reader = DataReader(db_path)
        selected_tables = self._resolve_tables(reader, tables)
        sample = reader.read_sample_data(tables=selected_tables, limit=max_rows)

        if not sample:
            return None
        if pd is None:
            self.logger.warning("pandas 未安装，跳过 Sweetviz 报告生成")
            return None

        non_empty_tables = {
            table_name: data
            for table_name, data in sample.items()
            if data and len(data) > 0
        }

        if not non_empty_tables:
            return None

        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            import sweetviz as sv

            if len(non_empty_tables) == 1:
                table_name = next(iter(non_empty_tables.keys()))
                df = pd.DataFrame(non_empty_tables[table_name])
                out_file = output_dir / "eda_sweetviz.html"
                report = sv.analyze(df)
                report.show_html(str(out_file), open_browser=False)
                if out_file.exists():
                    self.logger.info(
                        "生成 Sweetviz 报告: %s (表: %s, %d 行)",
                        out_file,
                        table_name,
                        len(df),
                    )
                    return out_file
                return None

            generated_files = []
            for table_name, data in non_empty_tables.items():
                df = pd.DataFrame(data)
                if df.empty:
                    continue
                safe_name = "".join(
                    c if c.isalnum() or c in "_-" else "_" for c in table_name
                )
                table_file = output_dir / f"eda_sweetviz_{safe_name}.html"
                try:
                    report = sv.analyze(df)
                    report.show_html(str(table_file), open_browser=False)
                    if table_file.exists():
                        generated_files.append((table_name, table_file.name, len(df)))
                        self.logger.info(
                            "生成 Sweetviz 表报告: %s (表: %s, %d 行)",
                            table_file,
                            table_name,
                            len(df),
                        )
                except Exception as exc:
                    self.logger.warning(
                        "生成表 %s 的 Sweetviz 报告失败: %s", table_name, exc
                    )

            if not generated_files:
                return None

            index_file = output_dir / "eda_sweetviz.html"
            index_content = self._build_eda_index_html(generated_files, "Sweetviz")
            index_file.write_text(index_content, encoding="utf-8")
            self.logger.info(
                "生成 Sweetviz EDA 索引页: %s (%d 张表)",
                index_file,
                len(generated_files),
            )
            return index_file

        except Exception as exc:
            self.logger.debug("Sweetviz 生成失败: %s", exc)
            return None

    def _read_non_empty_tables(
        self,
        db_path: Path,
        output_dir: Path,
        max_rows: int,
        tables: list[str] | None,
    ) -> dict[str, pd.DataFrame]:
        if pd is None or not db_path.exists():
            return {}

        from .data import DataReader

        reader = DataReader(db_path)
        selected_tables = self._resolve_tables(reader, tables)
        sample = reader.read_sample_data(tables=selected_tables, limit=max_rows)
        frames: dict[str, pd.DataFrame] = {}
        for table_name, data in (sample or {}).items():
            if not data:
                continue
            df = pd.DataFrame(data)
            if not df.empty:
                frames[table_name] = df
        return frames

    def generate_pygwalker_profile(
        self,
        db_path: Path,
        output_dir: Path,
        max_rows: int = 10000,
        tables: list[str] | None = None,
    ) -> Path | None:
        frames = self._read_non_empty_tables(db_path, output_dir, max_rows, tables)
        if not frames:
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            import pygwalker as pyg
        except ImportError:
            self.logger.warning("pygwalker 未安装，跳过拖拽探索报告")
            return None

        generated: list[tuple[str, str, int]] = []
        for table_name, df in frames.items():
            safe_name = "".join(
                c if c.isalnum() or c in "_-" else "_" for c in table_name
            )
            out_file = output_dir / f"eda_pygwalker_{safe_name}.html"
            html = pyg.to_html(df, embed_lib=True)
            out_file.write_text(html, encoding="utf-8")
            generated.append((table_name, out_file.name, len(df)))
            self.logger.info("生成 PyGWalker 报告: %s", out_file)

        if not generated:
            return None
        if len(generated) == 1:
            single = output_dir / generated[0][1]
            hub = output_dir / "eda_pygwalker.html"
            if hub != single:
                hub.write_text(single.read_text(encoding="utf-8"), encoding="utf-8")
            return hub
        index_file = output_dir / "eda_pygwalker.html"
        index_file.write_text(
            self._build_eda_index_html(generated, "PyGWalker"), encoding="utf-8"
        )
        return index_file

    def generate_datatable_profile(
        self,
        db_path: Path,
        output_dir: Path,
        max_rows: int = 5000,
        tables: list[str] | None = None,
    ) -> Path | None:
        frames = self._read_non_empty_tables(db_path, output_dir, max_rows, tables)
        if not frames:
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        generated: list[tuple[str, str, int]] = []
        for table_name, df in frames.items():
            safe_name = "".join(
                c if c.isalnum() or c in "_-" else "_" for c in table_name
            )
            out_file = output_dir / f"eda_datatable_{safe_name}.html"
            out_file.write_text(
                self._build_sortable_datatable_html(table_name, df),
                encoding="utf-8",
            )
            generated.append((table_name, out_file.name, len(df)))
            self.logger.info("生成可排序数据表: %s", out_file)

        index_file = output_dir / "eda_datatable.html"
        if len(generated) == 1:
            index_file.write_text(
                (output_dir / generated[0][1]).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        else:
            index_file.write_text(
                self._build_eda_index_html(generated, "Interactive tables"),
                encoding="utf-8",
            )
        return index_file

    def _build_sortable_datatable_html(self, table_name: str, df: pd.DataFrame) -> str:
        preview = df.head(500)
        esc = html_module.escape
        headers = "".join(f"<th>{esc(str(col))}</th>" for col in preview.columns)
        rows = []
        for _, row in preview.iterrows():
            cells = "".join(f"<td>{esc(str(row[col]))}</td>" for col in preview.columns)
            rows.append(f"<tr>{cells}</tr>")
        body = "\n".join(rows)
        truncated = len(df) > len(preview)
        note = (
            f"显示前 {len(preview)} / {len(df)} 行（完整数据见 sqlite）"
            if truncated
            else f"共 {len(df)} 行"
        )
        return f"""<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Table: {esc(table_name)}</title>
  {html_font_links()}
  <style>{eda_datatable_css()}</style>
</head>
<body>
  <div class="standalone-wrap">
  {brand_header_html(esc(table_name), esc(note), variant="standalone", lang="zh")}
  <div class="standalone-body">
  <p class="meta">{note}</p>
  <div class="toolbar">
    <input type="search" id="filter" placeholder="筛选任意列…" />
  </div>
  <div class="wrap">
    <table id="tbl">
      <thead><tr>{headers}</tr></thead>
      <tbody id="tbody">{body}</tbody>
    </table>
  </div>
  <script>
    (function () {{
      var tbl = document.getElementById("tbl");
      var filter = document.getElementById("filter");
      var tbody = document.getElementById("tbody");
      var rows = Array.prototype.slice.call(tbody.querySelectorAll("tr"));
      filter.addEventListener("input", function () {{
        var q = filter.value.toLowerCase();
        rows.forEach(function (tr) {{
          tr.style.display = tr.textContent.toLowerCase().indexOf(q) >= 0 ? "" : "none";
        }});
      }});
      tbl.querySelectorAll("th").forEach(function (th, idx) {{
        th.addEventListener("click", function () {{
          var asc = th.dataset.asc !== "1";
          tbl.querySelectorAll("th").forEach(function (h) {{ delete h.dataset.asc; }});
          th.dataset.asc = asc ? "1" : "0";
          rows.sort(function (a, b) {{
            var av = (a.children[idx] && a.children[idx].textContent) || "";
            var bv = (b.children[idx] && b.children[idx].textContent) || "";
            var an = parseFloat(av), bn = parseFloat(bv);
            if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
            return asc ? av.localeCompare(bv) : bv.localeCompare(av);
          }});
          rows.forEach(function (tr) {{ tbody.appendChild(tr); }});
        }});
      }});
    }})();
  </script>
  </div></div>
</body>
</html>"""

    def generate_plotly_profile(
        self,
        db_path: Path,
        output_dir: Path,
        max_rows: int = 8000,
        tables: list[str] | None = None,
    ) -> Path | None:
        frames = self._read_non_empty_tables(db_path, output_dir, max_rows, tables)
        if not frames:
            return None

        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            import plotly.express as px
        except ImportError:
            self.logger.warning("plotly 未安装，跳过 Plotly 概览")
            return None

        generated: list[tuple[str, str, int]] = []
        for table_name, df in frames.items():
            numeric = df.select_dtypes(include=["number"])
            if numeric.shape[1] < 1:
                continue
            cols = list(numeric.columns[:8])
            safe_name = "".join(
                c if c.isalnum() or c in "_-" else "_" for c in table_name
            )
            out_file = output_dir / f"eda_plotly_{safe_name}.html"
            if len(cols) >= 2:
                fig = px.scatter_matrix(
                    numeric[cols],
                    dimensions=cols,
                    title=f"Numeric overview: {table_name}",
                )
            else:
                fig = px.histogram(
                    numeric,
                    x=cols[0],
                    title=f"Distribution: {table_name}.{cols[0]}",
                )
            export_plotly_html(fig, out_file)
            generated.append((table_name, out_file.name, len(df)))
            self.logger.info("生成 Plotly 概览: %s", out_file)

        if not generated:
            return None
        index_file = output_dir / "eda_plotly.html"
        index_file.write_text(
            self._build_eda_index_html(generated, "Plotly"), encoding="utf-8"
        )
        return index_file

    def generate_eda_hub(
        self,
        output_dir: Path,
        *,
        title: str = "AgentSociety EDA Hub",
    ) -> Path:
        output_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = output_dir.parent / "assets"
        ensure_brand_icon(assets_dir)
        entries = []
        for spec in EDA_HUB_ENTRIES:
            path = output_dir / spec["file"]
            if path.is_file():
                entries.append(spec)

        hub_path = output_dir / "eda_hub.html"
        hub_path.write_text(
            self._build_eda_hub_html(entries, title=title, lang="zh"),
            encoding="utf-8",
        )
        self.logger.info("生成 EDA Hub: %s (%d 入口)", hub_path, len(entries))
        return hub_path

    def _build_eda_hub_html(
        self,
        entries: list[dict[str, str]],
        *,
        title: str,
        lang: str = "zh",
    ) -> str:
        zh = lang.startswith("zh")
        subtitle = (
            "多模式交互式数据探索 · 嵌入报告请使用 data/eda_hub.html"
            if zh
            else "Multi-mode interactive EDA · embed via data/eda_hub.html"
        )
        header = brand_header_html(title, subtitle, variant="hub", lang=lang)

        if not entries:
            body = '<p class="hub-empty">暂无 EDA 产物。请先运行 <code>run-eda --type bundle</code>。</p>'
        else:
            tab_buttons: list[str] = []
            tab_panels: list[str] = []
            for idx, spec in enumerate(entries):
                active = " active" if idx == 0 else ""
                tab_id = spec["key"]
                label = spec["zh"] if zh else spec["en"]
                desc = spec["desc_zh"] if zh else spec["desc_en"]
                icon = spec["icon"]
                tab_buttons.append(
                    f'<button type="button" class="tab{active}" data-tab="{tab_id}" '
                    f'role="tab" aria-selected="{"true" if idx == 0 else "false"}">'
                    f'<span class="tab-icon" aria-hidden="true">{icon}</span>'
                    f"<span>{label}</span></button>"
                )
                if spec["mode"] == "markdown":
                    md_path = spec["file"]
                    body_inner = (
                        f'<p class="panel-intro"><strong>{label}</strong> — {desc}</p>'
                        f'<p class="iframe-hint">'
                        f'<a href="{md_path}" target="_blank" rel="noopener">'
                        f"{'打开 Markdown' if zh else 'Open Markdown'}</a></p>"
                    )
                else:
                    open_lbl = "新标签页打开" if zh else "Open in new tab"
                    body_inner = (
                        f'<p class="panel-intro"><strong>{label}</strong> — {desc}</p>'
                        f'<p class="iframe-hint"><a href="{spec["file"]}" target="_blank" rel="noopener">{open_lbl}</a></p>'
                        f'<iframe class="eda-frame" src="{spec["file"]}" title="{label}" loading="lazy"></iframe>'
                    )
                tab_panels.append(
                    f'<div class="tab-panel{active} {spec["panel"]}" data-panel="{tab_id}" role="tabpanel">'
                    f"{body_inner}</div>"
                )
            tabs_html = (
                f'<div class="tab-root"><div class="tab-bar" role="tablist">{"".join(tab_buttons)}</div>'
                f"{''.join(tab_panels)}</div>"
            )
            body = tabs_html

        return f"""<!DOCTYPE html>
<html lang="{"zh" if zh else "en"}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  {html_font_links()}
  <style>{eda_hub_page_css()}</style>
</head>
<body>
  <div class="hub-shell">
    {header}
    <div class="hub-body">{body}</div>
  </div>
  {html_tab_switcher_script()}
</body>
</html>"""

    def generate_eda_bundle(
        self,
        db_path: Path,
        output_dir: Path,
        profiles: list[str] | None = None,
        tables: list[str] | None = None,
        max_rows: int = 10000,
    ) -> tuple[list[str], Path | None]:
        default_profiles = [
            "quick-stats",
            "ydata",
            "pygwalker",
            "datatable",
            "plotly-profile",
        ]
        active = profiles or default_profiles
        output_dir.mkdir(parents=True, exist_ok=True)
        ensure_brand_icon(output_dir.parent / "assets")
        files: list[str] = []

        runners = {
            "quick-stats": lambda: self._bundle_quick_stats(
                db_path, output_dir, tables
            ),
            "ydata": lambda: self.generate_ydata_profile(
                db_path, output_dir, max_rows=max_rows, tables=tables
            ),
            "sweetviz": lambda: self.generate_sweetviz_profile(
                db_path, output_dir, max_rows=max_rows, tables=tables
            ),
            "missingno": lambda: self.generate_missingno_report(
                db_path, output_dir, tables=tables
            ),
            "correlation": lambda: self.generate_correlation_report(
                db_path, output_dir, tables=tables
            ),
            "pygwalker": lambda: self.generate_pygwalker_profile(
                db_path, output_dir, max_rows=max_rows, tables=tables
            ),
            "datatable": lambda: self.generate_datatable_profile(
                db_path, output_dir, max_rows=max_rows, tables=tables
            ),
            "plotly-profile": lambda: self.generate_plotly_profile(
                db_path, output_dir, max_rows=max_rows, tables=tables
            ),
        }

        for name in active:
            if name in ("eda-hub", "bundle"):
                continue
            runner = runners.get(name)
            if not runner:
                continue
            result = runner()
            if name == "quick-stats":
                qs = output_dir / "eda_quick_stats.md"
                if qs.exists():
                    files.append(str(qs))
            elif result is not None:
                files.append(str(result))

        hub = self.generate_eda_hub(output_dir)
        files.append(str(hub))
        return files, hub

    def _bundle_quick_stats(
        self,
        db_path: Path,
        output_dir: Path,
        tables: list[str] | None,
    ) -> str | None:
        content = self.generate_quick_stats(db_path, tables=tables)
        if content is None:
            return None
        path = output_dir / "eda_quick_stats.md"
        path.write_text(content, encoding="utf-8")
        return content
