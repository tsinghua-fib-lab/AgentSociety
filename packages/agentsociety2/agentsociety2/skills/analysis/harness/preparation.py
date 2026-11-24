from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentsociety2.skills.analysis.chart_export import (
    BRAND_ICON_NAME,
    EDA_HUB_ENTRIES,
)
from agentsociety2.skills.analysis.harness import state as harness_state
from agentsociety2.skills.analysis.harness.json_io import (
    atomic_write_json,
    load_model_from_file,
)
from agentsociety2.skills.analysis.harness.layout import hypothesis_presentation_dir
from agentsociety2.skills.analysis.harness.paths import (
    hypothesis_prepare_manifest_path,
)
from agentsociety2.skills.analysis.harness.report_assets import referenced_asset_names
from agentsociety2.skills.analysis.harness.report_eda_embed import (
    EDA_INTERACTIVE_BEGIN,
    EDA_INTERACTIVE_END,
)

PREPARE_PRODUCE_SCHEMA_VERSION = 1
PREPARE_PRODUCE_STEP_IDS = (
    "report_context",
    "report_assets",
    "interactive_eda",
)
_GENERATED_DATA_FILES = {
    "evidence_index.json",
    "report_context.md",
    "interactive_eda_section.html",
}
_REPORT_HTML_FILES = ("report_zh.html", "report_en.html")


class PreparationStepRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_fingerprint: str
    output_fingerprints: dict[str, str] = Field(default_factory=dict)
    completed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PreparationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = PREPARE_PRODUCE_SCHEMA_VERSION
    operation: Literal["prepare-produce"] = "prepare-produce"
    hypothesis_id: str
    experiment_id: str
    steps: dict[str, PreparationStepRecord] = Field(default_factory=dict)
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class PreparationStepPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    step_id: str
    action: Literal["RUN", "SKIP"]
    reason: str
    input_fingerprint: str
    recorded_outputs: tuple[str, ...] = Field(default_factory=tuple)


def load_prepare_produce_manifest(
    workspace: Path,
    hypothesis_id: str,
    experiment_id: str,
) -> PreparationManifest:
    path = hypothesis_prepare_manifest_path(workspace, hypothesis_id)
    if not path.is_file():
        return PreparationManifest(
            hypothesis_id=hypothesis_id,
            experiment_id=experiment_id,
        )
    return load_model_from_file(path, PreparationManifest)


def save_prepare_produce_manifest(
    workspace: Path,
    hypothesis_id: str,
    manifest: PreparationManifest,
) -> Path:
    path = hypothesis_prepare_manifest_path(workspace, hypothesis_id)
    manifest.updated_at = datetime.now(UTC)
    atomic_write_json(path, manifest.model_dump(mode="json"))
    return path


def _path_label(workspace: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(workspace.resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _update_path_digest(digest: Any, workspace: Path, path: Path) -> None:
    label = _path_label(workspace, path)
    digest.update(label.encode("utf-8", errors="replace"))
    if not path.exists():
        digest.update(b"\0MISSING")
        return
    if path.is_file():
        digest.update(b"\0FILE")
        digest.update(path.read_bytes())
        return
    if not path.is_dir():
        digest.update(b"\0OTHER")
        return
    digest.update(b"\0DIR")
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        _update_path_digest(digest, workspace, child)


def _fingerprint(
    workspace: Path,
    *,
    payload: Any,
    paths: list[Path],
) -> str:
    digest = hashlib.sha256()
    digest.update(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8", errors="replace")
    )
    unique_paths = {path.resolve(): path for path in paths}
    for path in sorted(
        unique_paths.values(), key=lambda item: _path_label(workspace, item)
    ):
        _update_path_digest(digest, workspace, path)
    return digest.hexdigest()


def _context_sources(
    workspace: Path,
    hypothesis_id: str,
) -> tuple[dict[str, Any], list[Path]]:
    pres = hypothesis_presentation_dir(workspace, hypothesis_id)
    state = harness_state.load_hypothesis_state(workspace, hypothesis_id)
    claims = harness_state.load_claims(workspace, hypothesis_id)
    payload = {
        "phase_artifacts": state.phase_artifacts,
        "figure_contracts": [
            contract.model_dump(mode="json") for contract in state.figure_contracts
        ],
        "claims": claims.model_dump(mode="json"),
    }
    paths: list[Path] = []
    for artifact_paths in state.phase_artifacts.values():
        for raw_path in artifact_paths:
            path = Path(raw_path)
            resolved_path = path if path.is_absolute() else workspace / path
            if resolved_path.name not in _GENERATED_DATA_FILES:
                paths.append(resolved_path)
    data_dir = pres / "data"
    if data_dir.is_dir():
        paths.extend(
            path
            for path in data_dir.rglob("*")
            if path.is_file() and path.name not in _GENERATED_DATA_FILES
        )
    charts_dir = pres / "charts"
    if charts_dir.is_dir():
        paths.extend(charts_dir.glob("chart_*.png"))
        paths.extend(charts_dir.glob("figure_*.png"))
    return payload, paths


def _asset_sources(
    workspace: Path,
    hypothesis_id: str,
) -> tuple[dict[str, Any], list[Path]]:
    pres = hypothesis_presentation_dir(workspace, hypothesis_id)
    referenced = sorted(referenced_asset_names(pres))
    paths: list[Path] = []
    for name in referenced:
        chart_path = pres / "charts" / name
        asset_path = pres / "assets" / name
        paths.append(chart_path if chart_path.is_file() else asset_path)
    return {"referenced_assets": referenced}, paths


def _canonical_report_html(text: str) -> str:
    marker_pattern = re.compile(
        re.escape(EDA_INTERACTIVE_BEGIN) + r".*?" + re.escape(EDA_INTERACTIVE_END),
        re.DOTALL,
    )
    canonical = marker_pattern.sub("", text, count=1)
    return re.sub(r"\n[ \t]*\n+", "\n", canonical)


def _interactive_eda_sources(
    workspace: Path,
    hypothesis_id: str,
) -> tuple[dict[str, Any], list[Path]]:
    pres = hypothesis_presentation_dir(workspace, hypothesis_id)
    reports: dict[str, str | None] = {}
    for name in _REPORT_HTML_FILES:
        path = pres / name
        reports[name] = (
            _canonical_report_html(path.read_text(encoding="utf-8"))
            if path.is_file()
            else None
        )
    eda_names = {"eda_hub.html", *(entry["file"] for entry in EDA_HUB_ENTRIES)}
    paths = [pres / "data" / name for name in sorted(eda_names)]
    return {"reports": reports}, paths


def prepare_step_input_fingerprint(
    step_id: str,
    workspace: Path,
    hypothesis_id: str,
    experiment_id: str,
) -> str:
    workspace = workspace.resolve()
    if step_id == "report_context":
        payload, paths = _context_sources(workspace, hypothesis_id)
    elif step_id == "report_assets":
        payload, paths = _asset_sources(workspace, hypothesis_id)
    elif step_id == "interactive_eda":
        payload, paths = _interactive_eda_sources(workspace, hypothesis_id)
    else:
        raise KeyError(f"unknown prepare-produce step: {step_id}")
    return _fingerprint(
        workspace,
        payload={
            "schema_version": PREPARE_PRODUCE_SCHEMA_VERSION,
            "step_id": step_id,
            "hypothesis_id": hypothesis_id,
            "experiment_id": experiment_id,
            "input": payload,
        },
        paths=paths,
    )


def preparation_step_output_paths(
    step_id: str,
    workspace: Path,
    hypothesis_id: str,
) -> list[Path]:
    pres = hypothesis_presentation_dir(workspace, hypothesis_id)
    if step_id == "report_context":
        outputs = [
            pres / "data" / "evidence_index.json",
            pres / "data" / "report_context.md",
        ]
        summary = pres / "data" / "analysis_summary.json"
        if summary.is_file():
            outputs.append(summary)
        return outputs
    if step_id == "report_assets":
        outputs = [pres / "assets" / BRAND_ICON_NAME]
        outputs.extend(
            pres / "assets" / name for name in sorted(referenced_asset_names(pres))
        )
        return [path for path in outputs if path.is_file()]
    if step_id == "interactive_eda":
        outputs = [pres / "data" / "interactive_eda_section.html"]
        outputs.extend(pres / name for name in _REPORT_HTML_FILES)
        return [path for path in outputs if path.is_file()]
    raise KeyError(f"unknown prepare-produce step: {step_id}")


def collect_output_fingerprints(
    workspace: Path,
    paths: list[Path],
) -> dict[str, str]:
    fingerprints: dict[str, str] = {}
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"prepare-produce output missing: {path}")
        fingerprints[_path_label(workspace, path)] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return fingerprints


def _recorded_outputs_status(
    workspace: Path,
    outputs: dict[str, str],
) -> tuple[bool, str]:
    if not outputs:
        return False, "no_recorded_outputs"
    for raw_path, expected in sorted(outputs.items()):
        path = Path(raw_path)
        if not path.is_absolute():
            path = workspace / path
        if not path.is_file():
            return False, f"output_missing:{raw_path}"
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            return False, f"output_changed:{raw_path}"
    return True, "unchanged"


def build_prepare_produce_plan(
    workspace: Path,
    hypothesis_id: str,
    experiment_id: str,
) -> tuple[PreparationManifest, list[PreparationStepPlan]]:
    manifest = load_prepare_produce_manifest(
        workspace,
        hypothesis_id,
        experiment_id,
    )
    compatible = (
        manifest.schema_version == PREPARE_PRODUCE_SCHEMA_VERSION
        and manifest.operation == "prepare-produce"
        and manifest.hypothesis_id == hypothesis_id
        and manifest.experiment_id == experiment_id
    )
    plan: list[PreparationStepPlan] = []
    for step_id in PREPARE_PRODUCE_STEP_IDS:
        fingerprint = prepare_step_input_fingerprint(
            step_id,
            workspace,
            hypothesis_id,
            experiment_id,
        )
        record = manifest.steps.get(step_id) if compatible else None
        if record is None:
            action = "RUN"
            reason = "no_compatible_record"
            recorded_outputs: tuple[str, ...] = ()
        elif record.input_fingerprint != fingerprint:
            action = "RUN"
            reason = "input_changed"
            recorded_outputs = tuple(sorted(record.output_fingerprints))
        else:
            outputs_valid, reason = _recorded_outputs_status(
                workspace,
                record.output_fingerprints,
            )
            action = "SKIP" if outputs_valid else "RUN"
            recorded_outputs = tuple(sorted(record.output_fingerprints))
        plan.append(
            PreparationStepPlan(
                step_id=step_id,
                action=action,
                reason=reason,
                input_fingerprint=fingerprint,
                recorded_outputs=recorded_outputs,
            )
        )
    return manifest, plan
