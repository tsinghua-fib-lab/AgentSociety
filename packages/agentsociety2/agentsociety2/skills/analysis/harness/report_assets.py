from __future__ import annotations

import filecmp
import re
import shutil
from pathlib import Path

from agentsociety2.skills.analysis.chart_export import ensure_brand_icon

MD_ASSET_REF_RE = re.compile(
    r"!\[[^\]]*\]\((?:\./)?(?:assets|charts)/([^)]+)\)"
)
HTML_ASSET_REF_RE = re.compile(
    r"""<img[^>]*\ssrc=["'](?:\./)?(?:assets|charts)/([^"']+)["']""",
    re.IGNORECASE,
)
CHARTS_PATH_IN_BODY_RE = re.compile(
    r"""(?:\]\(|src=["'])(?:\./)?(charts/[^"')]+)"""
)
DATA_REF_IN_BODY_RE = re.compile(
    r"""(?:\]\(|(?:src|href)=["'])(?:\./)?(data/[^"')]+)"""
)


def referenced_asset_names(presentation_dir: Path) -> set[str]:
    names: set[str] = set()
    for fname in (
        "report_zh.md",
        "report_en.md",
        "report_zh.html",
        "report_en.html",
    ):
        path = presentation_dir / fname
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        names |= set(MD_ASSET_REF_RE.findall(text))
        names |= set(HTML_ASSET_REF_RE.findall(text))
    return names


def charts_path_refs_in_reports(presentation_dir: Path) -> list[str]:
    found: list[str] = []
    for fname in (
        "report_zh.md",
        "report_en.md",
        "report_zh.html",
        "report_en.html",
    ):
        path = presentation_dir / fname
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found.extend(CHARTS_PATH_IN_BODY_RE.findall(text))
    return found


def data_path_refs_in_reports(presentation_dir: Path) -> list[str]:
    """Return ``data/...`` links referenced from reports.

    :param presentation_dir: Presentation directory for one hypothesis.
    :returns: Relative paths beginning with ``data/``.
    """
    found: list[str] = []
    for fname in (
        "report_zh.md",
        "report_en.md",
        "report_zh.html",
        "report_en.html",
    ):
        path = presentation_dir / fname
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        found.extend(DATA_REF_IN_BODY_RE.findall(text))
    return found


def sync_report_assets_from_reports(presentation_dir: Path) -> dict:
    """Copy chart files referenced in reports from charts/ into assets/."""
    presentation_dir = presentation_dir.resolve()
    charts_dir = presentation_dir / "charts"
    assets_dir = presentation_dir / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    ensure_brand_icon(assets_dir)

    copied: list[str] = []
    missing: list[str] = []

    for name in sorted(referenced_asset_names(presentation_dir)):
        dest = assets_dir / name
        src = charts_dir / name
        if src.is_file():
            if not dest.is_file() or not filecmp.cmp(src, dest, shallow=False):
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dest)
                copied.append(name)
            continue
        if dest.is_file():
            continue
        missing.append(name)

    return {
        "copied": copied,
        "missing": missing,
        "assets_dir": str(assets_dir),
    }
