# PDF Intake Contract

This contract applies whenever the manuscript supplied to `agentsociety-paper-review` is a PDF. Its purpose is to make all three reviewer runs consume one page-aware extraction instead of producing three independent parses.

## Layering

- `.claude/skills/pdf/` remains the general PDF reading and visual-inspection toolbox.
- `agentsociety-paper-review/scripts/prepare_pdf_review.py` is the review-specific intake and quality gate.
- Do not modify or copy the generic PDF skill into this skill. The wrapper adds paper-review invariants without creating a second general PDF implementation.

## Invocation

After reserving the review round and before writing the frozen input manifest, run:

```bash
python3 .claude/skills/agentsociety-paper-review/scripts/prepare_pdf_review.py \
  --input paper/main.pdf \
  --output-dir paper/reviews/<venue>-review-r<N>/pdf-intake
```

The output directory must be new. Never reuse an intake from another review round, and never overwrite a prior intake.

## Required Outputs

```text
pdf-intake/
├── source.sha256
├── document.txt
├── layout.xml
├── images-list.txt             # when pdfimages is available
├── extraction-report.json
└── pages/
    ├── page-001.txt
    ├── page-001.png
    └── ...
```

The script uses Poppler for metadata, layout-preserving text extraction, bbox extraction, and full-page rendering. Page renders retain the requested DPI and are not downscaled. The JSON report records source identity, tool versions, page counts, per-page text density, rendered dimensions, warnings, errors, and a SHA-256 digest for every generated review input.

## Quality Gate

`extraction-report.json` has exactly one of these statuses:

| Status | Review behavior |
|--------|-----------------|
| `pass` | Continue. Reviewers use text and page renders together. |
| `pass_with_warnings` | Continue only with the warnings copied into the reviewer and MetaReview task capsules. Reviewers visually inspect every warned page. |
| `failed` | Stop before reviewer dispatch. Write `ensemble-status.md`; do not create individual reviews or a final MetaReview. |

The intake fails closed for an invalid PDF header, missing core Poppler tools, an encrypted PDF, invalid or mismatched bbox pages, rendering failure, page-count mismatch, invalid PNG output, or an image-only/unreliable text layer that requires OCR. `pdfimages` is optional; its absence or failure produces a warning because it does not prevent full-page visual inspection.

The default scan detector marks a page sparse below 80 non-whitespace extracted characters and fails when at least 80% of pages are sparse. A few sparse pages can be figure-only pages, so they produce `pass_with_warnings` and mandatory visual inspection instead of automatic failure.

This version does not silently attempt OCR. If OCR is required, report the capability gap and stop. Installing or selecting an OCR backend is a separate, explicit operation because OCR quality and language configuration materially affect scientific review.

## Frozen Manifest Binding

For a PDF round, add this block to `input-manifest.yaml`:

```yaml
pdf_intake:
  status: pass
  report_path: paper/reviews/iclr-review-r1/pdf-intake/extraction-report.json
  report_sha256: <sha256-of-extraction-report>
  source_path: paper/main.pdf
  source_sha256: <same-value-as-pdf-intake/source.sha256>
  page_count: 12
  warnings: []
```

Also keep the original PDF in `reviewed_artifacts`. The orchestrator must verify that:

1. `pdf_intake.source_sha256` equals the original PDF digest in `reviewed_artifacts`;
2. `report_sha256` matches the report file;
3. the report status is `pass` or `pass_with_warnings`;
4. every report artifact exists and matches its recorded digest;
5. every reviewer receives the same report path, page text, and page renders.

Repeat these checks at the input-integrity gate before MetaReview. A changed source, report, or generated artifact invalidates the entire round.

## Reviewer Reading Rule

Reviewers must read `document.txt` for full-paper coverage and use `layout.xml`, page text, and rendered PNG pages to preserve page pointers and inspect layout-dependent evidence. They must inspect the rendered page for every figure, table, equation, footnote, or formatting-dependent judgment they cite. Text extraction alone is never sufficient evidence that a visual element is present, absent, correct, or legible.

For `pass_with_warnings`, reviewers must acknowledge all intake warnings and visually inspect the listed sparse or low-resolution pages. If a material element remains unreadable, lower confidence and record the limitation instead of inferring content.

## MetaReview Verification Rule

MetaReview receives the same frozen intake. It must visually re-check the source pages for every candidate fatal or major concern before confirming or rejecting that concern. It must not adjudicate a layout-dependent dispute from extracted text alone.
