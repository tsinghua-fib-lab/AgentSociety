from __future__ import annotations

from pathlib import Path

from agentsociety2.skills.analysis.data import DataReader
from agentsociety2.skills.analysis.harness.models import AnalysisPlan, ValidationResult
from agentsociety2.skills.analysis.harness.validators._helpers import (
    blocked,
    issue,
    passed,
)


def _run_table_checks(db_path: Path, plan: AnalysisPlan) -> list:
    issues = []
    if not plan.table_checks:
        return issues

    schema = DataReader(db_path).read_schema()
    for check in plan.table_checks:
        table = check.table.strip()
        if not table:
            continue
        if table not in schema.tables:
            issues.append(
                issue(
                    "table_read_failed",
                    phase="explore",
                    message=f"Cannot read table {table}: table not found",
                )
            )
            continue
        count = schema.row_counts.get(table, 0)
        if count < check.min_rows:
            issues.append(
                issue(
                    "min_rows_failed",
                    phase="explore",
                    message=f"Table {table} has {count} rows, need >= {check.min_rows}",
                )
            )
        available_columns = {column["name"] for column in schema.columns.get(table, [])}
        for col in check.columns:
            if col not in available_columns:
                issues.append(
                    issue(
                        "column_missing",
                        phase="explore",
                        message=f"Table {table} missing column {col}",
                    )
                )
    return issues


def validate_explore(
    workspace: Path,
    hypothesis_id: str,
    *,
    db_path: Path,
    plan: AnalysisPlan,
    data_dir: Path | None = None,
    recorded_artifacts: list[str] | None = None,
) -> ValidationResult:
    issues: list = []
    if not db_path.exists():
        issues.append(
            issue(
                "db_missing",
                phase="explore",
                message=f"Replay data not found: {db_path}",
            )
        )
        return blocked(issues)

    schema = DataReader(db_path).read_schema()
    available = set(schema.tables)

    for table in plan.target_tables:
        if table not in available:
            issues.append(
                issue(
                    "target_table_missing",
                    phase="explore",
                    message=f"Target table not in database: {table}",
                )
            )
        else:
            count = schema.row_counts.get(table, 0)
            if count < 1:
                issues.append(
                    issue(
                        "target_table_empty",
                        phase="explore",
                        message=f"Target table {table} has no rows",
                    )
                )

    if recorded_artifacts:
        data_root = data_dir.resolve() if data_dir is not None else None
        for recorded in recorded_artifacts:
            path = Path(recorded)
            resolved = path.resolve()
            if data_root is not None and data_root not in resolved.parents:
                issues.append(
                    issue(
                        "phase_artifact_outside_data_dir",
                        phase="explore",
                        message=f"Explore artifact is outside data/: {recorded}",
                        fix_hint="Register files generated under presentation/hypothesis_{id}/data",
                    )
                )
            elif path.suffix.lower() not in {".md", ".html", ".csv"}:
                issues.append(
                    issue(
                        "phase_artifact_unrecognized",
                        phase="explore",
                        message=f"Unrecognized EDA artifact type: {recorded}",
                        fix_hint="Register eda_quick_stats.md, eda_*.html, or EDA CSV outputs",
                    )
                )
            elif not resolved.exists():
                issues.append(
                    issue(
                        "phase_artifact_missing",
                        phase="explore",
                        message=f"Recorded explore artifact missing: {recorded}",
                        fix_hint="Re-run run-eda and record-phase-artifacts",
                    )
                )
    elif data_dir is not None:
        if not data_dir.exists():
            issues.append(
                issue(
                    "explore_output_dir_missing",
                    phase="explore",
                    message=f"Explore output directory not found: {data_dir}",
                    fix_hint="Run intake and run-eda before validate-explore",
                )
            )
        elif not any(data_dir.iterdir()):
            issues.append(
                issue(
                    "explore_output_empty",
                    phase="explore",
                    message=f"No files under {data_dir}",
                    fix_hint="Run run-eda and record-phase-artifacts with output paths",
                )
            )

    issues.extend(_run_table_checks(db_path, plan))

    if issues:
        return blocked(
            issues, recommended_next_step="Fix data/EDA artifacts then validate-explore"
        )
    return passed()
