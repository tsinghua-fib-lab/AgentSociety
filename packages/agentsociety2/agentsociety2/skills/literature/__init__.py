"""文献检索与管理。

学术文献检索（MCP）、工作区索引、格式化以及全文辅助工具。
"""

from agentsociety2.skills.literature.core import (
    is_chinese_text,
    search_literature,
)
from agentsociety2.skills.literature.formatter import (
    format_article_as_markdown,
    sanitize_filename,
)
from agentsociety2.skills.literature.models import LiteratureEntry, LiteratureIndex
from agentsociety2.skills.literature.search import (
    format_search_results,
    generate_summary,
    load_literature_index,
    search_literature_and_save,
)

__all__ = [
    # Models
    "LiteratureEntry",
    "LiteratureIndex",
    "format_article_as_markdown",
    "format_search_results",
    "generate_summary",
    "is_chinese_text",
    "load_literature_index",
    # Formatter
    "sanitize_filename",
    # Core
    "search_literature",
    # Search
    "search_literature_and_save",
]
