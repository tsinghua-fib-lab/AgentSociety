from __future__ import annotations

from agentsociety2.skills.analysis.harness.models import (
    AttestationStatus,
    PhaseAttestation,
    ValidationIssue,
    ValidationResult,
)
from agentsociety2.skills.analysis.harness.validators._helpers import (
    blocked,
    issue,
    passed,
)

PHASE_RUBRIC_KEYS: dict[str, list[str]] = {
    "frame": ["research_question_confirmed", "success_criteria"],
    "explore": ["tables_inspected", "data_limitations", "eda_takeaway"],
    "claims": ["claims_user_approved", "confirmatory_vs_exploratory_clear"],
    "refine": ["charts_map_to_claims", "visual_message_clear"],
    "produce": [
        "bilingual_reports_reviewed",
        "limitations_stated",
        "independent_review_pass",
    ],
    "synthesis": [
        "scope_sources_integrated",
        "limitations_stated",
        "independent_review_pass",
    ],
}

# Booleans must be literally true; text/list fields must contain non-empty text.
BOOLEAN_RUBRIC_KEYS: frozenset[str] = frozenset(
    {
        "research_question_confirmed",
        "claims_user_approved",
        "bilingual_reports_reviewed",
        "independent_review_pass",
    }
)


def _rubric_value_valid(key: str, value: object) -> bool:
    """Return True when a rubric value carries a real affirmative judgment."""
    if key in BOOLEAN_RUBRIC_KEYS:
        return value is True
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple)):
        return any(isinstance(item, str) and item.strip() for item in value)
    return value is not None and bool(value)


def validate_attestation(att: PhaseAttestation) -> ValidationResult:
    issues: list[ValidationIssue] = []
    phase = att.phase.strip()
    if phase not in PHASE_RUBRIC_KEYS:
        issues.append(
            issue(
                "unknown_phase",
                phase=phase,
                message=f"Unknown attestation phase: {phase}",
                fix_hint="Use frame|explore|claims|refine|produce|synthesis",
            )
        )
        return blocked(issues)

    if att.status == AttestationStatus.BLOCKED:
        if not att.blocking_reason:
            issues.append(
                issue(
                    "blocking_reason_required",
                    phase=phase,
                    message="BLOCKED attestation requires blocking_reason",
                )
            )
        return blocked(
            issues,
            recommended_next_step=att.recommended_next_step
            or att.blocking_reason
            or "",
        )

    if not any(
        isinstance(item, str) and item.strip() for item in att.key_findings
    ):
        issues.append(
            issue(
                "key_findings_required",
                phase=phase,
                message="At least one non-empty key_finding is required",
                fix_hint="Summarize what this phase established before advancing",
            )
        )

    for key in PHASE_RUBRIC_KEYS[phase]:
        value = att.rubric.get(key)
        if key not in att.rubric or not _rubric_value_valid(key, value):
            issues.append(
                issue(
                    "rubric_field_missing",
                    phase=phase,
                    message=(
                        f"Attestation rubric missing or false: {key}"
                        if key in BOOLEAN_RUBRIC_KEYS
                        else f"Attestation rubric missing or empty: {key}"
                    ),
                    fix_hint=f"Set rubric.{key} in record-attestation payload (LLM judgment)",
                )
            )

    if issues:
        return blocked(
            issues,
            recommended_next_step="Complete record-attestation with rubric fields filled",
        )
    return passed()
