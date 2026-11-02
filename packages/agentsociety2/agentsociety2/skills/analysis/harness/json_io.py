from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

from agentsociety2.agent.json_utils import loads_llm_json

T = TypeVar("T", bound=BaseModel)


def atomic_write_json(path: Path, payload: Any) -> None:
    """Atomically replace a JSON file after flushing its temporary file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(serialized)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def loads_json_text(text: str) -> Any:
    if not text or not str(text).strip():
        raise ValueError("empty JSON payload")
    return loads_llm_json(text, expect="any")


def loads_json_file(path: Path) -> Any:
    return loads_json_text(path.read_text(encoding="utf-8"))


def load_model_from_text(text: str, model: type[T]) -> T:
    try:
        raw = loads_json_text(text)
        return model.model_validate(raw)
    except (ValueError, ValidationError) as exc:
        raise ValueError(f"invalid JSON for {model.__name__}: {exc}") from exc


def load_model_from_file(path: Path, model: type[T]) -> T:
    try:
        raw = loads_json_file(path)
        return model.model_validate(raw)
    except (json.JSONDecodeError, ValueError, ValidationError) as exc:
        raise ValueError(f"invalid JSON file {path}: {exc}") from exc


def save_model_to_file(path: Path, model: BaseModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(model.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def load_dict_payload(text_or_path: str) -> dict[str, Any]:
    stripped = str(text_or_path).lstrip()
    if stripped.startswith("{"):
        raw = loads_json_text(text_or_path)
    else:
        path = Path(text_or_path)
        try:
            is_file = path.exists() and path.is_file()
        except OSError:
            is_file = False
        raw = loads_json_file(path) if is_file else loads_json_text(text_or_path)
    if not isinstance(raw, dict):
        raise ValueError("payload must be a JSON object")
    return raw
