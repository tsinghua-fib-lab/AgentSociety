"""Tests for literature search core functions."""

from agentsociety2.skills.literature.core import (
    _convert_api_response,
    _split_query_by_keywords,
    is_chinese_text,
    merge_literature_results,
)


class TestChineseTextDetection:
    """Tests for is_chinese_text function."""

    def test_detects_chinese_characters(self):
        assert is_chinese_text("人工智能") is True
        assert is_chinese_text("机器学习") is True
        assert is_chinese_text("深度学习") is True

    def test_detects_mixed_chinese_english(self):
        assert is_chinese_text("人工智能 artificial intelligence") is True
        assert is_chinese_text("machine learning 机器学习") is True

    def test_returns_false_for_english(self):
        assert is_chinese_text("artificial intelligence") is False
        assert is_chinese_text("machine learning") is False

    def test_returns_false_for_numbers_and_symbols(self):
        assert is_chinese_text("12345") is False
        assert is_chinese_text("!@#$%") is False

    def test_returns_false_for_empty_string(self):
        assert is_chinese_text("") is False


class TestSplitQueryByKeywords:
    """Tests for _split_query_by_keywords function."""

    def test_splits_by_and(self):
        result = _split_query_by_keywords("social norms and cooperation mechanisms")
        assert len(result) == 2
        assert "social norms" in result
        assert "cooperation mechanisms" in result

    def test_splits_by_or(self):
        result = _split_query_by_keywords("machine learning or deep learning")
        assert len(result) == 2

    def test_splits_by_versus(self):
        result = _split_query_by_keywords(
            "reinforcement learning versus supervised learning"
        )
        assert len(result) == 2

    def test_returns_single_for_simple_query(self):
        result = _split_query_by_keywords("machine learning")
        assert len(result) == 1
        assert result[0] == "machine learning"

    def test_returns_single_for_short_parts(self):
        # Single word parts should not be split
        result = _split_query_by_keywords("AI and ML")
        assert len(result) == 1  # "AI" and "ML" are too short

    def test_handles_case_insensitive(self):
        result = _split_query_by_keywords("Social Norms AND Group Cooperation")
        assert len(result) == 2


class TestMergeLiteratureResults:
    """Tests for merge_literature_results function."""

    def test_merges_multiple_results(self):
        results = [
            {
                "articles": [
                    {"title": "Article A", "doi": "10.1000/a", "avg_similarity": 0.9},
                    {"title": "Article B", "doi": "10.1000/b", "avg_similarity": 0.8},
                ],
                "total": 2,
            },
            {
                "articles": [
                    {"title": "Article C", "doi": "10.1000/c", "avg_similarity": 0.7},
                ],
                "total": 1,
            },
        ]
        merged = merge_literature_results(results, "test query")
        assert merged is not None
        assert len(merged["articles"]) == 3
        assert merged["total"] == 3

    def test_deduplicates_by_title(self):
        results = [
            {
                "articles": [
                    {"title": "Duplicate Article", "doi": "", "avg_similarity": 0.9},
                ],
                "total": 1,
            },
            {
                "articles": [
                    {"title": "Duplicate Article", "doi": "", "avg_similarity": 0.8},
                ],
                "total": 1,
            },
        ]
        merged = merge_literature_results(results, "test query")
        assert merged is not None
        assert len(merged["articles"]) == 1

    def test_deduplicates_by_doi_when_title_missing(self):
        """Test deduplication by DOI when titles are missing."""
        results = [
            {
                "articles": [
                    {"title": "", "doi": "10.1000/same", "avg_similarity": 0.9},
                ],
                "total": 1,
            },
            {
                "articles": [
                    {"title": "", "doi": "10.1000/same", "avg_similarity": 0.8},
                ],
                "total": 1,
            },
        ]
        merged = merge_literature_results(results, "test query")
        assert merged is not None
        assert len(merged["articles"]) == 1

    def test_returns_none_for_empty_results(self):
        assert merge_literature_results([], "test query") is None
        assert merge_literature_results([None], "test query") is None

    def test_sorts_by_similarity(self):
        results = [
            {
                "articles": [
                    {"title": "Low Score", "doi": "10.1000/low", "avg_similarity": 0.5},
                ],
                "total": 1,
            },
            {
                "articles": [
                    {
                        "title": "High Score",
                        "doi": "10.1000/high",
                        "avg_similarity": 0.95,
                    },
                ],
                "total": 1,
            },
        ]
        merged = merge_literature_results(results, "test query")
        assert merged is not None
        assert merged["articles"][0]["title"] == "High Score"

    def test_merges_chunks_for_duplicates(self):
        results = [
            {
                "articles": [
                    {
                        "title": "Article with Chunks",
                        "doi": "10.1000/chunks",
                        "avg_similarity": 0.9,
                        "chunks": [
                            {"content": "Chunk A content here", "similarity": 0.9}
                        ],
                    },
                ],
                "total": 1,
            },
            {
                "articles": [
                    {
                        "title": "Article with Chunks",
                        "doi": "10.1000/chunks",
                        "avg_similarity": 0.8,
                        "chunks": [
                            {"content": "Chunk B content here", "similarity": 0.8}
                        ],
                    },
                ],
                "total": 1,
            },
        ]
        merged = merge_literature_results(results, "test query")
        assert merged is not None
        assert len(merged["articles"]) == 1
        # Chunks should be merged
        assert len(merged["articles"][0]["chunks"]) == 2


class TestConvertApiResponse:
    """Tests for _convert_api_response function."""

    def test_converts_basic_article(self):
        response = {
            "results": [
                {
                    "title": "Test Article",
                    "abstract": "Test abstract",
                    "doi": "10.1000/test",
                    "year": 2024,
                    "authors": ["Author A"],
                    "score": 0.85,
                }
            ],
            "total": 1,
        }
        result = _convert_api_response(response, "test query")
        assert result["total"] == 1
        assert len(result["articles"]) == 1
        article = result["articles"][0]
        assert article["title"] == "Test Article"
        assert article["doi"] == "10.1000/test"
        assert article["avg_similarity"] == 0.85

    def test_preserves_pdf_metadata(self):
        response = {
            "results": [
                {
                    "title": "Open Access Article",
                    "pdf_url": "https://example.com/paper.pdf",
                    "best_oa_location": {"pdf_url": "https://oa.example.com/paper.pdf"},
                    "score": 0.9,
                }
            ],
            "total": 1,
        }
        result = _convert_api_response(response, "open access")
        article = result["articles"][0]
        assert article["pdf_url"] == "https://example.com/paper.pdf"
        assert (
            article["best_oa_location"]["pdf_url"] == "https://oa.example.com/paper.pdf"
        )

    def test_converts_chunks(self):
        response = {
            "results": [
                {
                    "title": "Article with Chunks",
                    "chunks": [
                        {
                            "content": "Relevant content",
                            "similarity_score": 0.95,
                            "chunk_id": "chunk_1",
                        }
                    ],
                    "score": 0.8,
                }
            ],
            "total": 1,
        }
        result = _convert_api_response(response, "chunks test")
        article = result["articles"][0]
        assert len(article["chunks"]) == 1
        assert article["chunks"][0]["content"] == "Relevant content"
        assert article["chunks"][0]["similarity"] == 0.95

    def test_handles_empty_results(self):
        response = {"results": [], "total": 0}
        result = _convert_api_response(response, "empty query")
        assert result["total"] == 0
        assert len(result["articles"]) == 0
