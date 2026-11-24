"""AgentSociety2 技能模块。

本模块包含研究工作流和分析工具层入口，支持完整的科研流程：

技能列表
========

- **literature**: 学术文献搜索与管理，支持检索、索引和格式化
- **experiment**: 实验配置与执行，支持参数生成和配置验证
- **hypothesis**: 假设生成与管理，支持创建、读取、列表和删除
- **analysis**: 数据分析工具层，提供实验上下文读取、EDA 和工具注册能力

使用示例
========

.. code-block:: python

    from pathlib import Path

    from agentsociety2.skills import analysis, hypothesis, literature

    # 文献检索
    results = await literature.search_literature("machine learning")

    # 创建假设
    hypothesis.add_hypothesis(
        workspace_path=Path("./workspace"),
        hypothesis_data={
            "hypothesis": {
                "description": "社会网络密度影响信息传播速度",
                "rationale": "高密度网络提供更多传播路径",
            },
            "groups": [
                {
                    "name": "high_density",
                    "group_type": "treatment",
                    "description": "高密度网络",
                }
            ],
        },
    )

    # 读取实验 replay catalog
    from agentsociety2.storage import ReplayReader

    reader = ReplayReader(Path("./workspace/hypothesis_1/experiment_1/run/replay"))
    datasets = reader.load_dataset_catalog()
    reader.close()
"""

from agentsociety2.skills import (
    analysis,
    experiment,
    hypothesis,
    literature,
)

__all__ = [
    "analysis",
    "experiment",
    "hypothesis",
    "literature",
]
