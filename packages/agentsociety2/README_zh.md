# AgentSociety 2

<p align="center">
  <a href="./README.md">English</a> · <a href="./README_zh.md">中文</a>
</p>

AgentSociety 2 是面向计算社会科学的现代化、LLM 原生智能体仿真与科研平台。它把智能体、环境模块、实验运行、replay 存储和研究技能组织在一个统一的 Python 包中，并可通过 CLI、FastAPI 后端和 VS Code 扩展使用。

## 安装

```bash
pip install agentsociety2
```

要求：

- Python 3.11–3.13
- 一个 LiteLLM 支持的 LLM API Key

## 快速开始

运行会调用模型的示例前，先配置 LLM 环境变量；未显式指定模型名时使用框架默认值：

```bash
export AGENTSOCIETY_LLM_API_KEY="your-api-key"
export AGENTSOCIETY_LLM_API_BASE="https://api.openai.com/v1"
export AGENTSOCIETY_LLM_MODEL="gpt-5.5"
```

最小示例（智能体以 spec 元数据声明，由 ``AgentSociety`` 在 ``init`` 时批量创建 workspace）：

```python
import asyncio
from datetime import datetime
from pathlib import Path

from agentsociety2.contrib.env import SimpleSocialSpace
from agentsociety2.env import CodeGenRouter
from agentsociety2.society import AgentSociety


async def main():
    agent_specs = [
        {
            "id": 1,
            "profile": {
                "name": "Alice",
                "age": 28,
                "personality": "friendly and curious",
            },
            "config": {},
        }
    ]
    names = [(s["id"], s["profile"]["name"]) for s in agent_specs]

    social_env = SimpleSocialSpace(agent_id_name_pairs=names)
    env_router = CodeGenRouter(env_modules=[social_env])
    society = AgentSociety(
        agent_specs=agent_specs,
        agent_class_name="PersonAgent",
        env_router=env_router,
        start_t=datetime.now(),
        run_dir=Path("run"),
    )

    await society.init()
    print(await society.ask("What's your favorite activity?"))
    await society.close()


asyncio.run(main())
```

## 核心概念

- **PersonAgent / AgentBase**：默认人物智能体。基于 `AgentBase`（直接拥有 workspace / 技能运行时 / ReAct 循环 / TODO / trace），作为 workspace 绑定的**无状态 record**，由 Ray Task 流式驱动。
- **Agent Skills**：metadata-first 的 skill 选择模型；当前唯一内置技能是 `daily-guidance`，自定义技能放在 `custom/skills/`。内置技能脚本可在进程内执行；自定义技能的 `entrypoint(argv, ctx)` 在独立 worker 子进程中执行。
- **Environment Modules**：继承 `EnvBase`，通过 `@tool` 暴露可观察、统计和读写工具；可声明
  `is_concurrency_safe()`，全部安全时 env Ray actor 并行 fan-out（`AGENTSOCIETY_ENV_ACTOR_MAX_CONCURRENCY`）。
- **ServiceProxy**：把 env / LLM clients / trace / replay 句柄收口为单一容器注入 agent。
- **CodeGenRouter**：推荐的环境路由器（另有 ReAct / Plan-Execute / Two-Tier / Search 路由器可选）；
  FAISS 指令模板缓存仅在 `template_mode=True` 时启用。
- **ReplayWriter / ReplayReader / Trace**：`run/replay/` 下的 sharded JSONL replay dataset、`_schema.json` catalog 与 DuckDB 读侧 + 分布式 trace span。新实验不再写旧的 `sqlite.db`、`agent_profile` / `agent_status` / `agent_dialog` 表。
- **Agent Workspace**：每个 `PersonAgent` 在 `run/agents/agent_xxxx/` 下维护 `config.json` / `AGENT.json`（含 `world_description`） / `MEMORY.md` / `memory/` / `state/`；调用追踪位于 `run/trace/`。

## 示例

包内 `examples/`：

- `basics/`：入门（含 contrib `WeatherEnvironment`）
- `games/`：囚徒困境 / 公共物品 / 声誉博弈
- `advanced/`：多路由器比较与 contrib `SpecialistAgent`

更长的批量实验脚本见 `experiments/env_main_*_v2.py`。

## 配置

默认模型配置：

```bash
export AGENTSOCIETY_LLM_API_KEY="your-api-key"
export AGENTSOCIETY_LLM_API_BASE="https://api.openai.com/v1"
export AGENTSOCIETY_LLM_MODEL="gpt-5.5"
```

可选：

```bash
export AGENTSOCIETY_CODER_LLM_MODEL="gpt-5.5"
export AGENTSOCIETY_NANO_LLM_MODEL="gpt-5.5"
export AGENTSOCIETY_EMBEDDING_MODEL="text-embedding-3-large"
export AGENTSOCIETY_EMBEDDING_DIMS="1024"
export AGENTSOCIETY_HOME_DIR="./agentsociety_data"
```

源码仓库中也可以从根目录复制 `.env.example`：

```bash
cp .env.example .env
```

## CLI 运行实验

```bash
python -m agentsociety2.society.cli \
  --config my_experiment/init/init_config.json \
  --steps my_experiment/init/steps.yaml \
  --run-dir my_experiment/run \
  --log-level INFO \
  --log-file my_experiment/run/output.log
```

后台运行时请务必指定 `--log-file`。

## 后端服务

```bash
python -m agentsociety2.backend.run
```

默认地址：

- API: http://localhost:8001
- Swagger: http://localhost:8001/docs
- ReDoc: http://localhost:8001/redoc

## 文档与开发

- 在线文档：https://agentsociety2.readthedocs.io/
- 开发指南：[docs/development.rst](./docs/development.rst)
- 贡献指南：[../../CONTRIBUTING.md](../../CONTRIBUTING.md)

开发常用命令：

```bash
uv sync
MEM0_TELEMETRY=False ANONYMIZED_TELEMETRY=False uv run pytest packages/agentsociety2/tests
uv run ruff check packages/agentsociety2
uv run ruff format packages/agentsociety2
```

## 许可证

Apache License 2.0，详见 [LICENSE](./LICENSE)。

## 引用

如果您在研究中使用了 AgentSociety 2，请引用：

```bibtex
@misc{piao2026agentsociety2,
  title        = {{AgentSociety} 2: An Integrated Research Environment for Executable Social Science},
  author       = {Jinghua Piao and Jun Zhang and Haoyu Huang and Keming Zhang and Jing Yi Wang and Xinran Zhao and Songwei Li and Boyuan Sun and Jiayi Chang and Fengli Xu and Chunyan Wang and Fang Zhang and Ke Rong and Jun Su and Tianguang Meng and Yi Liu and Qingguo Meng and Yu Wang and Yong Li},
  year         = {2026},
  eprint       = {2607.11895},
  archiveprefix= {arXiv},
  primaryclass = {cs.CY},
  doi          = {10.48550/arXiv.2607.11895},
  url          = {https://arxiv.org/abs/2607.11895},
}
```

论文：[arXiv:2607.11895](https://arxiv.org/abs/2607.11895)。仓库级引用：[CITATION.cff](../../CITATION.cff) · [citations.bib](../../citations.bib)。

## 联系我们

- **问题反馈**：[GitHub Issues](https://github.com/tsinghua-fib-lab/AgentSociety/issues)
- **讨论**：[GitHub Discussions](https://github.com/tsinghua-fib-lab/AgentSociety/discussions)
- **邮件**：agentsociety.fiblab2025@gmail.com
