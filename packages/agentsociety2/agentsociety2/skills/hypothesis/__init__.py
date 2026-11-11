"""假设管理模块

提供以下功能：

- 创建假设
- 读取假设
- 列出假设
- 删除假设
"""

from agentsociety2.skills.hypothesis.manager import (
    add_hypothesis,
    add_hypothesis_with_validation,
    create_hypothesis_structure,
    delete_hypothesis,
    find_existing_hypotheses,
    generate_experiment_markdown,
    generate_hypothesis_markdown,
    generate_sim_settings,
    get_hypothesis,
    get_next_hypothesis_id,
    list_hypotheses,
    validate_hypothesis_schema,
)
from agentsociety2.skills.hypothesis.models import (
    ExperimentGroupModel,
    HypothesisDataModel,
    HypothesisModel,
)

__all__ = [
    "ExperimentGroupModel",
    "HypothesisDataModel",
    # Models
    "HypothesisModel",
    "add_hypothesis",
    "add_hypothesis_with_validation",
    "create_hypothesis_structure",
    "delete_hypothesis",
    # Manager
    "find_existing_hypotheses",
    "generate_experiment_markdown",
    "generate_hypothesis_markdown",
    "generate_sim_settings",
    "get_hypothesis",
    "get_next_hypothesis_id",
    "list_hypotheses",
    "validate_hypothesis_schema",
]
