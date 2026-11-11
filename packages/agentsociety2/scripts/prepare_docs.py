"""Remove generated source viewers whose cached anchors may be stale."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def clear_source_pages(html_root: Path) -> None:
    """Clear only Sphinx's reserved source-viewer directories for both languages."""
    root = html_root.resolve()
    package = Path(__file__).resolve().parents[1]
    if root in {Path(root.anchor), package, package / "docs", package.parents[1]}:
        raise ValueError("Choose a dedicated HTML output directory")
    for language in ("zh", "en"):
        language_root = root / language
        if language_root.is_symlink():
            raise ValueError("Use a dedicated directory for each language output")
        generated = language_root / "_modules"
        if generated.is_symlink():
            generated.unlink()
        elif generated.is_dir():
            shutil.rmtree(generated)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html-root", type=Path, required=True)
    args = parser.parse_args()
    clear_source_pages(args.html_root)


if __name__ == "__main__":
    main()
