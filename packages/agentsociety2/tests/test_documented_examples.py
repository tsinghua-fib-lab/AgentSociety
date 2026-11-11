"""Run the real script included in the storage guide without model credentials."""

import json
import os
import runpy
import subprocess
import sys
from pathlib import Path

import pytest

EXAMPLE = Path(__file__).resolve().parents[1] / "examples/offline/replay_round_trip.py"


@pytest.mark.asyncio
async def test_documented_replay_example_creates_readable_artifacts(
    tmp_path: Path,
) -> None:
    example = runpy.run_path(str(EXAMPLE))
    rows = await example["round_trip"](tmp_path / "replay")
    assert rows == [{"id": 1, "value": 3.5}]
    metadata = json.loads((tmp_path / "replay/_schema.json").read_text())
    assert metadata["datasets"]["example.observations"]["entity_key"] == "id"
    assert list((tmp_path / "replay").glob("observations.*.jsonl"))


def test_documented_replay_cli_needs_no_model_credentials(tmp_path: Path) -> None:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AGENTSOCIETY_") and key != "LITERATURE_SEARCH_API_KEY"
    }
    env.update(
        TMPDIR=str(tmp_path), MEM0_TELEMETRY="False", ANONYMIZED_TELEMETRY="False"
    )
    result = subprocess.run(
        [sys.executable, str(EXAMPLE)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    assert result.stdout.strip() == "Replay round trip passed."
    assert not list(tmp_path.iterdir())
