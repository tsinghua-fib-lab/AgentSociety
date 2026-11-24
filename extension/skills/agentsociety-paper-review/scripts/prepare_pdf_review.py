#!/usr/bin/env python3
"""Prepare one frozen, page-aware PDF intake for an ensemble paper review."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


SCHEMA = "agentsociety.paper-review.pdf-intake/v1"
CORE_TOOLS = ("pdfinfo", "pdftotext", "pdftoppm")
OPTIONAL_TOOLS = ("pdfimages",)
DEFAULT_RENDER_DPI = 200
DEFAULT_MIN_TEXT_CHARS = 80
DEFAULT_MAX_SPARSE_PAGE_RATIO = 0.8
COMMAND_TIMEOUT_SECONDS = 300
VERSION_TIMEOUT_SECONDS = 10


class IntakeError(RuntimeError):
    """A PDF cannot safely proceed through the review intake gate."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run_command(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        completed = subprocess.run(
            args,
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise IntakeError(
            f"{Path(args[0]).name} exceeded {COMMAND_TIMEOUT_SECONDS} seconds"
        ) from exc
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no diagnostic"
        raise IntakeError(f"{Path(args[0]).name} failed: {detail}")
    return completed


def tool_version(path: str) -> str:
    try:
        completed = subprocess.run(
            [path, "-v"],
            capture_output=True,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=VERSION_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return "version_probe_timed_out"
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    for line in output.splitlines():
        if line.strip():
            return line.strip()
    return "unknown"


def discover_tools() -> tuple[dict[str, dict[str, str]], list[str]]:
    tools: dict[str, dict[str, str]] = {}
    missing_core: list[str] = []
    for name in (*CORE_TOOLS, *OPTIONAL_TOOLS):
        resolved = shutil.which(name)
        if resolved is None:
            if name in CORE_TOOLS:
                missing_core.append(name)
            continue
        tools[name] = {"path": resolved, "version": tool_version(resolved)}
    return tools, missing_core


def parse_pdfinfo(output: str) -> tuple[int, bool]:
    pages_match = re.search(r"^Pages:\s+(\d+)\s*$", output, flags=re.MULTILINE)
    encrypted_match = re.search(
        r"^Encrypted:\s+(yes|no)\b", output, flags=re.IGNORECASE | re.MULTILINE
    )
    if pages_match is None:
        raise IntakeError("pdfinfo did not report a page count")
    page_count = int(pages_match.group(1))
    if page_count < 1:
        raise IntakeError("PDF has no pages")
    encrypted = encrypted_match is not None and encrypted_match.group(1).lower() == "yes"
    return page_count, encrypted


def count_bbox_pages(path: Path) -> int:
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError) as exc:
        raise IntakeError(f"layout.xml is not valid XML: {exc}") from exc
    return sum(1 for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "page")


def png_dimensions(path: Path) -> tuple[int, int]:
    try:
        from PIL import Image
    except ImportError as exc:  # pragma: no cover - dependency error
        raise IntakeError(
            "Pillow is required to verify rendered PDF pages"
        ) from exc
    try:
        with Image.open(path) as image:
            size = image.size
            image.verify()
    except Exception as exc:
        raise IntakeError(f"rendered page is not a valid PNG: {path.name}: {exc}") from exc
    return int(size[0]), int(size[1])


def numeric_render_order(path: Path) -> int:
    match = re.search(r"-(\d+)\.png$", path.name)
    if match is None:
        raise IntakeError(f"unexpected pdftoppm output name: {path.name}")
    return int(match.group(1))


def artifact_record(output_dir: Path, path: Path, role: str) -> dict[str, Any]:
    return {
        "role": role,
        "path": path.relative_to(output_dir).as_posix(),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def write_report(output_dir: Path, report: dict[str, Any]) -> None:
    report_path = output_dir / "extraction-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def prepare_pdf(
    input_path: Path,
    output_dir: Path,
    *,
    render_dpi: int = DEFAULT_RENDER_DPI,
    min_text_chars: int = DEFAULT_MIN_TEXT_CHARS,
    max_sparse_page_ratio: float = DEFAULT_MAX_SPARSE_PAGE_RATIO,
) -> dict[str, Any]:
    input_path = input_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()

    if not input_path.is_file():
        raise FileNotFoundError(f"input PDF does not exist: {input_path}")
    if input_path.suffix.lower() != ".pdf":
        raise ValueError(f"input must use the .pdf extension: {input_path}")
    if output_dir.exists():
        raise FileExistsError(f"output directory already exists: {output_dir}")
    if not 72 <= render_dpi <= 600:
        raise ValueError("render DPI must be between 72 and 600")
    if min_text_chars < 1:
        raise ValueError("minimum text characters must be positive")
    if not 0 < max_sparse_page_ratio <= 1:
        raise ValueError("maximum sparse page ratio must be in (0, 1]")

    output_dir.mkdir(parents=True)
    pages_dir = output_dir / "pages"
    pages_dir.mkdir()

    source_digest = sha256_file(input_path)
    source_hash_path = output_dir / "source.sha256"
    source_hash_path.write_text(f"{source_digest}\n", encoding="ascii")

    report: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "failed",
        "source": {
            "path": str(input_path),
            "sha256": source_digest,
            "size_bytes": input_path.stat().st_size,
        },
        "quality_policy": {
            "render_dpi": render_dpi,
            "minimum_non_whitespace_characters_per_page": min_text_chars,
            "maximum_sparse_page_ratio": max_sparse_page_ratio,
            "ocr_policy": "fail_closed_when_required",
            "command_timeout_seconds": COMMAND_TIMEOUT_SECONDS,
        },
        "tools": {},
        "document": {},
        "pages": [],
        "artifacts": [],
        "warnings": [],
        "errors": [],
    }

    try:
        with input_path.open("rb") as handle:
            if b"%PDF-" not in handle.read(1024):
                raise IntakeError("file does not contain a PDF header in the first 1024 bytes")

        tools, missing_core = discover_tools()
        report["tools"] = tools
        if missing_core:
            raise IntakeError(
                "missing required Poppler tools: " + ", ".join(sorted(missing_core))
            )
        if "pdfimages" not in tools:
            report["warnings"].append(
                "pdfimages is unavailable; embedded-image inventory was not generated"
            )

        pdfinfo_output = run_command(
            [tools["pdfinfo"]["path"], str(input_path)]
        ).stdout
        page_count, encrypted = parse_pdfinfo(pdfinfo_output)
        report["document"] = {"page_count": page_count, "encrypted": encrypted}
        if encrypted:
            raise IntakeError("encrypted PDFs are not accepted by the unattended intake")

        document_text_path = output_dir / "document.txt"
        layout_path = output_dir / "layout.xml"
        run_command(
            [
                tools["pdftotext"]["path"],
                "-layout",
                "-enc",
                "UTF-8",
                str(input_path),
                str(document_text_path),
            ]
        )
        run_command(
            [
                tools["pdftotext"]["path"],
                "-bbox-layout",
                "-enc",
                "UTF-8",
                str(input_path),
                str(layout_path),
            ]
        )
        bbox_page_count = count_bbox_pages(layout_path)
        if bbox_page_count != page_count:
            raise IntakeError(
                f"layout page count mismatch: pdfinfo={page_count}, bbox={bbox_page_count}"
            )

        page_text_paths: list[Path] = []
        page_character_counts: list[int] = []
        for page_number in range(1, page_count + 1):
            page_text_path = pages_dir / f"page-{page_number:03d}.txt"
            run_command(
                [
                    tools["pdftotext"]["path"],
                    "-layout",
                    "-enc",
                    "UTF-8",
                    "-f",
                    str(page_number),
                    "-l",
                    str(page_number),
                    str(input_path),
                    str(page_text_path),
                ]
            )
            page_text_paths.append(page_text_path)
            page_text = page_text_path.read_text(encoding="utf-8", errors="replace")
            page_character_counts.append(sum(not char.isspace() for char in page_text))

        page_image_paths: list[Path] = []
        with tempfile.TemporaryDirectory(prefix=".render-", dir=output_dir) as temp_dir:
            render_prefix = Path(temp_dir) / "page"
            run_command(
                [
                    tools["pdftoppm"]["path"],
                    "-png",
                    "-r",
                    str(render_dpi),
                    str(input_path),
                    str(render_prefix),
                ]
            )
            rendered = sorted(
                Path(temp_dir).glob("page-*.png"), key=numeric_render_order
            )
            if len(rendered) != page_count:
                raise IntakeError(
                    f"rendered page count mismatch: pdfinfo={page_count}, rendered={len(rendered)}"
                )
            for page_number, rendered_path in enumerate(rendered, start=1):
                destination = pages_dir / f"page-{page_number:03d}.png"
                shutil.move(str(rendered_path), destination)
                page_image_paths.append(destination)

        image_inventory_path: Path | None = None
        if "pdfimages" in tools:
            image_inventory_path = output_dir / "images-list.txt"
            try:
                inventory = run_command(
                    [tools["pdfimages"]["path"], "-list", str(input_path)]
                ).stdout
                image_inventory_path.write_text(inventory, encoding="utf-8")
            except IntakeError as exc:
                report["warnings"].append(str(exc))
                image_inventory_path = None

        sparse_pages: list[int] = []
        low_resolution_pages: list[int] = []
        page_records: list[dict[str, Any]] = []
        for page_number, (text_path, image_path, character_count) in enumerate(
            zip(page_text_paths, page_image_paths, page_character_counts, strict=True),
            start=1,
        ):
            width, height = png_dimensions(image_path)
            is_sparse = character_count < min_text_chars
            if is_sparse:
                sparse_pages.append(page_number)
            if min(width, height) < 1000:
                low_resolution_pages.append(page_number)
            page_records.append(
                {
                    "page": page_number,
                    "text_path": text_path.relative_to(output_dir).as_posix(),
                    "image_path": image_path.relative_to(output_dir).as_posix(),
                    "non_whitespace_characters": character_count,
                    "text_is_sparse": is_sparse,
                    "image_width": width,
                    "image_height": height,
                }
            )

        sparse_page_ratio = len(sparse_pages) / page_count
        report["pages"] = page_records
        report["document"].update(
            {
                "bbox_page_count": bbox_page_count,
                "rendered_page_count": len(page_image_paths),
                "total_non_whitespace_characters": sum(page_character_counts),
                "sparse_pages": sparse_pages,
                "sparse_page_ratio": sparse_page_ratio,
            }
        )
        if low_resolution_pages:
            report["warnings"].append(
                "rendered pages have a dimension below 1000 px: "
                + ", ".join(map(str, low_resolution_pages))
            )
        if sparse_pages:
            report["warnings"].append(
                "pages with sparse extracted text require visual inspection: "
                + ", ".join(map(str, sparse_pages))
            )
        if sparse_page_ratio >= max_sparse_page_ratio:
            raise IntakeError(
                "image-only or unreliable text layer detected; OCR is required before review"
            )

        artifacts = [
            artifact_record(output_dir, source_hash_path, "source_digest"),
            artifact_record(output_dir, document_text_path, "full_text"),
            artifact_record(output_dir, layout_path, "bbox_layout"),
        ]
        if image_inventory_path is not None:
            artifacts.append(
                artifact_record(output_dir, image_inventory_path, "embedded_image_inventory")
            )
        for text_path, image_path in zip(
            page_text_paths, page_image_paths, strict=True
        ):
            artifacts.append(artifact_record(output_dir, text_path, "page_text"))
            artifacts.append(artifact_record(output_dir, image_path, "page_render"))
        report["artifacts"] = artifacts
        report["status"] = "pass_with_warnings" if report["warnings"] else "pass"
    except IntakeError as exc:
        report["errors"].append(str(exc))
        existing_artifacts: list[dict[str, Any]] = []
        for path in sorted(output_dir.rglob("*")):
            if path.is_file() and path.name != "extraction-report.json":
                existing_artifacts.append(
                    artifact_record(output_dir, path, "partial_output")
                )
        report["artifacts"] = existing_artifacts

    write_report(output_dir, report)
    return report


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare a frozen PDF intake for agentsociety-paper-review."
    )
    parser.add_argument("--input", required=True, type=Path, help="source paper PDF")
    parser.add_argument(
        "--output-dir", required=True, type=Path, help="new pdf-intake directory"
    )
    parser.add_argument("--render-dpi", type=int, default=DEFAULT_RENDER_DPI)
    parser.add_argument(
        "--minimum-text-chars-per-page", type=int, default=DEFAULT_MIN_TEXT_CHARS
    )
    parser.add_argument(
        "--maximum-sparse-page-ratio",
        type=float,
        default=DEFAULT_MAX_SPARSE_PAGE_RATIO,
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = prepare_pdf(
            args.input,
            args.output_dir,
            render_dpi=args.render_dpi,
            min_text_chars=args.minimum_text_chars_per_page,
            max_sparse_page_ratio=args.maximum_sparse_page_ratio,
        )
    except (FileExistsError, FileNotFoundError, OSError, ValueError) as exc:
        print(f"PDF intake setup failed: {exc}", file=sys.stderr)
        return 2

    print(
        json.dumps(
            {
                "status": report["status"],
                "report": str(args.output_dir / "extraction-report.json"),
                "warnings": report["warnings"],
                "errors": report["errors"],
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["status"] in {"pass", "pass_with_warnings"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
