from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_ROOT = REPO_ROOT / "extension/skills/agentsociety-paper-review"
SKILL_VERSION_ROOT = SKILL_ROOT


def test_paper_review_skill_bundle_is_complete() -> None:
    skill_text = (SKILL_VERSION_ROOT / "SKILL.md").read_text(encoding="utf-8")
    assert "name: agentsociety-paper-review" in skill_text
    assert "author-side internal mock review" in skill_text
    assert "Do not call `research-pipeline update-stage`" in skill_text

    required_references = {
        "ensemble-protocol.md",
        "meta-review-contract.md",
        "pdf-intake-contract.md",
        "review-contract.md",
        "reroute-guide.md",
        "venues/generic.md",
        "venues/iclr.md",
        "venues/neurips.md",
        "venues/icml.md",
        "venues/acl-arr.md",
        "venues/aaai.md",
    }
    for relative_path in required_references:
        assert (SKILL_VERSION_ROOT / "references" / relative_path).is_file()

    assert (SKILL_VERSION_ROOT / "scripts/prepare_pdf_review.py").is_file()


def test_paper_review_requires_three_isolated_reviewers_and_meta_review() -> None:
    skill_text = (SKILL_VERSION_ROOT / "SKILL.md").read_text(encoding="utf-8")
    ensemble_text = (SKILL_VERSION_ROOT / "references/ensemble-protocol.md").read_text(
        encoding="utf-8"
    )
    meta_text = (SKILL_VERSION_ROOT / "references/meta-review-contract.md").read_text(
        encoding="utf-8"
    )

    assert "exactly three isolated subagents" in skill_text
    assert "R1`, `R2`, and `R3` run concurrently" in ensemble_text
    assert "must not see one another's" in skill_text
    assert "separately spawned MetaReview" in skill_text
    assert "score_spread_steps" in ensemble_text
    assert "score_median" in meta_text
    assert "concern_agreement" in meta_text
    assert "per-dimension agreement table" in meta_text
    assert "robustness_status" in meta_text
    assert "adjudication_required" in meta_text
    assert (
        "Never create a normal final MetaReview from fewer than three valid reviews"
        in meta_text
    )


def test_paper_review_uses_one_frozen_pdf_intake_for_all_agents() -> None:
    skill_text = (SKILL_VERSION_ROOT / "SKILL.md").read_text(encoding="utf-8")
    pdf_text = (SKILL_VERSION_ROOT / "references/pdf-intake-contract.md").read_text(
        encoding="utf-8"
    )
    ensemble_text = (SKILL_VERSION_ROOT / "references/ensemble-protocol.md").read_text(
        encoding="utf-8"
    )

    assert "scripts/prepare_pdf_review.py" in skill_text
    assert "Do not let reviewer subagents independently extract" in skill_text
    assert "fail_closed_when_required" in (
        SKILL_VERSION_ROOT / "scripts/prepare_pdf_review.py"
    ).read_text(encoding="utf-8")
    assert "Text extraction alone is never sufficient" in pdf_text
    assert "the same report path, page text, and page renders" in pdf_text
    assert "recompute the intake report digest" in ensemble_text


def test_paper_review_reroutes_use_existing_pipeline_stage_names() -> None:
    reroute_text = (SKILL_VERSION_ROOT / "references/reroute-guide.md").read_text(
        encoding="utf-8"
    )
    skill_text = (SKILL_VERSION_ROOT / "SKILL.md").read_text(encoding="utf-8")

    expected_reroutes = {
        "literature_search",
        "hypothesis",
        "experiment_config",
        "run_experiment",
        "analysis",
        "generate_paper",
        "human_decision",
        "none",
    }
    for reroute in expected_reroutes:
        assert f"`{reroute}`" in skill_text
        assert f"`{reroute}`" in reroute_text


def test_paper_review_is_advisory_not_a_cli_or_progress_stage() -> None:
    pipeline_script = (
        REPO_ROOT
        / "extension/skills/agentsociety-research-pipeline/scripts/progress.py"
    ).read_text(encoding="utf-8")
    launcher_text = (REPO_ROOT / "extension/runtime/agentsociety/bin/ags.py").read_text(
        encoding="utf-8"
    )

    assert '"paper_review"' not in pipeline_script
    assert '"paper-review"' not in launcher_text
    assert '"paper_review"' not in launcher_text


def test_paper_review_is_routed_after_draft_generation() -> None:
    pipeline_text = (
        REPO_ROOT / "extension/skills/agentsociety-research-pipeline/SKILL.md"
    ).read_text(encoding="utf-8")
    workspace_text = (REPO_ROOT / "extension/src/workspaceManager.ts").read_text(
        encoding="utf-8"
    )

    assert "paper-toolkit" in pipeline_text
    assert "agentsociety-paper-review" in pipeline_text
    assert "advisory reroutes" in pipeline_text
    assert "agentsociety-paper-review" in workspace_text
    assert "three isolated reviewer subagents concurrently" in workspace_text
    assert "must not revise research artifacts" in workspace_text
