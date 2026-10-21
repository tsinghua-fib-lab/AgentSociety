"""Shared checks for onboarding examples (fail loud, no silent LLM collapse)."""

from __future__ import annotations

import shutil
from pathlib import Path

_FAILURE_MARKERS = (
    "CRITICAL FAILURE",
    "LLMDispatchError",
    "Failed to get valid response after",
    "No deployments available for selected model",
)


def fresh_run_dir(path: Path) -> Path:
    """Remove ``path`` if present and return it (caller creates as needed).

    :param path: Target run directory path.
    :returns: The same ``path`` after deletion (if it existed).
    """
    if path.exists():
        shutil.rmtree(path)
    return path


def find_critical_failures(run_dir: Path) -> list[str]:
    """Return relative paths under ``run_dir`` that contain LLM collapse markers.

    :param run_dir: Experiment run directory to scan.
    :returns: Relative file paths containing known failure markers.
    """
    root = Path(run_dir)
    if not root.is_dir():
        return []
    hits: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".log", ".json", ".jsonl", ".txt", ".md"}:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if any(marker in text for marker in _FAILURE_MARKERS):
            hits.append(str(path.relative_to(root)))
    return hits


def require_no_critical_failures(run_dir: Path) -> None:
    """Raise ``SystemExit(1)`` when agent/env artifacts show LLM dispatch collapse.

    :param run_dir: Experiment run directory to scan.
    :raises SystemExit: When any artifact contains a critical failure marker.
    """
    hits = find_critical_failures(run_dir)
    if hits:
        preview = ", ".join(hits[:8])
        more = "" if len(hits) <= 8 else f" (+{len(hits) - 8} more)"
        print(
            f"ERROR: LLM critical failure markers in run artifacts: {preview}{more}",
            flush=True,
        )
        raise SystemExit(1)
