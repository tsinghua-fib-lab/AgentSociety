import json
import subprocess
import sys
from pathlib import Path

import pytest

import agentsociety2.skills.literature.search as literature_search_module
from agentsociety2.skills.literature.search import search_literature_and_save
from agentsociety2.skills.literature.core import _convert_api_response


REPO_ROOT = Path(__file__).resolve().parents[3]
FULL_TEXT_SCRIPT = (
    REPO_ROOT
    / "extension"
    / "skills"
    / "agentsociety-literature-search"
    / "v1.0.0"
    / "scripts"
    / "full_text.py"
)


def test_convert_api_response_preserves_full_text_metadata():
    converted = _convert_api_response(
        {
            "results": [
                {
                    "title": "Open Article",
                    "pdf_url": "https://example.org/open.pdf",
                    "best_oa_location": {"pdf_url": "https://example.org/oa.pdf"},
                    "score": 0.8,
                }
            ]
        },
        "open access",
    )

    article = converted["articles"][0]
    assert article["pdf_url"] == "https://example.org/open.pdf"
    assert article["best_oa_location"]["pdf_url"] == "https://example.org/oa.pdf"


@pytest.mark.asyncio
async def test_search_literature_deduplication_by_title(monkeypatch, tmp_path):
    """Test that duplicate articles are not added to index when searching multiple times."""

    call_count = 0

    async def fake_search_literature(**kwargs):
        nonlocal call_count
        call_count += 1
        return {
            "query": kwargs["query"],
            "total": 1,
            "articles": [
                {
                    "title": "Duplicate Article Title",
                    "abstract": "Same article searched multiple times.",
                    "doi": "10.1000/duplicate",
                    "year": 2026,
                    "authors": ["Test Author"],
                    "avg_similarity": 0.95,
                    "source": "arxiv",
                }
            ],
        }

    monkeypatch.setattr(
        literature_search_module,
        "search_literature",
        fake_search_literature,
    )

    # First search
    await search_literature_and_save(
        query="test query",
        workspace_path=tmp_path,
        router=object(),
    )

    index_path = tmp_path / "papers" / "literature_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    assert len(index["entries"]) == 1

    # Second search with same article (should be deduplicated)
    await search_literature_and_save(
        query="another query",
        workspace_path=tmp_path,
        router=object(),
    )

    index = json.loads(index_path.read_text(encoding="utf-8"))
    # Should still be 1 entry, not 2
    assert len(index["entries"]) == 1, "Duplicate article should not be added"
    assert call_count == 2, "Search should be called twice"


@pytest.mark.asyncio
async def test_search_literature_deduplication_by_doi(monkeypatch, tmp_path):
    """Test that articles with same DOI but different titles are deduplicated."""

    async def fake_search_literature(**kwargs):
        # Return article with same DOI but slightly different title
        return {
            "query": kwargs["query"],
            "total": 1,
            "articles": [
                {
                    "title": "Article Title Variant",
                    "abstract": "Different title but same DOI.",
                    "doi": "10.1000/same-doi",
                    "year": 2026,
                    "authors": ["Test Author"],
                    "avg_similarity": 0.90,
                    "source": "crossref",
                }
            ],
        }

    monkeypatch.setattr(
        literature_search_module,
        "search_literature",
        fake_search_literature,
    )

    # Create existing index with same DOI
    index_path = tmp_path / "papers" / "literature_index.json"
    index_path.parent.mkdir(parents=True, exist_ok=True)
    index_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "entries": [
                    {
                        "title": "Original Article Title",
                        "file_path": "papers/Original_Article.md",
                        "file_type": "markdown",
                        "source": "literature_search",
                        "saved_at": "2026-05-09T00:00:00",
                        "doi": "10.1000/same-doi",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    await search_literature_and_save(
        query="test query",
        workspace_path=tmp_path,
        router=object(),
    )

    index = json.loads(index_path.read_text(encoding="utf-8"))
    # Should still be 1 entry, not 2 (deduplicated by DOI)
    assert len(index["entries"]) == 1, "Duplicate by DOI should not be added"


@pytest.mark.asyncio
async def test_search_literature_and_save_updates_index(monkeypatch, tmp_path):
    async def fake_search_literature(**kwargs):
        return {
            "query": kwargs["query"],
            "total": 1,
            "articles": [
                {
                    "title": "Agent Societies in Simulation",
                    "abstract": "A short abstract.",
                    "doi": "10.1000/example",
                    "year": 2026,
                    "authors": ["A. Researcher"],
                    "avg_similarity": 0.91,
                    "source": "arxiv",
                    "url": "https://arxiv.org/abs/2601.00001",
                }
            ],
        }

    monkeypatch.setattr(
        literature_search_module,
        "search_literature",
        fake_search_literature,
    )

    result = await search_literature_and_save(
        query="agent societies",
        workspace_path=tmp_path,
        router=object(),
    )

    index_path = tmp_path / "papers" / "literature_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))

    assert result["success"] is True
    assert len(index["entries"]) == 1
    entry = index["entries"][0]
    file_path = Path(entry["file_path"])
    assert file_path.as_posix().startswith("papers/Agent_Societies_in_Simulation_")
    assert (tmp_path / file_path).exists()
    assert entry["extra_fields"]["authors"] == ["A. Researcher"]
    assert entry["extra_fields"]["url"] == "https://arxiv.org/abs/2601.00001"


def test_full_text_helper_registers_pdf_and_updates_index(tmp_path):
    papers = tmp_path / "papers"
    papers.mkdir()
    index_path = papers / "literature_index.json"
    index_path.write_text(
        json.dumps(
            {
                "version": "1.0",
                "entries": [
                    {
                        "title": "Agent Societies in Simulation",
                        "file_path": "papers/Agent_Societies.md",
                        "file_type": "markdown",
                        "source": "literature_search",
                        "saved_at": "2026-05-09T00:00:00",
                        "extra_fields": {
                            "url": "https://arxiv.org/abs/2601.00001",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    source_pdf = tmp_path / "source.pdf"
    source_pdf.write_bytes(b"%PDF-1.4\n")

    subprocess.run(
        [
            sys.executable,
            str(FULL_TEXT_SCRIPT),
            "--workspace",
            str(tmp_path),
            "register",
            "--entry",
            "1",
            "--file",
            str(source_pdf),
            "--source-url",
            "https://arxiv.org/pdf/2601.00001.pdf",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    updated = json.loads(index_path.read_text(encoding="utf-8"))
    full_text = updated["entries"][0]["extra_fields"]["full_text"]
    assert full_text["status"] == "downloaded"
    assert full_text["file_path"].startswith("papers/full_texts/")
    assert (tmp_path / full_text["file_path"]).exists()
    assert full_text["source_url"] == "https://arxiv.org/pdf/2601.00001.pdf"
