"""假设数据模型

用于假设与实验分组的 Pydantic 模型。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class HypothesisModel(BaseModel):
    """假设模型"""

    description: str = Field(
        ...,
        description="Concrete statement of the hypothesis to be tested",
    )
    rationale: str = Field(
        ...,
        description="Theoretical or empirical basis and motivation for this hypothesis",
    )


class ExperimentGroupModel(BaseModel):
    """实验分组模型（用于假设生成阶段）"""

    name: str = Field(
        ...,
        description="Name of the experiment group",
    )
    group_type: str = Field(
        ...,
        description="Type of the experiment group (e.g., control, treatment_1, treatment_2)",
    )
    description: str = Field(
        ...,
        description="What is manipulated/varied in this group and what outcome is expected to change",
    )
    agent_selection_criteria: str | None = Field(
        default=None,
        description=(
            "Explicit criteria for selecting agents, described in CONCEPTUAL terms. "
            "Examples: 'agents with collectivist/group-oriented personality', "
            "'agents with high positive mood', 'agents with moderate risk tolerance'. "
            "Use natural language or concepts, NOT specific field names."
        ),
    )


class HypothesisDataModel(BaseModel):
    """假设数据模型（包含假设与实验分组）"""

    hypothesis: HypothesisModel = Field(
        ...,
        description="Hypothesis to be tested",
    )
    groups: list[ExperimentGroupModel] = Field(
        ...,
        min_length=1,
        description="Experiment groups designed to test this hypothesis (at least 1 group required)",
    )
    agent_classes: list[str] | None = Field(
        default=None,
        description=(
            "List of agent class types to use in this hypothesis's simulation. "
            "These should be agent type identifiers (e.g., 'basic_agent', 'social_agent'). "
            "If not provided, will be empty and can be configured later."
        ),
    )
    env_modules: list[str] | None = Field(
        default=None,
        description=(
            "List of environment module types to use in this hypothesis's simulation. "
            "These should be environment module type identifiers (e.g., 'mobility_space', 'event_space'). "
            "If not provided, will be empty and can be configured later."
        ),
    )
