"""Write and read a replay dataset without Ray, model credentials or network calls."""

from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from agentsociety2.storage import (
    ColumnDef,
    ReplayDatasetSpec,
    ReplayReader,
    ReplayWriter,
    TableSchema,
)


async def round_trip(replay_dir: Path) -> list[dict[str, Any]]:
    """Register a dataset, append one observation and read it back in ID order."""
    columns = [ColumnDef("id", "INTEGER"), ColumnDef("value", "REAL")]
    dataset = ReplayDatasetSpec(
        dataset_id="example.observations",
        table_name="observations",
        module_name="Example",
        kind="entity_static",
        entity_key="id",
        default_order=["id"],
    )
    writer = ReplayWriter(replay_dir)
    try:
        await writer.init()
        await writer.register_table(TableSchema(name="observations", columns=columns))
        await writer.register_dataset(dataset, columns)
        await writer.write("observations", {"id": 1, "value": 3.5})
    finally:
        await writer.close()

    reader = ReplayReader(replay_dir)
    try:
        catalog_entry = reader.get_dataset_by_id("example.observations")
        return reader.fetch_dataset_rows(catalog_entry)["rows"]
    finally:
        reader.close()


def main() -> None:
    """Verify the round trip in a temporary directory that is cleaned on exit."""
    with TemporaryDirectory(prefix="agentsociety-replay-") as temporary:
        rows = asyncio.run(round_trip(Path(temporary)))
        assert rows == [{"id": 1, "value": 3.5}], rows
    print("Replay round trip passed.")


if __name__ == "__main__":
    main()
