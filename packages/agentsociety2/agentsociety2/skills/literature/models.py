"""文献数据模型

用于文献检索结果与索引的 Pydantic 模型。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from agentsociety2.logger import get_logger

logger = get_logger()


class LiteratureEntry(BaseModel):
    """文献条目数据模型

    用于标准化文献 JSON 条目，确保数据结构一致性与类型安全。
    """

    # Basic information
    title: str = Field(..., description="Literature title")

    journal: str | None = Field(None, description="Journal name")

    doi: str | None = Field(None, description="DOI identifier")

    abstract: str | None = Field(None, description="Abstract")

    # File information
    file_path: str = Field(..., description="File path (relative to workspace root)")

    file_type: Literal["markdown", "pdf", "docx", "txt", "md"] = Field(
        ..., description="File type"
    )

    # Source information
    source: Literal["literature_search", "user_upload"] = Field(
        ..., description="Literature source"
    )

    # Search related (only when source is literature_search)
    query: str | None = Field(None, description="Search query")

    avg_similarity: float | None = Field(
        None, ge=0.0, le=1.0, description="Average similarity score (0-1)"
    )

    # Time information
    saved_at: str = Field(..., description="Save time (ISO format)")

    # Other fields (allow extension)
    extra_fields: dict[str, Any] | None = Field(
        None, description="Other extension fields"
    )

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "title": "Example Research Paper",
                "journal": "Journal of Example Studies",
                "doi": "10.1000/example",
                "abstract": "This is an example abstract...",
                "file_path": "papers/Example_Research_Paper_2024-01-01.md",
                "file_type": "markdown",
                "source": "literature_search",
                "query": "example research",
                "avg_similarity": 0.85,
                "saved_at": "2024-01-01T12:00:00",
            }
        },
    )

    @field_validator("saved_at")
    @classmethod
    def validate_saved_at(cls, v: str) -> str:
        """校验保存时间格式"""
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError(f"Invalid ISO format for saved_at: {v}") from None
        return v

    @field_validator("doi")
    @classmethod
    def validate_doi(cls, v: str | None) -> str | None:
        """校验 DOI 格式（基础检查）"""
        if v is None:
            return v
        # Basic DOI format check: 10.xxxx/xxxx
        if not v.startswith("10."):
            logger.warning(f"DOI format may be invalid: {v}")
        return v


class LiteratureIndex(BaseModel):
    """文献索引数据模型

    用于标准化整个文献索引 JSON 文件的结构。
    """

    entries: list[LiteratureEntry] = Field(
        default_factory=list, description="List of literature entries"
    )

    version: str = Field(default="1.0", description="Index file version")

    created_at: str | None = Field(None, description="Index creation time (ISO format)")

    updated_at: str | None = Field(
        None, description="Index last update time (ISO format)"
    )

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "version": "1.0",
                "created_at": "2024-01-01T12:00:00",
                "updated_at": "2024-01-01T12:00:00",
                "entries": [
                    {
                        "title": "Example Research Paper",
                        "journal": "Journal of Example Studies",
                        "doi": "10.1000/example",
                        "abstract": "This is an example abstract...",
                        "file_path": "papers/Example_Research_Paper_2024-01-01.md",
                        "file_type": "markdown",
                        "source": "literature_search",
                        "query": "example research",
                        "avg_similarity": 0.85,
                        "saved_at": "2024-01-01T12:00:00",
                    }
                ],
            }
        },
    )
