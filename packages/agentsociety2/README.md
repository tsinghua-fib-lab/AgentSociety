# AgentSociety 2

<p align="center">
  <a href="./README.md">English</a> · <a href="./README_zh.md">中文</a>
</p>

<p align="center">
  <a href="https://github.com/tsinghua-fib-lab/AgentSociety/stargazers">
    <img src="https://img.shields.io/github/stars/tsinghua-fib-lab/AgentSociety?style=social" alt="GitHub Stars">
  </a>
  <a href="https://pypi.org/project/agentsociety2/">
    <img src="https://img.shields.io/pypi/v/agentsociety2.svg" alt="PyPI Version">
  </a>
  <a href="https://pypi.org/project/agentsociety2/">
    <img src="https://img.shields.io/pypi/pyversions/agentsociety2.svg" alt="Python Version">
  </a>
  <a href="https://github.com/tsinghua-fib-lab/AgentSociety/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License">
  </a>
</p>

<p align="center">
  <a href="https://agentsociety2.readthedocs.io/">
    <img src="https://img.shields.io/badge/docs-English-brightgreen" alt="English Docs">
  </a>
  <a href="https://agentsociety2.readthedocs.io/zh_CN/latest/">
    <img src="https://img.shields.io/badge/docs-%E4%B8%AD%E6%96%87-red" alt="Chinese Docs">
  </a>
</p>

> **AgentSociety 2** is a modern, LLM-native agent simulation platform designed for social science research and experimentation.

## Features

- **LLM-Native Design**: Built from the ground up for LLM-driven agents
- **Flexible Environment System**: Modular environment components with hot-pluggable tools
- **Multiple Reasoning Patterns**: CodeGen (default), ReAct, Plan-Execute, Two-Tier, and Search routers
- **Scalable Execution**: Agents are workspace-bound stateless records driven by Ray Tasks;
  env / LLM clients / trace / replay handles are passed behind a single `ServiceProxy`
- **Developer-Friendly**: Pythonic API with type hints and comprehensive documentation
- **Experiment Replay**: Catalog-driven JSONL replay with DuckDB-powered reads and distributed tracing
- **MCP Support**: Model Context Protocol integration for tool extensibility

## Installation

```bash
pip install agentsociety2
```

### Requirements

- Python 3.11–3.13
- An LLM API key (OpenAI, Anthropic, or any provider supported by LiteLLM)

## Quick Start

Before running examples that call a model, set the LLM environment variables in
[Configuration](#configuration). The framework uses its default model when no model name is supplied.

### Create Your First Agent

```python
import asyncio
from datetime import datetime
from pathlib import Path
from agentsociety2.env import CodeGenRouter
from agentsociety2.contrib.env import SimpleSocialSpace
from agentsociety2.society import AgentSociety


async def main():
    # Declare agent metadata (id / profile / config); agents are NOT instantiated here.
    # AgentSociety batch-creates their workspaces during init().
    agent_specs = [
        {
            "id": 1,
            "profile": {
                "name": "Alice",
                "age": 28,
                "personality": "friendly and curious",
                "bio": "A software engineer who loves hiking and reading.",
            },
            "config": {},
        }
    ]
    names = [(s["id"], s["profile"]["name"]) for s in agent_specs]

    # Create environment module with agent info
    social_env = SimpleSocialSpace(agent_id_name_pairs=names)

    # Create environment router (in-process CodeGenRouter; production uses an EnvRouterProxy Ray actor)
    env_router = CodeGenRouter(env_modules=[social_env])

    # Create the society
    society = AgentSociety(
        agent_specs=agent_specs,
        agent_class_name="PersonAgent",
        env_router=env_router,
        start_t=datetime.now(),
        run_dir=Path("run"),
    )

    # Initialize (batch-creates agent workspaces, binds the environment)
    await society.init()

    # Query (read-only)
    response = await society.ask("What's your favorite activity?")
    print(f"Agent: {response}")

    # Close the society
    await society.close()


if __name__ == "__main__":
    asyncio.run(main())
```

### Create a Custom Environment Module

```python
from agentsociety2.env import EnvBase, tool


class MyCustomEnvironment(EnvBase):
    """A custom environment module."""

    @tool(readonly=True, kind="observe")
    def get_weather(self, agent_id: int) -> str:
        """Get the current weather for an agent."""
        return "The weather is sunny and 25°C."

    @tool(readonly=False)
    def set_mood(self, agent_id: int, mood: str) -> str:
        """Change the mood of an agent."""
        return f"Agent {agent_id}'s mood is now {mood}."


# Use the custom module
from agentsociety2.env import CodeGenRouter

env_router = CodeGenRouter(env_modules=[MyCustomEnvironment()])
```

### Run a Complete Experiment

```python
import asyncio
from datetime import datetime
from pathlib import Path
from agentsociety2.env import CodeGenRouter
from agentsociety2.contrib.env import SimpleSocialSpace
from agentsociety2.society import AgentSociety


async def main():
    # Declare agent metadata
    agent_specs = [
        {
            "id": i,
            "profile": {"name": f"Player{i}", "personality": "friendly"},
            "config": {},
        }
        for i in range(1, 4)
    ]
    names = [(s["id"], s["profile"]["name"]) for s in agent_specs]

    # Create environment router (replay is enabled by default -> run/replay/)
    env_router = CodeGenRouter(
        env_modules=[SimpleSocialSpace(agent_id_name_pairs=names)]
    )

    # Create the society
    society = AgentSociety(
        agent_specs=agent_specs,
        agent_class_name="PersonAgent",
        env_router=env_router,
        start_t=datetime.now(),
        run_dir=Path("run"),
    )
    await society.init()

    # Query (read-only)
    answer = await society.ask("What are the names of all agents?")
    print(f"Answer: {answer}")

    # Intervene (read-write)
    result = await society.intervene("Ask Alice to send Bob a greeting")
    print(f"Result: {result}")

    await society.close()


if __name__ == "__main__":
    asyncio.run(main())
```

## Core Concepts

### Agents

Agents are autonomous entities that interact with environments through LLM-powered reasoning:

- **AgentBase**: Abstract base class for all agents
- **PersonAgent**: Skills-based agent — a lightweight orchestrator whose capabilities are provided by a pluggable skill pipeline
- Agents support two interaction modes:
  - `society.ask(question)`: Query using read-only environment tools
  - `society.intervene(instruction)`: Use available write tools to change the environment

#### Agent Skills

PersonAgent follows a **metadata-first, selected-only** model. Skills are self-contained
directories; the only built-in skill is `daily-guidance` (daily behavior / needs-decay
guidance). The old `observation / cognition / plan / memory` skills have been removed —
those capabilities are now expressed via custom skills + workspace state files + `ask_env`.

```
agent/skills/
└── daily-guidance/     # SKILL.md + scripts/daily_guidance.py (pre_step hook)
```

Each skill has:

- `SKILL.md` — YAML frontmatter (`name`, `description`, optional `script` / `hooks`) + behavior docs
- `scripts/*.py` — optional scripts. Trusted built-in skills run **in-process via an `entrypoint(argv, ctx)`**
  contract; custom/`env:` skills execute the same contract in an isolated `skill_worker.py` subprocess,
  and scripts without a callable run as plain subprocesses.

Skills follow metadata-first selection:

- the catalog exposes only name/description until activation
- execution is tool-loop driven (`activate_skill` / `read_skill_file` / `execute_skill_script`)
- `pre_step` / `post_step` lifecycle hooks are rendered into a dedicated `<skill_hooks>` block

Custom skills can be placed in `<workspace>/custom/skills/` and hot-loaded at runtime.

### Environment Modules

Environment modules encapsulate specific functionality through tools:

- **EnvBase**: Base class for creating custom modules
- **@tool decorator**: Register methods as discoverable tools
- Tool kinds:
  - `observe`: Single-parameter observation functions
  - `statistics`: No-parameter aggregation functions
  - Regular tools: Full read/write operations

### Routers

Routers mediate agent-environment interactions using different reasoning patterns:

- **ReActRouter**: Reasoning + Acting loop
- **PlanExecuteRouter**: Plan-first, then execute
- **CodeGenRouter**: Code generation based tool use
- **TwoTierReActRouter**: Two-level reasoning hierarchy
- **TwoTierPlanExecuteRouter**: Two-level planning hierarchy

### Storage

The following example registers a replay table. Register a dataset as well when it should appear in the catalog; directory and dataset conventions are in [the storage guide](docs/storage.rst):

```python
from agentsociety2.storage import ReplayReader, ReplayWriter
from pathlib import Path

writer = ReplayWriter(Path("run/replay"))
await writer.init()

# Replay schema sidecar: run/replay/_schema.json

# Environment modules can register and write their own replay tables.
from agentsociety2.storage import ColumnDef, TableSchema

schema = TableSchema(
    name="custom_metrics",
    columns=[
        ColumnDef("metric_id", "INTEGER", nullable=False),
        ColumnDef("value", "REAL"),
    ],
    primary_key=["metric_id"],
)
await writer.register_table(schema)

reader = ReplayReader(Path("run/replay"))
print(reader.load_dataset_catalog())
reader.close()
```

- **ReplayWriter / ReplayReader**: write sharded JSONL replay datasets plus `_schema.json`
  metadata, then read them through DuckDB-backed views.
- **PersonAgent workspace**: stores per-agent local files under `run/agents/agent_xxxx/`, such as
  `config.json`, `AGENT.json`, `MEMORY.md`, `memory/episodes.jsonl` and `state/`.
- **Trace**: the `agentsociety2.trace` module writes distributed tracing spans through per-process sharded append writers in `run/trace/`
  for profiling steps and model calls.

Legacy SQLite tables like `agent_profile`, `agent_status`, and `agent_dialog` are kept only for compatibility when reading old experiment databases; new runs write `run/replay/` instead.

## Configuration

Set your LLM API credentials via environment variables. The examples below use the OpenAI API endpoint and `gpt-5.5`; other LiteLLM-supported providers can be used by changing the base URL and model id.

**Default Model Configuration**

```bash
# Default LLM (required - used for most operations)
export AGENTSOCIETY_LLM_API_KEY="your-api-key"
export AGENTSOCIETY_LLM_API_BASE="https://api.openai.com/v1"
export AGENTSOCIETY_LLM_MODEL="gpt-5.5"
```

**Optional Configuration**

For specialized tasks, you can configure separate LLM instances:

```bash
# Code Generation LLM (for code-related tasks)
# Falls back to default LLM if not set
export AGENTSOCIETY_CODER_LLM_API_KEY="your-coder-api-key"
export AGENTSOCIETY_CODER_LLM_API_BASE="https://api.openai.com/v1"
export AGENTSOCIETY_CODER_LLM_MODEL="gpt-5.5"

# Nano LLM (for high-frequency, low-latency operations)
# Falls back to default LLM if not set
export AGENTSOCIETY_NANO_LLM_API_KEY="your-nano-api-key"
export AGENTSOCIETY_NANO_LLM_API_BASE="https://api.openai.com/v1"
export AGENTSOCIETY_NANO_LLM_MODEL="gpt-5.5"

# Embedding Model (for text embeddings and semantic search)
# Falls back to default LLM if not set
export AGENTSOCIETY_EMBEDDING_API_KEY="your-embedding-api-key"
export AGENTSOCIETY_EMBEDDING_API_BASE="https://api.openai.com/v1"
export AGENTSOCIETY_EMBEDDING_MODEL="text-embedding-3-large"
export AGENTSOCIETY_EMBEDDING_DIMS="1024"

# Data directory (optional, default: ./agentsociety_data)
export AGENTSOCIETY_HOME_DIR="/path/to/your/data"
```

Or use a `.env` file:

```bash
# From the repository root:
cp .env.example .env
# Edit .env with your credentials before importing agentsociety2
```

> **Note**
> Configure credentials before model calls. If using `.env`, load it early in your entrypoint.
> Simulation model settings are separate from Claude Code / Codex provider routing.

## Examples

The `examples/` directory (under this package) contains ready-to-run examples:

- `basics/`: Basic agent and environment usage (workspace `agent_specs` + `run_dir`);
  `02_custom_env_module.py` uses contrib `WeatherEnvironment`
- `games/`: Classic game theory simulations
  - Prisoner's Dilemma (`01_prisoners_dilemma.py`)
  - Public Goods Game (`02_public_goods.py`)
  - Reputation Game (`reputation_game.py`)
- `advanced/`: Multi-router comparison and contrib `SpecialistAgent`
  (`01_custom_agent.py`); production-style runs use `create_env_router_proxy`

Longer batch scripts (Trust Game, Volunteer's Dilemma, Commons Tragedy, etc.) live under
`experiments/env_main_*_v2.py`.

## Documentation

- [English Documentation](https://agentsociety2.readthedocs.io/)
- [中文文档](https://agentsociety2.readthedocs.io/zh_CN/latest/)
- [API Reference](https://agentsociety2.readthedocs.io/en/latest/api/index.html)

## Development

For development guidelines, see [docs/development.rst](docs/development.rst).

### Contributing

We welcome contributions! Please see [CONTRIBUTING.md](../../CONTRIBUTING.md) for details.

## Citation

If you use AgentSociety 2 in your research, please cite:

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

Paper: [arXiv:2607.11895](https://arxiv.org/abs/2607.11895). Repository-wide citations: [CITATION.cff](../../CITATION.cff) · [citations.bib](../../citations.bib).

## License

Apache License 2.0 - see [LICENSE](LICENSE) for details.

## Acknowledgments

AgentSociety 2 builds upon excellent open-source projects:

- [litellm](https://github.com/BerriAI/litellm) - Unified LLM API
- [FastAPI](https://fastapi.tiangolo.com/) - Backend API framework
- [Pydantic](https://docs.pydantic.dev/) - Data validation

## Contact

- **Issues**: [GitHub Issues](https://github.com/tsinghua-fib-lab/agentsociety/issues)
- **Discussions**: [GitHub Discussions](https://github.com/tsinghua-fib-lab/agentsociety/discussions)

---

For the original AgentSociety (v1.x) focused on city simulation, see the [agentsociety package](https://pypi.org/project/agentsociety/).
