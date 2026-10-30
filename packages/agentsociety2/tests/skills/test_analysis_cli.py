"""Tests for the extension analysis CLI helpers."""

import json
import re
import sqlite3
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

from agentsociety2.skills.analysis.harness import cli as harness_cli
from agentsociety2.skills.analysis.harness import state as harness_state
from agentsociety2.skills.analysis.harness.capabilities import EDA_PROFILE_MODULES
from agentsociety2.skills.analysis.harness.models import AnalysisPhase, PhaseCheckpoint
from agentsociety2.skills.analysis.harness.operations import operation_registry
from agentsociety2.skills.analysis.harness.preflight import OperationAvailability
from agentsociety2.skills.analysis.models import ReportAsset


def _load_analysis_cli_module():
    repo_root = Path(__file__).resolve().parents[4]
    module_path = (
        repo_root
        / "extension"
        / "skills"
        / "agentsociety-analysis"
        / "v1.0.0"
        / "scripts"
        / "analysis.py"
    )
    spec = spec_from_file_location("analysis_cli_test_module", module_path)
    module = module_from_spec(spec)
    assert spec is not None
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


analysis_cli = _load_analysis_cli_module()


def _analysis_skill_root() -> Path:
    return (
        Path(__file__).resolve().parents[4]
        / "extension"
        / "skills"
        / "agentsociety-analysis"
        / "v1.0.0"
    )


def test_cli_commands_and_help_match_operation_registry():
    parser = analysis_cli._build_parser()
    command_parsers = parser._subparsers._group_actions[0].choices

    assert set(command_parsers) == set(operation_registry())
    for command, command_parser in command_parsers.items():
        assert command_parser.description == operation_registry()[command].summary


def test_registry_parser_matches_structured_input_contract():
    parser = analysis_cli._build_parser()
    command_parsers = parser._subparsers._group_actions[0].choices
    workspace_default = str(analysis_cli._default_workspace())

    for command, operation in operation_registry().items():
        command_parser = command_parsers[command]
        actions = {
            action.dest: action
            for action in command_parser._actions
            if action.dest != "help"
        }
        assert set(actions) == {item.name for item in operation.inputs} | {"dry_run"}
        for input_spec in operation.inputs:
            action = actions[input_spec.name]
            expected_default = input_spec.default
            if input_spec.default_source == "workspace":
                expected_default = workspace_default
            elif input_spec.action == "store_true":
                expected_default = False
            assert tuple(action.option_strings) == input_spec.flags
            assert action.required is input_spec.cli_required
            assert action.default == expected_default
            assert tuple(action.choices or ()) == input_spec.choices
            assert (action.__class__.__name__ == "_StoreTrueAction") is (
                input_spec.action == "store_true"
            )

        parser_groups = {
            tuple(action.dest for action in group._group_actions): group.required
            for group in command_parser._mutually_exclusive_groups
        }
        assert parser_groups == {
            group.members: group.required for group in operation.input_groups
        }


def test_compose_figure_contract_is_claim_scoped_and_versioned():
    operation = operation_registry()["compose-figure"]

    assert operation.contract_version == 2
    assert operation.required_inputs == ("workspace", "hypothesis_id", "spec")
    assert operation.depends_on_gates == ("claims",)


def test_registry_handlers_are_resolvable():
    local_handlers = {
        "load-context",
        "list-tables",
        "data-summary",
        "query-data",
        "eda",
        "collect-assets",
        "compose-figure",
    }
    for operation in operation_registry().values():
        if operation.handler in local_handlers:
            assert hasattr(analysis_cli, f"_run_{operation.handler.replace('-', '_')}")
        else:
            assert hasattr(harness_cli, f"cmd_{operation.handler.replace('-', '_')}")


def test_validate_chart_parser_enforces_exactly_one_input():
    parser = analysis_cli._build_parser()
    base = ["validate-chart", "--hypothesis-id", "1"]

    with pytest.raises(analysis_cli._ArgumentParseError):
        parser.parse_args(base)
    with pytest.raises(analysis_cli._ArgumentParseError):
        parser.parse_args([*base, "--chart-path", "a.png", "--code", "code.py"])

    assert parser.parse_args([*base, "--chart-path", "a.png"]).chart_path == "a.png"


def test_cli_help_exits_successfully_and_uses_registry(monkeypatch, capsys):
    monkeypatch.setattr(
        analysis_cli.sys,
        "argv",
        ["analysis.py", "validate-release", "--help"],
    )

    result = analysis_cli.main()
    output = capsys.readouterr().out

    assert result == 0
    assert " ".join(
        operation_registry()["validate-release"].summary.split()
    ) in " ".join(output.split())
    assert '"success":false' not in output


def test_cli_dry_run_reports_preflight_without_writing(monkeypatch, capsys, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        analysis_cli.sys,
        "argv",
        [
            "analysis.py",
            "intake",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--experiment-id",
            "1",
            "--dry-run",
        ],
    )

    assert analysis_cli.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["success"] is True
    assert payload["preflight"]["status"] == "AVAILABLE"
    assert not (workspace / ".agentsociety").exists()


def test_cli_dry_run_reports_missing_gate(monkeypatch, capsys, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        analysis_cli.sys,
        "argv",
        [
            "analysis.py",
            "validate-explore",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--experiment-id",
            "1",
            "--dry-run",
        ],
    )

    assert analysis_cli.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["preflight"]["status"] == "BLOCKED_BY_GATE"
    assert payload["preflight"]["missing_gates"] == ["frame"]


def test_cli_prepare_produce_dry_run_includes_plan_without_writing(
    monkeypatch, capsys, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    harness_cli.cmd_intake(workspace, "1", "1")
    state = harness_state.load_hypothesis_state(workspace, "1")
    for phase in AnalysisPhase:
        if phase == AnalysisPhase.produce:
            break
        state.phase_checkpoints[phase.value] = PhaseCheckpoint(
            phase=phase.value,
            structural_pass=True,
            attestation_pass=True,
            gate_pass=True,
        )
    harness_state.save_hypothesis_state(workspace, "1", state)
    monkeypatch.setattr(
        analysis_cli.sys,
        "argv",
        [
            "analysis.py",
            "prepare-produce",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--experiment-id",
            "1",
            "--dry-run",
        ],
    )

    assert analysis_cli.main() == 0
    payload = json.loads(capsys.readouterr().out)

    assert payload["success"] is True
    assert payload["preflight"]["status"] == "AVAILABLE"
    assert payload["execution_plan"]["status"] == "PLANNED"
    assert {item["action"] for item in payload["execution_plan"]["plan"]} == {"RUN"}
    assert not Path(payload["execution_plan"]["manifest_path"]).exists()
    assert not (
        workspace / "presentation" / "hypothesis_1" / "data" / "evidence_index.json"
    ).exists()


def test_cli_mutating_operation_writes_success_receipt(monkeypatch, capsys, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setattr(
        analysis_cli.sys,
        "argv",
        [
            "analysis.py",
            "intake",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--experiment-id",
            "1",
        ],
    )

    assert analysis_cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    run_id = payload["outcome"]["run_id"]
    receipt_path = workspace / ".agentsociety" / "analysis" / "runs" / f"{run_id}.json"
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert payload["success"] is True
    assert payload["outcome"]["status"] == "SUCCEEDED"
    assert run_id.startswith("run_")
    assert receipt["operation_id"] == "intake"
    assert receipt["schema_version"] == 2
    assert len(receipt["execution_key"]) == 64
    assert receipt["attempt"] == 1
    assert receipt["status"] == "SUCCEEDED"
    assert receipt["repeatable"] is False
    assert receipt["retryable"] is False
    assert receipt["safe_inputs"] == {
        "hypothesis_id": "1",
        "experiment_id": "1",
    }
    assert "workspace" in receipt["input_names"]
    assert (
        ".agentsociety/analysis/hypothesis_1/state.yaml"
        in receipt["artifact_fingerprints"]
    )

    monkeypatch.setattr(
        analysis_cli.sys,
        "argv",
        [
            "analysis.py",
            "status",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--run-id",
            run_id,
        ],
    )
    assert analysis_cli.main() == 0
    status_payload = json.loads(capsys.readouterr().out)
    assert status_payload["outcome"]["run_id"] == ""
    assert status_payload["run"]["run_id"] == run_id
    assert status_payload["recent_runs"][0]["run_id"] == run_id
    assert (
        len(list((workspace / ".agentsociety" / "analysis" / "runs").glob("*.json")))
        == 1
    )


def test_cli_non_repeatable_duplicate_returns_unchanged(monkeypatch, capsys, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    argv = [
        "analysis.py",
        "intake",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--experiment-id",
        "1",
    ]
    monkeypatch.setattr(analysis_cli.sys, "argv", argv)
    assert analysis_cli.main() == 0
    first = json.loads(capsys.readouterr().out)

    monkeypatch.setattr(analysis_cli.sys, "argv", argv)
    assert analysis_cli.main() == 0
    second = json.loads(capsys.readouterr().out)
    receipts = sorted(
        (workspace / ".agentsociety" / "analysis" / "runs").glob("*.json")
    )

    assert first["outcome"]["status"] == "SUCCEEDED"
    assert second["success"] is True
    assert second["outcome"]["status"] == "UNCHANGED"
    assert second["reason"] == "non_repeatable_operation_already_succeeded"
    assert second["prior_run_id"] == first["outcome"]["run_id"]
    assert len(receipts) == 2


def test_cli_preflight_block_writes_blocked_receipt(monkeypatch, capsys, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    harness_cli.cmd_intake(workspace, "1", "1")
    monkeypatch.setattr(
        analysis_cli.sys,
        "argv",
        [
            "analysis.py",
            "validate-explore",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--experiment-id",
            "1",
        ],
    )

    assert analysis_cli.main() == 2
    payload = json.loads(capsys.readouterr().out)
    receipt_path = (
        workspace
        / ".agentsociety"
        / "analysis"
        / "runs"
        / f"{payload['outcome']['run_id']}.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert payload["success"] is False
    assert payload["outcome"]["status"] == "BLOCKED"
    assert payload["outcome"]["preflight"]["status"] == "BLOCKED_BY_GATE"
    assert receipt["status"] == "BLOCKED"
    assert receipt["retryable"] is True


def test_cli_handler_failure_writes_redacted_failed_receipt(
    monkeypatch, capsys, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    secret = "private-plan-value"

    def fail_write_plan(*_args, **_kwargs):
        raise RuntimeError(f"synthetic handler failure: {secret}")

    monkeypatch.setattr(harness_cli, "cmd_write_plan", fail_write_plan)
    monkeypatch.setattr(
        analysis_cli.sys,
        "argv",
        [
            "analysis.py",
            "write-plan",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--payload",
            json.dumps({"research_question": secret}),
        ],
    )

    assert analysis_cli.main() == 1
    payload = json.loads(capsys.readouterr().out)
    receipt_path = (
        workspace
        / ".agentsociety"
        / "analysis"
        / "runs"
        / f"{payload['outcome']['run_id']}.json"
    )
    receipt_text = receipt_path.read_text(encoding="utf-8")
    receipt = json.loads(receipt_text)

    assert payload["success"] is False
    assert payload["outcome"]["status"] == "FAILED"
    assert payload["outcome"]["error"]["type"] == "RuntimeError"
    assert payload["error"] == "synthetic handler failure: [REDACTED]"
    assert receipt["status"] == "FAILED"
    assert receipt["retryable"] is True
    assert "payload" in receipt["input_names"]
    assert "payload" not in receipt["safe_inputs"]
    assert secret not in receipt_text


def test_cli_local_mutating_operations_write_receipts_and_artifact_hashes(
    monkeypatch, capsys, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def available(args):
        return OperationAvailability(operation_id=args.command, status="AVAILABLE")

    def execute_eda(args):
        output = Path(args.output_dir) / "eda_quick_stats.md"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text("# EDA\n", encoding="utf-8")
        return {"type": args.type, "files": [str(output)]}

    def execute_collect_assets(args):
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        output = output_dir / "chart_01.png"
        output.write_bytes(b"chart")
        return {
            "assets": [
                ReportAsset(
                    asset_id="chart-01",
                    asset_type="chart",
                    title="Chart 01",
                    file_path=str(output),
                    file_size=output.stat().st_size,
                )
            ],
            "assets_dir": str(output_dir),
        }

    def execute_compose_figure(_args):
        output = (
            workspace / "presentation" / "hypothesis_1" / "charts" / "figure_01.png"
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"figure")
        metadata = output.with_suffix(".json")
        metadata.write_text('{"panels":[]}', encoding="utf-8")
        return {"output": str(output), "metadata": str(metadata), "panels": []}

    monkeypatch.setattr(analysis_cli, "_operation_preflight", available)
    monkeypatch.setattr(analysis_cli, "_execute_eda", execute_eda)
    monkeypatch.setattr(
        analysis_cli,
        "_execute_collect_assets",
        execute_collect_assets,
    )
    monkeypatch.setattr(
        analysis_cli,
        "_execute_compose_figure",
        execute_compose_figure,
    )

    data_dir = workspace / "presentation" / "hypothesis_1" / "data"
    assets_dir = workspace / "presentation" / "hypothesis_1" / "assets"
    spec_path = workspace / "presentation" / "hypothesis_1" / "charts" / "spec.json"
    commands = [
        [
            "analysis.py",
            "run-eda",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--data-path",
            str(workspace / "replay"),
            "--output-dir",
            str(data_dir),
            "--type",
            "quick-stats",
        ],
        [
            "analysis.py",
            "collect-assets",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--experiment-id",
            "1",
            "--output-dir",
            str(assets_dir),
        ],
        [
            "analysis.py",
            "compose-figure",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--spec",
            str(spec_path),
        ],
    ]
    expected_artifacts = {
        "run-eda": "presentation/hypothesis_1/data/eda_quick_stats.md",
        "collect-assets": "presentation/hypothesis_1/assets/chart_01.png",
        "compose-figure": "presentation/hypothesis_1/charts/figure_01.png",
    }

    for argv in commands:
        monkeypatch.setattr(analysis_cli.sys, "argv", argv)
        assert analysis_cli.main() == 0
        payload = json.loads(capsys.readouterr().out)
        receipt_path = (
            workspace
            / ".agentsociety"
            / "analysis"
            / "runs"
            / f"{payload['outcome']['run_id']}.json"
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

        assert payload["outcome"]["status"] == "SUCCEEDED"
        if argv[1] == "collect-assets":
            assert payload["assets"][0]["asset_id"] == "chart-01"
        assert receipt["operation_id"] == argv[1]
        assert receipt["status"] == "SUCCEEDED"
        assert expected_artifacts[argv[1]] in receipt["artifact_fingerprints"]

    assert (
        len(list((workspace / ".agentsociety" / "analysis" / "runs").glob("*.json")))
        == 3
    )


def test_cli_local_mutating_preflight_block_writes_receipt(
    monkeypatch, capsys, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    spec_path = tmp_path / "figure.json"
    spec_path.write_text("{}", encoding="utf-8")

    def must_not_execute(_args):
        raise AssertionError("blocked local handler must not run")

    monkeypatch.setattr(
        analysis_cli,
        "_execute_compose_figure",
        must_not_execute,
    )
    monkeypatch.setattr(
        analysis_cli.sys,
        "argv",
        [
            "analysis.py",
            "compose-figure",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--spec",
            str(spec_path),
        ],
    )

    assert analysis_cli.main() == 2
    payload = json.loads(capsys.readouterr().out)
    receipt_path = (
        workspace
        / ".agentsociety"
        / "analysis"
        / "runs"
        / f"{payload['outcome']['run_id']}.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert payload["outcome"]["status"] == "BLOCKED"
    assert payload["outcome"]["preflight"]["missing_gates"] == ["claims"]
    assert receipt["operation_id"] == "compose-figure"
    assert receipt["status"] == "BLOCKED"


def test_cli_local_mutating_failure_writes_failed_receipt(
    monkeypatch, capsys, tmp_path
):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    def fail_collect_assets(_args):
        raise RuntimeError("synthetic collect failure")

    monkeypatch.setattr(
        analysis_cli,
        "_execute_collect_assets",
        fail_collect_assets,
    )
    monkeypatch.setattr(
        analysis_cli.sys,
        "argv",
        [
            "analysis.py",
            "collect-assets",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--experiment-id",
            "1",
            "--output-dir",
            str(workspace / "presentation" / "hypothesis_1" / "assets"),
        ],
    )

    assert analysis_cli.main() == 1
    payload = json.loads(capsys.readouterr().out)
    receipt_path = (
        workspace
        / ".agentsociety"
        / "analysis"
        / "runs"
        / f"{payload['outcome']['run_id']}.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert payload["outcome"]["status"] == "FAILED"
    assert payload["outcome"]["error"]["type"] == "RuntimeError"
    assert receipt["operation_id"] == "collect-assets"
    assert receipt["status"] == "FAILED"


def test_cli_compose_figure_runs_after_claims_gate_with_receipt(
    monkeypatch, capsys, tmp_path
):
    image_module = pytest.importorskip("PIL.Image")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    harness_cli.cmd_intake(workspace, "1", "1")
    state = harness_state.load_hypothesis_state(workspace, "1")
    state.phase_checkpoints["claims"] = PhaseCheckpoint(
        phase="claims",
        structural_pass=True,
        attestation_pass=True,
        gate_pass=True,
    )
    harness_state.save_hypothesis_state(workspace, "1", state)

    charts_dir = workspace / "presentation" / "hypothesis_1" / "charts"
    charts_dir.mkdir(parents=True, exist_ok=True)
    chart_a = charts_dir / "chart_01_a.png"
    chart_b = charts_dir / "chart_02_b.png"
    image_module.new("RGB", (240, 160), "#ccddee").save(chart_a)
    image_module.new("RGB", (240, 160), "#f4c095").save(chart_b)
    spec_path = charts_dir / "figure_01.json"
    spec_path.write_text(
        json.dumps(
            {
                "output": "figure_01.png",
                "layout": {"type": "grid", "rows": 1, "cols": 2},
                "panels": [
                    {"source": chart_a.name, "label": "a"},
                    {"source": chart_b.name, "label": "b"},
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        analysis_cli.sys,
        "argv",
        [
            "analysis.py",
            "compose-figure",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--spec",
            str(spec_path),
        ],
    )

    assert analysis_cli.main() == 0
    payload = json.loads(capsys.readouterr().out)
    receipt_path = (
        workspace
        / ".agentsociety"
        / "analysis"
        / "runs"
        / f"{payload['outcome']['run_id']}.json"
    )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))

    assert payload["outcome"]["status"] == "SUCCEEDED"
    assert Path(payload["output"]).is_file()
    assert Path(payload["metadata"]).is_file()
    assert (
        "presentation/hypothesis_1/charts/figure_01.png"
        in receipt["artifact_fingerprints"]
    )
    assert (
        "presentation/hypothesis_1/charts/figure_01.json"
        in receipt["artifact_fingerprints"]
    )


def test_run_eda_profiles_match_capability_registry():
    parser = analysis_cli._build_parser()
    run_eda_parser = parser._subparsers._group_actions[0].choices["run-eda"]
    type_action = next(
        action for action in run_eda_parser._actions if action.dest == "type"
    )

    assert list(type_action.choices) == list(EDA_PROFILE_MODULES)


def test_analysis_skill_document_references_resolve():
    skill_root = _analysis_skill_root()
    repo_root = Path(__file__).resolve().parents[4]
    reference_pattern = re.compile(
        r"(?P<path>(?:references|stages|support|subagent-prompts|checklists)/"
        r"[A-Za-z0-9_./-]+\.md)(?:#[A-Za-z0-9_.-]+)?"
    )
    backticked_markdown_pattern = re.compile(r"`(?P<path>[^`\s]+\.md)(?:#[^`]*)?`")
    runtime_artifact_prefixes = (
        "data/",
        "presentation/",
        "synthesis/",
        "report_",
        "synthesis_report_",
        "eda_",
        ".claude/",
    )
    missing: list[str] = []

    for document in sorted(skill_root.rglob("*.md")):
        text = document.read_text(encoding="utf-8")
        matches = [
            *reference_pattern.finditer(text),
            *backticked_markdown_pattern.finditer(text),
        ]
        for match in matches:
            raw_path = match.group("path")
            if (
                raw_path.startswith(runtime_artifact_prefixes)
                or "*" in raw_path
                or "{" in raw_path
            ):
                continue
            relative = Path(raw_path)
            local_candidate = document.parent / relative
            root_candidate = skill_root / relative
            repo_candidate = repo_root / relative
            if not any(
                candidate.is_file()
                for candidate in (local_candidate, root_candidate, repo_candidate)
            ):
                missing.append(f"{document.relative_to(skill_root)} -> {relative}")

    assert not missing, "Missing analysis skill references:\n" + "\n".join(missing)


def test_validate_plotting_conventions_accepts_publication_scaffold():
    code = """
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["Arial", "DejaVu Sans"]
plt.rcParams["svg.fonttype"] = "none"
"""
    analysis_cli._validate_plotting_conventions(code)


def test_validate_plotting_conventions_accepts_rcparams_update():
    code = """
import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "DejaVu Sans"],
    "svg.fonttype": "none",
})
"""
    analysis_cli._validate_plotting_conventions(code)


def test_validate_plotting_conventions_requires_scaffold():
    code = """
import matplotlib.pyplot as plt

fig, ax = plt.subplots()
"""
    with pytest.raises(ValueError) as exc_info:
        analysis_cli._validate_plotting_conventions(code)

    assert 'matplotlib backend configured to "Agg"' in str(exc_info.value)
    assert '`svg.fonttype = "none"`' in str(exc_info.value)


def test_filter_assets_with_companions_keeps_same_stem_vector_exports():
    class Asset:
        def __init__(self, file_path: str):
            self.file_path = file_path

    assets = [
        Asset("/tmp/chart_01_growth.png"),
        Asset("/tmp/chart_01_growth.svg"),
        Asset("/tmp/chart_02_other.png"),
    ]

    filtered = analysis_cli._filter_assets_with_companions(
        assets,
        {"chart_01_growth.png"},
    )

    assert [Path(asset.file_path).name for asset in filtered] == [
        "chart_01_growth.png",
        "chart_01_growth.svg",
    ]


def test_load_context_parser_defaults_workspace_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("AGENTSOCIETY_WORKSPACE", str(tmp_path))

    parser = analysis_cli._build_parser()
    args = parser.parse_args(
        ["load-context", "--hypothesis-id", "1", "--experiment-id", "2"]
    )

    assert Path(args.workspace) == tmp_path.resolve()


def test_experience_memory_commands_parse(tmp_path):
    parser = analysis_cli._build_parser()

    draft = parser.parse_args(
        [
            "draft-reflection",
            "--workspace",
            str(tmp_path),
            "--hypothesis-id",
            "1",
            "--experiment-id",
            "2",
        ]
    )
    assert draft.command == "draft-reflection"

    record = parser.parse_args(
        [
            "record-reflection",
            "--workspace",
            str(tmp_path),
            "--hypothesis-id",
            "1",
            "--payload",
            "{}",
        ]
    )
    assert record.command == "record-reflection"

    promote = parser.parse_args(
        [
            "promote-reflection",
            "--workspace",
            str(tmp_path),
            "--hypothesis-id",
            "1",
            "--include-preferences",
        ]
    )
    assert promote.command == "promote-reflection"
    assert promote.include_preferences is True

    context = parser.parse_args(
        [
            "memory-context",
            "--workspace",
            str(tmp_path),
            "--hypothesis-id",
            "1",
        ]
    )
    assert context.command == "memory-context"

    feedback = parser.parse_args(
        [
            "record-feedback",
            "--workspace",
            str(tmp_path),
            "--hypothesis-id",
            "1",
            "--payload",
            "{}",
        ]
    )
    assert feedback.command == "record-feedback"

    review = parser.parse_args(
        [
            "review-reflection",
            "--workspace",
            str(tmp_path),
            "--hypothesis-id",
            "1",
            "--include-preferences",
        ]
    )
    assert review.command == "review-reflection"
    assert review.include_preferences is True


def _run_harness_cli_result(capsys, *args):
    parser = analysis_cli._build_parser()
    namespace = parser.parse_args(list(args))
    rc = analysis_cli._dispatch_harness(namespace)
    output = capsys.readouterr().out.strip()
    return rc, json.loads(output)


def _run_harness_cli(capsys, *args):
    rc, payload = _run_harness_cli_result(capsys, *args)
    assert rc == 0
    assert payload["success"] is True
    return payload


def _run_analysis_cli(capsys, *args):
    parser = analysis_cli._build_parser()
    namespace = parser.parse_args(list(args))
    if namespace.command == "run-eda":
        rc = analysis_cli._dispatch_local_mutating_from_registry(
            namespace,
            preflight=analysis_cli._operation_preflight(namespace),
            persist_receipt=True,
        )
    else:
        rc = analysis_cli._dispatch_harness(namespace)
    output = capsys.readouterr().out.strip()
    assert rc == 0
    payload = json.loads(output)
    assert payload["success"] is True
    return payload


def test_analysis_experience_memory_cli_smoke(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _run_harness_cli(
        capsys,
        "intake",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--experiment-id",
        "1",
    )
    _run_harness_cli(
        capsys,
        "write-plan",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--payload",
        json.dumps(
            {
                "research_question": "Does treatment increase value?",
                "primary_metrics": ["value"],
                "target_tables": ["metrics"],
                "confirmatory_claims": ["Treatment increases value"],
            }
        ),
    )
    _run_harness_cli(
        capsys,
        "record-claim",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--payload",
        json.dumps(
            {
                "claim_id": "c1",
                "statement": "Treatment increases value",
                "mode": "confirmatory",
                "approved": True,
            }
        ),
    )

    draft = _run_harness_cli(
        capsys,
        "draft-reflection",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--experiment-id",
        "1",
    )
    assert Path(draft["reflection_path"]).exists()

    promoted = _run_harness_cli(
        capsys,
        "promote-reflection",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
    )

    memory_dir = Path(promoted["memory_dir"])
    assert (memory_dir / "project_lessons.jsonl").exists()
    assert any((memory_dir / "method_recipes").glob("*.md"))
    assert promoted["preference_keys"] == []

    context = _run_harness_cli(
        capsys,
        "memory-context",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
    )["memory_context"]
    assert context["active"] is True
    assert context["method_recipes"]

    loop = _run_harness_cli(
        capsys,
        "run-loop",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--experiment-id",
        "1",
    )
    assert loop["memory_context"]["active"] is True
    assert loop["recommended_next_step"].startswith("0. Memory:")


def test_feedback_and_review_guard_preference_promotion(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    _run_harness_cli(
        capsys,
        "record-reflection",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--payload",
        json.dumps(
            {
                "hypothesis_id": "1",
                "experiment_id": "1",
                "what_worked": [
                    {
                        "title": "Concise reports worked",
                        "content": "Short summaries were easier to review.",
                        "evidence": ["report_zh.md"],
                    }
                ],
                "user_preferences_observed": [
                    {
                        "item_id": "report_style",
                        "title": "Report style",
                        "category": "writing",
                        "value": "concise",
                        "content": "Prefer concise reports.",
                        "evidence": [],
                    }
                ],
            }
        ),
    )

    blocked_rc, blocked = _run_harness_cli_result(
        capsys,
        "promote-reflection",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--include-preferences",
    )
    assert blocked_rc == 2
    assert blocked["success"] is False
    assert blocked["outcome"]["status"] == "BLOCKED"
    assert blocked["status"] == "BLOCKED"
    assert blocked["error"] == "reflection_review_blocked"

    _run_harness_cli(
        capsys,
        "record-feedback",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--payload",
        json.dumps(
            {
                "hypothesis_id": "1",
                "experiment_id": "1",
                "rating": 5,
                "satisfied": True,
                "comments": "请长期保持简洁报告风格。",
                "preference_candidates": [
                    {
                        "item_id": "report_style",
                        "title": "Report style",
                        "category": "writing",
                        "value": "concise",
                        "content": "User explicitly asked for concise reports.",
                        "evidence": ["feedback:user-confirmed"],
                        "confidence": "high",
                    }
                ],
            }
        ),
    )

    review = _run_harness_cli(
        capsys,
        "review-reflection",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--include-preferences",
    )
    assert review["review"]["verdict"] == "PASS"

    promoted = _run_harness_cli(
        capsys,
        "promote-reflection",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--include-preferences",
    )
    assert promoted["preference_keys"] == ["report_style"]


def test_synthetic_analysis_workflow_evolves_memory(tmp_path, capsys):
    workspace = tmp_path / "workspace"
    db_path = workspace / "hypothesis_1" / "experiment_1" / "run" / "sqlite.db"
    db_path.parent.mkdir(parents=True)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE metrics (
                agent_id INTEGER,
                step INTEGER,
                treatment INTEGER,
                value REAL
            )
            """
        )
        rows = []
        for agent_id in range(1, 13):
            treatment = 1 if agent_id > 6 else 0
            for step in range(1, 5):
                baseline = 10 + step
                lift = 4.5 if treatment else 0.0
                rows.append(
                    (agent_id, step, treatment, baseline + lift + agent_id / 20)
                )
        conn.executemany("INSERT INTO metrics VALUES (?, ?, ?, ?)", rows)

    _run_analysis_cli(
        capsys,
        "intake",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--experiment-id",
        "1",
    )
    _run_analysis_cli(
        capsys,
        "write-plan",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--payload",
        json.dumps(
            {
                "research_question": "Does treatment increase simulated value?",
                "primary_metrics": ["value", "treatment"],
                "target_tables": ["metrics"],
                "confirmatory_claims": [
                    "Treatment agents have higher mean value than controls"
                ],
                "eda_profile": "quick-stats",
                "table_checks": [
                    {"table": "metrics", "min_rows": 24, "columns": ["value"]}
                ],
            }
        ),
    )
    _run_analysis_cli(
        capsys,
        "record-attestation",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--payload",
        json.dumps(
            {
                "phase": "frame",
                "status": "DONE",
                "key_findings": ["Synthetic AB test plan is ready"],
                "rubric": {
                    "research_question_confirmed": True,
                    "success_criteria": "Compare treatment vs control mean value",
                },
            }
        ),
    )
    assert (
        _run_analysis_cli(
            capsys,
            "validate-plan",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
        )["status"]
        == "PASS"
    )

    data_dir = workspace / "presentation" / "hypothesis_1" / "data"
    eda = _run_analysis_cli(
        capsys,
        "run-eda",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--db-path",
        str(db_path),
        "--output-dir",
        str(data_dir),
        "--type",
        "quick-stats",
        "--tables",
        "metrics",
    )
    assert Path(eda["files"][0]).name == "eda_quick_stats.md"

    _run_analysis_cli(
        capsys,
        "record-attestation",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--payload",
        json.dumps(
            {
                "phase": "explore",
                "status": "DONE",
                "key_findings": ["metrics table has synthetic treatment contrast"],
                "artifacts_written": [
                    "presentation/hypothesis_1/data/eda_quick_stats.md"
                ],
                "rubric": {
                    "tables_inspected": ["metrics"],
                    "data_limitations": "Synthetic fixture; not external evidence",
                    "eda_takeaway": "Treatment rows have visibly higher values",
                },
            }
        ),
    )
    assert (
        _run_analysis_cli(
            capsys,
            "validate-explore",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
            "--experiment-id",
            "1",
        )["status"]
        == "PASS"
    )

    _run_analysis_cli(
        capsys,
        "record-claim",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--payload",
        json.dumps(
            {
                "claim_id": "c1",
                "statement": "Treatment agents have higher mean value",
                "mode": "confirmatory",
                "evidence": "metrics grouped by treatment",
                "needs_chart": True,
                "approved": True,
            }
        ),
    )
    _run_analysis_cli(
        capsys,
        "record-attestation",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--payload",
        json.dumps(
            {
                "phase": "claims",
                "status": "DONE",
                "key_findings": ["Confirmatory claim approved for fixture"],
                "rubric": {
                    "claims_user_approved": True,
                    "confirmatory_vs_exploratory_clear": True,
                },
            }
        ),
    )
    assert (
        _run_analysis_cli(
            capsys,
            "validate-claims",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
        )["status"]
        == "PASS"
    )

    chart_path = (
        workspace
        / "presentation"
        / "hypothesis_1"
        / "charts"
        / "chart_01_treatment_value.png"
    )
    chart_path.parent.mkdir(parents=True, exist_ok=True)
    chart_path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"synthetic-chart" * 20)
    _run_analysis_cli(
        capsys,
        "record-contract",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--payload",
        json.dumps(
            {
                "contract_id": "f1",
                "claim_id": "c1",
                "core_finding": "Treatment raises simulated value",
                "output_files": [str(chart_path)],
            }
        ),
    )
    _run_analysis_cli(
        capsys,
        "validate-chart",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--chart-path",
        str(chart_path),
    )
    _run_analysis_cli(
        capsys,
        "record-attestation",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--payload",
        json.dumps(
            {
                "phase": "refine",
                "status": "DONE",
                "key_findings": ["Chart maps directly to approved claim"],
                "rubric": {
                    "charts_map_to_claims": True,
                    "visual_message_clear": True,
                },
            }
        ),
    )
    assert (
        _run_analysis_cli(
            capsys,
            "validate-refine",
            "--workspace",
            str(workspace),
            "--hypothesis-id",
            "1",
        )["status"]
        == "PASS"
    )

    reflection = _run_analysis_cli(
        capsys,
        "draft-reflection",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--experiment-id",
        "1",
    )["reflection"]
    assert "frame" in reflection["what_worked"][0]["content"]
    assert reflection["reusable_methods"][0]["recommended_steps"]

    promoted = _run_analysis_cli(
        capsys,
        "promote-reflection",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
    )
    lessons = (
        workspace / ".agentsociety" / "memory" / "project_lessons.jsonl"
    ).read_text(encoding="utf-8")
    recipe = next(
        (workspace / ".agentsociety" / "memory" / "method_recipes").glob("*.md")
    )
    assert "Phase gates passed" in lessons
    assert "Does treatment increase simulated value" in recipe.read_text(
        encoding="utf-8"
    )
    assert promoted["preference_keys"] == []

    loop = _run_analysis_cli(
        capsys,
        "run-loop",
        "--workspace",
        str(workspace),
        "--hypothesis-id",
        "1",
        "--experiment-id",
        "1",
    )
    assert loop["memory_context"]["active"] is True
    assert loop["memory_context"]["recent_lessons"]
    assert loop["memory_context"]["method_recipes"]
    assert loop["recommended_next_step"].startswith("0. Memory:")


def test_compose_figure_grid_layout(tmp_path):
    image_module = pytest.importorskip("PIL.Image")

    chart_a = tmp_path / "chart_01_a.png"
    chart_b = tmp_path / "chart_02_b.png"
    image_module.new("RGB", (320, 200), "#ccddee").save(chart_a)
    image_module.new("RGB", (180, 260), "#f4c095").save(chart_b)

    spec_path = tmp_path / "figure_01_summary.json"
    spec_path.write_text(
        json.dumps(
            {
                "output": "figure_01_summary.png",
                "canvas": {"width": 1000, "height": 700, "background": "#FFFFFF"},
                "layout": {
                    "type": "grid",
                    "rows": 1,
                    "cols": 2,
                    "padding": 40,
                    "gap": 20,
                },
                "panels": [
                    {"source": chart_a.name, "label": "a"},
                    {"source": chart_b.name, "label": "b"},
                ],
            }
        ),
        encoding="utf-8",
    )

    result = analysis_cli._compose_figure(spec_path)

    output_path = Path(result["output"])
    metadata_path = Path(result["metadata"])
    assert output_path.exists()
    assert metadata_path.exists()

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["layout"]["type"] == "grid"
    assert [panel["label"] for panel in metadata["panels"]] == ["a", "b"]


def test_compose_figure_manual_layout_writes_output(tmp_path):
    image_module = pytest.importorskip("PIL.Image")

    chart_path = tmp_path / "chart_01_main.png"
    image_module.new("RGB", (400, 240), "#9ec5ab").save(chart_path)

    spec_path = tmp_path / "figure_02_manual.json"
    spec_path.write_text(
        json.dumps(
            {
                "output": "figure_02_manual.png",
                "layout": {"type": "manual"},
                "panels": [
                    {
                        "source": chart_path.name,
                        "label": "a",
                        "box": {"x": 60, "y": 60, "width": 500, "height": 300},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    result = analysis_cli._compose_figure(spec_path)
    assert Path(result["output"]).exists()
