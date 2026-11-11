"""文献检索与工作区持久化。

通过 MCP 检索学术文献、保存 Markdown 元数据，并可选地将开放获取的
PDF 下载到工作区索引中。
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from litellm import AllMessageValues

from agentsociety2.config import build_client_for_role, get_model_name
from agentsociety2.logger import get_logger
from agentsociety2.skills.literature.core import search_literature
from agentsociety2.skills.literature.formatter import (
    format_article_as_markdown,
    sanitize_filename,
)
from agentsociety2.skills.literature.full_text import download_open_access_pdfs
from agentsociety2.skills.literature.models import LiteratureEntry, LiteratureIndex

logger = get_logger()


async def _default_acompletion(messages: list[AllMessageValues]):
    dispatcher = build_client_for_role("default")
    return await dispatcher.call(
        model=get_model_name("default"),
        messages=messages,
        stream=False,
    )


async def search_literature_and_save(
    query: str,
    workspace_path: Path,
    router: Any | None = None,
    limit: int = 10,
    year_from: int | None = None,
    year_to: int | None = None,
    sources: list[Literal["local", "arxiv", "crossref", "openalex"]] | None = None,
    enable_multi_query: bool = False,
    download_full_text: bool = True,
) -> dict[str, Any]:
    """检索文献并将结果保存到工作区

    :param query: 检索词（支持中文，会自动翻译成英文）
    :param workspace_path: 工作区目录路径
    :param router: 可选的 litellm router；省略时使用默认的 LLM dispatcher。
    :param limit: 返回的文章数量（默认：10）
    :param year_from: 按发表年份过滤（起始）
    :param year_to: 按发表年份过滤（结束）
    :param sources: 要检索的数据源（默认：全部来源）
    :param enable_multi_query: 启用多查询模式，将复杂查询拆分为子主题
    :param download_full_text: 保存元数据后，尝试下载开放获取的 PDF

    :returns: 包含检索结果与已保存文件信息的字典
    """
    # Build call kwargs
    call_kwargs: dict[str, Any] = {
        "query": query,
    }
    if router is not None:
        call_kwargs["router"] = router
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

    saved_files: list[str] = []
    full_text_stats: dict[str, int] = {}
    if articles and workspace_path:
        try:
            saved_files = await _save_literature_to_workspace(
                result,
                workspace_path,
            )
            logger.info(f"Saved {len(saved_files)} literature files to workspace")
        except Exception as e:
            logger.error(f"Failed to save literature to workspace: {e}", exc_info=True)

        if download_full_text and saved_files:
            try:
                full_text_stats = download_open_access_pdfs(
                    workspace_path,
                    only_without_full_text=True,
                )
            except Exception as e:
                logger.error(
                    "Failed to download open-access full texts: %s", e, exc_info=True
                )

    return {
        "success": True,
        "articles": articles,
        "total": total,
        "query": query,
        "saved_files": saved_files,
        "full_text_stats": full_text_stats,
        "content": format_search_results(articles, total, query),
    }


async def generate_summary(
    query: str,
    articles: list,
    total: int,
    router: Any | None = None,
) -> str:
    """使用 LLM 生成摘要，引导用户进行后续步骤

    :param query: 原始检索词
    :param articles: 已找到的文章列表
    :param total: 找到的文章总数
    :param router: 可选的 LLM router；省略时使用默认的 LLM dispatcher。

    :returns: 生成的摘要文本
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

        messages: list[AllMessageValues] = [{"role": "user", "content": prompt}]

        if router is None:
            response = await _default_acompletion(messages)
        else:
            model_name = router.model_list[0]["model_name"]
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
    result: dict[str, Any],
    workspace_path: Path,
) -> list[str]:
    """将文献检索结果保存到工作区 papers 目录

    :param result: 文献检索结果字典
    :param workspace_path: 工作区目录路径

    :returns: 已保存文件路径的列表
    """
    if not workspace_path:
        logger.warning("Workspace path not set, cannot save literature files")
        return []

    papers_dir = workspace_path / "papers"
    papers_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    timestamp = datetime.now(UTC).isoformat().replace(":", "-").replace(".", "-")[:19]

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
                "saved_at": datetime.now(UTC).isoformat(),
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
            now = datetime.now(UTC).isoformat()
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
            if (
                entry.title
                and entry.title.strip().lower() in existing_by_title
                or entry.doi
                and entry.doi.strip().lower() in existing_by_doi
            ):
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
        existing_index.updated_at = datetime.now(UTC).isoformat()

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
    """格式化检索结果用于展示

    :param articles: 文章字典列表
    :param total: 文章总数
    :param query: 检索词

    :returns: 用于展示的格式化字符串
    """
    if not articles:
        return f"No articles found related to '{query}'."

    content_parts = [
        f"Found {total} article(s) related to '{query}':\n",
    ]
    for idx, article in enumerate(articles[:10], 1):
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

    if total > 10:
        content_parts.append(f"... {total - 10} more article(s) not shown")

    return "\n".join(content_parts)


def load_literature_index(workspace_path: Path) -> LiteratureIndex | None:
    """从工作区加载文献索引

    :param workspace_path: 工作区目录路径

    :returns: LiteratureIndex 对象；文件不存在时返回 None
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
