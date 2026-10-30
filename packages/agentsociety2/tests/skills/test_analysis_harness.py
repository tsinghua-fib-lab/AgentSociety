"""Tests for the analysis harness validators and state."""

import json
import os
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from agentsociety2.skills.analysis.harness import capabilities as harness_capabilities
from agentsociety2.skills.analysis.harness import cli as harness_cli
from agentsociety2.skills.analysis.harness import json_io as harness_json_io
from agentsociety2.skills.analysis.harness import state as harness_state
from agentsociety2.skills.analysis.harness.capabilities import (
    analysis_capability_statuses,
)
from agentsociety2.skills.analysis.harness.execution import (
    OperationRunReceipt,
    execute_operation,
    list_run_receipts,
    operation_execution_key,
    operation_lock,
    save_run_receipt,
    unresolved_retryable_runs,
)
from agentsociety2.skills.analysis.harness.guidance import get_harness_guidance
from agentsociety2.skills.analysis.harness.json_io import load_model_from_text
from agentsociety2.skills.analysis.harness.models import (
    AnalysisPlan,
    Claim,
    ClaimMode,
    ClaimsDocument,
    FigureContract,
    HypothesisAnalysisState,
    ReflectionReport,
)
from agentsociety2.skills.analysis.harness.operations import operation_registry
from agentsociety2.skills.analysis.harness.paths import analysis_operation_lock_path
from agentsociety2.skills.analysis.harness.preflight import (
    evaluate_operation_availability,
)
from agentsociety2.skills.analysis.harness.report_assets import (
    sync_report_assets_from_reports,
)
from agentsociety2.skills.analysis.harness.review import (
    REPORT_DIMENSION_KEYS,
    report_content_fingerprint,
    save_report_review,
)
from agentsociety2.skills.analysis.harness.schemas import (
    ReportOutline,
    ReportQualityReview,
    ReviewVerdict,
)
from agentsociety2.skills.analysis.harness.validators import (
    validate_chart_script,
    validate_claims,
    validate_explore,
    validate_plan,
    validate_refine,
    validate_release,
    validate_report_quality,
    validate_synthesis,
)


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "workspace"
    ws.mkdir()
    db_path = ws / "hypothesis_1" / "experiment_1" / "run" / "sqlite.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE metrics (step INTEGER, value REAL)")
    conn.executemany("INSERT INTO metrics VALUES (?, ?)", [(1, 1.0), (2, 2.0)])
    conn.commit()
    conn.close()

    data_dir = ws / "presentation" / "hypothesis_1" / "data"
    data_dir.mkdir(parents=True)
    (data_dir / "eda_quick_stats.md").write_text("# quick stats\n", encoding="utf-8")
    return ws


def test_validate_plan_blocks_empty(workspace: Path) -> None:
    result = validate_plan(AnalysisPlan())
    assert result.status == "BLOCKED"
    assert any(i.code == "missing_research_question" for i in result.issues)


def _minimal_report_html(lang: str = "zh") -> str:
    title = "Overview" if lang == "en" else "概述"
    return (
        f'<!DOCTYPE html><html lang="{lang}"><head><meta charset="utf-8"/></head>'
        f"<body><h1>{title}</h1><h2>Data</h2><h2>Findings</h2>"
        f'<img src="assets/chart_01_test.png" alt="c"/>'
        f"<h2>Conclusion</h2></body></html>"
    )


def test_validate_plan_passes_minimal(workspace: Path) -> None:
    plan = AnalysisPlan(
        research_question="Does treatment increase metric?",
        primary_metrics=["value"],
        target_tables=["metrics"],
        confirmatory_claims=["Treatment raises mean value"],
    )
    result = validate_plan(plan)
    assert result.status == "PASS"


def test_validate_explore_requires_eda_artifact(workspace: Path) -> None:
    plan = AnalysisPlan(
        research_question="q",
        primary_metrics=["value"],
        target_tables=["metrics"],
        confirmatory_claims=["c"],
        eda_profile="quick-stats",
    )
    db = workspace / "hypothesis_1" / "experiment_1" / "run" / "sqlite.db"
    result = validate_explore(workspace, "1", db_path=db, plan=plan)
    assert result.status == "PASS"


def test_validate_explore_missing_eda(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    db_path = ws / "hypothesis_1" / "experiment_1" / "run" / "sqlite.db"
    db_path.parent.mkdir(parents=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE metrics (value REAL)")
    conn.execute("INSERT INTO metrics VALUES (1.0)")
    conn.commit()
    conn.close()
    data_dir = ws / "presentation" / "hypothesis_1" / "data"
    data_dir.mkdir(parents=True)
    plan = AnalysisPlan(
        research_question="q",
        primary_metrics=["value"],
        target_tables=["metrics"],
        confirmatory_claims=["c"],
        eda_profile="ydata",
    )
    result = validate_explore(
        ws, "1", db_path=db_path, plan=plan, data_dir=data_dir, recorded_artifacts=[]
    )
    assert result.status == "BLOCKED"
    assert any(i.code == "explore_output_empty" for i in result.issues)


def test_validate_explore_missing_output_dir_blocks(workspace: Path) -> None:
    plan = AnalysisPlan(
        research_question="q",
        primary_metrics=["value"],
        target_tables=["metrics"],
        confirmatory_claims=["c"],
    )
    db = workspace / "hypothesis_1" / "experiment_1" / "run" / "sqlite.db"
    result = validate_explore(
        workspace,
        "1",
        db_path=db,
        plan=plan,
        data_dir=workspace / "presentation" / "hypothesis_1" / "missing_data",
    )
    assert result.status == "BLOCKED"
    assert any(i.code == "explore_output_dir_missing" for i in result.issues)


def test_validate_claims_requires_approved_confirmatory() -> None:
    doc = ClaimsDocument(
        hypothesis_id="1",
        claims=[
            Claim(
                claim_id="c1",
                statement="Treatment increases value",
                mode=ClaimMode.confirmatory,
                evidence="metrics table mean comparison",
                approved=False,
            )
        ],
    )
    result = validate_claims(doc)
    assert result.status == "BLOCKED"
    assert any(i.code == "no_approved_confirmatory_claim" for i in result.issues)


def test_validate_refine_requires_contracts_and_validated_charts(
    workspace: Path,
) -> None:
    st = HypothesisAnalysisState(hypothesis_id="1", chart_count=1)
    result = validate_refine(st, workspace, "1")
    assert result.status == "BLOCKED"
    assert any(i.code == "refine_no_contracts" for i in result.issues)

    st = HypothesisAnalysisState(
        hypothesis_id="1",
        figure_contracts=[
            FigureContract(
                contract_id="f1",
                claim_id="c1",
                core_finding="Treatment increases value",
                output_files=["chart_01_value.png"],
            )
        ],
        chart_count=0,
    )
    result = validate_refine(st, workspace, "1")
    assert result.status == "BLOCKED"
    assert any(i.code == "refine_no_validated_charts" for i in result.issues)


def test_validate_chart_deduplicates_chart_count(workspace: Path) -> None:
    harness_cli.cmd_intake(workspace, "1", "1")
    chart = (
        workspace / "presentation" / "hypothesis_1" / "charts" / "chart_01_value.png"
    )
    chart.parent.mkdir(parents=True, exist_ok=True)
    chart.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 200)

    first = harness_cli.cmd_validate_chart(workspace, "1", chart_path=str(chart))
    second = harness_cli.cmd_validate_chart(workspace, "1", chart_path=str(chart))

    assert first["chart_count"] == 1
    assert second["chart_count"] == 1
    st = harness_state.load_hypothesis_state(workspace, "1")
    assert st.phase_artifacts["refine_validated_charts"] == [str(chart.resolve())]


def test_intake_and_write_plan(workspace: Path) -> None:
    out = harness_cli.cmd_intake(workspace, "1", "1")
    assert out["db_ready"] is True
    harness_cli.cmd_write_plan(
        workspace,
        "1",
        {
            "research_question": "Test question",
            "primary_metrics": ["value"],
            "target_tables": ["metrics"],
            "confirmatory_claims": ["Hypothesis holds"],
            "eda_profile": "quick-stats",
        },
    )
    from agentsociety2.skills.analysis.harness.models import (
        AttestationStatus,
    )

    harness_cli.cmd_record_attestation(
        workspace,
        "1",
        {
            "phase": "frame",
            "status": AttestationStatus.DONE.value,
            "key_findings": ["Plan locked"],
            "rubric": {
                "research_question_confirmed": True,
                "success_criteria": "Compare mean value across steps",
            },
        },
    )
    result = harness_cli.cmd_validate_plan(workspace, "1")
    assert result["status"] == "PASS"
    assert result["attestation_pass"] is True


def test_gate_status_only_shows_next_phase_after_current_gate_pass(
    workspace: Path,
) -> None:
    from agentsociety2.skills.analysis.harness.models import AttestationStatus

    harness_cli.cmd_intake(workspace, "1", "1")
    status = harness_cli.cmd_gate_status(workspace, "1")["hypothesis"]
    assert status["current_phase"] == "frame"
    assert status["next_phase"] is None
    assert "structural" in status["blocked_by"]

    harness_cli.cmd_write_plan(
        workspace,
        "1",
        {
            "research_question": "Does treatment increase value?",
            "primary_metrics": ["value"],
            "target_tables": ["metrics"],
            "confirmatory_claims": ["Treatment increases value"],
        },
    )
    harness_cli.cmd_record_attestation(
        workspace,
        "1",
        {
            "phase": "frame",
            "status": AttestationStatus.DONE.value,
            "key_findings": ["Plan approved"],
            "rubric": {
                "research_question_confirmed": True,
                "success_criteria": "Compare value",
            },
        },
    )
    harness_cli.cmd_validate_plan(workspace, "1")

    status = harness_cli.cmd_gate_status(workspace, "1")["hypothesis"]
    assert status["current_gate_pass"] is True
    assert status["blocked_by"] == []
    assert status["next_phase"] == "explore"


def test_phase_attestation_becomes_stale_after_artifact_change(workspace: Path) -> None:
    from agentsociety2.skills.analysis.harness.models import AttestationStatus

    harness_cli.cmd_intake(workspace, "1", "1")
    harness_cli.cmd_write_plan(
        workspace,
        "1",
        {
            "research_question": "Test question",
            "primary_metrics": ["value"],
            "target_tables": ["metrics"],
            "confirmatory_claims": ["Hypothesis holds"],
        },
    )
    harness_cli.cmd_record_attestation(
        workspace,
        "1",
        {
            "phase": "frame",
            "status": AttestationStatus.DONE.value,
            "key_findings": ["Plan approved"],
            "rubric": {
                "research_question_confirmed": True,
                "success_criteria": "Compare metrics",
            },
        },
    )
    assert harness_cli.cmd_validate_plan(workspace, "1")["status"] == "PASS"

    harness_cli.cmd_write_plan(
        workspace,
        "1",
        {"research_question": "Changed question after attestation"},
    )
    result = harness_cli.cmd_validate_plan(workspace, "1")
    assert result["status"] == "BLOCKED"
    assert any(i.get("code") == "attestation_stale" for i in result["issues"])


def test_draft_reflection_creates_reviewable_learning_report(
    workspace: Path,
) -> None:
    harness_cli.cmd_intake(workspace, "1", "1")
    harness_cli.cmd_write_plan(
        workspace,
        "1",
        {
            "research_question": "Does treatment increase value?",
            "primary_metrics": ["value"],
            "target_tables": ["metrics"],
            "confirmatory_claims": ["Treatment increases value"],
        },
    )
    harness_cli.cmd_record_claim(
        workspace,
        "1",
        {
            "claim_id": "c1",
            "statement": "Treatment increases value",
            "mode": "confirmatory",
            "approved": True,
        },
    )

    result = harness_cli.cmd_draft_reflection(workspace, "1", "1")

    assert Path(result["reflection_path"]).exists()
    reflection = ReflectionReport.model_validate(result["reflection"])
    assert reflection.hypothesis_id == "1"
    assert reflection.reusable_methods
    assert any(item.item_id == "approved_claims" for item in reflection.what_worked)


def test_promote_reflection_writes_lessons_recipes_and_confirmed_preferences(
    workspace: Path,
) -> None:
    harness_cli.cmd_record_reflection(
        workspace,
        "1",
        {
            "hypothesis_id": "1",
            "experiment_id": "1",
            "what_worked": [
                {
                    "title": "Conservative claims worked",
                    "content": "User preferred cautious confirmatory claims.",
                    "evidence": ["claims.json"],
                    "confidence": "high",
                }
            ],
            "reusable_methods": [
                {
                    "recipe_id": "cautious_claims",
                    "title": "Cautious claim protocol",
                    "content": "Keep claim strength aligned with evidence.",
                    "recommended_steps": ["Ask for user alignment", "Approve claims"],
                    "pitfalls": ["Do not overclaim"],
                    "confidence": "high",
                }
            ],
            "user_preferences_observed": [
                {
                    "item_id": "claim_style",
                    "title": "Claim style",
                    "content": "Use conservative wording.",
                    "category": "writing",
                    "value": "conservative claims",
                    "evidence": ["user-confirmed"],
                    "confidence": "high",
                }
            ],
        },
    )

    promoted = harness_cli.cmd_promote_reflection(workspace, "1")
    assert promoted["status"] == "PROMOTED"
    assert promoted["preference_keys"] == []

    skipped = harness_cli.cmd_promote_reflection(workspace, "1")
    assert skipped["status"] == "SKIPPED"
    assert skipped["reason"] == "reflection_already_promoted"

    harness_cli.cmd_record_feedback(
        workspace,
        "1",
        {
            "hypothesis_id": "1",
            "experiment_id": "1",
            "rating": 5,
            "satisfied": True,
            "comments": "请长期保持保守表述。",
            "preference_candidates": [
                {
                    "item_id": "claim_style",
                    "title": "Claim style",
                    "category": "writing",
                    "value": "conservative claims",
                    "content": "User confirmed conservative claim wording.",
                    "evidence": ["feedback:user-confirmed"],
                    "confidence": "high",
                }
            ],
        },
    )

    promoted_prefs = harness_cli.cmd_promote_reflection(
        workspace, "1", include_preferences=True
    )
    assert promoted_prefs["status"] == "PROMOTED"
    assert promoted_prefs["already_promoted"] is True

    memory_dir = Path(promoted_prefs["memory_dir"])
    assert (memory_dir / "project_lessons.jsonl").exists()
    assert (memory_dir / "method_recipes" / "cautious_claims.md").exists()
    assert promoted_prefs["preference_keys"] == ["claim_style"]
    index = harness_state.load_memory_index(workspace)
    assert index.preferences["claim_style"].value == "conservative claims"


def test_validate_release_pass(workspace: Path) -> None:
    pres = workspace / "presentation" / "hypothesis_1"
    pres.mkdir(parents=True, exist_ok=True)
    assets = pres / "assets"
    assets.mkdir()
    (assets / "chart_01_test.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 200)
    (pres / "report_zh.md").write_text(
        "## 概述\n\n## 数据\n\n## 发现\n\n![c](assets/chart_01_test.png)\none line\n\n## 结论\n",
        encoding="utf-8",
    )
    (pres / "report_en.md").write_text(
        "## Overview\n\n## Data\n\n## Findings\n\n![c](assets/chart_01_test.png)\ncaption\n\n## Conclusion\n",
        encoding="utf-8",
    )
    (pres / "report_zh.html").write_text(_minimal_report_html("zh"), encoding="utf-8")
    (pres / "report_en.html").write_text(_minimal_report_html("en"), encoding="utf-8")
    (pres / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "hypothesis_id": "1",
                "artifacts": [
                    {
                        "filename": "chart_01_test.png",
                        "type": "chart",
                        "description": "test",
                        "finding_number": 1,
                        "included_in_report": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (pres / "data").mkdir(exist_ok=True)
    (pres / "data" / "analysis_summary.json").write_text(
        json.dumps(
            {
                "summary": "Treatment raises mean metric across steps in simulation.",
                "key_findings": [
                    "Step-wise mean value increases under treatment condition"
                ],
                "limitations": "Single seed ABM; not external validity",
            }
        ),
        encoding="utf-8",
    )
    (pres / "report_outline.json").write_text(
        json.dumps(
            {
                "hypothesis_id": "1",
                "sections": [
                    {"id": "overview"},
                    {"id": "data"},
                    {"id": "findings"},
                    {"id": "conclusions"},
                ],
                "figures": [
                    {
                        "asset": "chart_01_test.png",
                        "caption": "Test chart caption",
                        "finding_number": 1,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    from agentsociety2.skills.analysis.harness.report_bundle import write_report_bundle

    write_report_bundle(workspace, "1")
    save_report_review(
        workspace,
        "1",
        ReportQualityReview(
            hypothesis_id="1",
            verdict=ReviewVerdict.PASS,
            overall_score=5,
            dimensions={k: 5 for k in REPORT_DIMENSION_KEYS},
            report_fingerprint=report_content_fingerprint(pres),
        ),
    )
    result = validate_release(pres)
    assert result.status == "PASS"


def test_validate_release_blocks_missing_html(workspace: Path) -> None:
    pres = workspace / "presentation" / "hypothesis_1"
    pres.mkdir(parents=True, exist_ok=True)
    (pres / "report_zh.md").write_text(
        "## 概述\n\n## 数据\n\n## 发现\n\n## 结论\n", encoding="utf-8"
    )
    (pres / "report_en.md").write_text(
        "## Overview\n\n## Data\n\n## Findings\n\n## Conclusion\n",
        encoding="utf-8",
    )
    result = validate_release(pres)
    assert result.status == "BLOCKED"
    assert any(i.code == "report_missing" for i in result.issues)


def test_validate_release_is_pure_and_does_not_sync_assets(tmp_path: Path) -> None:
    pres = tmp_path / "presentation" / "hypothesis_1"
    charts = pres / "charts"
    charts.mkdir(parents=True)
    (charts / "fig_a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 80)
    (pres / "report_zh.md").write_text(
        "## 发现\n\n![a](assets/fig_a.png)\ncaption\n",
        encoding="utf-8",
    )
    (pres / "report_en.md").write_text(
        "## Findings\n\n![a](assets/fig_a.png)\ncaption\n",
        encoding="utf-8",
    )

    result = validate_release(pres)

    assert result.status == "BLOCKED"
    assert any(i.code == "asset_file_missing" for i in result.issues)
    assert not (pres / "assets" / "fig_a.png").exists()


def test_validate_report_quality_blocks_fluff(tmp_path: Path) -> None:
    pres = tmp_path / "presentation" / "hypothesis_1"
    pres.mkdir(parents=True)
    (pres / "report_zh.md").write_text(
        "## 概述\n\n结果显示出有趣的模式。\n\n## 数据\n\n## 发现\n\n## 结论\n",
        encoding="utf-8",
    )
    (pres / "report_en.md").write_text(
        "## Overview\n\nFurther research is needed.\n\n## Data\n\n## Findings\n\n## Conclusion\n",
        encoding="utf-8",
    )
    (pres / "report_zh.html").write_text(_minimal_report_html("zh"), encoding="utf-8")
    (pres / "report_en.html").write_text(_minimal_report_html("en"), encoding="utf-8")
    (pres / "data").mkdir()
    (pres / "data" / "analysis_summary.json").write_text(
        json.dumps(
            {"summary": "x", "key_findings": ["ok finding here"], "limitations": "sim"}
        ),
        encoding="utf-8",
    )
    result = validate_report_quality(pres)
    assert result.status == "BLOCKED"
    assert any(i.code == "report_fluff_phrase" for i in result.issues)


def test_validate_release_requires_fresh_review(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    pres = ws / "presentation" / "hypothesis_1"
    pres.mkdir(parents=True)
    (pres / "data").mkdir()
    (pres / "data" / "evidence_index.json").write_text(
        '{"sources":[]}', encoding="utf-8"
    )
    (pres / "report_zh.md").write_text("## 概述\n\n" + "word " * 40, encoding="utf-8")
    (pres / "report_en.md").write_text(
        "## Overview\n\n" + "word " * 40, encoding="utf-8"
    )
    (pres / "data" / "analysis_summary.json").write_text(
        json.dumps(
            {
                "summary": "ok summary here",
                "key_findings": ["finding with enough length"],
                "limitations": "simulation only",
            }
        ),
        encoding="utf-8",
    )
    (pres / "artifact_manifest.json").write_text(
        json.dumps({"hypothesis_id": "1", "artifacts": []}),
        encoding="utf-8",
    )
    (pres / "report_outline.json").write_text(
        json.dumps(
            {
                "hypothesis_id": "1",
                "sections": [{"id": "overview"}, {"id": "data"}, {"id": "findings"}],
                "figures": [],
            }
        ),
        encoding="utf-8",
    )
    harness_cli.cmd_intake(ws, "1", "1")
    _mark_prior_phases_gate_pass(ws, "1", "refine")
    result = harness_cli.cmd_validate_release(ws, "1", "1")
    assert result["status"] == "BLOCKED"
    assert any(
        i.get("code") == "report_review_missing" for i in result.get("issues", [])
    )


def test_build_report_context_collects_eda(workspace: Path) -> None:
    from agentsociety2.skills.analysis.harness.report_bundle import write_report_bundle

    harness_cli.cmd_intake(workspace, "1", "1")
    harness_cli.cmd_record_phase_artifacts(
        workspace,
        "1",
        "explore",
        ["presentation/hypothesis_1/data/eda_quick_stats.md"],
    )
    out = write_report_bundle(workspace, "1")
    assert out["source_count"] >= 1
    index_path = (
        workspace / "presentation" / "hypothesis_1" / "data" / "evidence_index.json"
    )
    assert index_path.exists()
    ctx_path = (
        workspace / "presentation" / "hypothesis_1" / "data" / "report_context.md"
    )
    assert "eda_quick_stats" in ctx_path.read_text(encoding="utf-8")
    rerun = write_report_bundle(workspace, "1")
    assert rerun["source_count"] == out["source_count"]
    index = json.loads(index_path.read_text(encoding="utf-8"))
    indexed_names = {Path(source["path"]).name for source in index["sources"]}
    assert indexed_names.isdisjoint(
        {
            "evidence_index.json",
            "report_context.md",
            "interactive_eda_section.html",
        }
    )


def test_validate_chart_script_requires_agg() -> None:
    bad = "import matplotlib.pyplot as plt\nplt.plot([1,2,3])\n"
    result = validate_chart_script(bad)
    assert result.status == "BLOCKED"


def test_validate_synthesis_missing_reports(workspace: Path) -> None:
    syn_dir = workspace / "synthesis"
    syn_dir.mkdir()
    result = validate_synthesis(
        workspace, synthesis_dir=syn_dir, scope_hypothesis_ids=["1"]
    )
    assert result.status == "BLOCKED"


def test_validate_synthesis_requires_scoped_source_artifacts(workspace: Path) -> None:
    syn_dir = workspace / "synthesis"
    syn_dir.mkdir()
    for name in (
        "synthesis_report_zh.md",
        "synthesis_report_en.md",
        "synthesis_report_zh.html",
        "synthesis_report_en.html",
    ):
        content = "<html>ok</html>" if name.endswith(".html") else "ok"
        (syn_dir / name).write_text(content, encoding="utf-8")
    (syn_dir / "synthesis_brief.json").write_text(
        json.dumps(
            {
                "synthesis_question": "What holds across hypotheses?",
                "scope_hypothesis_ids": ["1"],
                "source_artifacts": ["presentation/hypothesis_1/report_zh.md"],
            }
        ),
        encoding="utf-8",
    )
    pres = workspace / "presentation" / "hypothesis_1"
    pres.mkdir(parents=True, exist_ok=True)
    (pres / "report_zh.md").write_text("ok", encoding="utf-8")
    (pres / "report_zh.html").write_text("<html>ok</html>", encoding="utf-8")

    result = validate_synthesis(
        workspace, synthesis_dir=syn_dir, scope_hypothesis_ids=["1"]
    )

    assert result.status == "BLOCKED"
    assert any(i.code == "scope_hypothesis_source_missing" for i in result.issues)


def test_json_repair_loads_trailing_comma_outline() -> None:
    raw = """{
        "hypothesis_id": "1",
        "sections": [{"id": "overview"},],
        "figures": [],
    }"""
    outline = load_model_from_text(raw, ReportOutline)
    assert outline.hypothesis_id == "1"
    assert len(outline.sections) == 1


def test_validate_release_blocks_forbidden_presentation_dirs(tmp_path: Path) -> None:
    pres = tmp_path / "presentation" / "hypothesis_1"
    (pres / "analysis").mkdir(parents=True)
    (pres / "figures").mkdir()
    (pres / "report_zh.md").write_text(
        "## 概述\n\n## 数据\n\n## 发现\n\n## 结论\n", encoding="utf-8"
    )
    (pres / "report_en.md").write_text(
        "## Overview\n\n## Data\n\n## Findings\n\n## Conclusion\n",
        encoding="utf-8",
    )
    result = validate_release(pres)
    assert result.status == "BLOCKED"
    assert any(i.code == "presentation_layout_invalid" for i in result.issues)


def test_hypothesis_harness_dir_under_dot_agentsociety(workspace: Path) -> None:
    from agentsociety2.skills.analysis.harness.paths import hypothesis_harness_dir

    harness_cli.cmd_intake(workspace, "1", "1")
    harness_dir = hypothesis_harness_dir(workspace, "1")
    assert ".agentsociety" in str(harness_dir)
    assert harness_dir.name == "hypothesis_1"
    assert (harness_dir / "state.yaml").exists()


def test_validate_release_repairs_loose_json(tmp_path: Path) -> None:
    pres = tmp_path / "presentation" / "hypothesis_1"
    pres.mkdir(parents=True)
    assets = pres / "assets"
    assets.mkdir()
    (assets / "chart_01_test.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 200)
    (pres / "report_zh.md").write_text(
        "## 概述\n\n## 数据\n\n## 发现\n\n![c](assets/chart_01_test.png)\ncap\n\n## 结论\n",
        encoding="utf-8",
    )
    (pres / "report_en.md").write_text(
        "## Overview\n\n## Data\n\n## Findings\n\n![c](assets/chart_01_test.png)\ncap\n\n## Conclusion\n",
        encoding="utf-8",
    )
    (pres / "report_zh.html").write_text(_minimal_report_html("zh"), encoding="utf-8")
    (pres / "report_en.html").write_text(_minimal_report_html("en"), encoding="utf-8")
    (pres / "artifact_manifest.json").write_text(
        '{"hypothesis_id": "1", "artifacts": [{"filename": "chart_01_test.png", "type": "chart", "description": "t", "finding_number": 1, "included_in_report": true}],}',
        encoding="utf-8",
    )
    (pres / "data").mkdir(exist_ok=True)
    (pres / "data" / "analysis_summary.json").write_text(
        '{"summary": "ok", "key_findings": ["f1"], "limitations": "sim",}',
        encoding="utf-8",
    )
    (pres / "report_outline.json").write_text(
        '{"hypothesis_id": "1", "sections": [{"id": "overview"}, {"id": "data"}, {"id": "findings"}, {"id": "conclusions"}], "figures": [{"asset": "chart_01_test.png", "caption": "cap", "finding_number": 1}],}',
        encoding="utf-8",
    )
    from agentsociety2.skills.analysis.harness.report_bundle import write_report_bundle

    write_report_bundle(tmp_path, "1")
    result = validate_release(pres)
    assert result.status == "PASS"


def _mark_prior_phases_gate_pass(
    workspace: Path, hypothesis_id: str, through: str
) -> None:
    from agentsociety2.skills.analysis.harness.models import (
        AnalysisPhase,
        PhaseCheckpoint,
    )

    order = [p.value for p in AnalysisPhase]
    st = harness_state.load_hypothesis_state(workspace, hypothesis_id)
    for ph in order[: order.index(through) + 1]:
        cp = PhaseCheckpoint(
            phase=ph,
            structural_pass=True,
            attestation_pass=True,
            gate_pass=True,
        )
        st.phase_checkpoints[ph] = cp
    harness_state.save_hypothesis_state(workspace, hypothesis_id, st)


def test_record_attestation_produce_blocked_without_refine_gate(
    workspace: Path,
) -> None:
    from agentsociety2.skills.analysis.harness.models import AttestationStatus

    harness_cli.cmd_intake(workspace, "1", "1")
    _mark_prior_phases_gate_pass(workspace, "1", "claims")

    out = harness_cli.cmd_record_attestation(
        workspace,
        "1",
        {
            "phase": "produce",
            "status": AttestationStatus.DONE.value,
            "key_findings": ["Reports done"],
            "rubric": {
                "bilingual_reports_reviewed": True,
                "limitations_stated": "sim only",
                "independent_review_pass": True,
            },
        },
    )
    assert out.get("error") == "prior_phase_gate_blocked"
    assert any(
        i.get("code") == "prior_phase_gate_blocked" for i in out.get("issues", [])
    )


def test_sync_report_assets_copies_from_charts(tmp_path: Path) -> None:
    pres = tmp_path / "presentation" / "hypothesis_1"
    charts = pres / "charts"
    charts.mkdir(parents=True)
    (charts / "fig_a.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 80)
    (pres / "report_zh.md").write_text(
        "## 发现\n\n![a](assets/fig_a.png)\ncaption\n",
        encoding="utf-8",
    )
    result = sync_report_assets_from_reports(pres)
    assert result["copied"] == ["fig_a.png"]
    assert (pres / "assets" / "fig_a.png").is_file()


def test_validate_release_blocks_charts_dir_refs(tmp_path: Path) -> None:
    pres = tmp_path / "presentation" / "hypothesis_1"
    pres.mkdir(parents=True)
    (pres / "report_zh.md").write_text(
        "## 发现\n\n![a](charts/fig_a.png)\n",
        encoding="utf-8",
    )
    (pres / "report_en.md").write_text(
        "## Findings\n\n## Conclusion\n",
        encoding="utf-8",
    )
    result = validate_release(pres)
    assert result.status == "BLOCKED"
    assert any(i.code == "report_embeds_charts_dir" for i in result.issues)


def test_validate_release_blocked_when_refine_gate_not_pass(workspace: Path) -> None:
    harness_cli.cmd_intake(workspace, "1", "1")
    pres = workspace / "presentation" / "hypothesis_1"
    pres.mkdir(parents=True, exist_ok=True)
    (pres / "report_zh.md").write_text(
        "## 概述\n\n## 数据\n\n## 发现\n\n## 结论\n",
        encoding="utf-8",
    )
    (pres / "report_en.md").write_text(
        "## Overview\n\n## Data\n\n## Findings\n\n## Conclusion\n",
        encoding="utf-8",
    )
    result = harness_cli.cmd_validate_release(workspace, "1", "1")
    assert result["status"] == "BLOCKED"
    assert any(
        i.get("code") == "prior_phase_gate_blocked" for i in result.get("issues", [])
    )


def test_prepare_produce_requires_refine_gate(workspace: Path) -> None:
    harness_cli.cmd_intake(workspace, "1", "1")

    result = harness_cli.cmd_prepare_produce(workspace, "1", "1")

    assert result["status"] == "BLOCKED"
    assert any(i["code"] == "prior_phase_gate_blocked" for i in result["issues"])


def _prepare_ready_workspace(workspace: Path) -> tuple[Path, Path]:
    harness_cli.cmd_intake(workspace, "1", "1")
    _mark_prior_phases_gate_pass(workspace, "1", "refine")
    pres = workspace / "presentation" / "hypothesis_1"
    chart = pres / "charts" / "fig_a.png"
    chart.parent.mkdir(parents=True, exist_ok=True)
    chart.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 80)
    (pres / "report_zh.md").write_text(
        "## 发现\n\n![a](assets/fig_a.png)\ncaption\n",
        encoding="utf-8",
    )
    return pres, chart


def test_prepare_produce_runs_explicit_write_side_steps(workspace: Path) -> None:
    pres, _ = _prepare_ready_workspace(workspace)

    result = harness_cli.cmd_prepare_produce(workspace, "1", "1")

    assert result["status"] == "PREPARED"
    assert result["executed_steps"] == [
        "report_context",
        "report_assets",
        "interactive_eda",
    ]
    assert result["report_assets"]["copied"] == ["fig_a.png"]
    assert (pres / "assets" / "fig_a.png").is_file()
    assert (pres / "data" / "evidence_index.json").is_file()
    assert (pres / "data" / "interactive_eda_section.html").is_file()
    assert Path(result["manifest_path"]).is_file()


def test_prepare_produce_skips_unchanged_steps(workspace: Path) -> None:
    pres, _ = _prepare_ready_workspace(workspace)
    first = harness_cli.cmd_prepare_produce(workspace, "1", "1")
    manifest_path = Path(first["manifest_path"])
    tracked_paths = [
        manifest_path,
        pres / "data" / "evidence_index.json",
        pres / "data" / "report_context.md",
        pres / "data" / "interactive_eda_section.html",
        pres / "assets" / "fig_a.png",
    ]
    before = {
        path: (path.stat().st_mtime_ns, path.read_bytes()) for path in tracked_paths
    }

    second = harness_cli.cmd_prepare_produce(workspace, "1", "1")

    assert second["status"] == "UNCHANGED"
    assert second["executed_steps"] == []
    assert second["skipped_steps"] == [
        "report_context",
        "report_assets",
        "interactive_eda",
    ]
    assert {item["action"] for item in second["plan"]} == {"SKIP"}
    assert before == {
        path: (path.stat().st_mtime_ns, path.read_bytes()) for path in tracked_paths
    }


def test_prepare_produce_reruns_only_invalidated_asset_step(workspace: Path) -> None:
    pres, chart = _prepare_ready_workspace(workspace)
    harness_cli.cmd_prepare_produce(workspace, "1", "1")
    changed = b"\x89PNG\r\n\x1a\n" + b"changed" * 20
    chart.write_bytes(changed)

    result = harness_cli.cmd_prepare_produce(workspace, "1", "1")
    actions = {item["step_id"]: item["action"] for item in result["plan"]}

    assert actions == {
        "report_context": "SKIP",
        "report_assets": "RUN",
        "interactive_eda": "SKIP",
    }
    assert result["executed_steps"] == ["report_assets"]
    assert (pres / "assets" / "fig_a.png").read_bytes() == changed


def test_prepare_produce_invalidates_context_and_embed_for_eda_change(
    workspace: Path,
) -> None:
    pres, _ = _prepare_ready_workspace(workspace)
    harness_cli.cmd_prepare_produce(workspace, "1", "1")
    (pres / "data" / "eda_quick_stats.md").write_text(
        "# changed quick stats\n",
        encoding="utf-8",
    )

    result = harness_cli.cmd_prepare_produce(workspace, "1", "1")
    actions = {item["step_id"]: item["action"] for item in result["plan"]}

    assert actions == {
        "report_context": "RUN",
        "report_assets": "SKIP",
        "interactive_eda": "RUN",
    }
    assert result["executed_steps"] == ["report_context", "interactive_eda"]


def test_prepare_produce_rebuilds_missing_recorded_output(workspace: Path) -> None:
    pres, _ = _prepare_ready_workspace(workspace)
    harness_cli.cmd_prepare_produce(workspace, "1", "1")
    context_path = pres / "data" / "report_context.md"
    context_path.unlink()

    result = harness_cli.cmd_prepare_produce(workspace, "1", "1")
    plan = {item["step_id"]: item for item in result["plan"]}

    assert plan["report_context"]["action"] == "RUN"
    assert plan["report_context"]["reason"].startswith("output_missing:")
    assert result["executed_steps"] == ["report_context"]
    assert context_path.is_file()


def test_prepare_produce_rebuilds_changed_recorded_output(workspace: Path) -> None:
    pres, _ = _prepare_ready_workspace(workspace)
    harness_cli.cmd_prepare_produce(workspace, "1", "1")
    context_path = pres / "data" / "report_context.md"
    context_path.write_text("tampered", encoding="utf-8")

    result = harness_cli.cmd_prepare_produce(workspace, "1", "1")
    plan = {item["step_id"]: item for item in result["plan"]}

    assert plan["report_context"]["action"] == "RUN"
    assert plan["report_context"]["reason"].startswith("output_changed:")
    assert result["executed_steps"] == ["report_context"]
    assert context_path.read_text(encoding="utf-8") != "tampered"


def test_prepare_produce_dry_run_does_not_write(workspace: Path) -> None:
    pres, _ = _prepare_ready_workspace(workspace)
    manifest_path = (
        workspace
        / ".agentsociety"
        / "analysis"
        / "hypothesis_1"
        / "prepare_produce_manifest.json"
    )

    result = harness_cli.cmd_prepare_produce(workspace, "1", "1", dry_run=True)

    assert result["status"] == "PLANNED"
    assert result["would_write"] is True
    assert {item["action"] for item in result["plan"]} == {"RUN"}
    assert not manifest_path.exists()
    assert not (pres / "data" / "evidence_index.json").exists()
    assert not (pres / "assets" / "fig_a.png").exists()


def test_prepare_produce_failure_does_not_commit_manifest(
    workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pres, _ = _prepare_ready_workspace(workspace)
    manifest_path = (
        workspace
        / ".agentsociety"
        / "analysis"
        / "hypothesis_1"
        / "prepare_produce_manifest.json"
    )

    def fail_asset_sync(*_args, **_kwargs):
        raise RuntimeError("asset sync failed")

    monkeypatch.setattr(harness_cli, "cmd_sync_report_assets", fail_asset_sync)

    with pytest.raises(RuntimeError, match="asset sync failed"):
        harness_cli.cmd_prepare_produce(workspace, "1", "1")

    assert (pres / "data" / "report_context.md").is_file()
    assert not manifest_path.exists()


def test_prepare_produce_missing_asset_does_not_commit_manifest(
    workspace: Path,
) -> None:
    pres, chart = _prepare_ready_workspace(workspace)
    chart.unlink()
    manifest_path = (
        workspace
        / ".agentsociety"
        / "analysis"
        / "hypothesis_1"
        / "prepare_produce_manifest.json"
    )

    with pytest.raises(FileNotFoundError, match="fig_a.png"):
        harness_cli.cmd_prepare_produce(workspace, "1", "1")

    assert (pres / "data" / "report_context.md").is_file()
    assert not manifest_path.exists()


def test_capabilities_and_operations_surface_in_orchestration(workspace: Path) -> None:
    intake = harness_cli.cmd_intake(workspace, "1", "1")
    status = harness_cli.cmd_status(workspace, "1")
    run_loop = harness_cli.cmd_run_loop(workspace, "1", "1")
    guidance = get_harness_guidance("workflow")

    valid_states = {"available", "missing_dependency", "unhealthy", "disabled"}
    assert intake["capabilities"]
    assert status["capabilities"]
    assert {item["state"] for item in status["capabilities"]} <= valid_states
    assert {item.id for item in analysis_capability_statuses()} >= {
        "eda.quick-stats",
        "report.html",
        "report.render-validation",
    }
    available_ids = {item["id"] for item in run_loop["available_operations"]}
    assert {"intake", "write-plan", "validate-plan"} <= available_ids
    assert set(guidance["operation_contracts"]) == set(operation_registry())


def test_operation_registry_contracts_are_complete() -> None:
    for operation_id, spec in operation_registry().items():
        assert spec.id == operation_id
        assert spec.phases
        assert (
            spec.required_inputs
            or spec.optional_inputs
            or operation_id == "chart-scaffold"
        )
        assert not set(spec.required_inputs) & set(spec.optional_inputs)
        assert {item.name for item in spec.inputs} == {
            name
            for raw_name in (*spec.required_inputs, *spec.optional_inputs)
            for name in raw_name.split("|")
        }
        assert spec.handler
        if spec.mutates_workspace:
            assert spec.produced_artifacts
        if operation_id.startswith("validate"):
            assert spec.validator


def test_operation_preflight_checks_inputs_gates_and_capabilities() -> None:
    chart = operation_registry()["validate-chart"]
    missing_chart = evaluate_operation_availability(
        chart,
        passed_gates={"claims"},
        values={"workspace": ".", "hypothesis_id": "1"},
    )
    duplicate_chart = evaluate_operation_availability(
        chart,
        passed_gates={"claims"},
        values={
            "workspace": ".",
            "hypothesis_id": "1",
            "chart_path": "a.png",
            "code": "code.py",
        },
    )
    ready_chart = evaluate_operation_availability(
        chart,
        passed_gates={"claims"},
        values={
            "workspace": ".",
            "hypothesis_id": "1",
            "chart_path": "a.png",
        },
    )
    explore = evaluate_operation_availability(
        operation_registry()["validate-explore"],
        values={"workspace": ".", "hypothesis_id": "1", "experiment_id": "1"},
    )
    eda = evaluate_operation_availability(
        operation_registry()["run-eda"],
        values={
            "data_path": "replay",
            "output_dir": "data",
            "type": "ydata",
        },
        capability_states={"eda.ydata": "missing_dependency"},
    )

    assert missing_chart.status == "INVALID_INPUT"
    assert duplicate_chart.status == "INVALID_INPUT"
    assert ready_chart.status == "AVAILABLE"
    assert explore.status == "BLOCKED_BY_GATE"
    assert eda.status == "MISSING_DEPENDENCY"


def _start_operation_lock_holder(lock_path: Path) -> subprocess.Popen[str]:
    script = """
import sys
from pathlib import Path
from agentsociety2.skills.analysis.harness.execution import operation_lock

with operation_lock(Path(sys.argv[1])) as acquired:
    print("locked" if acquired else "blocked", flush=True)
    if acquired:
        sys.stdin.read(1)
"""
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(lock_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "locked"
    return process


def _release_operation_lock_holder(process: subprocess.Popen[str]) -> None:
    assert process.stdin is not None
    process.stdin.write("x")
    process.stdin.flush()
    stdout, stderr = process.communicate(timeout=5)
    assert process.returncode == 0, stdout + stderr


def test_operation_singleflight_lock_blocks_equivalent_handler(
    workspace: Path,
) -> None:
    spec = operation_registry()["write-plan"]
    values = {
        "workspace": str(workspace),
        "hypothesis_id": "1",
        "payload": {"research_question": "q"},
    }
    lock_path = analysis_operation_lock_path(
        workspace,
        operation_execution_key(spec, values),
    )
    process = _start_operation_lock_holder(lock_path)
    invoked = False

    def invoke() -> dict[str, str]:
        nonlocal invoked
        invoked = True
        return {"status": "SUCCEEDED"}

    try:
        with operation_lock(lock_path) as acquired:
            assert acquired is False
        outcome = execute_operation(
            spec,
            workspace=workspace,
            values=values,
            preflight=None,
            invoke=invoke,
            persist_receipt=True,
        )
    finally:
        _release_operation_lock_holder(process)

    assert outcome.status == "BLOCKED"
    assert outcome.exit_code == 2
    assert outcome.error is not None
    assert outcome.error.type == "OperationAlreadyRunning"
    assert outcome.result["reason"] == "operation_already_running"
    assert invoked is False
    assert list_run_receipts(workspace) == []


def test_non_repeatable_operation_is_deduplicated_by_execution_key(
    workspace: Path,
) -> None:
    spec = operation_registry()["intake"]
    values = {
        "workspace": str(workspace),
        "hypothesis_id": "1",
        "experiment_id": "1",
    }
    calls = 0

    def invoke() -> dict[str, object]:
        nonlocal calls
        calls += 1
        return harness_cli.cmd_intake(workspace, "1", "1")

    first = execute_operation(
        spec,
        workspace=workspace,
        values=values,
        preflight=None,
        invoke=invoke,
        persist_receipt=True,
    )
    second = execute_operation(
        spec,
        workspace=workspace,
        values=values,
        preflight=None,
        invoke=invoke,
        persist_receipt=True,
    )
    receipts = list_run_receipts(workspace, hypothesis_id="1")

    assert first.status == "SUCCEEDED"
    assert second.status == "UNCHANGED"
    assert second.exit_code == 0
    assert calls == 1
    assert len(receipts) == 2
    assert receipts[0].status == "UNCHANGED"
    assert receipts[0].attempt == 2
    assert receipts[0].deduplicated_from_run_id == first.run_id
    assert receipts[0].execution_key == receipts[1].execution_key


def test_execution_key_canonicalizes_paths_and_hashes_payload_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)
    intake = operation_registry()["intake"]
    absolute_key = operation_execution_key(
        intake,
        {
            "workspace": str(workspace),
            "hypothesis_id": "1",
            "experiment_id": "1",
        },
    )
    relative_key = operation_execution_key(
        intake,
        {
            "workspace": "workspace",
            "hypothesis_id": "1",
            "experiment_id": "1",
        },
    )
    next_contract_key = operation_execution_key(
        intake.model_copy(update={"contract_version": 2}),
        {
            "workspace": str(workspace),
            "hypothesis_id": "1",
            "experiment_id": "1",
        },
    )
    payload_path = tmp_path / "plan.json"
    payload_path.write_text('{"research_question":"first"}', encoding="utf-8")
    write_plan = operation_registry()["write-plan"]
    first_payload_key = operation_execution_key(
        write_plan,
        {
            "workspace": str(workspace),
            "hypothesis_id": "1",
            "payload": str(payload_path),
        },
    )
    payload_path.write_text('{"research_question":"second"}', encoding="utf-8")
    second_payload_key = operation_execution_key(
        write_plan,
        {
            "workspace": str(workspace),
            "hypothesis_id": "1",
            "payload": str(payload_path),
        },
    )
    compact_payload_key = operation_execution_key(
        write_plan,
        {
            "workspace": str(workspace),
            "hypothesis_id": "1",
            "payload": '{"primary_metrics":["value"],"research_question":"q"}',
        },
    )
    formatted_payload_key = operation_execution_key(
        write_plan,
        {
            "workspace": str(workspace),
            "hypothesis_id": "1",
            "payload": '{ "research_question": "q", "primary_metrics": ["value"] }',
        },
    )
    review = operation_registry()["review-reflection"]
    implicit_defaults_key = operation_execution_key(
        review,
        {"workspace": str(workspace)},
    )
    explicit_defaults_key = operation_execution_key(
        review,
        {
            "workspace": str(workspace),
            "hypothesis_id": None,
            "include_preferences": False,
        },
    )

    assert absolute_key == relative_key
    assert absolute_key != next_contract_key
    assert first_payload_key != second_payload_key
    assert compact_payload_key == formatted_payload_key
    assert implicit_defaults_key == explicit_defaults_key


def test_retryable_run_is_resolved_by_later_success(workspace: Path) -> None:
    spec = operation_registry()["write-plan"]
    values = {
        "workspace": str(workspace),
        "hypothesis_id": "1",
        "payload": {"research_question": "q"},
    }
    failed = OperationRunReceipt(
        run_id="run_failed_write_plan",
        operation_id=spec.id,
        operation_contract_version=spec.contract_version,
        execution_key=operation_execution_key(spec, values),
        status="FAILED",
        hypothesis_id="1",
        input_fingerprint="failed-input",
        retryable=True,
    )
    save_run_receipt(workspace, failed)
    success = execute_operation(
        spec,
        workspace=workspace,
        values=values,
        preflight=None,
        invoke=lambda: {"status": "SUCCEEDED"},
        persist_receipt=True,
    )
    receipts = list_run_receipts(workspace, hypothesis_id="1", limit=None)
    status = harness_cli.cmd_status(workspace, "1")

    assert success.status == "SUCCEEDED"
    assert unresolved_retryable_runs(receipts) == []
    assert status["retryable_runs"] == []


def test_run_loop_uses_receipts_for_completion_retry_and_in_flight_state(
    workspace: Path,
) -> None:
    spec = operation_registry()["intake"]
    values = {
        "workspace": str(workspace),
        "hypothesis_id": "1",
        "experiment_id": "1",
    }
    intake = execute_operation(
        spec,
        workspace=workspace,
        values=values,
        preflight=None,
        invoke=lambda: harness_cli.cmd_intake(workspace, "1", "1"),
        persist_receipt=True,
    )
    retry = OperationRunReceipt(
        run_id="run_retry_write_plan",
        operation_id="write-plan",
        status="FAILED",
        hypothesis_id="1",
        experiment_id="1",
        input_fingerprint="retry-input",
        retryable=True,
    )
    active = OperationRunReceipt(
        run_id="run_active_validate_plan",
        operation_id="validate-plan",
        status="RUNNING",
        hypothesis_id="1",
        experiment_id="1",
        input_fingerprint="active-input",
        pid=os.getpid(),
        hostname=socket.gethostname(),
    )
    save_run_receipt(workspace, retry)
    save_run_receipt(workspace, active)

    run_loop = harness_cli.cmd_run_loop(workspace, "1", "1")
    available = {item["id"]: item for item in run_loop["available_operations"]}
    blocked = {item["operation_id"]: item for item in run_loop["blocked_operations"]}
    completed = {
        item["operation_id"]: item for item in run_loop["completed_operations"]
    }

    assert "intake" not in available
    assert blocked["intake"]["status"] == "ALREADY_COMPLETED"
    assert blocked["validate-plan"]["status"] == "ALREADY_RUNNING"
    assert available["write-plan"]["execution_state"] == "RETRYABLE"
    assert available["write-plan"]["retry_run_id"] == retry.run_id
    assert completed["intake"]["run_id"] == intake.run_id
    assert run_loop["in_flight_runs"][0]["run_id"] == active.run_id
    assert run_loop["recommended_operations"] == run_loop["available_operations"]
    other_experiment = harness_cli.cmd_run_loop(workspace, "1", "2")
    assert "intake" in {item["id"] for item in other_experiment["available_operations"]}


def test_run_receipt_recovers_dead_process_and_surfaces_in_run_loop(
    workspace: Path,
) -> None:
    harness_cli.cmd_intake(workspace, "1", "1")
    receipt = OperationRunReceipt(
        run_id="run_interrupted_test",
        operation_id="write-plan",
        status="RUNNING",
        hypothesis_id="1",
        experiment_id="1",
        input_fingerprint="abc123",
        repeatable=True,
        pid=99_999_999,
        hostname=socket.gethostname(),
    )
    save_run_receipt(workspace, receipt)

    recovered = list_run_receipts(workspace, hypothesis_id="1")
    run_loop = harness_cli.cmd_run_loop(workspace, "1", "1")

    assert recovered[0].status == "INTERRUPTED"
    assert recovered[0].retryable is True
    assert recovered[0].error is not None
    assert recovered[0].error.type == "InterruptedOperation"
    assert run_loop["recent_runs"][0]["run_id"] == "run_interrupted_test"
    assert run_loop["retryable_runs"][0]["status"] == "INTERRUPTED"


def test_atomic_json_write_preserves_previous_file_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "receipt.json"
    path.write_text('{"status":"old"}', encoding="utf-8")

    def fail_replace(*_args, **_kwargs):
        raise OSError("replace failed")

    monkeypatch.setattr(harness_json_io.os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed"):
        harness_json_io.atomic_write_json(path, {"status": "new"})

    assert json.loads(path.read_text(encoding="utf-8")) == {"status": "old"}
    assert list(tmp_path.glob(".receipt.json.*.tmp")) == []


def test_capability_probe_distinguishes_unhealthy_dependency(monkeypatch) -> None:
    original_find_spec = harness_capabilities.importlib.util.find_spec

    def find_spec(module: str):
        if module == "pandas":
            raise ValueError("invalid module spec")
        return original_find_spec(module)

    monkeypatch.setattr(harness_capabilities.importlib.util, "find_spec", find_spec)

    statuses = {
        item.id: item for item in harness_capabilities.analysis_capability_statuses()
    }

    assert statuses["eda.quick-stats"].state == "unhealthy"
    assert "invalid module spec" in statuses["eda.quick-stats"].detail
