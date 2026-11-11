## Meet the Layout

Click **AI Social Scientist** in the activity bar to open the project tree. The table lists the main entry points.

![Workbench overview](../images/vscode-layout-overview.png)

| Name | What it does |
|------|--------------|
| **Activity Bar** | Switch Explorer, Search, Git, Extensions, AI Social Scientist, and other views. |
| **AI Social Scientist sidebar** | Project tree: AI Chat, skill management (Runtime / Claude / Market / MCP), environments & agents, research topic (`TOPIC.md`), literature, user data, datasets, custom modules. |
| **Editor** | Config pages, Markdown, experiment files, Claude Code, replay, and more; idle view shows useful shortcuts. |
| **AI Chat** | Chat surface: select an available model, describe a task and attach file context. The exact panel depends on the installed client. |
| **Status Bar** | Git, diagnostics, backend port (e.g. `8001`), active model; click to manage backend and gateway. |
| **Accounts / Settings** | Bottom of the activity bar: account sync and VS Code settings, keybindings, themes. |
| **Title bar / breadcrumbs** | Current path and layout controls; quick access to chat or panel layout. |

### A human-steered research workspace

The interface implements the paper's **Interactive Research Environment (IRE)**: the researcher keeps high-level control over questions, assumptions, interventions, and interpretation, while the AI Social Scientist carries out lower-level operations across files, agents, artifacts, simulation, and experiment execution.

![Human-steered IRE: high-level researcher guidance and low-level AI Social Scientist execution](../images/agentsociety2-human-steered-ire.png)

*Conceptual architecture adapted from Figure 4 of the [AgentSociety 2 paper](https://arxiv.org/abs/2607.11895). Human guidance determines the question and review points; tool operations update workspace files and experiments.*

### Sidebar actions

| Button | Function |
|--------|----------|
| ⚙️ Config | Open LLM / API settings |
| 🔄 Refresh | Reload the project tree |
| 🗺️ Quick Start | Open this walkthrough |
| ⬇️ Export | Pack this research project to send to someone else |
| ⬆️ Import | Open a project archive someone shared with you |
| 🌐 Language | Switch the extension UI between Chinese and English |

Skill management is not a toolbar button: click the **Skills** item at the top of the project tree (Agent · Claude · Marketplace), or use the Command Palette. The user guide is also available from the Command Palette.

### Typical folders

```
workspace-root/
├── TOPIC.md
├── papers/          # Literature
├── datasets/        # Datasets
├── user_data/       # User data
├── custom/          # Custom modules and agent skills
├── .claude/skills/  # Claude / Codex skills
├── .agentsociety/   # Project settings and workflow state
├── hypothesis_*/    # Hypotheses and experiments
├── presentation/    # Analysis reports and assets
├── synthesis/       # Cross-hypothesis synthesis
└── paper/           # Paper workspace
```

[Open Sidebar](command:projectStructureView.focus)
