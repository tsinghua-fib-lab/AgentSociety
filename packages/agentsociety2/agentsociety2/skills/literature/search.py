"""Literature search functionality

Core functions for searching academic literature and managing results.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Literal, Optional
from litellm import AllMessageValues

from agentsociety2.skills.literature.models import LiteratureEntry, LiteratureIndex
from agentsociety2.skills.literature.formatter import (
    sanitize_filename,
    format_article_as_markdown,
)
from agentsociety2.config import get_llm_router
from agentsociety2.skills.literature.core import search_literature
from agentsociety2.logger import get_logger

logger = get_logger()


async def search_literature_and_save(
    query: str,
    workspace_path: Path,
    router: Optional[Any] = None,
    limit: Optional[int] = None,
    year_from: Optional[int] = None,
    year_to: Optional[int] = None,
    sources: Optional[List[Literal["local", "arxiv", "crossref", "openalex"]]] = None,
    enable_multi_query: bool = False,
) -> Dict[str, Any]:
    """Search for literature and save results to workspace

    :param query: Search query (supports Chinese, will be translated to English)
    :param workspace_path: Path to workspace directory
    :param router: Optional litellm router (will create if not provided)
    :param limit: Number of articles to return (default: 10)
    :param year_from: Filter by publication year (start)
    :param year_to: Filter by publication year (end)
    :param sources: Data sources to search (default: all sources)
    :param enable_multi_query: Enable multi-query mode to split complex queries into subtopics

    :returns: Dictionary with search results and saved file information
    """
    if router is None:
        router = get_llm_router("default")

    # Build call kwargs
    call_kwargs: Dict[str, Any] = {
        "query": query,
        "router": router,
    }
    if limit is not None:
        call_kwargs["limit"] = limit
    if year_from is not None:
        call_kwargs["year_from"] = year_from
    if year_to is not None:
        call_kwargs["year_to"] = year_to
    if sources is not None:
        call_kwargs["sources"] = sources
    if enable_multi_query:
        call_kwargs["enable_multi_query"] = True

    result = await search_literature(**call_kwargs)

    if result is None:
        return {
            "success": False,
            "articles": [],
            "total": 0,
            "query": query,
            "content": f"No articles found related to '{query}'.",
            "error": "No results found",
        }

    articles = result.get("articles", [])
    total = result.get("total", len(articles))

    # Save literature results to workspace
    saved_files = []
    if articles and workspace_path:
        try:
            saved_files = await _save_literature_to_workspace(
                result,
                workspace_path,
            )
            logger.info(f"Saved {len(saved_files)} literature files to workspace")
        except Exception as e:
            logger.error(f"Failed to save literature to workspace: {e}", exc_info=True)

    return {
        "success": True,
        "articles": articles,
        "total": total,
        "query": query,
        "saved_files": saved_files,
        "content": format_search_results(articles, total, query),
    }


async def generate_summary(
    query: str,
    articles: list,
    total: int,
    router: Any,
) -> str:
    """Generate a summary using LLM to guide users on next steps

    :param query: Original search query
    :param articles: List of found articles
    :param total: Total number of articles found
    :param router: LLM router

    :returns: Generated summary text
    """
    try:
        # Prepare article summaries for LLM context
        article_summaries = []
        for idx, article in enumerate(
            articles[:10], 1
        ):  # Use up to 10 articles for context
            title = article.get("title", "Unknown Title")
            journal = article.get("journal", "")
            abstract = article.get("abstract", "")
            doi = article.get("doi", "")
            year = article.get("year")

            article_info = f"{idx}. {title}"
            if year:
                article_info += f" ({year})"
            if journal:
                article_info += f" - {journal}"
            if abstract:
                abstract_preview = (
                    abstract[:300] + "..." if len(abstract) > 300 else abstract
                )
                article_info += f"\n   Abstract: {abstract_preview}"
            if doi:
                article_info += f"\n   DOI: {doi}"
            article_summaries.append(article_info)

        articles_text = "\n\n".join(article_summaries)

        # Create prompt for LLM
        prompt = f"""You are an AI Social Scientist assistant. A literature search has been completed for the query: "{query}"

Found {total} relevant article(s). The article files have been saved to the workspace's `papers` directory.

Here are the key articles found:
{articles_text}

Please generate a helpful summary and guidance for the user. The summary should:
1. Briefly acknowledge the search completion
2. Highlight 2-3 key themes or findings from the articles (if visible in titles/abstracts)
3. Suggest concrete next steps for the research workflow
4. Be encouraging and actionable

Format the response as markdown with clear sections. Keep it concise but informative (around 150-200 words)."""

        # Get model name from router
        model_name = router.model_list[0]["model_name"]

        # Call LLM
        messages: List[AllMessageValues] = [{"role": "user", "content": prompt}]

        response = await router.acompletion(
            model=model_name,
            messages=messages,
            stream=False,
        )

        # Extract content from response
        if hasattr(response, "choices") and len(response.choices) > 0:
            choice = response.choices[0]
            if hasattr(choice, "message") and hasattr(choice.message, "content"):  # type: ignore
                summary = choice.message.content or ""  # type: ignore
            else:
                summary = ""
        else:
            summary = ""

        if not summary:
            raise ValueError("Empty response from LLM")

        return summary

    except Exception as e:
        logger.error(f"Error generating summary: {e}", exc_info=True)
        raise


async def _save_literature_to_workspace(
    result: Dict[str, Any],
    workspace_path: Path,
) -> List[str]:
    """Save literature search results to workspace papers directory

    :param result: Literature search result dictionary
    :param workspace_path: Path to workspace directory

    :returns: List of saved file paths
    """
    if not workspace_path:
        logger.warning("Workspace path not set, cannot save literature files")
        return []

    papers_dir = workspace_path / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    timestamp = (
        datetime.now(timezone.utc).isoformat().replace(":", "-").replace(".", "-")[:19]
    )

    articles = result.get("articles", [])
    json_entries = []

    for idx, article in enumerate(articles):
        title = article.get("title", f"Article_{idx + 1}")
        sanitized_title = sanitize_filename(title)
        filename = f"{sanitized_title}_{timestamp}.md"
        filepath = papers_dir / filename

        content = format_article_as_markdown(article, result.get("query", ""))
        try:
            filepath.write_text(content, encoding="utf-8")
            saved_files.append(str(filepath))

            # Prepare JSON entry data. file_path intentionally points to the
            # local Markdown note so @references are always readable by agents.
            entry_data = {
                "title": article.get("title", ""),
                "journal": article.get("journal"),
                "doi": article.get("doi"),
                "abstract": article.get("abstract"),
                "avg_similarity": article.get("avg_similarity"),
                "file_path": filepath.relative_to(workspace_path).as_posix(),
                "file_type": "markdown",
                "source": "literature_search",
                "query": result.get("query"),
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }

            # Add other fields to extra_fields
            exclude_fields = {"title", "journal", "doi", "abstract", "avg_similarity"}
            extra_fields = {}
            for key, value in article.items():
                if key not in exclude_fields and value is not None:
                    extra_fields[key] = value

            if extra_fields:
                entry_data["extra_fields"] = extra_fields

            # Use Pydantic model to validate and create entry
            json_entry = LiteratureEntry(**entry_data)
            json_entries.append(json_entry)
        except Exception as e:
            logger.error(f"Failed to save article {idx + 1}: {e}")

    # Save or update JSON file
    json_filename = "literature_index.json"
    json_filepath = papers_dir / json_filename

    try:
        # If JSON file exists, read existing data
        existing_index = None
        if json_filepath.exists():
            try:
                with open(json_filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                existing_index = LiteratureIndex(**data)
            except Exception as e:
                logger.error(
                    f"Failed to read existing JSON file: {e}, creating new one"
                )
                existing_index = None

        # Create or update index
        if existing_index is None:
            now = datetime.now(timezone.utc).isoformat()
            existing_index = LiteratureIndex(
                entries=[],
                created_at=now,
                updated_at=now,
            )

        # Merge new data (avoid duplicates by title/DOI, same logic as merge_literature_results)
        # Build lookup by title (lowercase) and DOI (lowercase)
        existing_by_title: dict[str, int] = {}
        existing_by_doi: dict[str, int] = {}
        for idx, entry in enumerate(existing_index.entries):
            if entry.title:
                existing_by_title[entry.title.strip().lower()] = idx
            if entry.doi:
                existing_by_doi[entry.doi.strip().lower()] = idx

        for entry in json_entries:
            # Check for duplicates using title or DOI
            is_duplicate = False
            if entry.title and entry.title.strip().lower() in existing_by_title:
                is_duplicate = True
            elif entry.doi and entry.doi.strip().lower() in existing_by_doi:
                is_duplicate = True

            if not is_duplicate:
                existing_index.entries.append(entry)
                # Update lookup tables
                idx = len(existing_index.entries) - 1
                if entry.title:
                    existing_by_title[entry.title.strip().lower()] = idx
                if entry.doi:
                    existing_by_doi[entry.doi.strip().lower()] = idx

        # Update update time
        existing_index.updated_at = datetime.now(timezone.utc).isoformat()

        # Save updated JSON
        with open(json_filepath, "w", encoding="utf-8") as f:
            json.dump(existing_index.model_dump(), f, ensure_ascii=False, indent=2)

        logger.info(
            f"Saved/updated literature index JSON with {len(existing_index.entries)} entries"
        )
    except Exception as e:
        logger.error(f"Failed to save JSON index: {e}", exc_info=True)

    return saved_files


def format_search_results(articles: list, total: int, query: str) -> str:
    """Format search results for display

    :param articles: List of article dictionaries
    :param total: Total number of articles
    :param query: Search query

    :returns: Formatted string for display
    """
    if not articles:
        return f"No articles found related to '{query}'."

    content_parts = [
        f"Found {total} article(s) related to '{query}':\n",
    ]
    for idx, article in enumerate(articles[:5], 1):  # Show first 5 articles
        title = article.get("title", "Unknown Title")
        journal = article.get("journal", "")
        abstract = article.get("abstract", "")
        doi = article.get("doi", "")
        url = article.get("url", "")
        year = article.get("year")
        avg_sim = article.get("avg_similarity") or 0
        source = article.get("source", "")

        content_parts.append(f"{idx}. {title}")
        if year:
            content_parts.append(f"   Year: {year}")
        if journal:
            content_parts.append(f"   Journal: {journal}")
        if source:
            content_parts.append(f"   Source: {source}")
        if doi:
            # DOI 链接格式
            doi_url = f"https://doi.org/{doi}" if not doi.startswith("http") else doi
            content_parts.append(f"   DOI: [{doi}]({doi_url})")
        if url and not doi:
            # 直接 URL 链接
            content_parts.append(f"   URL: {url}")
        if avg_sim > 0:
            content_parts.append(f"   Score: {avg_sim:.3f}")
        if abstract:
            abstract_preview = (
                abstract[:200] + "..." if len(abstract) > 200 else abstract
            )
            content_parts.append(f"   Abstract: {abstract_preview}")
        content_parts.append("")

    if total > 5:
        content_parts.append(f"... {total - 5} more article(s) not shown")

    return "\n".join(content_parts)


def load_literature_index(workspace_path: Path) -> Optional[LiteratureIndex]:
    """Load literature index from workspace

    :param workspace_path: Path to workspace directory

    :returns: LiteratureIndex object or None if file doesn't exist
    """
    json_filepath = workspace_path / "papers" / "literature_index.json"
    if not json_filepath.exists():
        return None

    try:
        with open(json_filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return LiteratureIndex(**data)
    except Exception as e:
        logger.error(f"Failed to load literature index: {e}")
        return None
