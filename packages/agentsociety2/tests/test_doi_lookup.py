"""Unit + live probes for DOI / arXiv bibliographic lookup."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentsociety2.skills.literature import doi_lookup as doi_lookup_module
from agentsociety2.skills.literature.doi_lookup import (
    classify_identifier,
    extract_identifier_from_pdf,
    lookup_arxiv,
    lookup_doi_content_negotiation,
    lookup_doi_crossref,
    lookup_identifier,
    normalize_arxiv_id,
    normalize_doi,
    record_to_bibtex,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("10.1038/nature14539", "10.1038/nature14539"),
        ("https://doi.org/10.1038/nature14539", "10.1038/nature14539"),
        ("https://dx.doi.org/10.1038/nature14539", "10.1038/nature14539"),
        ("doi:10.1038/nature14539", "10.1038/nature14539"),
        ("DOI: 10.1038/nature14539", "10.1038/nature14539"),
    ],
)
def test_normalize_doi(raw: str, expected: str) -> None:
    assert normalize_doi(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1706.03762", "1706.03762"),
        ("arxiv:1706.03762", "1706.03762"),
        ("https://arxiv.org/abs/1706.03762", "1706.03762"),
        ("https://arxiv.org/pdf/1706.03762.pdf", "1706.03762"),
        ("1706.03762v7", "1706.03762"),
    ],
)
def test_normalize_arxiv_id(raw: str, expected: str) -> None:
    assert normalize_arxiv_id(raw) == expected


def test_classify_identifier() -> None:
    assert classify_identifier("10.1000/xyz") == ("doi", "10.1000/xyz")
    assert classify_identifier("arxiv:1234.56789") == ("arxiv", "1234.56789")
    with pytest.raises(ValueError, match="Unsupported"):
        classify_identifier("not-an-id")


def test_extract_identifier_from_pdf_finds_doi(tmp_path: Path) -> None:
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(
        b"%PDF-1.4\n1 0 obj<<>>endobj\n(doi:10.1038/nature14539) Tj\ntrailer<<>>\n"
    )
    assert extract_identifier_from_pdf(pdf) == "10.1038/nature14539"


def test_extract_identifier_from_pdf_finds_arxiv(tmp_path: Path) -> None:
    pdf = tmp_path / "attn.pdf"
    pdf.write_bytes(b"%PDF-1.4\nhttps://arxiv.org/abs/1706.03762v7\n%%EOF\n")
    assert extract_identifier_from_pdf(pdf) == "1706.03762"


def test_extract_identifier_from_pdf_none(tmp_path: Path) -> None:
    pdf = tmp_path / "blank.pdf"
    pdf.write_bytes(b"%PDF-1.4 mock without identifiers")
    assert extract_identifier_from_pdf(pdf) is None


def test_record_to_bibtex_shape() -> None:
    from agentsociety2.skills.literature.doi_lookup import BibliographicRecord

    record = BibliographicRecord(
        identifier="10.1000/example",
        id_type="doi",
        title="Hello {World}",
        authors=("Ada Lovelace", "Alan Turing"),
        year=2024,
        venue="Journal of Tests",
        doi="10.1000/example",
        url="https://doi.org/10.1000/example",
        abstract=None,
        cite_key="lovelace2024hello",
    )
    bib = record_to_bibtex(record)
    assert bib.startswith("@article{lovelace2024hello,")
    assert "title = {Hello \\{World\\}}" in bib
    assert "author = {Ada Lovelace and Alan Turing}" in bib
    assert "doi = {10.1000/example}" in bib


def test_lookup_identifier_dispatches_without_network(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, float]] = []
    doi_result = object()
    arxiv_result = object()

    def fake_lookup_doi(identifier: str, *, timeout: float) -> object:
        calls.append(("doi", identifier, timeout))
        return doi_result

    def fake_lookup_arxiv(identifier: str, *, timeout: float) -> object:
        calls.append(("arxiv", identifier, timeout))
        return arxiv_result

    monkeypatch.setattr(doi_lookup_module, "lookup_doi", fake_lookup_doi)
    monkeypatch.setattr(doi_lookup_module, "lookup_arxiv", fake_lookup_arxiv)

    assert lookup_identifier("doi:10.1038/nature14539", timeout=1.25) is doi_result
    assert lookup_identifier("arxiv:1706.03762", timeout=2.5) is arxiv_result
    assert calls == [
        ("doi", "10.1038/nature14539", 1.25),
        ("arxiv", "1706.03762", 2.5),
    ]


@pytest.mark.network
def test_live_crossref_journal_doi() -> None:
    """Journal DOIs resolve on Crossref; arXiv DataCite DOIs often do not."""
    record = lookup_doi_crossref("10.1038/nature14539", timeout=30.0)
    assert record.doi == "10.1038/nature14539"
    assert record.title
    assert record.authors
    with pytest.raises(ValueError, match="HTTP 404"):
        lookup_doi_crossref("10.48550/arXiv.1706.03762", timeout=30.0)


@pytest.mark.network
def test_live_doi_content_negotiation_covers_journal_and_arxiv_doi() -> None:
    journal = lookup_doi_content_negotiation(
        "https://doi.org/10.1038/nature14539", timeout=30.0
    )
    assert journal.doi == "10.1038/nature14539"
    assert journal.title

    arxiv_doi = lookup_doi_content_negotiation(
        "10.48550/arXiv.1706.03762", timeout=30.0
    )
    assert arxiv_doi.doi == "10.48550/arXiv.1706.03762"
    assert "attention" in arxiv_doi.title.lower()
    bib = record_to_bibtex(arxiv_doi)
    assert "doi = {" in bib


@pytest.mark.network
def test_live_arxiv_lookup() -> None:
    record = lookup_arxiv("https://arxiv.org/abs/1706.03762", timeout=30.0)
    assert record.id_type == "arxiv"
    assert record.identifier == "1706.03762"
    assert "attention" in record.title.lower()
    assert record.venue == "arXiv"
    assert record.url == "https://arxiv.org/abs/1706.03762"


@pytest.mark.network
def test_live_lookup_identifier_dispatch() -> None:
    from agentsociety2.skills.literature.doi_lookup import lookup_doi

    doi_record = lookup_identifier("doi:10.1038/nature14539", timeout=30.0)
    assert doi_record.id_type == "doi"
    assert doi_record.title
    # Preferred DOI path matches content negotiation (not Crossref-only).
    assert lookup_doi("10.48550/arXiv.1706.03762", timeout=30.0).title
    arxiv_record = lookup_identifier("1706.03762", timeout=30.0)
    assert arxiv_record.id_type == "arxiv"
