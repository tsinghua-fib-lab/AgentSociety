"""Regression tests for analysis gate integrity."""

from __future__ import annotations

from pathlib import Path

from agentsociety2.skills.analysis.harness import cli as harness_cli
from agentsociety2.skills.analysis.harness import state as harness_state
from agentsociety2.skills.analysis.harness.attestation import validate_attestation
from agentsociety2.skills.analysis.harness.cli import cmd_validate_chart
from agentsociety2.skills.analysis.harness.execution import _normalize_status
from agentsociety2.skills.analysis.harness.models import (
    AnalysisPhase,
    HypothesisAnalysisState,
    PhaseAttestation,
    PhaseCheckpoint,
    SynthesisAnalysisState,
)
from agentsociety2.skills.analysis.harness.report_eda_embed import (
    EDA_INTERACTIVE_BEGIN,
    EDA_INTERACTIVE_END,
    embed_interactive_eda_in_html,
)

REPO_ROOT = Path(__file__).resolve().parents[4]
REPORT_SHELL = (
    REPO_ROOT
    / "extension/skills/agentsociety-analysis/assets/report-shell.reference.html"
)


def _attestation(**rubric: object) -> PhaseAttestation:
    return PhaseAttestation(
        phase="claims",
        key_findings=["Confirmed one claim"],
        rubric=rubric,
    )


def test_attestation_rejects_false_boolean_rubric() -> None:
    result = validate_attestation(
        _attestation(
            claims_user_approved=False,
            confirmatory_vs_exploratory_clear="explicit",
        )
    )
    assert result.status == "BLOCKED"
    assert any("claims_user_approved" in item.message for item in result.issues)


def test_attestation_rejects_zero_and_blank_text() -> None:
    result = validate_attestation(
        _attestation(
            claims_user_approved=True,
            confirmatory_vs_exploratory_clear="   ",
        )
    )
    assert result.status == "BLOCKED"


def test_attestation_accepts_true_boolean() -> None:
    result = validate_attestation(
        _attestation(
            claims_user_approved=True,
            confirmatory_vs_exploratory_clear="confirmatory vs exploratory stated",
        )
    )
    assert result.status == "PASS"


def test_gate_blocked_is_not_normalized_to_success() -> None:
    assert (
        _normalize_status(
            {"status": "BLOCKED", "structural_pass": True, "attestation_pass": False}
        )
        == "BLOCKED"
    )


def test_synthesis_scope_inferred_from_presentation(tmp_path: Path) -> None:
    (tmp_path / "presentation" / "hypothesis_1").mkdir(parents=True)
    (tmp_path / "presentation" / "hypothesis_2").mkdir(parents=True)
    harness_state.save_synthesis_state(tmp_path, SynthesisAnalysisState())
    assert harness_state.resolve_synthesis_scope(tmp_path) == ["1", "2"]


def test_validate_chart_does_not_reset_refine_gate(tmp_path: Path) -> None:
    state = HypothesisAnalysisState(
        current_phase=AnalysisPhase.refine,
        phase_checkpoints={
            "refine": PhaseCheckpoint(
                phase="refine", structural_pass=True, gate_pass=True
            )
        },
    )
    harness_state.save_hypothesis_state(tmp_path, "1", state)

    # A failing per-chart validation must not overwrite the holistic gate.
    cmd_validate_chart(
        tmp_path,
        "1",
        code="import matplotlib\nprint('missing Agg')",
    )
    reloaded = harness_state.load_hypothesis_state(tmp_path, "1")
    assert reloaded.phase_checkpoints["refine"].gate_pass is True


def test_report_shell_preserves_authored_data_when_reembedding_eda() -> None:
    prose = "实验共采集了 12,400 条记录。"
    shell = REPORT_SHELL.read_text(encoding="utf-8").replace(
        "<!-- 从 eda_quick_stats / SQL 提炼的 prose -->", prose
    )
    prefix, _, region = shell.partition(EDA_INTERACTIVE_BEGIN)
    _, _, suffix = region.partition(EDA_INTERACTIVE_END)
    authored_html = prefix + suffix
    assert prose in authored_html
    assert "<table" in authored_html

    initial_section = "<div>Initial EDA summary</div>"
    updated_section = r"<div>Updated EDA summary from C:\replay\metrics</div>"
    first = embed_interactive_eda_in_html(shell, initial_section)
    assert initial_section in first

    updated = embed_interactive_eda_in_html(first, updated_section)
    updated_prefix, _, region = updated.partition(EDA_INTERACTIVE_BEGIN)
    generated, _, updated_suffix = region.partition(EDA_INTERACTIVE_END)
    assert (updated_prefix, updated_suffix) == (prefix, suffix)
    assert generated.strip() == updated_section
    assert embed_interactive_eda_in_html(updated, updated_section) == updated


def test_refine_checks_the_declared_chart_directory(tmp_path):
    from agentsociety2.skills.analysis.harness.models import FigureContract
    from agentsociety2.skills.analysis.harness.validators.refine import validate_refine

    pres = tmp_path / "presentation/hypothesis_1"
    (pres / "assets").mkdir(parents=True)
    (pres / "assets/figure.png").write_bytes(b"figure")
    contract = FigureContract(contract_id="c1", output_files=["charts/figure.png"])
    state = HypothesisAnalysisState(figure_contracts=[contract])
    result = validate_refine(state, tmp_path, "1")
    assert any(item.code == "refine_output_missing" for item in result.issues)
    contract.output_files = ["figure.png"]
    result = validate_refine(state, tmp_path, "1")
    assert all(item.code != "refine_output_missing" for item in result.issues)


def test_synthesis_attestation_requires_produce_gate(tmp_path: Path) -> None:
    harness_state.save_synthesis_state(
        tmp_path, SynthesisAnalysisState(synthesis_scope_hypothesis_ids=["1"])
    )
    result = harness_cli.cmd_record_attestation(tmp_path, None, {"phase": "synthesis"})
    assert result["status"] == "BLOCKED"
    assert result["issues"][0]["hypothesis_id"] == "1"
