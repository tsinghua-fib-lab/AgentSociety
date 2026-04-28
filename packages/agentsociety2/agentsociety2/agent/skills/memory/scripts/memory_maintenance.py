#!/usr/bin/env python3
"""Apply forgetting-curve and ACT-R style maintenance to state/memory.jsonl."""

from __future__ import annotations

import argparse
import json
import math
import os
import time
from pathlib import Path
from typing import Any


def clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-file", required=True)
    parser.add_argument("--current-tick", type=int, required=True)
    parser.add_argument("--strength", type=float, default=None)
    parser.add_argument("--decay", type=float, default=None)
    parser.add_argument("--retrieval-threshold", type=float, default=None)
    parser.add_argument("--max-entries", type=int, default=None)
    return parser.parse_args()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def importance_multiplier(importance: str) -> float:
    if importance == "high":
        return 1.5
    if importance == "low":
        return 0.5
    return 1.0


def _presentations(item: dict[str, Any]) -> list[int]:
    raw = item.get("_presentations")
    if isinstance(raw, list):
        out: list[int] = []
        for value in raw:
            try:
                out.append(int(value))
            except (TypeError, ValueError):
                continue
        if out:
            return out
    try:
        return [int(item.get("tick", 0))]
    except (TypeError, ValueError):
        return [0]


def base_retention(current_tick: int, item: dict[str, Any], strength: float) -> float:
    item_tick = int(item.get("tick", current_tick))
    age = max(0, current_tick - item_tick)
    imp = str(item.get("importance", "medium")).lower()
    mult = importance_multiplier(imp)
    denom = max(1.0, strength * mult)
    return math.exp(-(age / denom))


def base_level_activation(
    current_tick: int,
    item: dict[str, Any],
    decay: float,
    retrieval_threshold: float,
) -> tuple[float, float]:
    """Return ACT-R style base-level activation and retrieval probability."""
    terms: list[float] = []
    for presented_at in _presentations(item):
        lag = max(1, current_tick - presented_at)
        terms.append(lag ** (-decay))

    activation = math.log(sum(terms)) if terms else -10.0

    imp = str(item.get("importance", "medium")).lower()
    activation += math.log(max(0.1, importance_multiplier(imp)))

    access_count = int(item.get("_access_count", 0))
    activation += 0.08 * min(10, access_count)

    # Logistic mapping keeps a continuous retrieval signal while preserving a
    # readable activation value for debugging.
    retrieval_probability = 1.0 / (1.0 + math.exp(-(activation - retrieval_threshold)))
    return activation, clamp(retrieval_probability)


def retention_value(
    current_tick: int,
    item: dict[str, Any],
    strength: float,
    decay: float,
    retrieval_threshold: float,
) -> tuple[float, float, float, float]:
    ebbinghaus = base_retention(current_tick, item, strength)
    activation, retrieval_probability = base_level_activation(
        current_tick,
        item,
        decay,
        retrieval_threshold,
    )
    # Keep the Ebbinghaus curve as a conservative forgetting floor, while ACT-R
    # activation lets repeated presentation or retrieval preserve useful facts.
    combined = max(ebbinghaus, retrieval_probability)
    return clamp(combined, 0.0, 0.98), ebbinghaus, activation, retrieval_probability


def main() -> int:
    args = parse_args()
    path = Path(args.memory_file)

    strength = args.strength
    if strength is None:
        try:
            strength = float(os.getenv("AGENT_MEMORY_STRENGTH", "100"))
        except ValueError:
            strength = 100.0

    max_entries = args.max_entries
    if max_entries is None:
        try:
            max_entries = int(os.getenv("AGENT_MEMORY_MAX_ENTRIES", "1000"))
        except ValueError:
            max_entries = 1000

    decay = args.decay
    if decay is None:
        try:
            decay = float(os.getenv("AGENT_MEMORY_ACTR_DECAY", "0.5"))
        except ValueError:
            decay = 0.5

    retrieval_threshold = args.retrieval_threshold
    if retrieval_threshold is None:
        try:
            retrieval_threshold = float(
                os.getenv("AGENT_MEMORY_RETRIEVAL_THRESHOLD", "-2.5")
            )
        except ValueError:
            retrieval_threshold = -2.5

    rows = read_jsonl(path)
    processed: list[dict[str, Any]] = []

    for row in rows:
        r, ebbinghaus, activation, retrieval_probability = retention_value(
            args.current_tick,
            row,
            strength,
            decay,
            retrieval_threshold,
        )
        if r < 0.1:
            continue
        row.setdefault("_presentations", _presentations(row))
        row["_retention"] = round(r, 4)
        row["_ebbinghaus_retention"] = round(ebbinghaus, 4)
        row["_activation"] = round(activation, 4)
        row["_retrieval_probability"] = round(retrieval_probability, 4)
        row["_faded"] = bool(0.1 < r < 0.5)
        row["_maintained_at_unix"] = int(time.time())
        processed.append(row)

    if len(processed) > max_entries:
        processed.sort(key=lambda x: float(x.get("_retention", 0.0)), reverse=True)
        processed = processed[:max_entries]
        processed.sort(key=lambda x: int(x.get("tick", 0)))

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(row, ensure_ascii=False) for row in processed]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "entries_before": len(rows),
                "entries_after": len(processed),
                "strength": strength,
                "actr_decay": decay,
                "retrieval_threshold": retrieval_threshold,
                "max_entries": max_entries,
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
