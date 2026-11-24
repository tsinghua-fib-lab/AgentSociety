from __future__ import annotations

from pathlib import Path

from agentsociety2.skills.analysis.harness.json_io import load_model_from_file
from agentsociety2.skills.analysis.harness.models import ReleaseStatus, ValidationResult
from agentsociety2.skills.analysis.harness.paths import hypothesis_report_review_path
from agentsociety2.skills.analysis.harness.review import validate_report_review
from agentsociety2.skills.analysis.harness.schemas import SynthesisBrief
from agentsociety2.skills.analysis.harness.state import load_hypothesis_state
from agentsociety2.skills.analysis.harness.validators._helpers import (
    blocked,
    issue,
    passed,
)


def _load_brief(path: Path) -> tuple[SynthesisBrief | None, list]:
    if not path.exists():
        return None, [
            issue(
                "synthesis_brief_missing",
                phase="synthesis",
                message="synthesis/synthesis_brief.json not found",
                fix_hint="Run `ags.py analysis payload-template --name synthesis_brief`",
            )
        ]
    try:
        return load_model_from_file(path, SynthesisBrief), []
    except ValueError as exc:
        return None, [
            issue(
                "synthesis_brief_invalid",
                phase="synthesis",
                message=str(exc),
            )
        ]


def validate_synthesis(
    workspace: Path,
    *,
    synthesis_dir: Path,
    scope_hypothesis_ids: list[str],
    max_synthesis_charts: int = 0,
) -> ValidationResult:
    issues: list = []
    report_zh = synthesis_dir / "synthesis_report_zh.md"
    report_en = synthesis_dir / "synthesis_report_en.md"
    brief_path = synthesis_dir / "synthesis_brief.json"

    for path, label in (
        (report_zh, "synthesis_report_zh.md"),
        (report_en, "synthesis_report_en.md"),
        (synthesis_dir / "synthesis_report_zh.html", "synthesis_report_zh.html"),
        (synthesis_dir / "synthesis_report_en.html", "synthesis_report_en.html"),
    ):
        if not path.exists() or not path.read_text(encoding="utf-8").strip():
            issues.append(
                issue(
                    "synthesis_report_missing",
                    phase="synthesis",
                    message=f"{label} missing or empty",
                    fix_hint="Write bilingual synthesis MD + HTML; run `ags.py analysis guidance --topic reports`",
                )
            )
        elif path.suffix.lower() == ".html":
            lower = path.read_text(encoding="utf-8").lower()
            if "<html" not in lower and "<!doctype" not in lower:
                issues.append(
                    issue(
                        "synthesis_report_html_invalid",
                        phase="synthesis",
                        message=f"{label} is not a complete HTML document",
                        fix_hint="Author synthesis HTML mirroring MD structure",
                    )
                )

    brief, brief_issues = _load_brief(brief_path)
    issues.extend(brief_issues)

    presentation_root = workspace / "presentation"
    if brief is not None:
        if scope_hypothesis_ids:
            missing_from_brief = sorted(
                set(scope_hypothesis_ids) - set(brief.scope_hypothesis_ids)
            )
            extra_in_brief = sorted(
                set(brief.scope_hypothesis_ids) - set(scope_hypothesis_ids)
            )
            if missing_from_brief or extra_in_brief:
                issues.append(
                    issue(
                        "synthesis_scope_mismatch",
                        phase="synthesis",
                        message=(
                            "synthesis_brief scope does not match harness scope: "
                            f"missing={missing_from_brief}, extra={extra_in_brief}"
                        ),
                        fix_hint="Align synthesis_brief.scope_hypothesis_ids with gate-status synthesis scope",
                    )
                )
        workspace_root = workspace.resolve()
        for rel in brief.source_artifacts:
            rel_path = Path(rel)
            if rel_path.is_absolute() or ".." in rel_path.parts:
                issues.append(
                    issue(
                        "source_artifact_unsafe",
                        phase="synthesis",
                        message=f"source_artifacts must stay inside the workspace: {rel}",
                        fix_hint="Use relative paths under presentation/ or synthesis/",
                    )
                )
                continue
            path = workspace / rel_path
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path
            if not resolved.is_relative_to(workspace_root):
                issues.append(
                    issue(
                        "source_artifact_unsafe",
                        phase="synthesis",
                        message=f"source_artifacts points outside the workspace: {rel}",
                        fix_hint="Use relative paths under presentation/ or synthesis/",
                    )
                )
                continue
            if not path.is_file():
                issues.append(
                    issue(
                        "source_artifact_missing",
                        phase="synthesis",
                        message=f"source_artifacts path not found: {rel}",
                        fix_hint="List real paths to presentation reports or analysis_summary.json",
                    )
                )
        for hid in brief.scope_hypothesis_ids:
            pres = presentation_root / f"hypothesis_{hid}"
            if (
                not (pres / "report_zh.md").exists()
                or not (pres / "report_zh.html").exists()
                or not (pres / "report_en.md").exists()
                or not (pres / "report_en.html").exists()
            ):
                issues.append(
                    issue(
                        "scope_hypothesis_no_report",
                        phase="synthesis",
                        message=f"Incomplete bilingual presentation outputs for hypothesis {hid}",
                        fix_hint="Complete validate-release for each scoped hypothesis first",
                    )
                )
            state = load_hypothesis_state(workspace, hid)
            if state.hypothesis_release != ReleaseStatus.ready:
                issues.append(
                    issue(
                        "scope_hypothesis_not_released",
                        phase="synthesis",
                        message=(
                            f"Hypothesis {hid} release is "
                            f"{state.hypothesis_release.value}, expected ready"
                        ),
                        fix_hint="Run validate-release for this hypothesis",
                    )
                )
            review_result = validate_report_review(workspace, hid, pres)
            issues.extend(review_result.issues)
            for required in (
                pres / "data" / "analysis_summary.json",
                pres / "data" / "evidence_index.json",
                hypothesis_report_review_path(workspace, hid),
            ):
                if not required.exists():
                    issues.append(
                        issue(
                            "scope_hypothesis_source_missing",
                            phase="synthesis",
                            message=f"Required source for hypothesis {hid} is missing: {required}",
                            fix_hint="Run build-report-context, record-report-review, and validate-release for each scoped hypothesis",
                        )
                    )

    charts_dir = synthesis_dir / "charts"
    if charts_dir.exists():
        chart_count = len(list(charts_dir.glob("chart_*.png"))) + len(
            list(charts_dir.glob("figure_*.png"))
        )
        if max_synthesis_charts > 0 and chart_count > max_synthesis_charts:
            issues.append(
                issue(
                    "synthesis_chart_cap",
                    phase="synthesis",
                    message=f"Synthesis charts {chart_count} > cap {max_synthesis_charts}",
                )
            )

    if scope_hypothesis_ids and brief is None:
        for hid in scope_hypothesis_ids:
            pres = presentation_root / f"hypothesis_{hid}"
            if not (pres / "report_zh.md").exists():
                issues.append(
                    issue(
                        "scope_hypothesis_no_report",
                        phase="synthesis",
                        message=f"hypothesis {hid} missing report_zh.md",
                    )
                )

    if issues:
        return blocked(
            issues, recommended_next_step="Fix synthesis_brief.json and reports"
        )
    return passed()
