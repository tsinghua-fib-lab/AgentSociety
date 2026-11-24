#!/usr/bin/env python3
"""CLI wrapper for literature full-text helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _workspace_root() -> Path:
    raw = os.environ.get("AGENTSOCIETY_WORKSPACE")
    if raw:
        return Path(raw).expanduser().resolve()
    here = Path(__file__).resolve()
    for candidate in here.parents:
        if (candidate / ".env").exists() or (candidate / ".agentsociety").exists():
            return candidate
    return here.parents[4]


workspace_root = _workspace_root()
sys.path.insert(0, str(workspace_root / "packages" / "agentsociety2"))

from agentsociety2.skills.literature.full_text import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
