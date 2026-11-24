"""Tests for automatic open-access PDF download after literature search."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from agentsociety2.skills.literature.full_text import (
    candidate_urls,
    download_entry_pdf,
    download_open_access_pdfs,
    entry_extra_fields,
    nested_dict,
    safe_output_name,
)
from agentsociety2.skills.literature.search import search_literature_and_save


def test_candidate_urls_resolves_arxiv_abs_to_pdf():
    entry: dict[str, Any] = {
        "extra_fields": {"url": "https://arxiv.org/abs/2601.00001"},
    }
    urls = candidate_urls(entry)
    assert "https://arxiv.org/pdf/2601.00001.pdf" in urls


def test_download_entry_pdf_writes_file(tmp_path: Path):
    entry: dict[str, Any] = {
        "title": "Test Paper",
        "file_path": "papers/Test_Paper.md",
        "extra_fields": {"url": "https://arxiv.org/abs/2601.00001"},
    }
    pdf_bytes = b"%PDF-1.4 test"

    with patch(
        "agentsociety2.skills.literature.full_text.download_pdf_bytes",
        return_value=(pdf_bytes, "https://arxiv.org/pdf/2601.00001.pdf"),
    ):
        outcome = download_entry_pdf(tmp_path, entry)

    assert outcome == "downloaded"
    full_text = entry_extra_fields(entry)["full_text"]
    assert isinstance(full_text, dict)
    rel = full_text["file_path"]
    assert (tmp_path / rel).read_bytes() == pdf_bytes


@pytest.mark.asyncio
async def test_search_literature_and_save_downloads_open_access(
    monkeypatch, tmp_path: Path
):
    async def fake_search_literature(**kwargs):
        return {
            "query": kwargs["query"],
            "articles": [
                {
                    "title": "Agent Societies in Simulation",
                    "abstract": "Abstract",
                    "url": "https://arxiv.org/abs/2601.00001",
                    "avg_similarity": 0.9,
                }
            ],
            "total": 1,
        }

    monkeypatch.setattr(
        "agentsociety2.skills.literature.search.search_literature",
        fake_search_literature,
    )

    pdf_bytes = b"%PDF-1.4 auto"
    with patch(
        "agentsociety2.skills.literature.full_text.download_pdf_bytes",
        return_value=(pdf_bytes, "https://arxiv.org/pdf/2601.00001.pdf"),
    ):
        result = await search_literature_and_save(
            query="agent societies",
            workspace_path=tmp_path,
            router=object(),
        )

    assert result["success"] is True
    assert result["full_text_stats"]["downloaded"] == 1

    index: dict[str, Any] = json.loads(
        (tmp_path / "papers" / "literature_index.json").read_text(encoding="utf-8")
    )
    entry0: dict[str, Any] = index["entries"][0]
    full_text = nested_dict(entry_extra_fields(entry0), "full_text")
    assert full_text["status"] == "downloaded"
    assert (tmp_path / full_text["file_path"]).exists()


def test_download_open_access_pdfs_skips_already_downloaded(tmp_path: Path):
    papers = tmp_path / "papers"
    papers.mkdir()
    pdf_path = papers / "full_texts" / "existing.pdf"
    pdf_path.parent.mkdir(parents=True)
    pdf_path.write_bytes(b"%PDF-1.4")

    index_path = papers / "literature_index.json"
    index_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "entries": [
                    {
                        "title": "Done",
                        "file_path": "papers/Done.md",
                        "extra_fields": {
                            "full_text": {
                                "status": "downloaded",
                                "file_path": "papers/full_texts/existing.pdf",
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    stats = download_open_access_pdfs(tmp_path)
    assert stats["skipped"] == 1
    assert stats["downloaded"] == 0


def test_safe_output_name_rejects_traversal() -> None:
    with pytest.raises(ValueError):
        safe_output_name("../escape.pdf", {})
    assert safe_output_name("paper.pdf", {}) == "paper.pdf"
