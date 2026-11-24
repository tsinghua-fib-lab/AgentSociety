from __future__ import annotations

from typing import Any

from agentsociety2.skills.analysis.harness.attestation import (
    PHASE_RUBRIC_KEYS,
    validate_attestation,
)
from agentsociety2.skills.analysis.harness.models import (
    HYPOTHESIS_PHASE_ORDER,
    AnalysisPhase,
    GateReport,
    HypothesisAnalysisState,
    PhaseAttestation,
    PhaseCheckpoint,
    SynthesisAnalysisState,
    ValidationIssue,
)
from agentsociety2.skills.analysis.harness.validators._helpers import issue

PHASE_VALIDATE_COMMAND: dict[str, str] = {
    "frame": "validate-plan",
    "explore": "validate-explore",
    "claims": "validate-claims",
    "refine": "validate-refine",
    "produce": "validate-release",
    "synthesis": "validate-synthesis",
}


def validate_command_for(phase: str) -> str:
    """Return the CLI command that validates a phase.

    :param phase: Phase name.
    :returns: Command name such as ``validate-plan``.
    """
    return PHASE_VALIDATE_COMMAND.get(phase, f"validate-{phase}")


def prior_phase_gate_issues(
    state: HypothesisAnalysisState,
    target: AnalysisPhase,
) -> list[ValidationIssue]:
    """All phases before ``target`` must have gate_pass on checkpoint."""
    idx = HYPOTHESIS_PHASE_ORDER.index(target)
    issues: list[ValidationIssue] = []
    for prior in HYPOTHESIS_PHASE_ORDER[:idx]:
        cp = state.phase_checkpoints.get(prior.value)
        if cp is None or not cp.gate_pass:
            issues.append(
                issue(
                    "prior_phase_gate_blocked",
                    phase=target.value,
                    message=f"Prior phase {prior.value} gate not passed",
                    fix_hint=(
                        f"Run {validate_command_for(prior.value)}, record-attestation --phase {prior.value}, "
                        f"confirm gate-status PASS, then advance"
                    ),
                )
            )
    return issues


def _checkpoint(state: HypothesisAnalysisState, phase: str) -> PhaseCheckpoint:
    if phase not in state.phase_checkpoints:
        state.phase_checkpoints[phase] = PhaseCheckpoint(phase=phase)
    return state.phase_checkpoints[phase]


def evaluate_hypothesis_gate(
    phase: str,
    *,
    state: HypothesisAnalysisState,
    structural_result,
    attestation: PhaseAttestation | None = None,
) -> GateReport:
    cp = _checkpoint(state, phase)
    structural_issues: list[ValidationIssue] = list(structural_result.issues)
    cp.structural_pass = structural_result.status == "PASS"
    cp.structural_issues = [i.code for i in structural_issues]

    attestation_issues: list[ValidationIssue] = []
    cp.attestation_required = True
    if attestation is None:
        attestation = state.phase_attestations.get(phase)
    if attestation is None:
        attestation_issues.append(
            issue(
                "attestation_missing",
                phase=phase,
                message=f"No phase attestation recorded for {phase}",
                fix_hint=f"Run record-attestation --phase {phase} after LLM review of this stage",
            )
        )
        cp.attestation_pass = False
    else:
        att_result = validate_attestation(attestation)
        cp.attestation_pass = att_result.status == "PASS"
        attestation_issues = list(att_result.issues)
        if cp.attestation_pass:
            cp.completed_at = attestation.completed_at

    all_issues = structural_issues + attestation_issues
    status = "PASS" if cp.structural_pass and cp.attestation_pass else "BLOCKED"
    cp.gate_pass = status == "PASS"

    recommended = structural_result.recommended_next_step
    if not cp.attestation_pass and attestation_issues:
        recommended = attestation_issues[0].fix_hint or recommended

    return GateReport(
        phase=phase,
        status=status,
        structural_pass=cp.structural_pass,
        attestation_pass=cp.attestation_pass,
        structural_issues=structural_issues,
        attestation_issues=attestation_issues,
        issues=all_issues,
        recommended_next_step=recommended,
        rubric_keys=PHASE_RUBRIC_KEYS.get(phase, []),
        checkpoint=cp,
    )


def evaluate_synthesis_gate(
    *,
    state: SynthesisAnalysisState,
    structural_result,
    attestation: PhaseAttestation | None = None,
) -> GateReport:
    phase = "synthesis"
    if attestation is None:
        attestation = state.phase_attestation
    attestation_issues: list[ValidationIssue] = []
    attestation_pass = False
    if attestation is None:
        attestation_issues.append(
            issue(
                "attestation_missing",
                phase=phase,
                message="No synthesis phase attestation",
                fix_hint="Run record-attestation --phase synthesis",
            )
        )
    else:
        att_result = validate_attestation(attestation)
        attestation_pass = att_result.status == "PASS"
        attestation_issues = list(att_result.issues)

    structural_pass = structural_result.status == "PASS"
    all_issues = list(structural_result.issues) + attestation_issues
    status = "PASS" if structural_pass and attestation_pass else "BLOCKED"
    return GateReport(
        phase=phase,
        status=status,
        structural_pass=structural_pass,
        attestation_pass=attestation_pass,
        structural_issues=list(structural_result.issues),
        attestation_issues=attestation_issues,
        issues=all_issues,
        recommended_next_step=structural_result.recommended_next_step,
        rubric_keys=PHASE_RUBRIC_KEYS["synthesis"],
    )


def gate_status_hypothesis(state: HypothesisAnalysisState) -> dict[str, Any]:
    phases = [p.value for p in AnalysisPhase]
    rows = []
    for ph in phases:
        cp = state.phase_checkpoints.get(ph, PhaseCheckpoint(phase=ph))
        rows.append(
            {
                "phase": ph,
                "current": state.current_phase.value == ph,
                "structural_pass": cp.structural_pass,
                "attestation_pass": cp.attestation_pass,
                "gate_pass": cp.gate_pass,
                "structural_issues": cp.structural_issues,
                "completed_at": cp.completed_at.isoformat()
                if cp.completed_at
                else None,
                "rubric_keys": PHASE_RUBRIC_KEYS.get(ph, []),
                "has_attestation": ph in state.phase_attestations,
            }
        )
    current_cp = state.phase_checkpoints.get(
        state.current_phase.value, PhaseCheckpoint(phase=state.current_phase.value)
    )
    blocked_by: list[str] = []
    if not current_cp.structural_pass:
        blocked_by.append("structural")
    if not current_cp.attestation_pass:
        blocked_by.append("attestation")
    return {
        "current_phase": state.current_phase.value,
        "hypothesis_release": state.hypothesis_release.value,
        "current_gate_pass": current_cp.gate_pass,
        "blocked_by": blocked_by,
        "phases": rows,
        "next_phase": _next_phase(state),
    }


def _next_phase(state: HypothesisAnalysisState) -> str | None:
    order = list(AnalysisPhase)
    idx = order.index(state.current_phase)
    cp = state.phase_checkpoints.get(state.current_phase.value)
    if cp is None or not cp.gate_pass:
        return None
    if idx + 1 < len(order):
        return order[idx + 1].value
    return None
