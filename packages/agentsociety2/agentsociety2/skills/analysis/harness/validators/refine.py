from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from agentsociety2.skills.analysis.harness.validators._helpers import (
    ValidationResult,
    blocked,
    issue,
    passed,
)

if TYPE_CHECKING:
    from agentsociety2.skills.analysis.harness.models import HypothesisAnalysisState


def validate_refine(
    state: HypothesisAnalysisState,
    workspace: Path,
    hypothesis_id: str,
) -> ValidationResult:
    """Holistic refine gate: contracts and chart outputs on disk."""
    issues = []
    pres = workspace / "presentation" / f"hypothesis_{hypothesis_id}"
    assets = pres / "assets"
    charts_dir = pres / "charts"

    if not state.figure_contracts:
        issues.append(
            issue(
                "refine_no_contracts",
                phase="refine",
                message="No figure contracts recorded",
                fix_hint="Record a figure contract for each report-facing chart or figure",
            )
        )

    if state.chart_count < 1:
        issues.append(
            issue(
                "refine_no_validated_charts",
                phase="refine",
                message="No validated chart or figure files recorded",
                fix_hint="Run validate-chart --chart-path for each contract output",
            )
        )

    from agentsociety2.skills.analysis.harness.state import load_claims

    claims = load_claims(workspace, hypothesis_id)
    approved_claim_ids = {c.claim_id for c in claims.claims if c.approved}
    known_claim_ids = {c.claim_id for c in claims.claims}

    for contract in state.figure_contracts:
        if not contract.claim_id:
            issues.append(
                issue(
                    "refine_contract_missing_claim",
                    phase="refine",
                    message=f"Contract {contract.contract_id} has no claim_id",
                    fix_hint="Trace each figure to a recorded claim",
                )
            )
        elif contract.claim_id not in known_claim_ids:
            issues.append(
                issue(
                    "refine_contract_unknown_claim",
                    phase="refine",
                    message=(
                        f"Contract {contract.contract_id} references unknown claim "
                        f"{contract.claim_id}"
                    ),
                    fix_hint="Use a claim_id from claims.json",
                )
            )
        elif contract.claim_id not in approved_claim_ids:
            issues.append(
                issue(
                    "refine_contract_unapproved_claim",
                    phase="refine",
                    message=(
                        f"Contract {contract.contract_id} references claim "
                        f"{contract.claim_id} which is not approved"
                    ),
                    fix_hint="Approve the claim or point the contract at an approved claim",
                )
            )

    for contract in state.figure_contracts:
        if not contract.output_files:
            issues.append(
                issue(
                    "refine_contract_empty_outputs",
                    phase="refine",
                    message=f"Contract {contract.contract_id} has no output_files",
                    fix_hint="Set output_files to generated chart/figure paths",
                )
            )
            continue
        for rel in contract.output_files:
            rel_path = Path(rel)
            if rel_path.is_absolute() or ".." in rel_path.parts:
                issues.append(
                    issue(
                        "refine_output_outside_presentation",
                        phase="refine",
                        message=f"Contract {contract.contract_id} has unsafe output path: {rel}",
                        fix_hint="Use a path under presentation/hypothesis_{id}/charts or assets",
                    )
                )
                continue
            candidates = [pres / rel_path]
            if len(rel_path.parts) == 1:
                candidates.extend((assets / rel_path, charts_dir / rel_path))
            if not any(p.exists() and p.is_file() for p in candidates):
                issues.append(
                    issue(
                        "refine_output_missing",
                        phase="refine",
                        message=f"Missing output for {contract.contract_id}: {rel}",
                        fix_hint="Generate chart then validate-chart --chart-path",
                    )
                )

    if issues:
        return blocked(issues)
    return passed()
