from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import ModuleType

from agentsociety2.skills.analysis import output as output_module
from agentsociety2.skills.analysis.harness import state as harness_state
from agentsociety2.skills.analysis.harness.cli import cmd_record_phase_artifacts
from agentsociety2.skills.analysis.harness.execution import _safe_result_summary
from agentsociety2.skills.analysis.harness.validators.report_quality import (
    validate_report_quality,
)
from agentsociety2.skills.analysis.models import ReportAsset
from agentsociety2.skills.analysis.output import AssetManager


def _load_extension_analysis_script() -> ModuleType:
    repo_root = Path(__file__).resolve().parents[3]
    script_path = (
        repo_root
        / "extension"
        / "skills"
        / "agentsociety-analysis"
        / "scripts"
        / "analysis.py"
    )
    spec = importlib.util.spec_from_file_location(
        "agentsociety_analysis_extension_script",
        script_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _report_markdown(*, zh: bool) -> str:
    if zh:
        return """# 报告

## 1 概览

本 报告 使用 真实 实验 数据 比较 三个 条件 并 记录 分析 限制 与 证据 来源。

## 2 数据与方法

数据 包含 三个 实验 条件 以及 真实 行数 和 指标。

| 条件 | 行数 | 均值 |
| --- | ---: | ---: |
| Control | 1600 | 28.7 |
| Counter | 1600 | 35.7 |

## 3 结论

结论 仅 适用 于 当前 仿真 与 已记录 的 分析 口径。
"""
    return """# Report

## 1 Overview

This report uses real experiment records to compare three conditions with explicit evidence sources limitations and reproducible analysis methods for review.

## 2 Data and methods

The data section preserves the observed table sizes condition labels and measured values used by the report.

| Condition | Rows | Mean |
| --- | ---: | ---: |
| Control | 1600 | 28.7 |
| Counter | 1600 | 35.7 |

## 3 Conclusion

The conclusion applies only to this simulation run and the documented measurement definitions in the analysis plan.
"""


def _valid_report_html(*, zh: bool) -> str:
    title = "数据与方法" if zh else "Data and methods"
    return f"""<!doctype html><html><body>
<section id="overview"><h2>Overview</h2><p>Evidence overview.</p></section>
<section id="data"><h2>{title}</h2>
<p>The report preserves real experiment table sizes, conditions, and measured values.</p>
<table><tr><th>Condition</th><th>Rows</th><th>Mean</th></tr>
<tr><td>Control</td><td>1600</td><td>28.7</td></tr>
<tr><td>Counter</td><td>1600</td><td>35.7</td></tr></table></section>
<section id="findings"><h2>Findings</h2><p>Scoped conclusion.</p></section>
</body></html>"""


def test_report_validator_blocks_duplicate_ids_and_lost_data_section(
    tmp_path: Path,
) -> None:
    (tmp_path / "report_zh.md").write_text(_report_markdown(zh=True), encoding="utf-8")
    (tmp_path / "report_en.md").write_text(_report_markdown(zh=False), encoding="utf-8")
    (tmp_path / "report_en.html").write_text(
        _valid_report_html(zh=False), encoding="utf-8"
    )
    (tmp_path / "report_zh.html").write_text(
        """<html><body>
<section id="data"><h2>数据与探索</h2>
<section id="data"><p>暂无交互式 EDA。请运行 run-eda --type bundle。</p></section>
</section></body></html>""",
        encoding="utf-8",
    )

    result = validate_report_quality(tmp_path)
    codes = {item.code for item in result.issues}

    assert result.status == "BLOCKED"
    assert "report_html_duplicate_ids" in codes
    assert "report_data_section_parity" in codes


def test_report_validator_accepts_preserved_static_data_sections(
    tmp_path: Path,
) -> None:
    for language, zh in (("zh", True), ("en", False)):
        (tmp_path / f"report_{language}.md").write_text(
            _report_markdown(zh=zh), encoding="utf-8"
        )
        (tmp_path / f"report_{language}.html").write_text(
            _valid_report_html(zh=zh), encoding="utf-8"
        )
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "analysis_summary.json").write_text(
        json.dumps(
            {
                "limitations": (
                    "Simulation results may not generalize beyond the tested "
                    "scenario and agent population."
                ),
                "key_findings": [
                    "Treatment agents show a higher mean value than control agents."
                ],
            }
        ),
        encoding="utf-8",
    )

    result = validate_report_quality(tmp_path)

    assert result.status == "PASS", result.model_dump(mode="json")


def test_phase_artifact_merge_is_deduplicated_and_replace_stays_explicit(
    tmp_path: Path,
) -> None:
    cmd_record_phase_artifacts(tmp_path, "1", "explore", ["first.md"])
    merged = cmd_record_phase_artifacts(
        tmp_path,
        "1",
        "explore",
        ["second.md", "first.md"],
        merge=True,
    )

    assert merged["artifacts"] == ["first.md", "second.md"]
    assert harness_state.load_hypothesis_state(tmp_path, "1").phase_artifacts[
        "explore"
    ] == ["first.md", "second.md"]

    replaced = cmd_record_phase_artifacts(tmp_path, "1", "explore", ["replacement.md"])
    assert replaced["artifacts"] == ["replacement.md"]


def test_load_context_prefers_existing_sqlite_and_collect_assets_avoids_nesting(
    tmp_path: Path,
) -> None:
    analysis_script = _load_extension_analysis_script()
    sqlite_path = tmp_path / "hypothesis_1" / "experiment_2" / "run" / "sqlite.db"
    sqlite_path.parent.mkdir(parents=True)
    sqlite_path.touch()

    paths = analysis_script._experiment_data_paths(tmp_path, "1", "2")
    report_dir, assets_dir = analysis_script._collect_assets_output_dirs(
        tmp_path / "presentation" / "hypothesis_1" / "assets"
    )

    assert paths["data_path"] == sqlite_path
    assert paths["db_path"].is_file()
    assert report_dir == tmp_path / "presentation" / "hypothesis_1"
    assert assets_dir == report_dir / "assets"


def test_asset_manager_can_omit_base64_and_receipt_keeps_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    source = tmp_path / "source.png"
    source.write_bytes(b"real-image-fixture")
    report_dir = tmp_path / "report"
    report_dir.mkdir()

    def fake_brand_icon(assets_dir: Path) -> Path:
        icon = assets_dir / "agentsociety_icon.svg"
        icon.write_text("<svg></svg>", encoding="utf-8")
        return icon

    monkeypatch.setattr(output_module, "ensure_brand_icon", fake_brand_icon)
    asset = ReportAsset(
        asset_id="chart_one",
        asset_type="chart",
        title="Chart one",
        file_path=str(source),
        description="A real chart fixture",
        file_size=source.stat().st_size,
    )

    processed = AssetManager(tmp_path).process_assets(
        [asset],
        report_dir,
        include_embedded_data=False,
    )
    summary = _safe_result_summary(
        {
            "asset_count": 1,
            "assets_dir": str(report_dir / "assets"),
            "embedded_data_included": False,
            "assets": processed,
        }
    )

    assert processed["chart_one"]["embedded_data"] is None
    assert (report_dir / "assets" / "source.png").read_bytes() == source.read_bytes()
    assert summary == {
        "asset_count": 1,
        "assets_dir": str(report_dir / "assets"),
        "embedded_data_included": False,
    }


def test_dry_run_preflight_rejects_malformed_json_inputs(tmp_path: Path) -> None:
    analysis_script = _load_extension_analysis_script()
    argparse = __import__("argparse")

    malformed_payload = analysis_script._operation_preflight(
        argparse.Namespace(
            command="record-attestation",
            workspace=str(tmp_path),
            hypothesis_id="1",
            payload="{not json",
        )
    )
    malformed_artifacts = analysis_script._operation_preflight(
        argparse.Namespace(
            command="record-phase-artifacts",
            workspace=str(tmp_path),
            hypothesis_id="1",
            phase="explore",
            artifacts='["data/explore.md", 3]',
        )
    )
    missing_spec = analysis_script._operation_preflight(
        argparse.Namespace(
            command="compose-figure",
            workspace=str(tmp_path),
            hypothesis_id="1",
            spec=str(tmp_path / "missing_spec.json"),
        )
    )

    assert malformed_payload.status == "INVALID_INPUT"
    assert "payload" in malformed_payload.reasons[0]
    assert malformed_artifacts.status == "INVALID_INPUT"
    assert "artifacts" in malformed_artifacts.reasons[0]
    assert missing_spec.status == "INVALID_INPUT"
    assert "spec" in missing_spec.reasons[0]


def _write_report_fixture(
    tmp_path: Path,
    *,
    zh_html_figure: str | None = None,
    en_html_figure: str | None = None,
    markdown_asset: str = "chart_01.png",
) -> None:
    figure_md = f"![Mean value by condition](assets/{markdown_asset})\nMean value by condition with 95% CI.\n\n"
    for language, zh in (("zh", True), ("en", False)):
        markdown = _report_markdown(zh=zh).replace("## 3", figure_md + "## 3")
        (tmp_path / f"report_{language}.md").write_text(markdown, encoding="utf-8")
    default_figure = (
        '<figure class="figure-block">\n'
        '<img src="assets/chart_01.png" alt="Mean value by condition">\n'
        "<figcaption>Mean value by condition with 95% CI.</figcaption>\n"
        "</figure>\n<p>Scoped conclusion.</p>"
    )
    for language, zh, override in (
        ("zh", True, zh_html_figure),
        ("en", False, en_html_figure),
    ):
        html = _valid_report_html(zh=zh).replace(
            "<p>Scoped conclusion.</p>", override or default_figure
        )
        (tmp_path / f"report_{language}.html").write_text(html, encoding="utf-8")
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "analysis_summary.json").write_text(
        json.dumps(
            {
                "limitations": (
                    "Simulation results may not generalize beyond the tested "
                    "scenario and agent population."
                ),
                "key_findings": [
                    "Treatment agents show a higher mean value than control agents."
                ],
            }
        ),
        encoding="utf-8",
    )


def test_report_validator_requires_captioned_figure_blocks_in_html(
    tmp_path: Path,
) -> None:
    _write_report_fixture(
        tmp_path,
        zh_html_figure='<img src="assets/chart_01.png">\n<p>Scoped conclusion.</p>',
    )

    result = validate_report_quality(tmp_path)
    codes = {item.code for item in result.issues}

    assert result.status == "BLOCKED"
    assert "html_image_alt_missing" in codes
    assert "html_figure_wrapper_missing" in codes


def test_report_validator_requires_per_language_figure_parity(
    tmp_path: Path,
) -> None:
    _write_report_fixture(
        tmp_path,
        zh_html_figure=(
            '<figure class="figure-block">\n'
            '<img src="assets/chart_99.png" alt="Other chart">\n'
            "<figcaption>Another chart.</figcaption>\n"
            "</figure>\n<p>Scoped conclusion.</p>"
        ),
    )

    result = validate_report_quality(tmp_path)
    codes = {item.code for item in result.issues}

    assert result.status == "BLOCKED"
    assert "report_figure_parity" in codes


def test_report_validator_accepts_captioned_html_figures(tmp_path: Path) -> None:
    _write_report_fixture(tmp_path)

    result = validate_report_quality(tmp_path)

    assert result.status == "PASS", result.model_dump(mode="json")


def test_chart_scaffold_reference_runs_and_writes_png(tmp_path: Path) -> None:
    script_path = (
        Path(__file__).resolve().parents[3]
        / "extension/skills/agentsociety-analysis/assets/chart_scaffold.reference.py"
    )

    completed = subprocess.run(
        [sys.executable, str(script_path)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    png = tmp_path / "charts" / "chart_01_example_trend.png"
    assert png.is_file() and png.stat().st_size > 0


def test_report_validator_accepts_dense_cjk_prose(tmp_path: Path) -> None:
    dense = (
        "本研究使用真实实验记录比较处理组与对照组并记录分析口径证据来源与限制条件"
        "确保结论可复核且仅适用于当前仿真场景"
    )
    (tmp_path / "report_zh.md").write_text(
        f"""# 报告

## 1 概览

{dense}

## 2 发现

{dense}

## 3 结论

{dense}
""",
        encoding="utf-8",
    )
    (tmp_path / "report_en.md").write_text(_report_markdown(zh=False), encoding="utf-8")
    (tmp_path / "report_zh.html").write_text(
        _valid_report_html(zh=True), encoding="utf-8"
    )
    (tmp_path / "report_en.html").write_text(
        _valid_report_html(zh=False), encoding="utf-8"
    )
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "analysis_summary.json").write_text(
        json.dumps(
            {
                "limitations": (
                    "Simulation results may not generalize beyond the tested "
                    "scenario and agent population."
                ),
                "key_findings": [
                    "Treatment agents show a higher mean value than control agents."
                ],
            }
        ),
        encoding="utf-8",
    )

    result = validate_report_quality(tmp_path)

    assert result.status == "PASS", result.model_dump(mode="json")


def test_report_validator_checks_dot_slash_figure_embeds(tmp_path: Path) -> None:
    _write_report_fixture(tmp_path)
    for language in ("zh", "en"):
        path = tmp_path / f"report_{language}.md"
        text = path.read_text(encoding="utf-8").replace(
            "(assets/chart_01.png)\nMean value by condition with 95% CI.\n",
            "(./assets/chart_01.png)\n",
        )
        path.write_text(text, encoding="utf-8")

    result = validate_report_quality(tmp_path)
    codes = {item.code for item in result.issues}

    assert result.status == "BLOCKED"
    assert "figure_caption_missing" in codes
