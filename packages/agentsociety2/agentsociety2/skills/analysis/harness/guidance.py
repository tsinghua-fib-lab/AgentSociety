from __future__ import annotations

from copy import deepcopy
from typing import Any

from agentsociety2.skills.analysis.harness.attestation import PHASE_RUBRIC_KEYS
from agentsociety2.skills.analysis.harness.operations import (
    operation_registry,
    workflow_operations_by_phase,
)

GUIDANCE_TOPICS = (
    "workflow",
    "paths",
    "attestation",
    "charts",
    "reports",
    "reflection",
    "optional-refs",
)
REPORT_SECTION_ORDER = ("overview", "data", "findings", "conclusions", "appendix")

CHART_SCAFFOLD = '''"""AgentSociety2 analysis chart scaffold.

Copy into presentation/hypothesis_{id}/charts/chart_NN_slug.py and adapt.
Every report-facing chart should trace to a FigureContract.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

OKABE_ITO = [
    "#E69F00",
    "#56B4E9",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
    "#000000",
]

SEMANTIC_COLORS = {
    "treatment": "#0072B2",
    "baseline": "#6B6B6B",
    "improvement": "#009E73",
    "decline": "#D55E00",
}


def mm_to_inches(mm: float) -> float:
    return mm / 25.4


def report_figsize(width_mm: float = 120.0, aspect: float = 0.62) -> tuple[float, float]:
    width = mm_to_inches(width_mm)
    return width, width * aspect


def apply_analysis_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans"],
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": 9,
            "axes.labelsize": 9,
            "axes.titlesize": 10,
            "xtick.labelsize": 8.5,
            "ytick.labelsize": 8.5,
            "legend.fontsize": 8.5,
            "axes.spines.right": False,
            "axes.spines.top": False,
            "axes.linewidth": 0.8,
            "axes.grid": False,
            "legend.frameon": False,
            "axes.prop_cycle": plt.cycler(color=OKABE_ITO),
            "figure.facecolor": "#FFFFFF",
            "axes.facecolor": "#FFFFFF",
            "savefig.facecolor": "#FFFFFF",
        }
    )


def save_chart_bundle(fig, stem: str, output_dir: str | Path = "charts") -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / f"{stem}.png"
    svg_path = output_dir / f"{stem}.svg"
    fig.savefig(png_path, dpi=220, bbox_inches="tight", facecolor="white")
    fig.savefig(svg_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return png_path, svg_path


def sample_frame(frame, n: int = 5000, random_state: int = 42):
    if len(frame) <= n:
        return frame
    return frame.sample(n=n, random_state=random_state)


def main() -> None:
    apply_analysis_style()
    # Replace this example data with a SQLite query loaded into a DataFrame.
    steps = [1, 2, 3, 4]
    treatment = [0.42, 0.47, 0.51, 0.55]
    baseline = [0.40, 0.41, 0.43, 0.44]

    fig, ax = plt.subplots(figsize=report_figsize())
    ax.plot(steps, treatment, label="Treatment", color=SEMANTIC_COLORS["treatment"])
    ax.plot(steps, baseline, label="Baseline", color=SEMANTIC_COLORS["baseline"])
    ax.set_xlabel("Simulation step")
    ax.set_ylabel("Mean outcome (AU)")
    ax.set_title("Treatment increases mean outcome over steps")
    ax.legend(loc="best")
    fig.tight_layout()
    save_chart_bundle(fig, "chart_01_treatment_trend", "charts")


if __name__ == "__main__":
    main()
'''


PAYLOAD_TEMPLATES: dict[str, dict[str, Any]] = {
    "analysis_plan": {
        "research_question": "Does treatment X increase metric Y by step 10?",
        "primary_metrics": ["Y", "treatment_flag"],
        "target_tables": ["agent_metrics", "run_summary"],
        "confirmatory_claims": [
            "Mean Y is higher under treatment than control after step 10"
        ],
        "exploratory_notes": "Optional subgroup or timing comparisons",
        "simulation_limitations": "Single seed; simulation output is not external validation",
        "eda_profile": "bundle",
        "eda_profiles": [
            "quick-stats",
            "ydata",
            "pygwalker",
            "datatable",
            "plotly-profile",
        ],
        "table_checks": [
            {"table": "agent_metrics", "min_rows": 10, "columns": ["step", "Y"]}
        ],
        "synthesis_scope_hypothesis_ids": ["1"],
    },
    "claim": {
        "claim_id": "c1",
        "statement": "Treatment arm shows higher mean Y after step 10",
        "mode": "confirmatory",
        "evidence": "agent_metrics: filter step>=10; compare mean(Y) by treatment_flag",
        "needs_chart": True,
        "approved": True,
    },
    "figure_contract": {
        "contract_id": "f1",
        "claim_id": "c1",
        "core_finding": "Treatment raises metric Y after step 10",
        "figure_scope": "single chart",
        "chart_role": "comparison",
        "evidence_source": "agent_metrics grouped by treatment_flag after step 10",
        "analysis_scope": "agents with non-null Y, steps >= 10",
        "figure_archetype": "single-panel grouped comparison",
        "visual_center": "Treatment mean is above control mean",
        "axes_grouping": "x=treatment_flag, y=mean Y, optional points for agent values",
        "legend_strategy": "English labels; direct labels preferred when only two groups",
        "reviewer_check": "Could missing early-step values or unequal group sizes explain the contrast?",
        "caption_requirements": [
            "State n per group",
            "Define error bars as SE, SD, CI, or none",
            "State simulation-only limitation",
        ],
        "presentation_mode": "static",
        "output_files": ["charts/chart_01_treatment_compare.png"],
    },
    "phase_attestation": {
        "phase": "explore",
        "status": "DONE",
        "key_findings": ["agent_metrics has enough rows for the planned comparison"],
        "artifacts_read": [],
        "artifacts_written": ["presentation/hypothesis_1/data/eda_quick_stats.md"],
        "blocking_reason": None,
        "recommended_next_step": None,
        "rubric": {
            "tables_inspected": ["agent_metrics"],
            "data_limitations": "No demographic table; early steps contain missing Y",
            "eda_takeaway": "Treatment rows have a heavier upper tail",
        },
    },
    "report_outline": {
        "hypothesis_id": "1",
        "sections": [
            {"id": section_id, "title": section_id.title()}
            for section_id in REPORT_SECTION_ORDER
        ],
        "figures": [
            {
                "asset": "chart_01_treatment_compare.png",
                "caption": "Mean Y by treatment after step 10",
                "finding_number": 1,
            }
        ],
    },
    "analysis_summary": {
        "summary": "Treatment raises mean Y post step 10; effect is modest.",
        "key_findings": ["Confirmatory claim c1 is supported with simulation caveats"],
        "limitations": "Single simulation run; not external validation",
        "evidence_index_path": "data/evidence_index.json",
    },
    "artifact_manifest": {
        "hypothesis_id": "1",
        "generated_at": "2026-01-01T00:00:00Z",
        "artifacts": [
            {
                "filename": "chart_01_treatment_compare.png",
                "type": "chart",
                "description": "Mean Y by treatment after step 10",
                "finding_number": 1,
                "included_in_report": True,
            }
        ],
    },
    "report_review": {
        "hypothesis_id": "1",
        "reviewer_role": "independent",
        "verdict": "PASS",
        "overall_score": 4,
        "dimensions": {
            "evidence_traceability": 4,
            "narrative_clarity": 4,
            "limitations_honesty": 4,
            "bilingual_parity": 4,
            "chart_integration": 4,
        },
        "blocking_issues": [],
        "revision_instructions": [],
        "reviewed_artifact_paths": [
            "presentation/hypothesis_1/report_zh.md",
            "presentation/hypothesis_1/report_en.md",
        ],
    },
    "synthesis_brief": {
        "synthesis_question": "What is consistent across hypotheses 1 and 2?",
        "scope_hypothesis_ids": ["1", "2"],
        "source_artifacts": [
            "presentation/hypothesis_1/data/analysis_summary.json",
            "presentation/hypothesis_2/data/analysis_summary.json",
        ],
        "comparison_mode": "cross_hypothesis",
    },
    "reflection_report": {
        "hypothesis_id": "1",
        "experiment_id": "1",
        "source": "hypothesis",
        "what_worked": [
            {
                "title": "Claim-first charting worked",
                "content": "Charts were easier to justify after claims were approved.",
                "evidence": ["presentation/hypothesis_1/data/evidence_index.json"],
                "confidence": "high",
            }
        ],
        "what_failed": [],
        "reusable_methods": [
            {
                "recipe_id": "claim_first_charting",
                "title": "Claim-first charting",
                "content": "Approve confirmatory claims before producing final charts.",
                "applies_when": ["simulation analysis", "bilingual report"],
                "recommended_steps": [
                    "Record approved claims",
                    "Write figure contracts",
                    "Validate charts before report assembly",
                ],
                "pitfalls": [
                    "Do not promote exploratory EDA to a claim without review"
                ],
                "confidence": "high",
            }
        ],
        "user_preferences_observed": [],
    },
    "user_feedback": {
        "hypothesis_id": "1",
        "experiment_id": "1",
        "rating": 5,
        "satisfied": True,
        "comments": "Please keep conclusions cautious.",
        "requested_changes": ["Add robustness caveat before paper drafting"],
        "preference_candidates": [],
        "lesson_candidates": [],
    },
}


def list_payload_templates() -> list[str]:
    return sorted(PAYLOAD_TEMPLATES)


def get_payload_template(name: str) -> dict[str, Any]:
    key = name.strip().replace("-", "_")
    if key not in PAYLOAD_TEMPLATES:
        raise ValueError(
            f"Unknown payload template {name!r}; available: {list_payload_templates()}"
        )
    return deepcopy(PAYLOAD_TEMPLATES[key])


def get_harness_guidance(topic: str = "workflow") -> dict[str, Any]:
    topic = (topic or "workflow").strip().lower()
    if topic not in GUIDANCE_TOPICS:
        raise ValueError(
            f"Unknown guidance topic {topic!r}; available: {sorted(GUIDANCE_TOPICS)}"
        )

    common = {
        "topic": topic,
        "available_topics": list(GUIDANCE_TOPICS),
        "payload_templates": list_payload_templates(),
    }
    if topic == "workflow":
        operations_by_phase = workflow_operations_by_phase()
        return {
            **common,
            "required_sequence": [
                f"{phase}:{operation_id}"
                for phase, operation_ids in operations_by_phase.items()
                for operation_id in operation_ids
            ],
            "operations_by_phase": operations_by_phase,
            "operation_contracts": {
                operation_id: spec.model_dump(mode="json")
                for operation_id, spec in operation_registry().items()
            },
            "policies": [
                "Structural PASS is necessary but not sufficient; attestation records LLM judgment.",
                "Do not advance after editing phase artifacts until attestation is refreshed.",
                "Analysis is complete only after validate-synthesis passes.",
                "User approval is required before a confirmatory claim is marked approved.",
            ],
        }
    if topic == "paths":
        return {
            **common,
            "single_hypothesis": {
                "presentation": "presentation/hypothesis_{id}/",
                "required_reports": [
                    "report_zh.md",
                    "report_en.md",
                    "report_zh.html",
                    "report_en.html",
                ],
                "data": [
                    "data/evidence_index.json",
                    "data/report_context.md",
                    "data/analysis_summary.json",
                ],
                "assets": "assets/ contains report embeds; reports must not embed charts/ directly",
                "charts": "charts/ contains generated chart and figure source outputs",
            },
            "harness_state": ".agentsociety/analysis/hypothesis_{id}/",
            "synthesis": "synthesis/",
            "forbidden_under_presentation": ["analysis/", "figures/", "eda/"],
        }
    if topic == "attestation":
        return {
            **common,
            "rubric_keys": PHASE_RUBRIC_KEYS,
            "status_values": ["DONE", "DONE_WITH_CONCERNS", "BLOCKED"],
            "fingerprint_policy": "Leave artifact_fingerprint empty for new attestations; the CLI fills it and detects stale artifacts later.",
            "template": get_payload_template("phase_attestation"),
        }
    if topic == "charts":
        return {
            **common,
            "contract_first": [
                "Record a FigureContract before generating a report-facing chart.",
                "One figure should defend one approved claim; keep exploratory visuals in data/EDA.",
                "Drop a chart if it needs a paragraph just to explain what the viewer should see.",
            ],
            "chart_selection": {
                "comparison": "grouped bar, dot+interval, or box/strip when raw spread matters",
                "trend": "line with CI band when repeated observations support uncertainty",
                "distribution": "box, violin, histogram, or KDE",
                "relationship": "sampled scatter with transparency",
                "composition": "stacked bar only for few parts; heatmap for matrices",
                "composite": "2-4 related panels for one finding, assembled with compose-figure",
            },
            "quality_rules": [
                "Use matplotlib Agg and save PNG; SVG companion is recommended.",
                "Set sans-serif fonts and svg.fonttype='none'.",
                "Use Okabe-Ito or semantic colors; never jet/rainbow.",
                "Axis labels must name metric and unit/scope where possible.",
                "Legend text is English-only; bilingual explanation belongs in captions/report prose.",
                "Every report figure needs a one-line caption with sample scope and uncertainty definition.",
                "Prefer direct labels over crowded legends; keep legends to six entries or fewer.",
                "Same condition should keep the same color across the report.",
            ],
            "validator": (
                "validate-chart --code blocks missing backend/style/save calls, "
                "unlabeled axes, generic titles, rainbow palettes, and non-English legends."
            ),
            "scaffold_command": "ags.py analysis chart-scaffold",
        }
    if topic == "reports":
        return {
            **common,
            "required_files": [
                "report_zh.md",
                "report_en.md",
                "report_zh.html",
                "report_en.html",
                "report_outline.json",
                "artifact_manifest.json",
                "data/analysis_summary.json",
                "data/evidence_index.json",
            ],
            "section_ids": list(REPORT_SECTION_ORDER),
            "rules": [
                "Run prepare-produce before drafting final reports.",
                "Every report figure needs a one-line caption directly below it.",
                "Chinese and English reports should embed the same asset set.",
                "HTML reports must be complete authored documents, not mechanical Markdown conversion.",
                "Use assets/ references in reports; sync-report-assets copies from charts/.",
            ],
        }
    if topic == "reflection":
        return {
            **common,
            "required_epilogue": [
                "record-feedback",
                "draft-reflection",
                "record-reflection",
                "review-reflection",
                "promote-reflection",
            ],
            "promotion_policy": [
                "Lessons and method recipes can be promoted after review.",
                "Preferences are promoted only with --include-preferences and explicit feedback evidence.",
                "Promoted memory is advisory and must not override user instructions or gates.",
            ],
        }
    return {
        **common,
        "core_in_harness": [
            "workflow gates",
            "payload schemas and templates",
            "path rules",
            "report release checks",
            "experience memory governance",
        ],
        "optional_extension_refs": [
            "advanced chart recipes beyond the built-in scaffold",
            "HTML report shell examples",
            "subagent prompts",
            "interactive visualization support",
            "frontend design support",
            "external literature or dataset integrations",
        ],
    }


def get_chart_scaffold() -> str:
    return CHART_SCAFFOLD
