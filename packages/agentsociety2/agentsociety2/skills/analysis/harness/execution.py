from __future__ import annotations

import dataclasses
import errno
import hashlib
import json
import os
import socket
import sys
import time
import uuid
from collections.abc import Callable, Iterable, Iterator, Mapping
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agentsociety2.skills.analysis.harness.json_io import (
    atomic_write_json,
    load_model_from_file,
    loads_json_text,
)
from agentsociety2.skills.analysis.harness.operations import AnalysisOperationSpec
from agentsociety2.skills.analysis.harness.paths import (
    analysis_operation_lock_path,
    analysis_run_path,
    analysis_runs_dir,
    hypothesis_state_path,
    synthesis_state_path,
)
from agentsociety2.skills.analysis.harness.preflight import OperationAvailability

OutcomeStatus = Literal["SUCCEEDED", "BLOCKED", "FAILED", "SKIPPED", "UNCHANGED"]
ReceiptStatus = Literal[
    "PLANNED",
    "RUNNING",
    "SUCCEEDED",
    "BLOCKED",
    "FAILED",
    "SKIPPED",
    "UNCHANGED",
    "INTERRUPTED",
]

_SUCCESS_STATUSES = {"SUCCEEDED", "SKIPPED", "UNCHANGED"}
_RESULT_STATUS_MAP: dict[str, OutcomeStatus] = {
    "BLOCKED": "BLOCKED",
    "FAILED": "FAILED",
    "SKIPPED": "SKIPPED",
    "UNCHANGED": "UNCHANGED",
}
_SAFE_INPUT_NAMES = {
    "hypothesis_id",
    "experiment_id",
    "phase",
    "target",
    "type",
    "topic",
    "name",
    "include_preferences",
    "include_embedded_data",
    "skip_recipes",
    "skip_lessons",
}
_SENSITIVE_INPUT_NAMES = {"payload", "sql", "code"}
_SAFE_RESULT_KEYS = {
    "status",
    "reason",
    "phase",
    "current_phase",
    "effective_phase",
    "hypothesis_id",
    "hypothesis_release",
    "scope",
    "verdict",
    "overall_score",
    "recommended_next_step",
    "source_count",
    "section_counts",
    "executed_steps",
    "skipped_steps",
    "copied",
    "missing",
    "updated",
    "tabs",
    "asset_count",
    "assets_dir",
    "embedded_data_included",
}
_RESULT_PATH_KEYS = {
    "path",
    "paths",
    "files",
    "artifacts",
    "recipe_paths",
    "manifest_path",
    "reflection_path",
    "memory_dir",
    "assets_dir",
    "evidence_index",
    "report_context",
    "snippet",
    "output",
    "metadata",
}


class OperationFailure(BaseModel):
    model_config = ConfigDict(frozen=True)

    type: str
    message: str
    retryable: bool = False


class OperationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    operation_id: str
    status: OutcomeStatus
    run_id: str = ""
    started_at: datetime
    completed_at: datetime
    duration_ms: int = 0
    preflight: dict[str, Any] | None = None
    result: dict[str, Any] = Field(default_factory=dict)
    error: OperationFailure | None = None
    artifact_fingerprints: dict[str, str] = Field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status in _SUCCESS_STATUSES

    @property
    def exit_code(self) -> int:
        if self.success:
            return 0
        if self.status == "BLOCKED":
            return 2
        return 1


class OperationRunReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 2
    run_id: str
    operation_id: str
    operation_contract_version: int = 1
    execution_key: str = ""
    attempt: int = 1
    deduplicated_from_run_id: str = ""
    status: ReceiptStatus = "PLANNED"
    hypothesis_id: str = ""
    experiment_id: str = ""
    input_names: tuple[str, ...] = Field(default_factory=tuple)
    input_fingerprint: str
    safe_inputs: dict[str, Any] = Field(default_factory=dict)
    preflight: dict[str, Any] | None = None
    result_summary: dict[str, Any] = Field(default_factory=dict)
    error: OperationFailure | None = None
    declared_artifacts: tuple[str, ...] = Field(default_factory=tuple)
    artifact_fingerprints: dict[str, str] = Field(default_factory=dict)
    repeatable: bool = True
    retryable: bool = False
    recommended_action: str = ""
    pid: int = 0
    hostname: str = ""
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None
    duration_ms: int = 0


def _jsonable(value: Any) -> Any:
    def json_default(item: Any) -> Any:
        if isinstance(item, Path):
            return str(item)
        if isinstance(item, datetime):
            return item.isoformat()
        if isinstance(item, BaseModel):
            return item.model_dump(mode="json")
        if dataclasses.is_dataclass(item) and not isinstance(item, type):
            return dataclasses.asdict(item)
        return str(item)

    return json.loads(json.dumps(value, ensure_ascii=False, default=json_default))


def _canonical_input_value(
    spec: AnalysisOperationSpec,
    key: str,
    value: Any,
) -> Any:
    input_spec = next((item for item in spec.inputs if item.name == key), None)
    if input_spec is None or value is None:
        return _jsonable(value)
    if input_spec.kind == "path" and isinstance(value, (str, Path)):
        return str(Path(value).resolve())
    if input_spec.kind not in {"json_object", "json_array", "string_or_path"}:
        return _jsonable(value)
    if not isinstance(value, (str, Path)):
        return _jsonable(value)
    if input_spec.kind in {"json_object", "json_array"} and str(
        value
    ).lstrip().startswith(("{", "[")):
        try:
            return _jsonable(loads_json_text(str(value)))
        except (TypeError, ValueError):
            return _jsonable(value)
    path = Path(value)
    try:
        if not path.is_file():
            return _jsonable(value)
    except OSError:
        return _jsonable(value)
    resolved = path.resolve()
    try:
        digest = hashlib.sha256(resolved.read_bytes()).hexdigest()
    except OSError as exc:
        return {"path": str(resolved), "read_error": type(exc).__name__}
    return {
        "path": str(resolved),
        "sha256": digest,
    }


def _input_fingerprint(
    spec: AnalysisOperationSpec,
    values: Mapping[str, Any],
) -> str:
    payload: dict[str, Any] = {}
    declared_names = {input_spec.name for input_spec in spec.inputs}
    for input_spec in spec.inputs:
        if input_spec.name in values:
            value = values[input_spec.name]
        elif input_spec.action == "store_true":
            value = False
        else:
            value = input_spec.default
        payload[input_spec.name] = _canonical_input_value(
            spec,
            input_spec.name,
            value,
        )
    for key, value in sorted(values.items()):
        if key in declared_names or key in {"command", "dry_run"}:
            continue
        payload[key] = _canonical_input_value(spec, key, value)
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8", errors="replace")
    ).hexdigest()


def operation_execution_key(
    spec: AnalysisOperationSpec,
    values: Mapping[str, Any],
) -> str:
    return _execution_key(spec, _input_fingerprint(spec, values))


def _execution_key(
    spec: AnalysisOperationSpec,
    input_fingerprint: str,
) -> str:
    identity = f"{spec.id}\0{spec.contract_version}\0{input_fingerprint}"
    return hashlib.sha256(identity.encode("utf-8", errors="replace")).hexdigest()


@contextmanager
def operation_lock(path: Path) -> Iterator[bool]:
    """Try to hold one cross-process lock without waiting for another operation."""

    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_CREAT | os.O_RDWR, 0o600)
    acquired = False
    try:
        if os.fstat(fd).st_size == 0:
            os.write(fd, b"\0")
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno not in {errno.EACCES, errno.EAGAIN}:
                raise
            yield False
            return
        acquired = True
        yield True
    finally:
        if acquired:
            os.lseek(fd, 0, os.SEEK_SET)
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _safe_inputs(values: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _jsonable(value)
        for key, value in values.items()
        if key in _SAFE_INPUT_NAMES
        and isinstance(value, (str, int, float, bool, type(None)))
    }


def _iter_string_values(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
        stripped = value.lstrip()
        if stripped.startswith(("{", "[")):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError):
                return
            yield from _iter_string_values(parsed)
    elif isinstance(value, Mapping):
        for nested in value.values():
            yield from _iter_string_values(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _iter_string_values(nested)


def _redact_message(message: str, values: Mapping[str, Any]) -> str:
    redacted = message
    sensitive_tokens = {
        token
        for key, value in values.items()
        if key in _SENSITIVE_INPUT_NAMES
        for token in _iter_string_values(value)
        if len(token) >= 4
    }
    for token in sorted(sensitive_tokens, key=len, reverse=True):
        redacted = redacted.replace(token, "[REDACTED]")
    return redacted


def _safe_result_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for key in sorted(_SAFE_RESULT_KEYS):
        if key not in result:
            continue
        value = result[key]
        if isinstance(value, str):
            summary[key] = value[:500]
        elif isinstance(value, (int, float, bool, type(None))):
            summary[key] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            summary[key] = value[:50]
        elif key == "section_counts" and isinstance(value, dict):
            summary[key] = _jsonable(value)
    return summary


def _new_run_id() -> str:
    timestamp = datetime.now(UTC).strftime("%Y%m%dt%H%M%S")
    return f"run_{timestamp}_{uuid.uuid4().hex[:10]}"


def save_run_receipt(workspace: Path, receipt: OperationRunReceipt) -> Path:
    receipt.updated_at = datetime.now(UTC)
    path = analysis_run_path(workspace, receipt.run_id)
    atomic_write_json(path, receipt.model_dump(mode="json"))
    return path


def load_run_receipt(workspace: Path, run_id: str) -> OperationRunReceipt:
    path = analysis_run_path(workspace, run_id)
    if not path.is_file():
        raise FileNotFoundError(f"analysis run receipt not found: {run_id}")
    return load_model_from_file(path, OperationRunReceipt)


def _pid_is_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def recover_interrupted_runs(workspace: Path) -> list[str]:
    runs_dir = analysis_runs_dir(workspace)
    if not runs_dir.is_dir():
        return []
    current_host = socket.gethostname()
    recovered: list[str] = []
    for path in sorted(runs_dir.glob("*.json")):
        receipt = load_model_from_file(path, OperationRunReceipt)
        if (
            receipt.status != "RUNNING"
            or receipt.hostname != current_host
            or _pid_is_alive(receipt.pid)
        ):
            continue
        now = datetime.now(UTC)
        receipt.status = "INTERRUPTED"
        receipt.completed_at = now
        receipt.duration_ms = max(
            0,
            int((now - receipt.started_at).total_seconds() * 1000),
        )
        receipt.retryable = receipt.repeatable
        receipt.recommended_action = (
            "Rerun the operation after preflight; automatic payload replay is disabled."
            if receipt.repeatable
            else "Inspect artifacts manually; this operation is not repeatable."
        )
        receipt.error = OperationFailure(
            type="InterruptedOperation",
            message="The process that started this operation is no longer running.",
            retryable=receipt.repeatable,
        )
        save_run_receipt(workspace, receipt)
        recovered.append(receipt.run_id)
    return recovered


def list_run_receipts(
    workspace: Path,
    *,
    hypothesis_id: str | None = None,
    limit: int | None = 10,
    recover_interrupted: bool = True,
) -> list[OperationRunReceipt]:
    if recover_interrupted:
        recover_interrupted_runs(workspace)
    runs_dir = analysis_runs_dir(workspace)
    if not runs_dir.is_dir():
        return []
    receipts = [
        load_model_from_file(path, OperationRunReceipt)
        for path in runs_dir.glob("*.json")
    ]
    if hypothesis_id is not None:
        receipts = [item for item in receipts if item.hypothesis_id == hypothesis_id]
    receipts.sort(key=lambda item: item.started_at, reverse=True)
    return receipts if limit is None else receipts[: max(0, limit)]


def unresolved_retryable_runs(
    receipts: Iterable[OperationRunReceipt],
    *,
    limit: int = 10,
) -> list[OperationRunReceipt]:
    unresolved: list[OperationRunReceipt] = []
    seen: set[str] = set()
    for receipt in receipts:
        identity = receipt.execution_key or (
            f"legacy:{receipt.operation_id}:{receipt.operation_contract_version}:"
            f"{receipt.input_fingerprint}"
        )
        if identity in seen:
            continue
        seen.add(identity)
        if receipt.retryable:
            unresolved.append(receipt)
    return unresolved[: max(0, limit)]


def _receipt_matches_execution(
    receipt: OperationRunReceipt,
    candidate: OperationRunReceipt,
) -> bool:
    if receipt.execution_key and candidate.execution_key:
        return receipt.execution_key == candidate.execution_key
    return (
        receipt.operation_id == candidate.operation_id
        and receipt.operation_contract_version == candidate.operation_contract_version
        and receipt.input_fingerprint == candidate.input_fingerprint
    )


def _related_run_receipts(
    workspace: Path,
    receipt: OperationRunReceipt,
) -> list[OperationRunReceipt]:
    return [
        candidate
        for candidate in list_run_receipts(workspace, limit=None)
        if _receipt_matches_execution(receipt, candidate)
    ]


def _normalize_status(result: Mapping[str, Any]) -> OutcomeStatus:
    raw_status = str(result.get("status", "")).upper()
    if raw_status in _RESULT_STATUS_MAP:
        return _RESULT_STATUS_MAP[raw_status]
    if result.get("error"):
        if raw_status == "BLOCKED" or "blocked" in str(result["error"]).lower():
            return "BLOCKED"
        return "FAILED"
    return "SUCCEEDED"


def _result_error(
    status: OutcomeStatus,
    result: Mapping[str, Any],
    *,
    repeatable: bool,
) -> OperationFailure | None:
    if status not in {"BLOCKED", "FAILED"}:
        return None
    message = str(
        result.get("error")
        or result.get("recommended_next_step")
        or f"operation finished with status {status}"
    )
    return OperationFailure(
        type="OperationBlocked" if status == "BLOCKED" else "OperationFailed",
        message=message,
        retryable=repeatable,
    )


def _candidate_result_paths(result: Mapping[str, Any]) -> Iterable[str]:
    for key, value in result.items():
        normalized_key = key.lower()
        is_path_key = normalized_key in _RESULT_PATH_KEYS or normalized_key.endswith(
            ("_path", "_paths")
        )
        if not is_path_key:
            continue
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            yield from (item for item in value if isinstance(item, str))


def _declared_artifact_paths(
    spec: AnalysisOperationSpec,
    workspace: Path,
    values: Mapping[str, Any],
) -> Iterable[Path]:
    hypothesis_id = str(values.get("hypothesis_id") or "")
    for template in spec.produced_artifacts:
        if "/" not in template or " " in template:
            continue
        rendered = template.replace("{id}", hypothesis_id).replace(
            "{hypothesis_id}", hypothesis_id
        )
        if any(char in rendered for char in "*?["):
            yield from workspace.glob(rendered)
        else:
            yield workspace / rendered


def _hash_workspace_files(
    workspace: Path,
    paths: Iterable[Path],
) -> dict[str, str]:
    workspace = workspace.resolve()
    files: set[Path] = set()
    for path in paths:
        resolved = path.resolve()
        try:
            resolved.relative_to(workspace)
        except ValueError:
            continue
        if resolved.is_file():
            files.add(resolved)
        elif resolved.is_dir():
            files.update(
                item.resolve() for item in resolved.rglob("*") if item.is_file()
            )
    return {
        path.relative_to(workspace).as_posix(): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in sorted(files)
    }


def collect_operation_artifacts(
    spec: AnalysisOperationSpec,
    workspace: Path,
    values: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, str]:
    paths = list(_declared_artifact_paths(spec, workspace, values))
    for raw_path in _candidate_result_paths(result):
        path = Path(raw_path)
        paths.append(path if path.is_absolute() else workspace / path)
    hypothesis_id = str(values.get("hypothesis_id") or "")
    if spec.mutates_workspace and hypothesis_id:
        paths.append(hypothesis_state_path(workspace, hypothesis_id))
    if spec.mutates_workspace and spec.scope == "workspace":
        paths.append(synthesis_state_path(workspace))
    return _hash_workspace_files(workspace, paths)


def _receipt_for(
    spec: AnalysisOperationSpec,
    values: Mapping[str, Any],
    preflight: OperationAvailability | None,
    started_at: datetime,
) -> OperationRunReceipt:
    input_fingerprint = _input_fingerprint(spec, values)
    return OperationRunReceipt(
        run_id=_new_run_id(),
        operation_id=spec.id,
        operation_contract_version=spec.contract_version,
        execution_key=_execution_key(spec, input_fingerprint),
        status="PLANNED",
        hypothesis_id=str(values.get("hypothesis_id") or ""),
        experiment_id=str(values.get("experiment_id") or ""),
        input_names=tuple(
            sorted(
                key
                for key, value in values.items()
                if key not in {"command", "dry_run"} and value is not None
            )
        ),
        input_fingerprint=input_fingerprint,
        safe_inputs=_safe_inputs(values),
        preflight=preflight.model_dump(mode="json") if preflight else None,
        declared_artifacts=spec.produced_artifacts,
        repeatable=spec.repeatable,
        pid=os.getpid(),
        hostname=socket.gethostname(),
        started_at=started_at,
    )


def _operation_conflict_outcome(
    spec: AnalysisOperationSpec,
    *,
    workspace: Path,
    receipt: OperationRunReceipt,
    preflight: OperationAvailability | None,
    started_at: datetime,
    started_clock: float,
) -> OperationOutcome:
    active = next(
        (
            candidate
            for candidate in _related_run_receipts(workspace, receipt)
            if candidate.status == "RUNNING"
        ),
        None,
    )
    completed_at = datetime.now(UTC)
    error = OperationFailure(
        type="OperationAlreadyRunning",
        message=f"The same {spec.id} operation is already running.",
        retryable=True,
    )
    return OperationOutcome(
        operation_id=spec.id,
        status="BLOCKED",
        run_id=active.run_id if active is not None else "",
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=max(0, int((time.perf_counter() - started_clock) * 1000)),
        preflight=preflight.model_dump(mode="json") if preflight else None,
        result={
            "status": "BLOCKED",
            "reason": "operation_already_running",
            "active_run_id": active.run_id if active is not None else "",
        },
        error=error,
    )


def _deduplicated_outcome(
    spec: AnalysisOperationSpec,
    *,
    workspace: Path,
    receipt: OperationRunReceipt,
    prior: OperationRunReceipt,
    preflight: OperationAvailability | None,
    started_at: datetime,
    started_clock: float,
) -> OperationOutcome:
    completed_at = datetime.now(UTC)
    duration_ms = max(0, int((time.perf_counter() - started_clock) * 1000))
    result = {
        "status": "UNCHANGED",
        "reason": "non_repeatable_operation_already_succeeded",
        "prior_run_id": prior.run_id,
    }
    receipt.status = "UNCHANGED"
    receipt.deduplicated_from_run_id = prior.run_id
    receipt.result_summary = _safe_result_summary(result)
    receipt.artifact_fingerprints = prior.artifact_fingerprints
    receipt.retryable = False
    receipt.recommended_action = (
        "Use the existing successful run; change the operation inputs only if a new "
        "execution is intended."
    )
    receipt.completed_at = completed_at
    receipt.duration_ms = duration_ms
    save_run_receipt(workspace, receipt)
    return OperationOutcome(
        operation_id=spec.id,
        status="UNCHANGED",
        run_id=receipt.run_id,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        preflight=preflight.model_dump(mode="json") if preflight else None,
        result=result,
        artifact_fingerprints=prior.artifact_fingerprints,
    )


def _execute_available_operation(
    spec: AnalysisOperationSpec,
    *,
    workspace: Path | None,
    values: Mapping[str, Any],
    preflight: OperationAvailability | None,
    invoke: Callable[[], Mapping[str, Any]],
    should_persist: bool,
    receipt: OperationRunReceipt,
    started_at: datetime,
    started_clock: float,
) -> OperationOutcome:
    if should_persist and workspace is not None:
        related = _related_run_receipts(workspace, receipt)
        receipt.attempt = (
            max((candidate.attempt for candidate in related), default=0) + 1
        )
        prior_success = next(
            (candidate for candidate in related if candidate.status == "SUCCEEDED"),
            None,
        )
        if not spec.repeatable and prior_success is not None:
            return _deduplicated_outcome(
                spec,
                workspace=workspace,
                receipt=receipt,
                prior=prior_success,
                preflight=preflight,
                started_at=started_at,
                started_clock=started_clock,
            )
        receipt.status = "RUNNING"
        save_run_receipt(workspace, receipt)

    result: dict[str, Any] = {}
    error: OperationFailure | None = None
    try:
        result = dict(_jsonable(dict(invoke())))
        status = _normalize_status(result)
        error = _result_error(status, result, repeatable=spec.repeatable)
        if error is not None:
            error = error.model_copy(
                update={"message": _redact_message(error.message, values)}
            )
    except Exception as exc:
        status = "FAILED"
        error = OperationFailure(
            type=type(exc).__name__,
            message=_redact_message(str(exc), values),
            retryable=spec.repeatable,
        )

    artifact_fingerprints: dict[str, str] = {}
    if workspace is not None and workspace.is_dir():
        try:
            artifact_fingerprints = collect_operation_artifacts(
                spec,
                workspace,
                values,
                result,
            )
        except Exception as exc:
            status = "FAILED"
            error = OperationFailure(
                type="ArtifactFingerprintError",
                message=_redact_message(str(exc), values),
                retryable=spec.repeatable,
            )
    completed_at = datetime.now(UTC)
    duration_ms = max(0, int((time.perf_counter() - started_clock) * 1000))
    outcome = OperationOutcome(
        operation_id=spec.id,
        status=status,
        run_id=receipt.run_id if should_persist else "",
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=duration_ms,
        preflight=preflight.model_dump(mode="json") if preflight else None,
        result=result,
        error=error,
        artifact_fingerprints=artifact_fingerprints,
    )

    if should_persist and workspace is not None:
        receipt.status = status
        receipt.result_summary = _safe_result_summary(result)
        receipt.error = error
        receipt.artifact_fingerprints = artifact_fingerprints
        receipt.completed_at = completed_at
        receipt.duration_ms = duration_ms
        receipt.retryable = status in {"FAILED", "BLOCKED"} and spec.repeatable
        if receipt.retryable:
            receipt.recommended_action = (
                "Rerun the operation after preflight; automatic payload replay is "
                "disabled."
            )
        save_run_receipt(workspace, receipt)
    return outcome


def execute_operation(
    spec: AnalysisOperationSpec,
    *,
    workspace: Path | None,
    values: Mapping[str, Any],
    preflight: OperationAvailability | None,
    invoke: Callable[[], Mapping[str, Any]],
    persist_receipt: bool,
) -> OperationOutcome:
    started_at = datetime.now(UTC)
    started_clock = time.perf_counter()
    should_persist = bool(
        persist_receipt
        and spec.mutates_workspace
        and workspace is not None
        and workspace.is_dir()
    )
    receipt = _receipt_for(spec, values, preflight, started_at)

    if preflight is not None and not preflight.available:
        completed_at = datetime.now(UTC)
        preflight_error = OperationFailure(
            type=preflight.status,
            message=_redact_message(
                "; ".join(preflight.reasons) or preflight.status,
                values,
            ),
            retryable=spec.repeatable,
        )
        outcome = OperationOutcome(
            operation_id=spec.id,
            status="BLOCKED",
            run_id=receipt.run_id if should_persist else "",
            started_at=started_at,
            completed_at=completed_at,
            duration_ms=max(0, int((time.perf_counter() - started_clock) * 1000)),
            preflight=preflight.model_dump(mode="json"),
            error=preflight_error,
        )
        if should_persist and workspace is not None:
            receipt.status = "BLOCKED"
            receipt.error = preflight_error
            receipt.retryable = spec.repeatable
            receipt.recommended_action = (
                "Fix preflight blockers and rerun the operation."
            )
            receipt.completed_at = completed_at
            receipt.duration_ms = outcome.duration_ms
            save_run_receipt(workspace, receipt)
        return outcome

    if should_persist and workspace is not None:
        lock_path = analysis_operation_lock_path(workspace, receipt.execution_key)
        with operation_lock(lock_path) as acquired:
            if not acquired:
                return _operation_conflict_outcome(
                    spec,
                    workspace=workspace,
                    receipt=receipt,
                    preflight=preflight,
                    started_at=started_at,
                    started_clock=started_clock,
                )
            return _execute_available_operation(
                spec,
                workspace=workspace,
                values=values,
                preflight=preflight,
                invoke=invoke,
                should_persist=True,
                receipt=receipt,
                started_at=started_at,
                started_clock=started_clock,
            )
    return _execute_available_operation(
        spec,
        workspace=workspace,
        values=values,
        preflight=preflight,
        invoke=invoke,
        should_persist=False,
        receipt=receipt,
        started_at=started_at,
        started_clock=started_clock,
    )
