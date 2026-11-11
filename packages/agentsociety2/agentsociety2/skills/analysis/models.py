"""分析工具层的数据模型与路径约定。"""

from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

DIR_HYPOTHESIS_PREFIX = "hypothesis_"
DIR_EXPERIMENT_PREFIX = "experiment_"
DIR_RUN = "run"
DIR_ARTIFACTS = "artifacts"  # run/artifacts: 实验执行产物
DIR_PRESENTATION = "presentation"
DIR_SYNTHESIS = "synthesis"
DIR_DATA = "data"  # presentation/hypothesis_<id>/data: 分析子智能体写入的分析数据
DIR_CHARTS = (
    "charts"  # presentation/hypothesis_<id>/charts: generated visualization files
)
DIR_REPORT_ASSETS = "assets"  # presentation 或 synthesis 下 assets: 报告嵌入资源（复制自 charts + run/artifacts），包括图表、报告、分析数据等
FILE_SQLITE = "sqlite.db"
DIR_REPLAY = "replay"
FILE_PID = "pid.json"
FILE_HYPOTHESIS_MD = "HYPOTHESIS.md"
FILE_EXPERIMENT_MD = "EXPERIMENT.md"
FILE_ANALYSIS_SUMMARY_JSON = "analysis_summary.json"
FILE_README_MD = "README.md"
FILE_SYNTHESIS_REPORT_PREFIX = "synthesis_report_"

# Language suffixes for bilingual reports
LANG_ZH = "zh"
LANG_EN = "en"

# Bilingual report file patterns
FILE_REPORT_ZH_MD = f"report_{LANG_ZH}.md"
FILE_REPORT_ZH_HTML = f"report_{LANG_ZH}.html"
FILE_REPORT_EN_MD = f"report_{LANG_EN}.md"
FILE_REPORT_EN_HTML = f"report_{LANG_EN}.html"
FILE_SYNTHESIS_REPORT_ZH_SUFFIX = f"_{LANG_ZH}"
FILE_SYNTHESIS_REPORT_EN_SUFFIX = f"_{LANG_EN}"

SUPPORTED_IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
SUPPORTED_ASSET_FORMATS = SUPPORTED_IMAGE_FORMATS | {".pdf"}


class ExperimentPaths(BaseModel):
    """单实验在 workspace 下的约定路径（只读，由 ``utils.experiment_paths`` 构建）。"""

    hypothesis_base: Path = Field(..., description="hypothesis_<id> directory")
    experiment_path: Path = Field(..., description="experiment_<id> directory")
    run_path: Path = Field(..., description="run directory")
    db_path: Path = Field(..., description="replay directory or legacy sqlite.db path")
    pid_path: Path = Field(..., description="pid.json path")
    assets_path: Path = Field(..., description="run/artifacts directory")

    model_config = ConfigDict(arbitrary_types_allowed=True)


class PresentationPaths(BaseModel):
    """单实验分析产物的输出路径。

    这些路径按 hypothesis 聚合，位于 ``presentation/`` 下，由
    ``utils.presentation_paths`` 构建。

    典型产物包括：

    - ``output_dir/`` 下的双语报告、``README.md`` 与 ``data/analysis_summary.json`` 。
    - ``charts/`` 下的生成图表，以及复制到 ``assets/`` 的报告引用资源。
    """

    output_dir: Path = Field(..., description="presentation/hypothesis_<id>")
    charts_dir: Path = Field(
        ..., description="Charts output directory for generated visualizations"
    )
    report_assets_dir: Path = Field(
        ..., description="Report assets directory (assets/, referenced by report)"
    )
    report_zh_md: Path = Field(..., description="Chinese markdown report path")
    report_zh_html: Path = Field(..., description="Chinese HTML report path")
    report_en_md: Path = Field(..., description="English markdown report path")
    report_en_html: Path = Field(..., description="English HTML report path")
    result_json: Path = Field(..., description="analysis_summary.json path")
    readme: Path = Field(..., description="README.md path")

    model_config = ConfigDict(arbitrary_types_allowed=True)


class SynthesisPaths(BaseModel):
    """综合报告输出路径（位于独立 synthesis 根目录下）。"""

    output_dir: Path = Field(..., description="synthesis")
    report_assets_dir: Path = Field(..., description="Synthesis assets directory")
    report_zh_md: Path = Field(
        ..., description="Chinese synthesis markdown report path"
    )
    report_en_md: Path = Field(
        ..., description="English synthesis markdown report path"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ExperimentStatus(str, Enum):
    """实验执行的状态"""

    SUCCESSFUL = "successful"
    PARTIAL_SUCCESS = "partial_success"
    FAILED = "failed"
    INTERRUPTED = "interrupted"
    UNKNOWN = "unknown"


class ExperimentDesign(BaseModel):
    """实验设计"""

    hypothesis: str = Field(..., description="Primary hypothesis being tested")
    objectives: list[str] = Field(
        default_factory=list, description="Experiment objectives"
    )
    variables: dict[str, Any] = Field(default_factory=dict, description="Variables")
    methodology: str = Field(default="", description="Experimental methodology")
    success_criteria: list[str] = Field(
        default_factory=list, description="Success criteria"
    )

    hypothesis_markdown: str | None = Field(
        default=None, description="Raw content of HYPOTHESIS.md if available"
    )
    experiment_markdown: str | None = Field(
        default=None, description="Raw content of EXPERIMENT.md if available"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ExperimentContext(BaseModel):
    """完整实验状态"""

    experiment_id: str = Field(..., description="Experiment identifier")
    hypothesis_id: str = Field(..., description="Hypothesis identifier")
    design: ExperimentDesign = Field(..., description="Experiment design")

    duration_seconds: float | None = Field(None, description="Duration in seconds")
    execution_status: ExperimentStatus = Field(
        default=ExperimentStatus.UNKNOWN, description="Execution status"
    )
    completion_percentage: float = Field(
        default=0.0, description="Completion percentage"
    )
    error_messages: list[str] = Field(
        default_factory=list, description="Error messages"
    )


class AnalysisResult(BaseModel):
    """实验分析结果"""

    experiment_id: str = Field(..., description="Experiment identifier")
    hypothesis_id: str = Field(..., description="Hypothesis identifier")

    insights: list[Any] = Field(default_factory=list, description="Generated insights")
    findings: list[Any] = Field(default_factory=list, description="Key findings")
    conclusions: Any = Field(default="", description="Conclusions")
    recommendations: list[Any] = Field(
        default_factory=list, description="Recommendations"
    )

    generated_at: datetime = Field(
        default_factory=datetime.now, description="Generation time"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ReportContent(BaseModel):
    """报告内容（支持中英双语）"""

    title: str = Field(..., description="Report title")
    subtitle: str = Field(default="", description="Report subtitle")
    format_preference: str = Field(
        default="markdown", description="Preferred format: markdown, html, or both"
    )
    # 双语字段
    full_content_markdown_zh: str | None = Field(
        default=None, description="Chinese markdown report content"
    )
    full_content_html_zh: str | None = Field(
        default=None, description="Chinese HTML report content"
    )
    full_content_markdown_en: str | None = Field(
        default=None, description="English markdown report content"
    )
    full_content_html_en: str | None = Field(
        default=None, description="English HTML report content"
    )

    @property
    def full_content_markdown(self) -> str | None:
        """中文优先，否则英文。"""
        return self.full_content_markdown_zh or self.full_content_markdown_en

    @property
    def full_content_html(self) -> str | None:
        """中文优先，否则英文。"""
        return self.full_content_html_zh or self.full_content_html_en

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ReportAsset(BaseModel):
    """报告所需要的其他资源"""

    asset_id: str = Field(..., description="Asset identifier")
    asset_type: str = Field(..., description="Asset type")
    title: str = Field(..., description="Asset title")
    description: str = Field(default="", description="Asset description")

    file_path: str = Field(..., description="File path")
    embedded_content: str | None = Field(None, description="Base64 content")
    file_size: int = Field(default=0, description="File size in bytes")

    created_at: datetime = Field(
        default_factory=datetime.now, description="Creation time"
    )
    dimensions: dict[str, int] | None = Field(None, description="Dimensions")

    model_config = ConfigDict(arbitrary_types_allowed=True)


class HypothesisSummary(BaseModel):
    """跨多个实验的分析结果"""

    hypothesis_id: str = Field(..., description="Hypothesis identifier")
    hypothesis_text: str = Field(..., description="Hypothesis text")

    experiment_count: int = Field(default=0, description="Number of experiments")
    successful_experiments: int = Field(
        default=0, description="Number of successful experiments"
    )
    total_completion: float = Field(
        default=0.0, description="Average completion percentage"
    )

    key_insights: list[str] = Field(default_factory=list, description="Key insights")
    main_findings: list[str] = Field(default_factory=list, description="Main findings")
    experiment_results: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Analysis results for each experiment",
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ExperimentSynthesis(BaseModel):
    """多假设/多实验的综合结果。"""

    synthesis_id: str = Field(..., description="Synthesis identifier")
    workspace_path: str = Field(..., description="Workspace path")
    synthesis_timestamp: datetime = Field(
        default_factory=datetime.now, description="Analysis timestamp"
    )

    hypothesis_summaries: list[HypothesisSummary] = Field(
        default_factory=list,
        description="Summary information for each hypothesis",
    )

    synthesis_strategy: str = Field(
        default="", description="Analysis strategy decided by LLM"
    )
    cross_hypothesis_analysis: str = Field(
        default="", description="Cross-hypothesis analysis"
    )
    comparative_insights: list[str] = Field(
        default_factory=list, description="Comparative insights"
    )
    unified_conclusions: str = Field(default="", description="Unified conclusions")
    recommendations: list[str] = Field(
        default_factory=list, description="Comprehensive recommendations"
    )

    best_hypothesis: str | None = Field(None, description="Best hypothesis identifier")
    best_hypothesis_reason: str = Field(
        default="", description="Reason for best hypothesis"
    )
    overall_assessment: str = Field(default="", description="Overall assessment")

    synthesis_report_path: str | None = Field(
        None, description="Synthesis report Markdown file path"
    )
    synthesis_report_html_path: str | None = Field(
        None, description="Synthesis report HTML file path"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)
