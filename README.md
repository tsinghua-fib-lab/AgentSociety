<div style="text-align: center; background-color: white; padding: 20px; border-radius: 30px;">
  <img src="./static/agentsociety_logo.png" alt="AgentSociety Logo" width="200" style="display: block; margin: 0 auto;">
  <h1 style="color: black; margin: 0; font-size: 3em;">AgentSociety: LLM Agents in Society</h1>
</div>

<p align="center">
  <a href="./README.md">English</a> · <a href="./README_zh.md">中文</a>
</p>

<p align="center">
  <a href="https://github.com/tsinghua-fib-lab/AgentSociety/stargazers">
    <img src="https://img.shields.io/github/stars/tsinghua-fib-lab/AgentSociety?style=social" alt="GitHub Stars">
  </a>
  <a href="https://github.com/tsinghua-fib-lab/AgentSociety/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License">
  </a>
  <a href="https://pypi.org/project/agentsociety2/">
    <img src="https://img.shields.io/pypi/v/agentsociety2.svg" alt="PyPI (v2)">
  </a>
  <a href="https://pypi.org/project/agentsociety/">
    <img src="https://img.shields.io/pypi/v/agentsociety.svg?label=pypi%20(v1)" alt="PyPI (v1)">
  </a>
</p>

<p align="center">
  <a href="https://agentsociety2.readthedocs.io/">
    <img src="https://img.shields.io/badge/docs-v2%20(recommended)-brightgreen" alt="Documentation v2">
  </a>
  <a href="https://agentsociety.readthedocs.io/">
    <img src="https://img.shields.io/badge/docs-v1%20(legacy)-lightgrey" alt="Documentation v1">
  </a>
</p>

---

AgentSociety is a framework for building LLM-based agent simulations in urban environments and research workflows.

**Papers:**

- **AgentSociety 2** (recommended): [arXiv:2607.11895](https://arxiv.org/abs/2607.11895)
- **AgentSociety** (v1): [arXiv:2502.08691](https://arxiv.org/abs/2502.08691)

Machine-readable citations: [CITATION.cff](./CITATION.cff) · [citations.bib](./citations.bib)

## Star History

<a href="https://star-history.dera.page/#tsinghua-fib-lab/AgentSociety&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://star-history.dera.page/svg?repos=tsinghua-fib-lab/AgentSociety&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://star-history.dera.page/svg?repos=tsinghua-fib-lab/AgentSociety&type=Date" />
   <img alt="Star History Chart" src="https://star-history.dera.page/svg?repos=tsinghua-fib-lab/AgentSociety&type=Date" />
 </picture>
</a>

## Packages

This repository contains two main packages:

### AgentSociety 2 (Recommended)

[![PyPI Version](https://img.shields.io/pypi/v/agentsociety2.svg)](https://pypi.org/project/agentsociety2/)

**AgentSociety 2** is a modern, LLM-native agent simulation platform designed for social science research and experimentation.

```bash
pip install agentsociety2
```

**Features:**

- **LLM-Native Design**: Built from the ground up for LLM-driven agents
- **Flexible Environment System**: Modular environment components with hot-pluggable tools
- **Multiple Reasoning Patterns**: CodeGen (default), ReAct, Plan-Execute, Two-Tier, and Search routers
- **Scalable Execution**: Agents are workspace-bound stateless records driven by Ray Tasks, with env / LLM clients / trace / replay handles behind a single `ServiceProxy`
- **Research Skills**: Literature search, hypothesis generation, experiment design, paper writing
- **Experiment Replay**: Catalog-driven JSONL replay with DuckDB-powered reads and distributed tracing
- **MCP Support**: Model Context Protocol integration for tool extensibility

**Documentation:** [agentsociety2.readthedocs.io](https://agentsociety2.readthedocs.io/)

**Source:** [packages/agentsociety2/](./packages/agentsociety2/)

### AgentSociety 1.x (Legacy)

[![PyPI Version](https://img.shields.io/pypi/v/agentsociety.svg)](https://pypi.org/project/agentsociety/)

**AgentSociety 1.x** is the original city simulation framework with gRPC-based environment integration.

```bash
pip install agentsociety
```

**Features:**

- City-scale simulation with Ray distributed computing
- Urban environment modules (mobility, economy, social)
- Multi-agent coordination and communication

**Documentation:** [agentsociety.readthedocs.io](https://agentsociety.readthedocs.io/)

**Source:** [packages/agentsociety/](./packages/agentsociety/)

## Other Packages

- **[agentsociety-community](./packages/agentsociety-community/)**: Community contributions for custom agents and blocks
- **[agentsociety-benchmark](./packages/agentsociety-benchmark/)**: Benchmarking utilities for agent evaluation

## Project Structure

```
AgentSociety/
├── packages/
│   ├── agentsociety2/      # v2.x - Modern LLM-native platform (recommended)
│   ├── agentsociety/       # v1.x - Legacy city simulation
│   ├── agentsociety-community/
│   └── agentsociety-benchmark/
├── frontend/               # React web frontend
├── extension/              # VSCode extension
├── packages/agentsociety/docs/   # v1 Sphinx documentation (legacy)
└── examples/               # Example experiments
```

## Quick Start

### AgentSociety 2

Before running the example, configure the LLM environment variables:

```bash
export AGENTSOCIETY_LLM_API_KEY="your-api-key"
export AGENTSOCIETY_LLM_API_BASE="https://api.openai.com/v1"
export AGENTSOCIETY_LLM_MODEL="gpt-5.5"
```

```python
import asyncio
from datetime import datetime
from pathlib import Path
from agentsociety2.env import CodeGenRouter
from agentsociety2.contrib.env import SimpleSocialSpace
from agentsociety2.society import AgentSociety

async def main():
    # Agents are declared as metadata (specs); AgentSociety creates their workspaces in init().
    agent_specs = [{"id": 1, "profile": {"name": "Alice"}, "config": {}}]
    env = CodeGenRouter(env_modules=[SimpleSocialSpace(agent_id_name_pairs=[(1, "Alice")])])
    society = AgentSociety(
        agent_specs=agent_specs,
        agent_class_name="PersonAgent",
        env_router=env,
        start_t=datetime.now(),
        run_dir=Path("run"),
    )
    await society.init()
    response = await society.ask("What's your name?")
    print(response)
    await society.close()

asyncio.run(main())
```

### AgentSociety 1.x

```python
from agentsociety import AgentSociety

# See packages/agentsociety/README.md for usage
```

## Requirements

- Python >= 3.11
- An LLM API key (OpenAI, Anthropic, or any litellm-supported provider)

## Contributors

Thank you to everyone who has contributed to this project:

<a href="https://github.com/tsinghua-fib-lab/AgentSociety/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=tsinghua-fib-lab/AgentSociety" alt="Contributors" />
</a>

## License

AgentSociety is licensed under the Apache License Version 2.0 except for the `packages/agentsociety/commercial` folder. See the [LICENSE](LICENSE) file for details.

## Citation

If you use AgentSociety in your research, please cite the relevant paper(s). Prefer **AgentSociety 2** when using the current platform (`agentsociety2`); cite **AgentSociety (v1)** when referring to the original large-scale city simulator.

See also [CITATION.cff](./CITATION.cff) and [citations.bib](./citations.bib).

**AgentSociety 2** ([arXiv:2607.11895](https://arxiv.org/abs/2607.11895)):

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

**AgentSociety (v1)** ([arXiv:2502.08691](https://arxiv.org/abs/2502.08691)):

```bibtex
@misc{piao2025agentsociety,
  title        = {{AgentSociety}: Large-Scale Simulation of {LLM}-Driven Generative Agents Advances Understanding of Human Behaviors and Society},
  author       = {Jinghua Piao and Yuwei Yan and Jun Zhang and Nian Li and Junbo Yan and Xiaochong Lan and Zhihong Lu and Zhiheng Zheng and Jing Yi Wang and Di Zhou and Chen Gao and Fengli Xu and Fang Zhang and Ke Rong and Jun Su and Yong Li},
  year         = {2025},
  eprint       = {2502.08691},
  archiveprefix= {arXiv},
  primaryclass = {cs.SI},
  doi          = {10.48550/arXiv.2502.08691},
  url          = {https://arxiv.org/abs/2502.08691},
}
```

## Contact

- **Issues**: [GitHub Issues](https://github.com/tsinghua-fib-lab/AgentSociety/issues)
- **Discussions**: [GitHub Discussions](https://github.com/tsinghua-fib-lab/AgentSociety/discussions)
- **Email**: agentsociety.fiblab2025@gmail.com
