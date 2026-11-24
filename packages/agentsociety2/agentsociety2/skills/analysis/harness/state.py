from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from agentsociety2.skills.analysis.harness.json_io import load_model_from_file
from agentsociety2.skills.analysis.harness.models import (
    AnalysisPlan,
    ClaimsDocument,
    HypothesisAnalysisState,
    MemoryIndex,
    ReflectionReport,
    ReflectionReview,
    SynthesisAnalysisState,
    UserFeedback,
)
from agentsociety2.skills.analysis.harness.paths import (
    hypothesis_claims_path,
    hypothesis_feedback_path,
    hypothesis_plan_path,
    hypothesis_reflection_path,
    hypothesis_reflection_review_path,
    hypothesis_state_path,
    memory_index_path,
    synthesis_feedback_path,
    synthesis_reflection_path,
    synthesis_reflection_review_path,
    synthesis_state_path,
)


def _load_yaml(path: Path, model: type) -> Any:
    if not path.exists():
        return model()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return model.model_validate(raw)


def _save_yaml(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = obj.model_dump(mode="json")
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def load_hypothesis_state(
    workspace: Path, hypothesis_id: str
) -> HypothesisAnalysisState:
    state = _load_yaml(
        hypothesis_state_path(workspace, hypothesis_id), HypothesisAnalysisState
    )
    if not state.hypothesis_id:
        state.hypothesis_id = hypothesis_id
    return state


def save_hypothesis_state(
    workspace: Path,
    hypothesis_id: str,
    state: HypothesisAnalysisState,
) -> None:
    state.updated_at = datetime.now(UTC)
    _save_yaml(hypothesis_state_path(workspace, hypothesis_id), state)


def load_plan(workspace: Path, hypothesis_id: str) -> AnalysisPlan:
    return _load_yaml(hypothesis_plan_path(workspace, hypothesis_id), AnalysisPlan)


def save_plan(workspace: Path, hypothesis_id: str, plan: AnalysisPlan) -> None:
    _save_yaml(hypothesis_plan_path(workspace, hypothesis_id), plan)


def load_claims(workspace: Path, hypothesis_id: str) -> ClaimsDocument:
    path = hypothesis_claims_path(workspace, hypothesis_id)
    if not path.exists():
        return ClaimsDocument(hypothesis_id=hypothesis_id, claims=[])
    doc = load_model_from_file(path, ClaimsDocument)
    if not doc.hypothesis_id:
        doc.hypothesis_id = hypothesis_id
    return doc


def save_claims(workspace: Path, hypothesis_id: str, doc: ClaimsDocument) -> None:
    import json

    path = hypothesis_claims_path(workspace, hypothesis_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc.hypothesis_id = hypothesis_id
    path.write_text(
        json.dumps(doc.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def parse_payload_dict(payload: str) -> dict[str, Any]:
    from agentsociety2.skills.analysis.harness.json_io import load_dict_payload

    return load_dict_payload(payload)


def load_synthesis_state(workspace: Path) -> SynthesisAnalysisState:
    return _load_yaml(synthesis_state_path(workspace), SynthesisAnalysisState)


def save_synthesis_state(workspace: Path, state: SynthesisAnalysisState) -> None:
    state.updated_at = datetime.now(UTC)
    _save_yaml(synthesis_state_path(workspace), state)


def resolve_synthesis_scope(
    workspace: Path, state: SynthesisAnalysisState | None = None
) -> list[str]:
    """Return the configured synthesis scope, inferring it from presentation/.

    ``write-plan`` stores scope on ``AnalysisPlan``; the synthesis state starts
    empty. Preflight must use the same inference as ``validate-synthesis`` or it
    blocks every synthesis command before the handler can populate scope.

    :param workspace: Workspace root.
    :param state: Optional already-loaded synthesis state.
    :returns: Sorted hypothesis ids.
    """
    state = state or load_synthesis_state(workspace)
    if state.synthesis_scope_hypothesis_ids:
        return list(state.synthesis_scope_hypothesis_ids)
    pres_root = workspace / "presentation"
    if not pres_root.is_dir():
        return []
    return sorted(
        child.name.replace("hypothesis_", "", 1)
        for child in pres_root.iterdir()
        if child.is_dir() and child.name.startswith("hypothesis_")
    )


def load_reflection(
    workspace: Path, hypothesis_id: str | None = None
) -> ReflectionReport:
    path = (
        synthesis_reflection_path(workspace)
        if hypothesis_id is None
        else hypothesis_reflection_path(workspace, hypothesis_id)
    )
    if not path.exists():
        return ReflectionReport(
            source="synthesis" if hypothesis_id is None else "hypothesis",
            hypothesis_id=hypothesis_id or "",
        )
    return load_model_from_file(path, ReflectionReport)


def save_reflection(
    workspace: Path,
    reflection: ReflectionReport,
    hypothesis_id: str | None = None,
) -> Path:
    path = (
        synthesis_reflection_path(workspace)
        if hypothesis_id is None
        else hypothesis_reflection_path(workspace, hypothesis_id)
    )
    from agentsociety2.skills.analysis.harness.json_io import save_model_to_file

    save_model_to_file(path, reflection)
    return path


def load_feedback(workspace: Path, hypothesis_id: str | None = None) -> UserFeedback:
    path = (
        synthesis_feedback_path(workspace)
        if hypothesis_id is None
        else hypothesis_feedback_path(workspace, hypothesis_id)
    )
    if not path.exists():
        return UserFeedback(
            hypothesis_id=hypothesis_id or "",
        )
    return load_model_from_file(path, UserFeedback)


def save_feedback(
    workspace: Path,
    feedback: UserFeedback,
    hypothesis_id: str | None = None,
) -> Path:
    path = (
        synthesis_feedback_path(workspace)
        if hypothesis_id is None
        else hypothesis_feedback_path(workspace, hypothesis_id)
    )
    from agentsociety2.skills.analysis.harness.json_io import save_model_to_file

    save_model_to_file(path, feedback)
    return path


def load_reflection_review(
    workspace: Path, hypothesis_id: str | None = None
) -> ReflectionReview:
    path = (
        synthesis_reflection_review_path(workspace)
        if hypothesis_id is None
        else hypothesis_reflection_review_path(workspace, hypothesis_id)
    )
    if not path.exists():
        return ReflectionReview()
    return load_model_from_file(path, ReflectionReview)


def save_reflection_review(
    workspace: Path,
    review: ReflectionReview,
    hypothesis_id: str | None = None,
) -> Path:
    path = (
        synthesis_reflection_review_path(workspace)
        if hypothesis_id is None
        else hypothesis_reflection_review_path(workspace, hypothesis_id)
    )
    from agentsociety2.skills.analysis.harness.json_io import save_model_to_file

    save_model_to_file(path, review)
    return path


def load_memory_index(workspace: Path) -> MemoryIndex:
    return _load_yaml(memory_index_path(workspace), MemoryIndex)


def save_memory_index(workspace: Path, index: MemoryIndex) -> None:
    index.updated_at = datetime.now(UTC)
    _save_yaml(memory_index_path(workspace), index)


def merge_plan_payload(plan: AnalysisPlan, payload: dict[str, Any]) -> AnalysisPlan:
    merged = plan.model_dump()
    merged.update({k: v for k, v in payload.items() if v is not None})
    return AnalysisPlan.model_validate(merged)
