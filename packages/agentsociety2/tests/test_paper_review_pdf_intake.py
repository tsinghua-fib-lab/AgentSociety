from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT_PATH = (
    REPO_ROOT
    / "extension/skills/agentsociety-paper-review/scripts/prepare_pdf_review.py"
)


FAKE_POPPLER = r"""#!/usr/bin/env python3
import os
import sys
from pathlib import Path

from PIL import Image


tool = Path(sys.argv[0]).name
args = sys.argv[1:]

if "-v" in args:
    print(f"{tool} version 99.0")
    raise SystemExit(0)

if tool == "pdfinfo":
    print("Pages:          2")
    print("Encrypted:      no")
elif tool == "pdftotext":
    output = Path(args[-1])
    if "-bbox-layout" in args:
        output.write_text(
            "<html xmlns='http://www.w3.org/1999/xhtml'><body>"
            "<page width='612' height='792'/><page width='612' height='792'/>"
            "</body></html>",
            encoding="utf-8",
        )
    else:
        sparse = os.environ.get("FAKE_PDF_SPARSE") == "1"
        if "-f" in args:
            page = int(args[args.index("-f") + 1])
            text = "   \n" if sparse else f"Page {page} " + "scientific evidence " * 12
        else:
            text = "   \n" if sparse else "scientific evidence " * 24
        output.write_text(text, encoding="utf-8")
elif tool == "pdftoppm":
    prefix = Path(args[-1])
    for page in (1, 2):
        Image.new("RGB", (1200, 1600), "white").save(
            prefix.with_name(f"{prefix.name}-{page}.png")
        )
elif tool == "pdfimages":
    print("page num type width height color comp bpc enc interp object ID x-ppi y-ppi size ratio")
else:
    raise SystemExit(f"unexpected fake tool: {tool}")
"""


def install_fake_poppler(tmp_path: Path) -> Path:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for tool in ("pdfinfo", "pdftotext", "pdftoppm", "pdfimages"):
        tool_path = bin_dir / tool
        tool_path.write_text(
            FAKE_POPPLER.replace("#!/usr/bin/env python3", f"#!{sys.executable}", 1),
            encoding="utf-8",
        )
        tool_path.chmod(0o755)
    return bin_dir


def run_intake(
    tmp_path: Path, *, sparse: bool = False
) -> tuple[subprocess.CompletedProcess[str], Path, Path]:
    bin_dir = install_fake_poppler(tmp_path)
    input_path = tmp_path / "paper.pdf"
    input_path.write_bytes(b"%PDF-1.7\nfixture\n")
    output_dir = tmp_path / "review" / "pdf-intake"
    env = os.environ.copy()
    env["PATH"] = f"{bin_dir}{os.pathsep}{env['PATH']}"
    if sparse:
        env["FAKE_PDF_SPARSE"] = "1"
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT_PATH),
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
        ],
        capture_output=True,
        check=False,
        text=True,
        env=env,
    )
    return completed, input_path, output_dir


def test_pdf_intake_creates_page_aware_hashed_shared_artifacts(tmp_path: Path) -> None:
    completed, input_path, output_dir = run_intake(tmp_path)

    assert completed.returncode == 0, completed.stderr
    report = json.loads((output_dir / "extraction-report.json").read_text())
    expected_source_digest = hashlib.sha256(input_path.read_bytes()).hexdigest()

    assert report["schema"] == "agentsociety.paper-review.pdf-intake/v1"
    assert report["status"] == "pass"
    assert report["source"]["sha256"] == expected_source_digest
    assert report["document"]["page_count"] == 2
    assert report["document"]["bbox_page_count"] == 2
    assert report["document"]["rendered_page_count"] == 2
    assert report["document"]["sparse_page_ratio"] == 0
    assert (output_dir / "document.txt").is_file()
    assert (output_dir / "layout.xml").is_file()
    assert (output_dir / "pages/page-001.txt").is_file()
    assert (output_dir / "pages/page-001.png").is_file()

    for artifact in report["artifacts"]:
        artifact_path = output_dir / artifact["path"]
        assert artifact_path.is_file()
        assert (
            hashlib.sha256(artifact_path.read_bytes()).hexdigest() == artifact["sha256"]
        )


def test_pdf_intake_fails_closed_when_ocr_is_required(tmp_path: Path) -> None:
    completed, _, output_dir = run_intake(tmp_path, sparse=True)

    assert completed.returncode == 2
    report = json.loads((output_dir / "extraction-report.json").read_text())
    assert report["status"] == "failed"
    assert report["document"]["sparse_page_ratio"] == 1
    assert any("OCR is required" in error for error in report["errors"])
