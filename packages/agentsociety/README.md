<div style="text-align: center; background-color: white; padding: 20px; border-radius: 30px;">
  <img src="./static/agentsociety_logo.png" alt="AgentSociety Logo" width="200" style="display: block; margin: 0 auto;">
  <h1 style="color: black; margin: 0; font-size: 3em;">AgentSociety: LLM Agents in City</h1>
</div>

<p align="center">
  <a href="https://github.com/tsinghua-fib-lab/AgentSociety/stargazers">
    <img src="https://img.shields.io/github/stars/tsinghua-fib-lab/AgentSociety?style=social" alt="GitHub Stars">
  </a>
  <a href="https://pypi.org/project/agentsociety/">
    <img src="https://img.shields.io/pypi/v/agentsociety.svg" alt="PyPI Version">
  </a>
  <a href="https://github.com/tsinghua-fib-lab/AgentSociety/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-Apache%202.0-blue.svg" alt="License">
  </a>
  <a href="https://agentsociety.readthedocs.io/">
    <img src="https://img.shields.io/badge/docs-online-blue" alt="Documentation">
  </a>
</p>

---

AgentSociety is an advanced framework specifically designed for building agents in urban simulation environments. With AgentSociety, you can easily create and manage agents, enabling complex urban scenarios to be modeled and simulated efficiently.

The paper is available at [arXiv](https://arxiv.org/abs/2502.08691):

```bibtex
@article{piao2025agentsociety,
  title={AgentSociety: Large-Scale Simulation of LLM-Driven Generative Agents Advances Understanding of Human Behaviors and Society},
  author={Piao, Jinghua and Yan, Yuwei and Zhang, Jun and Li, Nian and Yan, Junbo and Lan, Xiaochong and Lu, Zhihong and Zheng, Zhiheng and Wang, Jing Yi and Zhou, Di and others},
  journal={arXiv preprint arXiv:2502.08691},
  year={2025}
}
```

> **Note**: This is AgentSociety 1.x (legacy). For the modern LLM-native platform, see [AgentSociety 2](https://pypi.org/project/agentsociety2/).

## Star History

<a href="https://www.star-history.com/#tsinghua-fib-lab/AgentSociety&Date">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=tsinghua-fib-lab/AgentSociety&type=Date&theme=dark" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=tsinghua-fib-lab/AgentSociety&type=Date" />
   <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=tsinghua-fib-lab/AgentSociety&type=Date" />
 </picture>
</a>

## Features

- **Mind-Behavior Coupling**: Integrates LLMs' planning, memory, and reasoning capabilities to generate realistic behaviors or uses established theories like Maslow's Hierarchy of Needs and Theory of Planned Behavior for explicit modeling.
- **Environment Design**: Supports dataset-based, text-based, and rule-based environments with varying degrees of realism and interactivity.
- **Interactive Visualization**: Real-time interfaces for monitoring and interacting with agents during experiments.
- **Extensive Tooling**: Includes utilities for interviews, surveys, interventions, and metric recording tailored for social experimentation.

## Framework

AgentSociety presents a robust framework for simulating social behaviors and economic activities in a controlled, virtual environment. 
Utilizing advanced LLMs, AgentSociety emulates human-like decision-making and interactions. 
Our framework is divided into several key layers, each responsible for different functionalities as depicted in the diagram below:

<img src="./static/framework.png" alt="AgentSociety Framework Overview" width="600" style="display: block; margin: 20px auto;">

### Architectural Layers

- **Model Layer**: At the core, this layer manages agent configuration, task definitions, logging setup, and result aggregation. It provides a unified execution entry point for all agent processes, ensuring centralized control over agent behaviors and objectives through task configuration.
- **Agent Layer**: This layer implements multi-head workflows to manage various aspects of agent actions. The Memory component stores agent-related information such as location and motion, with static profiles maintaining unchanging attributes and a custom data pool acting as working memory. The Multi-Head Workflow supports both normal and event-driven modes, utilizing Reason Blocks (for decision-making based on context and tools via LLMs), Route Blocks (for selecting optimal paths using LLMs or rules), and Action Blocks (for executing defined actions).
- **Message Layer**: Facilitating communication among agents, this layer supports peer-to-peer (P2P), peer-to-group (P2G), and group chat interactions, enabling rich, dynamic exchanges within the simulation.
- **Environment Layer**: Managing the interaction between agents and their urban environment, this layer includes Environment Sensing for reading environmental data, Interaction Handling for modifying environmental states, and Message Management for processing incoming and outgoing messages from agents.
- **LLM Layer**: Providing essential configuration and integration services for incorporating Large Language Models (LLMs) into the agents' workflow, this layer supports model invocation and monitoring through Prompting & Execution. It is compatible with various LLMs, including but not limited to OpenAI, Qwen, and Deepseek models, offering flexibility in model choice.
- **Tool Layer**: Complementing the framework's capabilities, this layer offers utilities like string processing for parsing and formatting, result analysis for interpreting responses in formats like JSON or dictionaries, and data storage and retrieval mechanisms that include ranking and search functionalities.

## Setup

### Requirements

- Python >= 3.11
- Linux AMD64 or macOS

### Install via pip

```bash
pip install agentsociety
```

## Quick Start

To get started quickly, please refer to the `examples` folder in the repository. It contains sample scripts and configurations to help you understand how to create and use agents in an urban simulation environment.

Check our online document for detailed usage tutorial: [AgentSociety Document](https://agentsociety.readthedocs.io/en/latest/index.html).

## Contributing

We welcome contributions from the community!

Thank you to everyone who has contributed to this project:

<a href="https://github.com/tsinghua-fib-lab/AgentSociety/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=tsinghua-fib-lab/AgentSociety" alt="Contributors" />
</a>

## License

AgentSociety is licensed under the Apache License Version 2.0 except for the `packages/agentsociety/commercial` folder. See the [LICENSE](LICENSE) file for more details.

---

For the modern LLM-native platform, see [AgentSociety 2](https://pypi.org/project/agentsociety2/).
