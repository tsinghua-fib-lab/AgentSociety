from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from agentsociety2.skills.analysis.harness import state as harness_state
from agentsociety2.skills.analysis.harness.layout import hypothesis_presentation_dir
from agentsociety2.skills.analysis.harness.models import AnalysisPhase
from agentsociety2.skills.analysis.harness.schemas import (
    EvidenceIndex,
    EvidenceKind,
    EvidenceSource,
)

_EXCERPT_MAX = 1200
_TEXT_SUFFIXES = {".md", ".txt", ".json", ".sql", ".csv"}
_GENERATED_CONTEXT_FILES = {
    "evidence_index.json",
    "report_context.md",
    "interactive_eda_section.html",
}


def _rel(workspace: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(workspace.resolve()))
    except ValueError:
        return str(path)


def _infer_kind(path: Path) -> EvidenceKind:
    name = path.name.lower()
    if name.startswith("eda_") or "quick_stats" in name:
        return "eda"
    if name.endswith(".sql"):
        return "sql"
    if name.startswith("chart_") and path.suffix.lower() in {".png", ".svg"}:
        return "chart"
    if name.startswith("figure_") and path.suffix.lower() in {".png", ".svg"}:
        return "figure"
    if name == "analysis_summary.json":
        return "summary"
    return "other"


def _default_section(kind: EvidenceKind, phase: str) -> str:
    if kind == "eda" or phase == AnalysisPhase.explore.value:
        return "data"
    if kind in ("chart", "figure", "contract") or phase == AnalysisPhase.refine.value:
        return "findings"
    if phase == AnalysisPhase.claims.value:
        return "findings"
    if kind == "summary":
        return "conclusions"
    return "appendix"


def _read_excerpt(path: Path) -> str:
    if not path.is_file():
        return ""
    if path.suffix.lower() not in _TEXT_SUFFIXES and path.suffix.lower() != ".html":
        return f"(binary file {path.name})"
    try:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""
    if len(text) <= _EXCERPT_MAX:
        return text
    return text[:_EXCERPT_MAX] + "\n…(truncated)"


def _add_source(
    sources: list[EvidenceSource],
    workspace: Path,
    path: Path,
    *,
    phase: str = "",
    kind: EvidenceKind | None = None,
    report_section: str = "",
    label: str = "",
) -> None:
    if not path.exists():
        return
    rel = _rel(workspace, path)
    if any(s.path == rel for s in sources):
        return
    inferred = kind or _infer_kind(path)
    section = report_section or _default_section(inferred, phase)
    sources.append(
        EvidenceSource(
            path=rel,
            kind=inferred,
            phase=phase,
            report_section=section,
            label=label or path.name,
            excerpt=_read_excerpt(path),
        )
    )


def build_evidence_index(workspace: Path, hypothesis_id: str) -> EvidenceIndex:
    workspace = workspace.resolve()
    pres = hypothesis_presentation_dir(workspace, hypothesis_id)
    st = harness_state.load_hypothesis_state(workspace, hypothesis_id)
    claims_doc = harness_state.load_claims(workspace, hypothesis_id)
    sources: list[EvidenceSource] = []

    for claim in claims_doc.claims:
        sources.append(
            EvidenceSource(
                path=f".agentsociety/analysis/hypothesis_{hypothesis_id}/claims.json",
                kind="claim",
                phase=AnalysisPhase.claims.value,
                report_section="findings",
                label=f"claim:{claim.claim_id}",
                excerpt=f"{claim.statement} | evidence: {claim.evidence}",
            )
        )

    for phase, paths in st.phase_artifacts.items():
        for raw in paths:
            p = workspace / raw if not Path(raw).is_absolute() else Path(raw)
            _add_source(sources, workspace, p, phase=phase)

    data_dir = pres / "data"
    if data_dir.is_dir():
        for p in sorted(data_dir.rglob("*")):
            if p.is_file() and p.name not in _GENERATED_CONTEXT_FILES:
                _add_source(sources, workspace, p, phase=AnalysisPhase.explore.value)

    charts_dir = pres / "charts"
    if charts_dir.is_dir():
        for p in sorted(charts_dir.glob("chart_*.png")) + sorted(
            charts_dir.glob("figure_*.png")
        ):
            _add_source(
                sources,
                workspace,
                p,
                phase=AnalysisPhase.refine.value,
                kind="chart" if p.name.startswith("chart_") else "figure",
            )

    for fc in st.figure_contracts:
        sources.append(
            EvidenceSource(
                path=".agentsociety/analysis/"
                f"hypothesis_{hypothesis_id}/state.yaml#figure_contracts",
                kind="contract",
                phase=AnalysisPhase.refine.value,
                report_section="findings",
                label=f"contract:{fc.contract_id}",
                excerpt=f"{fc.core_finding} -> {', '.join(fc.output_files)}",
            )
        )
        for out in fc.output_files:
            out_path = pres / out if not Path(out).is_absolute() else Path(out)
            if not out_path.is_file():
                out_path = charts_dir / Path(out).name
            _add_source(
                sources,
                workspace,
                out_path,
                phase=AnalysisPhase.refine.value,
                kind="chart",
            )

    section_map: dict[str, list[str]] = {
        "overview": [],
        "data": [],
        "findings": [],
        "conclusions": [],
        "appendix": [],
    }
    for src in sources:
        sec = src.report_section if src.report_section in section_map else "appendix"
        section_map[sec].append(src.path)

    return EvidenceIndex(
        hypothesis_id=hypothesis_id,
        generated_at=datetime.now(UTC).isoformat(),
        sources=sources,
        section_map=section_map,
    )


def render_report_context_md(index: EvidenceIndex) -> str:
    lines = [
        "# Report context (auto-generated)",
        "",
        (
            "Use this digest when drafting `report_zh.md` / `report_en.md` and "
            "`report_zh.html` / `report_en.html`. "
            "Synthesize tool outputs into prose — do not paste raw EDA wholesale."
        ),
        "",
    ]
    for section_id in ("overview", "data", "findings", "conclusions", "appendix"):
        paths = index.section_map.get(section_id) or []
        if not paths:
            continue
        lines.append(f"## Section: {section_id}")
        lines.append("")
        for src in index.sources:
            if src.path not in paths:
                continue
            lines.append(f"### {src.label} (`{src.kind}`, phase={src.phase or '—'})")
            lines.append(f"- path: `{src.path}`")
            if src.excerpt:
                lines.append("")
                lines.append(src.excerpt)
            lines.append("")
    lines.append("## Embed checklist")
    lines.append("")
    lines.append(
        "- **data**: After `run-eda --type bundle`, run `embed-interactive-eda` (or `sync-report-assets`) to inject multi-tab interactive EDA into `report_*.html`; keep `<!-- EDA_INTERACTIVE_BEGIN -->` … `<!-- EDA_INTERACTIVE_END -->` in the HTML shell"
    )
    lines.append(
        "- **findings**: `assets/` charts only (run `collect-assets`); caption under each figure"
    )
    lines.append(
        "- **appendix**: artifact table + EDA/tool paths; HTML uses `report-shell.reference.html`"
    )
    lines.append(
        "- Run `ags.py analysis guidance --topic reports` for required report files and embed rules"
    )
    lines.append("")
    return "\n".join(lines)


def write_report_bundle(workspace: Path, hypothesis_id: str) -> dict:
    workspace = workspace.resolve()
    pres = hypothesis_presentation_dir(workspace, hypothesis_id)
    pres.mkdir(parents=True, exist_ok=True)
    (pres / "data").mkdir(parents=True, exist_ok=True)

    index = build_evidence_index(workspace, hypothesis_id)
    index_path = pres / "data" / "evidence_index.json"
    index_path.write_text(
        index.model_dump_json(indent=2),
        encoding="utf-8",
    )
    context_path = pres / "data" / "report_context.md"
    context_path.write_text(
        render_report_context_md(index),
        encoding="utf-8",
    )

    summary_path = pres / "data" / "analysis_summary.json"
    if summary_path.exists():
        from agentsociety2.skills.analysis.harness.json_io import load_model_from_file
        from agentsociety2.skills.analysis.harness.schemas import AnalysisSummary

        summary = load_model_from_file(summary_path, AnalysisSummary)
        summary.evidence_index_path = _rel(workspace, index_path)
        summary_path.write_text(
            summary.model_dump_json(indent=2),
            encoding="utf-8",
        )

    return {
        "evidence_index": str(index_path),
        "report_context": str(context_path),
        "source_count": len(index.sources),
        "section_counts": {k: len(v) for k, v in index.section_map.items()},
    }


def cmd_embed_interactive_eda(workspace: Path, hypothesis_id: str) -> dict:
    from agentsociety2.skills.analysis.harness.report_eda_embed import (
        embed_interactive_eda_in_reports,
    )

    pres = hypothesis_presentation_dir(workspace, hypothesis_id)
    return embed_interactive_eda_in_reports(pres)
