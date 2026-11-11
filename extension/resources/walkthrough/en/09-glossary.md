## Glossary

This appendix explains common terms used by AI Social Scientist and AgentSociety², grouped alphabetically. You do not need to memorize them before starting; come back here when a concept feels unclear.

Quick index: [A](#a) · [B-C](#b-c) · [D-E](#d-e) · [F-I](#f-i) · [L-M](#l-m) · [P-R](#p-r) · [S-T](#s-t) · [V-W](#v-w)

### A

| Term | Meaning |
|------|---------|
| **Agent** | An entity that can observe an environment, plan actions, call tools, and keep state toward a goal. |
| **Agent runtime skill** | A skill installed under `custom/skills/`, mainly used by agents during simulations. |
| **AgentSociety²** | An LLM-native agentic research framework for turning social science questions into runnable and inspectable computational experiments. |
| **AGENTS.md** | Project instructions for general coding assistants, including structure, commands, and collaboration conventions. |
| **AI Chat** | The extension's chat entry point for asking research questions, generating configs, checking results, or operating on the project. |
| **AI CLI Gateway** | A built-in local proxy gateway that routes Claude Code and Codex CLI requests through third-party providers. |
| **AI Social Scientist** | The VS Code extension and research workbench for project management, configuration, skills, replay, and help pages; also the agentic research role that coordinates literature, hypotheses, experiment design, simulation, analysis, and manuscript drafting (earlier material may call the role a Silicon Scientist). |
| **API Base** | The service endpoint for model calls, such as `https://api.openai.com/v1`. |
| **API Key** | The secret key used to call a model provider. Keep it local and do not commit it to a public repository. |

### B-C

| Term | Meaning |
|------|---------|
| **Backend** | The local Python service behind the extension. Start it for the full extension experience; local file viewing, config editing, and CLI/Claude Code experiment runs can continue if it is not running yet. |
| **Bypass permission mode** | Claude Code `bypassPermissions`: fewer permission prompts in a trusted workspace; never use on untrusted repos. |
| **Claude Code skill** | A skill installed under `.claude/skills/`, mainly used by Claude Code or similar coding assistants in the IDE. |
| **CLAUDE.md** | Project instructions for Claude Code, used to explain how the coding assistant should understand and work with this project. |
| **Codex CLI** | OpenAI's command-line coding assistant. Can be routed through the local gateway to third-party providers. |
| **Command Palette** | VS Code's quick command launcher, opened with `Ctrl+Shift+P` or `Cmd+Shift+P`. |
| **Custom Module** | User-provided extension code for adding environment mechanisms, tools, or experiment logic. |

### D-E

| Term | Meaning |
|------|---------|
| **Embedding Model** | A model that converts text into vectors, often used for semantic search and literature retrieval. |
| **Environment** | The simulated setting in which agents act, such as space, resources, economic rules, social relations, or custom mechanisms. |
| **Evidence Graph** | A visualization of evidence relationships in analysis results, viewable by right-clicking in the project tree. |
| **`.env`** | A local workspace configuration file commonly used for API endpoints, keys, model names, and runtime settings. |
| **Experiment Config** | The configuration files that define how an experiment is initialized, executed, and saved. |
| **External Question** | An external survey or interview dispatched by the questionnaire runner; PersonAgent answers it in ask mode and returns the complete answer through a restricted `finish` tool. |

### F-I

| Term | Meaning |
|------|---------|
| **FastAPI backend** | The local Python API service for extension features such as agent runtime skill management, module discovery, prefill parameters, replay endpoints, and API docs. |
| **Integrated Research Environment** | A unified research environment that connects literature, hypotheses, experiments, simulations, analysis, and writing in one workflow. |

### L-M

| Term | Meaning |
|------|---------|
| **Literature Library** | The project area for paper PDFs, Markdown notes, literature indexes, and research materials. Supports PDF upload or pasted DOI / arXiv IDs with best-effort metadata lookup. |
| **LLM** | A large language model such as GPT, Claude, DeepSeek, or Qwen. |
| **MCP** | Model Context Protocol, which lets coding assistants such as Claude Code connect to external tools, remote HTTP/SSE services, or local backends. |
| **Model** | The model name used for requests. Model names differ across providers. |

### P-R

| Term | Meaning |
|------|---------|
| **Paper Workspace** | The paper working directory (`paper/`) containing sections, reviews, compile outputs, etc., managed by paper-toolkit. |
| **PersonAgent** | The default human-like agent in AgentSociety², used to simulate individuals with profiles, memory, intentions, and actions. |
| **Profile** | An agent's descriptive information, such as identity, background, goals, preferences, or role. |
| **Replay** | Recorded experiment traces used to inspect agent behavior, environment changes, and results. |
| **Research workflow** | A connected sequence from literature, hypotheses, experiment design, simulation, and analysis to writing. |
| **Run Directory** | The output directory for one experiment run, usually containing logs, config snapshots, results, and replay data. |

### S-T

| Term | Meaning |
|------|---------|
| **Share package** | An archive created with Export Workspace so you can send a research project to someone else. Secrets, `.env`, venvs, Git history, and local IDE state are omitted; the recipient opens it with Import Workspace. |
| **Silicon Participant** | A simulated participant that generates behavioral responses, receives interventions, and is measured in a configurable social environment; also called a Silicon Subject. |
| **Skill** | An installable capability module that tells an agent or coding assistant when to use a capability, what files to read, and what outputs to produce. |
| **Skill management** | Runtime, Claude, Market and MCP tabs. Runtime skills are activated as needed; Claude synchronization and loading controls belong to the corresponding client. |
| **Steps Config** | A configuration file that describes what an experiment should do, such as ask, intervene, run simulation steps, and save artifacts. |
| **Token** | The unit of text processed by a model, often used for pricing and context limits. |

### V-W

| Term | Meaning |
|------|---------|
| **VS Code workspace** | The project folder currently open in VS Code. The extension reads and writes `.env`, configs, results, skills, and replay data here. |
