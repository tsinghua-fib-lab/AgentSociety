from __future__ import annotations

import re
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from agentsociety2.skills.analysis.harness.json_io import load_model_from_file
from agentsociety2.skills.analysis.harness.layout import list_presentation_layout_issues
from agentsociety2.skills.analysis.harness.models import ValidationResult
from agentsociety2.skills.analysis.harness.report_assets import (
    charts_path_refs_in_reports,
    data_path_refs_in_reports,
)
from agentsociety2.skills.analysis.harness.schemas import (
    REPORT_SECTION_IDS,
    AnalysisSummary,
    ArtifactManifest,
    ReportOutline,
)
from agentsociety2.skills.analysis.harness.validators._helpers import (
    blocked,
    issue,
    passed,
)

ASSET_REF_RE = re.compile(r"!\[[^\]]*\]\((?:\./)?assets/([^)]+)\)")
HTML_IMG_SRC_RE = re.compile(
    r"""<img[^>]*\ssrc=["'](?:\./)?assets/([^"']+)["']""",
    re.IGNORECASE,
)

ModelT = TypeVar("ModelT", bound=BaseModel)


def _load_json_model(
    path: Path, model: type[ModelT], label: str
) -> tuple[ModelT | None, list]:
    if not path.exists():
        return None, [
            issue(
                f"{label}_missing",
                phase="produce",
                message=f"{path.name} not found",
                fix_hint=(
                    f"Write {path.name}; run `ags.py analysis payload-template "
                    f"--name {label}` for the SDK template"
                ),
            )
        ]
    try:
        return load_model_from_file(path, model), []
    except ValueError as exc:
        return None, [
            issue(
                f"{label}_invalid",
                phase="produce",
                message=str(exc),
                fix_hint=(
                    f"Fix JSON for {path.name}; run `ags.py analysis payload-template "
                    f"--name {label}` for the SDK template"
                ),
            )
        ]


def validate_release(presentation_dir: Path) -> ValidationResult:
    issues: list = []
    for raw in charts_path_refs_in_reports(presentation_dir):
        issues.append(
            issue(
                "report_embeds_charts_dir",
                phase="produce",
                message=f"Report must not reference charts/ path: {raw}",
                fix_hint="Rewrite embeds to assets/ and run sync-report-assets",
            )
        )
    for msg in list_presentation_layout_issues(presentation_dir):
        issues.append(
            issue(
                "presentation_layout_invalid",
                phase="produce",
                message=msg,
                fix_hint="Run `ags.py analysis guidance --topic paths` for output path rules",
            )
        )
    report_zh = presentation_dir / "report_zh.md"
    report_en = presentation_dir / "report_en.md"
    manifest_path = presentation_dir / "artifact_manifest.json"
    outline_path = presentation_dir / "report_outline.json"
    assets_dir = presentation_dir / "assets"
    evidence_index_path = presentation_dir / "data" / "evidence_index.json"
    if not evidence_index_path.exists():
        issues.append(
            issue(
                "evidence_index_missing",
                phase="produce",
                message="data/evidence_index.json not found",
                fix_hint="Run `ags.py analysis build-report-context --workspace . --hypothesis-id ID` before drafting the report",
            )
        )

    summary_path = presentation_dir / "data" / "analysis_summary.json"

    for path, label in (
        (report_zh, "report_zh.md"),
        (report_en, "report_en.md"),
        (presentation_dir / "report_zh.html", "report_zh.html"),
        (presentation_dir / "report_en.html", "report_en.html"),
    ):
        if not path.exists() or not path.read_text(encoding="utf-8").strip():
            issues.append(
                issue(
                    "report_missing",
                    phase="produce",
                    message=f"{label} missing or empty",
                    fix_hint="Write bilingual MD + HTML reports; run `ags.py analysis guidance --topic reports`",
                )
            )
        elif path.suffix.lower() == ".html":
            lower = path.read_text(encoding="utf-8").lower()
            if "<html" not in lower and "<!doctype" not in lower:
                issues.append(
                    issue(
                        "report_html_invalid",
                        phase="produce",
                        message=f"{label} is not a complete HTML document",
                        fix_hint="Author a complete HTML document; run `ags.py analysis guidance --topic reports`",
                    )
                )

    manifest, manifest_issues = _load_json_model(
        manifest_path, ArtifactManifest, "artifact_manifest"
    )
    issues.extend(manifest_issues)

    outline, outline_issues = _load_json_model(
        outline_path, ReportOutline, "report_outline"
    )
    issues.extend(outline_issues)

    _summary, summary_issues = _load_json_model(
        summary_path, AnalysisSummary, "analysis_summary"
    )
    issues.extend(summary_issues)

    if outline is not None:
        section_ids = {s.id.strip().lower() for s in outline.sections if s.id}
        if len(section_ids) < 3:
            issues.append(
                issue(
                    "report_outline_sections",
                    phase="produce",
                    message="report_outline.json needs at least 3 section ids",
                    fix_hint=f"Use section ids such as: {sorted(REPORT_SECTION_IDS)}",
                )
            )

    disk_files: set[str] = set()
    if assets_dir.exists():
        disk_files = {p.name for p in assets_dir.iterdir() if p.is_file()}

    manifest_files: set[str] = set()
    if manifest is not None:
        manifest_files = {a.filename for a in manifest.artifacts if a.filename}

    refs: set[str] = set()
    for report_path in (report_zh, report_en):
        if report_path.exists():
            text = report_path.read_text(encoding="utf-8")
            refs |= set(ASSET_REF_RE.findall(text))
    for html_path in (
        presentation_dir / "report_zh.html",
        presentation_dir / "report_en.html",
    ):
        if html_path.exists():
            refs |= set(HTML_IMG_SRC_RE.findall(html_path.read_text(encoding="utf-8")))

    if outline is not None:
        for fig in outline.figures:
            name = Path(fig.asset).name
            if not fig.caption.strip():
                issues.append(
                    issue(
                        "outline_figure_caption_empty",
                        phase="produce",
                        message=f"Outline figure {name} has empty caption",
                        fix_hint="Fill caption in report_outline.json (one line per figure)",
                    )
                )
            refs.add(name)

    for ref in refs:
        if ref not in disk_files:
            issues.append(
                issue(
                    "asset_file_missing",
                    phase="produce",
                    message=f"Referenced assets/{ref} not on disk",
                    fix_hint="Run sync-report-assets or collect-assets",
                )
            )
        if manifest is not None and ref not in manifest_files:
            issues.append(
                issue(
                    "manifest_asset_mismatch",
                    phase="produce",
                    message=f"{ref} missing from artifact_manifest.json",
                    fix_hint="Sync manifest with report_outline figures",
                )
            )

    if manifest is not None:
        for name in sorted(manifest_files - disk_files):
            issues.append(
                issue(
                    "manifest_asset_not_on_disk",
                    phase="produce",
                    message=f"artifact_manifest.json lists missing asset: {name}",
                    fix_hint="Remove stale manifest entries or regenerate the asset",
                )
            )

    for ref in data_path_refs_in_reports(presentation_dir):
        rel = Path(ref)
        if rel.is_absolute() or ".." in rel.parts:
            issues.append(
                issue(
                    "data_ref_unsafe",
                    phase="produce",
                    message=f"Report references unsafe data path: {ref}",
                    fix_hint="Use data/... paths inside the presentation directory",
                )
            )
            continue
        if not (presentation_dir / rel).is_file():
            issues.append(
                issue(
                    "data_ref_missing",
                    phase="produce",
                    message=f"Report references missing file: {ref}",
                    fix_hint="Regenerate EDA/evidence artifacts or fix the link",
                )
            )

    if issues:
        return blocked(
            issues,
            recommended_next_step="Fix structured produce artifacts and re-run validate-release",
        )
    return passed()
