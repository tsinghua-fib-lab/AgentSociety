"""Tests for literature search with mocked API calls."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentsociety2.skills.literature.core import (
    _search_literature_single,
    split_query_into_subtopics,
    translate_to_english,
)
from agentsociety2.skills.literature.search import (
    format_search_results,
    generate_summary,
    load_literature_index,
    search_literature_and_save,
)


class MockRouter:
    """Mock LLM router for testing."""

    def __init__(self, response_text: str = "translated text"):
        self.response_text = response_text
        self.model_list = [{"model_name": "test-model"}]

    async def acompletion(
        self, model: str, messages: list, stream: bool = False, **kwargs
    ):
        """Mock async completion."""
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = self.response_text
        return mock_response


class TestTranslateToEnglish:
    """Tests for translate_to_english function with mocked router."""

    @pytest.mark.asyncio
    async def test_translates_chinese_text(self):
        """Test translating Chinese text to English."""
        router = MockRouter(response_text="machine learning")
        result = await translate_to_english("机器学习", router)
        assert result == "machine learning"

    @pytest.mark.asyncio
    async def test_returns_original_on_failure(self):
        """Test that original text is returned on translation failure."""

        class FailingRouter:
            def __init__(self):
                self.model_list = [{"model_name": "test-model"}]

            async def acompletion(self, **kwargs):
                raise Exception("API Error")

        router = FailingRouter()
        result = await translate_to_english("测试文本", router)
        assert result == "测试文本"

    @pytest.mark.asyncio
    async def test_strips_markdown_fences(self):
        """Test that markdown fences are stripped from response."""
        router = MockRouter(response_text="```python\ntranslated text\n```")
        result = await translate_to_english("测试", router)
        assert "```" not in result


class TestSplitQueryIntoSubtopics:
    """Tests for split_query_into_subtopics function."""

    @pytest.mark.asyncio
    async def test_splits_complex_query(self):
        """Test splitting a complex query into subtopics."""
        router = MockRouter(
            response_text='["social networks", "information diffusion"]'
        )
        result = await split_query_into_subtopics(
            "social networks and information diffusion", router
        )
        assert len(result) == 2
        assert "social networks" in result

    @pytest.mark.asyncio
    async def test_returns_single_for_simple_query(self):
        """Test that simple queries are not split."""
        result = await split_query_into_subtopics("simple query", MockRouter())
        # Should use keyword splitting which returns single for short queries
        assert len(result) == 1

    @pytest.mark.asyncio
    async def test_uses_keyword_splitting_first(self):
        """Test that keyword splitting is attempted before LLM."""
        # "and" keyword should be detected
        result = await split_query_into_subtopics(
            "social norms and cooperation mechanisms", MockRouter()
        )
        assert len(result) == 2

    @pytest.mark.asyncio
    async def test_handles_malformed_llm_response(self):
        """Test handling malformed LLM response."""

        class BadResponseRouter:
            def __init__(self):
                self.model_list = [{"model_name": "test-model"}]

            async def acompletion(self, **kwargs):
                mock_response = MagicMock()
                mock_response.choices = [MagicMock()]
                mock_response.choices[0].message.content = "not a json array"
                return mock_response

        router = BadResponseRouter()
        # Should fall back to original query
        result = await split_query_into_subtopics(
            "complex query that needs splitting", router
        )
        assert len(result) >= 1


class TestSearchLiteratureSingle:
    """Tests for _search_literature_single with mocked MCP."""

    @pytest.mark.asyncio
    async def test_search_returns_results(self):
        """Test successful search returns results."""
        mock_response_data = {
            "results": [
                {
                    "title": "Test Article",
                    "abstract": "Test abstract",
                    "doi": "10.1000/test",
                    "score": 0.9,
                }
            ],
            "total": 1,
        }

        with patch(
            "agentsociety2.skills.literature.core.call_literature_search_mcp",
            new=AsyncMock(return_value=mock_response_data),
        ):
            result = await _search_literature_single(
                query="test query",
                limit=10,
                year_from=None,
                year_to=None,
                sources=None,
                similarity_threshold=None,
                vector_similarity_weight=None,
                chunk_content_limit=None,
                relevant_content_limit=None,
                max_chunks_per_article=None,
                return_chunks=True,
                mcp_url="http://test.api/mcp/sse",
                api_key="test-key",
                timeout=30,
            )

            assert result is not None
            assert result["total"] == 1
            assert len(result["articles"]) == 1

    @pytest.mark.asyncio
    async def test_search_handles_auth_error(self):
        """Test handling of authentication error."""
        with patch(
            "agentsociety2.skills.literature.core.call_literature_search_mcp",
            new=AsyncMock(side_effect=RuntimeError("401 auth failed")),
        ):
            result = await _search_literature_single(
                query="test query",
                limit=10,
                year_from=None,
                year_to=None,
                sources=None,
                similarity_threshold=None,
                vector_similarity_weight=None,
                chunk_content_limit=None,
                relevant_content_limit=None,
                max_chunks_per_article=None,
                return_chunks=True,
                mcp_url="http://test.api/mcp/sse",
                api_key="test-key",
                timeout=30,
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_search_handles_timeout(self):
        """Test handling of request timeout."""
        with patch(
            "agentsociety2.skills.literature.core.call_literature_search_mcp",
            new=AsyncMock(side_effect=TimeoutError()),
        ):
            result = await _search_literature_single(
                query="test query",
                limit=10,
                year_from=None,
                year_to=None,
                sources=None,
                similarity_threshold=None,
                vector_similarity_weight=None,
                chunk_content_limit=None,
                relevant_content_limit=None,
                max_chunks_per_article=None,
                return_chunks=True,
                mcp_url="http://test.api/mcp/sse",
                api_key="test-key",
                timeout=30,
            )

            assert result is None


class TestSearchLiteratureAndSave:
    """Tests for search_literature_and_save with mocked search."""

    @pytest.mark.asyncio
    async def test_search_and_save_success(self, tmp_path: Path):
        """Test successful search and save."""
        mock_result = {
            "query": "test query",
            "total": 1,
            "articles": [
                {
                    "title": "Test Article",
                    "abstract": "Test abstract",
                    "doi": "10.1000/test",
                    "year": 2024,
                    "authors": ["Test Author"],
                    "avg_similarity": 0.9,
                    "source": "arxiv",
                }
            ],
        }

        with patch(
            "agentsociety2.skills.literature.search.search_literature",
            new_callable=AsyncMock,
            return_value=mock_result,
        ):
            result = await search_literature_and_save(
                query="test query",
                workspace_path=tmp_path,
                router=MockRouter(),
            )

            assert result["success"] is True
            assert result["total"] == 1
            assert "saved_files" in result
            assert len(result["saved_files"]) == 1

    @pytest.mark.asyncio
    async def test_search_and_save_no_results(self, tmp_path: Path):
        """Test search with no results."""
        with patch(
            "agentsociety2.skills.literature.search.search_literature",
            new_callable=AsyncMock,
            return_value=None,
        ):
            result = await search_literature_and_save(
                query="no results query",
                workspace_path=tmp_path,
                router=MockRouter(),
            )

            assert result["success"] is False
            assert result["total"] == 0


class TestGenerateSummary:
    """Tests for generate_summary function."""

    @pytest.mark.asyncio
    async def test_generate_summary_success(self):
        """Test successful summary generation."""
        router = MockRouter(response_text="This is a summary of the search results.")
        articles = [
            {
                "title": "Article 1",
                "abstract": "Abstract 1",
                "doi": "10.1000/1",
                "year": 2024,
            }
        ]

        summary = await generate_summary("test query", articles, 1, router)
        assert summary == "This is a summary of the search results."

    @pytest.mark.asyncio
    async def test_generate_summary_with_multiple_articles(self):
        """Test summary generation with multiple articles."""
        router = MockRouter(response_text="Summary of multiple articles.")
        articles = [
            {"title": f"Article {i}", "abstract": f"Abstract {i}", "year": 2024}
            for i in range(10)
        ]

        summary = await generate_summary("test query", articles, 10, router)
        assert summary == "Summary of multiple articles."


class TestFormatSearchResults:
    """Tests for format_search_results function."""

    def test_format_with_results(self):
        """Test formatting with results."""
        articles = [
            {
                "title": "Test Article",
                "journal": "Test Journal",
                "abstract": "Test abstract content",
                "doi": "10.1000/test",
                "year": 2024,
                "avg_similarity": 0.9,
                "source": "arxiv",
            }
        ]
        result = format_search_results(articles, 1, "test query")
        assert "Found 1 article" in result
        assert "Test Article" in result
        assert "Test Journal" in result
        assert "10.1000/test" in result

    def test_format_with_no_results(self):
        """Test formatting with no results."""
        result = format_search_results([], 0, "test query")
        assert "No articles found" in result

    def test_format_truncates_long_abstracts(self):
        """Test that long abstracts are truncated."""
        articles = [
            {
                "title": "Test",
                "abstract": "A" * 500,  # Long abstract
            }
        ]
        result = format_search_results(articles, 1, "test")
        assert "..." in result

    def test_format_truncates_display_to_ten(self):
        """Test that at most 10 articles are shown with an overflow message."""
        articles = [{"title": f"Article {i}"} for i in range(15)]
        result = format_search_results(articles, 15, "test")
        assert "Article 9" in result
        assert "Article 10" not in result
        assert "5 more article" in result


class TestLoadLiteratureIndex:
    """Tests for load_literature_index function."""

    def test_load_existing_index(self, tmp_path: Path):
        """Test loading an existing index."""
        import json

        index_path = tmp_path / "papers" / "literature_index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_data = {
            "version": "1.0",
            "entries": [
                {
                    "title": "Test Article",
                    "file_path": "papers/test.md",
                    "file_type": "markdown",
                    "source": "literature_search",
                    "saved_at": "2024-01-01T00:00:00",
                }
            ],
        }
        index_path.write_text(json.dumps(index_data), encoding="utf-8")

        result = load_literature_index(tmp_path)
        assert result is not None
        assert len(result.entries) == 1

    def test_load_nonexistent_index(self, tmp_path: Path):
        """Test loading a nonexistent index."""
        result = load_literature_index(tmp_path)
        assert result is None

    def test_load_corrupted_index(self, tmp_path: Path):
        """Test loading a corrupted index file."""
        index_path = tmp_path / "papers" / "literature_index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index_path.write_text("not valid json", encoding="utf-8")

        result = load_literature_index(tmp_path)
        assert result is None
