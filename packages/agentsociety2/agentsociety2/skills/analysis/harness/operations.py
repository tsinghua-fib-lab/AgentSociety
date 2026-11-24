from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

OperationScope = Literal["hypothesis", "workspace"]
OperationPlane = Literal["evidence", "presentation", "governance"]
OperationRisk = Literal["low", "medium", "high"]
OperationPhasePolicy = Literal["advisory", "enforced"]
InputKind = Literal[
    "string",
    "path",
    "sql",
    "csv",
    "json_object",
    "json_array",
    "boolean",
    "string_or_path",
]
InputGroupMode = Literal["exactly_one", "at_least_one"]

HYPOTHESIS_PHASES = ("frame", "explore", "claims", "refine", "produce")
ALL_PHASES = (*HYPOTHESIS_PHASES, "synthesis")

EDA_PROFILE_NAMES = (
    "quick-stats",
    "ydata",
    "sweetviz",
    "missingno",
    "correlation",
    "pygwalker",
    "datatable",
    "plotly-profile",
    "eda-hub",
    "bundle",
)


class AnalysisInputSpec(BaseModel):
    """CLI and runtime contract for one operation input."""

    model_config = ConfigDict(frozen=True)

    name: str
    flags: tuple[str, ...]
    kind: InputKind = "string"
    required: bool = False
    cli_required: bool = False
    action: Literal["store_true"] | None = None
    default: Any = None
    default_source: Literal["workspace"] | None = None
    choices: tuple[str, ...] = Field(default_factory=tuple)
    help: str = ""


class AnalysisInputGroup(BaseModel):
    """Cross-input constraint enforced by parser and preflight."""

    model_config = ConfigDict(frozen=True)

    id: str
    members: tuple[str, ...]
    mode: InputGroupMode
    required: bool = True


class AnalysisOperationSpec(BaseModel):
    """Single source of truth for the public analysis operation surface."""

    model_config = ConfigDict(frozen=True)

    id: str
    contract_version: int = 1
    summary: str
    phases: tuple[str, ...] = Field(default_factory=tuple)
    scope: OperationScope = "hypothesis"
    plane: OperationPlane = "evidence"
    depends_on_gates: tuple[str, ...] = Field(default_factory=tuple)
    required_inputs: tuple[str, ...] = Field(default_factory=tuple)
    optional_inputs: tuple[str, ...] = Field(default_factory=tuple)
    inputs: tuple[AnalysisInputSpec, ...] = Field(default_factory=tuple)
    input_groups: tuple[AnalysisInputGroup, ...] = Field(default_factory=tuple)
    produced_artifacts: tuple[str, ...] = Field(default_factory=tuple)
    mutates_workspace: bool = False
    repeatable: bool = True
    risk: OperationRisk = "low"
    validator: str | None = None
    handler: str
    capability_requirements: tuple[str, ...] = Field(default_factory=tuple)
    phase_policy: OperationPhasePolicy = "advisory"
    workflow_order: int | None = None
    requires_current_gate: bool = False


_INPUT_CATALOG: Mapping[str, dict[str, Any]] = MappingProxyType(
    {
        "workspace": {
            "kind": "path",
            "default_source": "workspace",
        },
        "hypothesis_id": {},
        "experiment_id": {},
        "data_path": {
            "flags": ("--data-path", "--db-path"),
            "kind": "path",
            "help": (
                "Replay directory path; --db-path is accepted for legacy sqlite.db "
                "workflows"
            ),
        },
        "output_dir": {
            "kind": "path",
            "help": (
                "Destination directory. For collect-assets, pass either the report "
                "directory or its assets/ directory; only one assets/ level is used."
            ),
        },
        "charts_dir": {"kind": "path"},
        "spec": {"kind": "path"},
        "chart_path": {"kind": "path"},
        "code": {"kind": "string_or_path"},
        "sql": {"kind": "sql"},
        "type": {"choices": EDA_PROFILE_NAMES},
        "tables": {"kind": "csv"},
        "profiles": {
            "kind": "csv",
            "help": "Comma-separated profiles used by --type bundle",
        },
        "filter": {"kind": "csv"},
        "payload": {
            "kind": "json_object",
            "help": "JSON object or path to JSON file",
        },
        "artifacts": {
            "kind": "json_array",
            "help": "JSON array of file paths",
        },
        "merge": {
            "kind": "boolean",
            "action": "store_true",
            "help": "Merge new artifacts into the existing phase artifact list",
        },
        "phase": {},
        "topic": {"default": "workflow"},
        "name": {},
        "run_id": {},
        "include_preferences": {
            "kind": "boolean",
            "action": "store_true",
            "help": "Include preference candidates only with explicit feedback evidence",
        },
        "skip_recipes": {
            "kind": "boolean",
            "action": "store_true",
            "help": "Do not write method recipe markdown files",
        },
        "skip_lessons": {
            "kind": "boolean",
            "action": "store_true",
            "help": "Do not append project lessons JSONL records",
        },
        "include_embedded_data": {
            "kind": "boolean",
            "action": "store_true",
            "help": (
                "Include image data URLs in collect-assets JSON output; disabled by "
                "default to keep CLI and agent output bounded"
            ),
        },
    }
)


def _input_spec(name: str, *, required: bool) -> AnalysisInputSpec:
    catalog = dict(_INPUT_CATALOG.get(name, {}))
    flags = catalog.pop("flags", (f"--{name.replace('_', '-')}",))
    default_source = catalog.get("default_source")
    return AnalysisInputSpec(
        name=name,
        flags=tuple(flags),
        required=required,
        cli_required=required and default_source is None,
        **catalog,
    )


def _operation_inputs(
    required_inputs: tuple[str, ...], optional_inputs: tuple[str, ...]
) -> tuple[tuple[AnalysisInputSpec, ...], tuple[AnalysisInputGroup, ...]]:
    inputs: list[AnalysisInputSpec] = []
    groups: list[AnalysisInputGroup] = []
    for raw_name in required_inputs:
        if "|" not in raw_name:
            inputs.append(_input_spec(raw_name, required=True))
            continue
        members = tuple(name.strip() for name in raw_name.split("|") if name.strip())
        inputs.extend(_input_spec(name, required=False) for name in members)
        groups.append(
            AnalysisInputGroup(
                id=raw_name.replace("|", "_or_"),
                members=members,
                mode="exactly_one",
            )
        )
    inputs.extend(_input_spec(name, required=False) for name in optional_inputs)
    return tuple(inputs), tuple(groups)


def _op(
    operation_id: str,
    summary: str,
    *,
    contract_version: int = 1,
    phases: Iterable[str] = (),
    scope: OperationScope = "hypothesis",
    plane: OperationPlane = "evidence",
    depends_on_gates: Iterable[str] = (),
    required_inputs: Iterable[str] = (),
    optional_inputs: Iterable[str] = (),
    produced_artifacts: Iterable[str] = (),
    mutates_workspace: bool = False,
    repeatable: bool = True,
    risk: OperationRisk = "low",
    validator: str | None = None,
    handler: str | None = None,
    capability_requirements: Iterable[str] = (),
    phase_policy: OperationPhasePolicy | None = None,
    workflow_order: int | None = None,
    requires_current_gate: bool = False,
) -> AnalysisOperationSpec:
    required = tuple(required_inputs)
    optional = tuple(optional_inputs)
    inputs, input_groups = _operation_inputs(required, optional)
    return AnalysisOperationSpec(
        id=operation_id,
        contract_version=contract_version,
        summary=summary,
        phases=tuple(phases),
        scope=scope,
        plane=plane,
        depends_on_gates=tuple(depends_on_gates),
        required_inputs=required,
        optional_inputs=optional,
        inputs=inputs,
        input_groups=input_groups,
        produced_artifacts=tuple(produced_artifacts),
        mutates_workspace=mutates_workspace,
        repeatable=repeatable,
        risk=risk,
        validator=validator,
        handler=handler or operation_id,
        capability_requirements=tuple(capability_requirements),
        phase_policy=phase_policy or "advisory",
        workflow_order=workflow_order,
        requires_current_gate=requires_current_gate,
    )


_SPECS = (
    _op(
        "load-context",
        "Load hypothesis and experiment context plus replay paths.",
        phases=("frame", "explore"),
        required_inputs=("workspace", "hypothesis_id", "experiment_id"),
        workflow_order=5,
    ),
    _op(
        "list-tables",
        "List replay datasets and their column counts.",
        phases=("explore",),
        required_inputs=("data_path",),
        workflow_order=10,
    ),
    _op(
        "data-summary",
        "Read replay schema, row counts, samples, and summary statistics.",
        phases=("explore",),
        required_inputs=("data_path",),
        workflow_order=20,
    ),
    _op(
        "query-data",
        "Execute one read-only SELECT or WITH query against replay data.",
        phases=("explore", "claims", "refine"),
        required_inputs=("data_path", "sql"),
        risk="medium",
        workflow_order=30,
    ),
    _op(
        "run-eda",
        "Generate a capability-checked EDA artifact for selected tables.",
        phases=("explore",),
        required_inputs=("data_path", "output_dir", "type"),
        optional_inputs=("tables", "profiles", "workspace", "hypothesis_id"),
        produced_artifacts=("presentation/hypothesis_{id}/data/eda_*",),
        mutates_workspace=True,
        risk="medium",
        capability_requirements=("eda.{type}",),
        handler="eda",
        workflow_order=40,
    ),
    _op(
        "collect-assets",
        "Collect experiment and chart assets into a report asset directory.",
        contract_version=2,
        phases=("refine", "produce"),
        plane="presentation",
        required_inputs=("workspace", "hypothesis_id", "experiment_id", "output_dir"),
        optional_inputs=("charts_dir", "filter", "include_embedded_data"),
        produced_artifacts=("presentation/hypothesis_{id}/assets/*",),
        mutates_workspace=True,
        risk="medium",
    ),
    _op(
        "compose-figure",
        "Assemble multiple raster assets into one labeled composite figure.",
        contract_version=2,
        phases=("refine",),
        plane="presentation",
        depends_on_gates=("claims",),
        required_inputs=("workspace", "hypothesis_id", "spec"),
        produced_artifacts=("presentation/hypothesis_{id}/charts/figure_*",),
        mutates_workspace=True,
        risk="medium",
        workflow_order=40,
    ),
    _op(
        "intake",
        "Initialize hypothesis analysis state, paths, memory, and capability status.",
        phases=("frame",),
        plane="governance",
        required_inputs=("workspace", "hypothesis_id", "experiment_id"),
        produced_artifacts=(".agentsociety/analysis/hypothesis_{id}/state.yaml",),
        mutates_workspace=True,
        repeatable=False,
        phase_policy="enforced",
        workflow_order=10,
    ),
    _op(
        "write-plan",
        "Persist the PAP-lite analysis plan.",
        phases=("frame",),
        plane="governance",
        required_inputs=("workspace", "hypothesis_id", "payload"),
        produced_artifacts=(
            ".agentsociety/analysis/hypothesis_{id}/analysis_plan.yaml",
        ),
        mutates_workspace=True,
        workflow_order=30,
    ),
    _op(
        "validate-plan",
        "Run the deterministic frame/plan gate.",
        phases=("frame",),
        plane="governance",
        required_inputs=("workspace", "hypothesis_id"),
        produced_artifacts=("frame checkpoint in harness state",),
        mutates_workspace=True,
        validator="validate_plan",
        workflow_order=80,
    ),
    _op(
        "validate-explore",
        "Validate replay schema, target tables, and registered EDA artifacts.",
        phases=("explore",),
        plane="governance",
        depends_on_gates=("frame",),
        required_inputs=("workspace", "hypothesis_id", "experiment_id"),
        produced_artifacts=("explore checkpoint in harness state",),
        mutates_workspace=True,
        validator="validate_explore",
        workflow_order=80,
    ),
    _op(
        "record-claim",
        "Create or replace a confirmatory or exploratory claim.",
        phases=("claims",),
        plane="governance",
        depends_on_gates=("explore",),
        required_inputs=("workspace", "hypothesis_id", "payload"),
        produced_artifacts=(".agentsociety/analysis/hypothesis_{id}/claims.json",),
        mutates_workspace=True,
        workflow_order=30,
    ),
    _op(
        "validate-claims",
        "Validate claim shape and approved confirmatory coverage.",
        phases=("claims",),
        plane="governance",
        depends_on_gates=("explore",),
        required_inputs=("workspace", "hypothesis_id"),
        produced_artifacts=("claims checkpoint in harness state",),
        mutates_workspace=True,
        validator="validate_claims",
        workflow_order=80,
    ),
    _op(
        "record-contract",
        "Persist a claim-linked figure contract before chart generation.",
        phases=("refine",),
        plane="governance",
        depends_on_gates=("claims",),
        required_inputs=("workspace", "hypothesis_id", "payload"),
        produced_artifacts=("figure contract in harness state",),
        mutates_workspace=True,
        workflow_order=20,
    ),
    _op(
        "validate-chart",
        "Validate chart code or a rendered chart and register successful files.",
        phases=("refine",),
        plane="governance",
        depends_on_gates=("claims",),
        required_inputs=("workspace", "hypothesis_id", "chart_path|code"),
        produced_artifacts=("validated chart registration in harness state",),
        mutates_workspace=True,
        validator="validate_chart_file|validate_chart_script",
        workflow_order=60,
    ),
    _op(
        "validate-refine",
        "Run the holistic figure-contract and chart-artifact gate.",
        phases=("refine",),
        plane="governance",
        depends_on_gates=("claims",),
        required_inputs=("workspace", "hypothesis_id"),
        produced_artifacts=("refine checkpoint in harness state",),
        mutates_workspace=True,
        validator="validate_refine",
        workflow_order=80,
    ),
    _op(
        "record-phase-artifacts",
        "Register phase artifacts for validation and report-context assembly.",
        phases=("explore", "refine"),
        plane="governance",
        required_inputs=("workspace", "hypothesis_id", "phase", "artifacts"),
        optional_inputs=("merge",),
        produced_artifacts=("phase artifact registration in harness state",),
        mutates_workspace=True,
        workflow_order=60,
    ),
    _op(
        "build-report-context",
        "Build evidence_index.json and report_context.md from registered evidence.",
        phases=("produce",),
        plane="presentation",
        depends_on_gates=("refine",),
        required_inputs=("workspace", "hypothesis_id"),
        produced_artifacts=(
            "presentation/hypothesis_{id}/data/evidence_index.json",
            "presentation/hypothesis_{id}/data/report_context.md",
        ),
        mutates_workspace=True,
        workflow_order=10,
    ),
    _op(
        "sync-report-assets",
        "Copy report-referenced chart files into assets/.",
        phases=("produce",),
        plane="presentation",
        depends_on_gates=("refine",),
        required_inputs=("workspace", "hypothesis_id", "experiment_id"),
        produced_artifacts=("presentation/hypothesis_{id}/assets/*",),
        mutates_workspace=True,
        workflow_order=30,
    ),
    _op(
        "embed-interactive-eda",
        "Create the interactive EDA block and inject it into existing HTML reports.",
        phases=("produce",),
        plane="presentation",
        depends_on_gates=("refine",),
        required_inputs=("workspace", "hypothesis_id"),
        produced_artifacts=(
            "presentation/hypothesis_{id}/data/interactive_eda_section.html",
        ),
        mutates_workspace=True,
        workflow_order=35,
    ),
    _op(
        "prepare-produce",
        "Prepare report context, assets, and interactive EDA before release validation.",
        phases=("produce",),
        plane="presentation",
        depends_on_gates=("refine",),
        required_inputs=("workspace", "hypothesis_id", "experiment_id"),
        produced_artifacts=(
            ".agentsociety/analysis/hypothesis_{id}/prepare_produce_manifest.json",
            "presentation/hypothesis_{id}/data/evidence_index.json",
            "presentation/hypothesis_{id}/data/report_context.md",
            "presentation/hypothesis_{id}/assets/*",
        ),
        mutates_workspace=True,
        risk="medium",
        workflow_order=5,
    ),
    _op(
        "validate-report-quality",
        "Run deterministic bilingual narrative and figure-parity checks.",
        phases=("produce",),
        plane="governance",
        depends_on_gates=("refine",),
        required_inputs=("workspace", "hypothesis_id", "experiment_id"),
        validator="validate_report_quality",
        workflow_order=60,
    ),
    _op(
        "record-report-review",
        "Store an independent report review with the current report fingerprint.",
        phases=("produce",),
        plane="governance",
        depends_on_gates=("refine",),
        required_inputs=("workspace", "hypothesis_id", "experiment_id", "payload"),
        produced_artifacts=(
            ".agentsociety/analysis/hypothesis_{id}/report_review.json",
        ),
        mutates_workspace=True,
        workflow_order=70,
    ),
    _op(
        "validate-release",
        "Validate presentation artifacts without rewriting them, then record release gate state.",
        phases=("produce",),
        plane="governance",
        depends_on_gates=("refine",),
        required_inputs=("workspace", "hypothesis_id", "experiment_id"),
        produced_artifacts=("produce checkpoint in harness state",),
        mutates_workspace=True,
        validator="validate_release",
        workflow_order=80,
    ),
    _op(
        "record-synthesis-review",
        "Store an independent synthesis review with the current report fingerprint.",
        phases=("synthesis",),
        scope="workspace",
        plane="governance",
        depends_on_gates=("produce",),
        required_inputs=("workspace", "payload"),
        produced_artifacts=(".agentsociety/analysis/synthesis/synthesis_review.json",),
        mutates_workspace=True,
        workflow_order=70,
    ),
    _op(
        "validate-synthesis",
        "Validate scoped hypothesis sources, synthesis reports, review, and attestation.",
        phases=("synthesis",),
        scope="workspace",
        plane="governance",
        depends_on_gates=("produce",),
        required_inputs=("workspace",),
        produced_artifacts=("synthesis release state",),
        mutates_workspace=True,
        validator="validate_synthesis",
        workflow_order=80,
    ),
    _op(
        "validate",
        "Validate workspace completion through the required synthesis gate.",
        phases=("synthesis",),
        scope="workspace",
        plane="governance",
        depends_on_gates=("produce",),
        required_inputs=("workspace",),
        produced_artifacts=("synthesis release state",),
        mutates_workspace=True,
        validator="validate_synthesis",
    ),
    _op(
        "record-attestation",
        "Record LLM phase judgment with an automatic artifact fingerprint.",
        phases=ALL_PHASES,
        plane="governance",
        required_inputs=("workspace", "payload"),
        optional_inputs=("hypothesis_id",),
        produced_artifacts=("phase attestation in harness state",),
        mutates_workspace=True,
        risk="medium",
        workflow_order=90,
    ),
    _op(
        "advance",
        "Advance to the next hypothesis phase after the current gate passes.",
        phases=HYPOTHESIS_PHASES[:-1],
        plane="governance",
        required_inputs=("workspace", "hypothesis_id", "experiment_id", "phase"),
        produced_artifacts=("current phase in harness state",),
        mutates_workspace=True,
        workflow_order=100,
        requires_current_gate=True,
    ),
    _op(
        "status",
        "Show hypothesis, synthesis, memory, and capability status.",
        phases=ALL_PHASES,
        scope="workspace",
        plane="governance",
        required_inputs=("workspace",),
        optional_inputs=("hypothesis_id", "run_id"),
    ),
    _op(
        "gate-status",
        "Show structural and attestation checkpoints for every phase.",
        phases=ALL_PHASES,
        scope="workspace",
        plane="governance",
        required_inputs=("workspace",),
        optional_inputs=("hypothesis_id", "run_id"),
    ),
    _op(
        "run-loop",
        "Return the phase-aware next-step plan and currently available operations.",
        phases=ALL_PHASES,
        plane="governance",
        required_inputs=("workspace", "hypothesis_id", "experiment_id"),
    ),
    _op(
        "guidance",
        "Return machine-readable harness guidance generated from the operation registry.",
        phases=ALL_PHASES,
        scope="workspace",
        plane="governance",
        optional_inputs=("workspace", "topic"),
    ),
    _op(
        "payload-template",
        "Return a schema-compatible example payload by name.",
        phases=ALL_PHASES,
        scope="workspace",
        plane="governance",
        required_inputs=("name",),
        optional_inputs=("workspace",),
    ),
    _op(
        "chart-scaffold",
        "Return the publication-safe Python chart scaffold.",
        phases=("refine",),
        plane="presentation",
        optional_inputs=("workspace",),
    ),
    _op(
        "draft-reflection",
        "Draft reviewable post-run lessons and method recipes.",
        phases=("produce", "synthesis"),
        plane="governance",
        depends_on_gates=("produce",),
        required_inputs=("workspace", "hypothesis_id", "experiment_id"),
        produced_artifacts=("reflection draft",),
        mutates_workspace=True,
    ),
    _op(
        "record-reflection",
        "Store a reviewed reflection proposal before durable promotion.",
        phases=("produce", "synthesis"),
        plane="governance",
        depends_on_gates=("produce",),
        required_inputs=("workspace", "payload"),
        optional_inputs=("hypothesis_id",),
        produced_artifacts=("reflection report",),
        mutates_workspace=True,
    ),
    _op(
        "record-feedback",
        "Store explicit post-analysis user feedback.",
        phases=("produce", "synthesis"),
        plane="governance",
        required_inputs=("workspace", "payload"),
        optional_inputs=("hypothesis_id",),
        produced_artifacts=("user feedback record",),
        mutates_workspace=True,
    ),
    _op(
        "review-reflection",
        "Validate reflection quality and preference-confirmation evidence.",
        phases=("produce", "synthesis"),
        plane="governance",
        depends_on_gates=("produce",),
        required_inputs=("workspace",),
        optional_inputs=("hypothesis_id", "include_preferences"),
        produced_artifacts=("reflection review",),
        mutates_workspace=True,
        validator="review_reflection",
    ),
    _op(
        "promote-reflection",
        "Explicitly promote reviewed lessons, recipes, and confirmed preferences.",
        phases=("produce", "synthesis"),
        plane="governance",
        depends_on_gates=("produce",),
        required_inputs=("workspace",),
        optional_inputs=(
            "hypothesis_id",
            "include_preferences",
            "skip_recipes",
            "skip_lessons",
        ),
        produced_artifacts=("workspace experience memory",),
        mutates_workspace=True,
        risk="medium",
    ),
    _op(
        "memory-context",
        "Show active lessons, method recipes, and confirmed preferences.",
        phases=ALL_PHASES,
        scope="workspace",
        plane="governance",
        required_inputs=("workspace",),
        optional_inputs=("hypothesis_id",),
    ),
)

_OPERATION_REGISTRY: Mapping[str, AnalysisOperationSpec] = MappingProxyType(
    {spec.id: spec for spec in _SPECS}
)

if len(_OPERATION_REGISTRY) != len(_SPECS):  # pragma: no cover - import-time guard
    raise RuntimeError("duplicate analysis operation id")


def operation_registry() -> Mapping[str, AnalysisOperationSpec]:
    return _OPERATION_REGISTRY


def get_operation_spec(operation_id: str) -> AnalysisOperationSpec:
    return _OPERATION_REGISTRY[operation_id]


def operation_specs_for_phase(
    phase: str,
    *,
    passed_gates: Iterable[str] = (),
    current_gate_pass: bool = False,
) -> tuple[AnalysisOperationSpec, ...]:
    passed = set(passed_gates)
    selected = [
        spec
        for spec in _SPECS
        if phase in spec.phases
        and set(spec.depends_on_gates).issubset(passed)
        and (not spec.requires_current_gate or current_gate_pass)
    ]
    return tuple(
        sorted(
            selected,
            key=lambda spec: (
                spec.workflow_order is None,
                spec.workflow_order or 999,
                spec.id,
            ),
        )
    )


def workflow_operations_by_phase() -> dict[str, list[str]]:
    return {
        phase: [
            spec.id
            for spec in sorted(
                (
                    item
                    for item in _SPECS
                    if phase in item.phases and item.workflow_order is not None
                ),
                key=lambda item: (item.workflow_order or 999, item.id),
            )
        ]
        for phase in ALL_PHASES
    }
