<div style="text-align: center; background-color: white; padding: 20px; border-radius: 30px;">
  <img src="./static/agentsociety_logo.png" alt="AgentSociety Logo" width="200" style="display: block; margin: 0 auto;">
  <h1 style="color: black; margin: 0; font-size: 3em;">AgentSociety: LLM Agents in Society</h1>
</div>

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

The paper is available at [arXiv](https://arxiv.org/abs/2502.08691):

```bibtex
@article{piao2025agentsociety,
  title={AgentSociety: Large-Scale Simulation of LLM-Driven Generative Agents Advances Understanding of Human Behaviors and Society},
  author={Piao, Jinghua and Yan, Yuwei and Zhang, Jun and Li, Nian and Yan, Junbo and Lan, Xiaochong and Lu, Zhihong and Zheng, Zhiheng and Wang, Jing Yi and Zhou, Di and others},
  journal={arXiv preprint arXiv:2502.08691},
  year={2025}
}
```

## Star History

<a href="https://www.star-history.com/#tsinghua-fib-lab/AgentSociety&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=tsinghua-fib-lab/AgentSociety&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=tsinghua-fib-lab/AgentSociety&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=tsinghua-fib-lab/AgentSociety&type=Date" />
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
- **Multiple Reasoning Patterns**: ReAct, Plan-Execute, Code Generation, Two-Tier routers
- **Research Skills**: Literature search, hypothesis generation, experiment design, paper writing
- **Experiment Replay**: Full SQLite-based replay system
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
├── docs_v1/                # v1 Sphinx documentation
└── examples/               # Example experiments
```

## Quick Start

### AgentSociety 2

```python
import asyncio
from datetime import datetime
from agentsociety2 import PersonAgent
from agentsociety2.env import CodeGenRouter
from agentsociety2.contrib.env import SimpleSocialSpace
from agentsociety2.society import AgentSociety

async def main():
    agent = PersonAgent(id=1, profile={"name": "Alice"})
    env = CodeGenRouter(env_modules=[SimpleSocialSpace(agent_id_name_pairs=[(1, "Alice")])])
    society = AgentSociety(agents=[agent], env_router=env, start_t=datetime.now())
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

If you use AgentSociety in your research, please cite:

```bibtex
@article{piao2025agentsociety,
  title={AgentSociety: Large-Scale Simulation of LLM-Driven Generative Agents Advances Understanding of Human Behaviors and Society},
  author={Piao, Jinghua and Yan, Yuwei and Zhang, Jun and Li, Nian and Yan, Junbo and Lan, Xiaochong and Lu, Zhihong and Zheng, Zhiheng and Wang, Jing Yi and Zhou, Di and others},
  journal={arXiv preprint arXiv:2502.08691},
  year={2025}
}
```

## Contact

- **Issues**: [GitHub Issues](https://github.com/tsinghua-fib-lab/agentsociety/issues)
- **Discussions**: [GitHub Discussions](https://github.com/tsinghua-fib-lab/agentsociety/discussions)
- **Email**: agentsociety.fiblab2025@gmail.com
