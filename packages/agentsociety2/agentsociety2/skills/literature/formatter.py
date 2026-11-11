"""文献格式化工具

用于将文献条目格式化为 Markdown 以及管理文件名的函数集合。
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any


def sanitize_filename(filename: str) -> str:
    """清理文件名中的非法字符

    :param filename: 原始文件名

    :returns: 清理后可安全用于文件系统的文件名
    """
    # Remove or replace illegal characters
    sanitized = re.sub(r'[<>:"/\\|?*]', "_", filename)
    sanitized = re.sub(r"\s+", "_", sanitized)
    sanitized = re.sub(r"_{2,}", "_", sanitized)
    return sanitized[:100]  # Limit length


def format_article_as_markdown(article: dict[str, Any], query: str) -> str:
    """将单篇文献格式化为 Markdown

    :param article: 文章数据字典
    :param query: 检索到该文章的查询词

    :returns: Markdown 格式的字符串
    """
    lines = []
    lines.append(f"# {article.get('title', 'Untitled Article')}")
    lines.append("")
    lines.append(f"**Search Query:** {query}")
    lines.append("")
    lines.append(f"**Saved At:** {datetime.now(UTC).isoformat()}")
    lines.append("")

    if article.get("year"):
        lines.append(f"**Year:** {article['year']}")
        lines.append("")
    if article.get("journal"):
        lines.append(f"**Journal:** {article['journal']}")
        lines.append("")

    # 处理 DOI 和 URL
    doi = article.get("doi", "")
    url = article.get("url", "")
    source = article.get("source", "")

    if doi:
        doi_url = f"https://doi.org/{doi}" if not doi.startswith("http") else doi
        lines.append(f"**DOI:** [{doi}]({doi_url})")
        lines.append("")
    if url and not doi:
        lines.append(f"**URL:** [Open Link]({url})")
        lines.append("")

    if source:
        source_name = article.get("source_name", source)
        # 为外部数据源添加提示
        if source in ["arxiv", "crossref", "openalex"]:
            lines.append(f"**Source:** {source_name} (external)")
        else:
            lines.append(f"**Source:** {source_name}")
        lines.append("")
    if article.get("avg_similarity") is not None:
        lines.append(f"**Score:** {article['avg_similarity']:.3f}")
        lines.append("")

    if article.get("authors"):
        authors = article["authors"]
        if isinstance(authors, list):
            lines.append(f"**Authors:** {', '.join(authors)}")
        else:
            lines.append(f"**Authors:** {authors}")
        lines.append("")

    if article.get("abstract"):
        lines.append("## Abstract")
        lines.append("")
        lines.append(article["abstract"])
        lines.append("")

    # Add chunks if available
    chunks = article.get("chunks", [])
    if chunks:
        lines.append("## Relevant Content")
        lines.append("")
        for i, chunk in enumerate(chunks[:3], 1):
            content = chunk.get("content", "")
            similarity = chunk.get("similarity", 0)
            lines.append(f"### Chunk {i} (similarity: {similarity:.3f})")
            lines.append("")
            lines.append(content[:1000] + "..." if len(content) > 1000 else content)
            lines.append("")

    # Add other fields
    exclude_fields = {
        "title",
        "journal",
        "doi",
        "abstract",
        "avg_similarity",
        "year",
        "url",
        "source",
        "source_name",
        "authors",
        "chunks",
    }
    first_extra = True
    for key, value in article.items():
        if key not in exclude_fields and value is not None:
            if first_extra:
                lines.append("**Other Fields:**")
                lines.append("")
                first_extra = False
            lines.append(f"- **{key}:** {value}")
    if not first_extra:
        lines.append("")

    return "\n".join(lines)
