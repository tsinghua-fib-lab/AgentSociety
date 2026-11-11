## Start Research with the AI Social Scientist

AI Chat is the collaboration surface; the research itself lives in workspace artifacts and executable experiments. AgentSociety² organizes the process into seven inspectable and revisable stages:

![AI Social Scientist research workflow](../images/ai-social-scientist-workflow.png)

*Figure: from topic scoping, hypothesis generation, experiment design, and simulation configuration to execution, analysis, and manuscript drafting. Original figure from the [AgentSociety 2 paper](https://arxiv.org/abs/2607.11895).*

### First task

> Read `TOPIC.md`, check the workspace folders and current configuration, list missing settings, and show me where to edit them.

### Open AI Chat

Open the right-side **Chat** panel, choose an agent and a model, and describe the task:

![Start a chat](../images/gif/start-chat.gif)

You can also enter from **AI Chat** in the sidebar, the title-bar chat control, or the Command Palette:

[Open AI Chat](command:aiSocialScientist.openChat)

### Share with a colleague

When a project is ready to hand off, use **Export Workspace** in the sidebar. The picker shows the research question, hypotheses and experiments, literature, data, reports, project settings, and skills; existing key content is selected by default. Secrets, `.env`, virtual environments, Git history, and local IDE state (`.cursor` / `.vscode`) are not exported. With **Import Workspace**, the recipient chooses a parent folder and a new project name; the extension creates the directory without overwriting an existing project. They then enter their own model keys.

### Literature library tip

The sidebar **Literature Library** can upload PDFs or ingest a pasted DOI / arXiv ID, with best-effort metadata lookup. Topic-wide search still goes through the literature skill / MCP.
