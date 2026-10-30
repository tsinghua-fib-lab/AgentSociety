from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

from agentsociety2.skills.analysis import output as output_module
from agentsociety2.skills.analysis.chart_export import brand_icon_source_path
from agentsociety2.skills.analysis.harness import state as harness_state
from agentsociety2.skills.analysis.harness.cli import cmd_record_phase_artifacts
from agentsociety2.skills.analysis.harness.execution import _safe_result_summary
from agentsociety2.skills.analysis.harness.preparation import _canonical_report_html
from agentsociety2.skills.analysis.harness.report_eda_embed import (
    EDA_INTERACTIVE_BEGIN,
    EDA_INTERACTIVE_END,
    build_interactive_eda_section,
    embed_interactive_eda_in_html,
)
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
        / "v1.0.0"
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


def test_brand_icon_resolves_from_installed_workspace_skill(
    tmp_path: Path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "workspace"
    skill_asset = (
        workspace
        / ".codex"
        / "skills"
        / "agentsociety-analysis"
        / "assets"
        / "agentsociety_icon.svg"
    )
    skill_asset.parent.mkdir(parents=True)
    skill_asset.write_text("<svg></svg>", encoding="utf-8")
    launcher = workspace / ".agentsociety" / "bin" / "ags.py"
    launcher.parent.mkdir(parents=True)
    launcher.touch()
    other_cwd = tmp_path / "other"
    other_cwd.mkdir()
    monkeypatch.delenv("AGENTSOCIETY_ANALYSIS_SKILL_ROOT", raising=False)
    monkeypatch.setattr(sys, "argv", [str(launcher)])
    monkeypatch.chdir(other_cwd)

    assert brand_icon_source_path() == skill_asset.resolve()


def test_brand_icon_resolves_without_workspace(tmp_path: Path, monkeypatch) -> None:
    from importlib.resources import files
    from xml.etree import ElementTree

    monkeypatch.delenv("AGENTSOCIETY_ANALYSIS_SKILL_ROOT", raising=False)
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "standalone.py")])
    monkeypatch.chdir(tmp_path)
    packaged = files("agentsociety2.skills.analysis").joinpath(
        "assets", "agentsociety_icon.svg"
    )
    resolved = brand_icon_source_path()
    assert resolved == Path(str(packaged)).resolve()
    assert ElementTree.fromstring(resolved.read_bytes()).tag == (
        "{http://www.w3.org/2000/svg}svg"
    )


def test_empty_eda_is_an_id_free_child_fragment(tmp_path: Path) -> None:
    fragment = build_interactive_eda_section(tmp_path, lang="en")

    assert fragment.startswith('<div class="eda-interactive')
    assert 'id="data"' not in fragment
    assert "<section" not in fragment
    assert "<h2" not in fragment


def test_eda_embed_preserves_authored_data_section_and_is_idempotent() -> None:
    original = """<main>
<section id="data" class="eda-interactive"><h2>Data and methods</h2>
<p>Preserve this reconciliation narrative and its real values.</p>
<table><tr><td>1600</td><td>35.7</td></tr></table>
</section>
<h2 id="findings">Findings</h2>
</main>"""
    fragment = (
        '<div class="eda-interactive eda-interactive--empty" '
        'data-eda-interactive="empty"><p>No interactive EDA yet.</p></div>'
    )

    merged = embed_interactive_eda_in_html(original, fragment)
    merged_again = embed_interactive_eda_in_html(merged, fragment)

    assert "Preserve this reconciliation narrative" in merged
    assert "<table>" in merged
    assert merged.count('id="data"') == 1
    assert merged.count(EDA_INTERACTIVE_BEGIN) == 1
    assert merged.count(EDA_INTERACTIVE_END) == 1
    assert merged_again == merged
    assert _canonical_report_html(merged) == _canonical_report_html(original)


def test_eda_embed_upgrades_marker_wrapped_legacy_data_section() -> None:
    legacy = f"""<main>{EDA_INTERACTIVE_BEGIN}
<section class="eda-interactive" id="data"><h2>Data exploration</h2></section>
{EDA_INTERACTIVE_END}<h2 id="findings">Findings</h2></main>"""
    fragment = '<div class="eda-interactive">New child</div>'

    merged = embed_interactive_eda_in_html(legacy, fragment)

    assert merged.count('id="data"') == 1
    assert merged.count(EDA_INTERACTIVE_BEGIN) == 1
    assert "New child" in merged


def test_eda_embed_relocates_top_level_marker_into_authored_data_section() -> None:
    original = f"""<main>{EDA_INTERACTIVE_BEGIN}<div>Old EDA</div>{EDA_INTERACTIVE_END}
<section id="data"><h2>Data</h2><p>Keep this authored text.</p></section>
<h2 id="findings">Findings</h2></main>"""
    fragment = '<div class="eda-interactive">New child</div>'

    merged = embed_interactive_eda_in_html(original, fragment)
    data_start = merged.index('<section id="data">')
    data_end = merged.index("</section>", data_start)
    marker_start = merged.index(EDA_INTERACTIVE_BEGIN)

    assert data_start < marker_start < data_end
    assert merged.count('id="data"') == 1
    assert "Keep this authored text" in merged


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
