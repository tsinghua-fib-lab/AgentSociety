# AI Social Scientist User Guide

Quick Start Path: **Configure API → Start Backend → Manage Skills → Start Using**

---

## Table of Contents

- [Basic Concepts](#Basic-Concepts)
- [System Overview](#System-Overview)
- [System Architecture](#System-Architecture)
- [Main Components](#Main-Components)
- [Configuration](#Configuration)
- [FAQ](#FAQ)
- [Resources](#Resources)

---

## Basic Concepts

If you're new to AI Agents or LLMs, this section will help you understand the core concepts.

### What is LLM (Large Language Model)?

LLM (Large Language Model) is an AI system trained on massive amounts of text data.

**What can it do?**
- Understand natural language questions and tasks
- Generate coherent, logical text responses
- Perform complex reasoning, translation, summarization tasks

**Popular LLM Services:**
- OpenAI: GPT-5.5, GPT-5.4, GPT-5.5 Thinking, etc.
- Anthropic: Claude Opus 4.7, Claude Sonnet, etc.
- Google: Gemini 3.1 Pro, Gemini 3.1 Flash, etc.
- Chinese Models: Qwen3.6, DeepSeek-V4, GLM-5, Ernie-5.0, Kimi K2.6, etc.

### What is Token?

Token is the smallest unit that LLMs process text in. Think of it as a "fragment" - an English word might be split into 1-2 tokens, a Chinese character is typically 1-2 tokens.

**Why care about Tokens?**
- LLMs charge by token - more tokens = higher cost
- Each LLM has context length limits (e.g., 128K, 400K tokens) - exceeding limits causes errors
- Longer conversations consume more tokens

**Tips:**
- Put important content first to avoid truncation
- Periodically summarize long conversations to save tokens

### What is Agent?

An Agent is "AI with agency". While regular LLMs can only answer questions, Agents can:

- **Autonomous Planning**: Break complex tasks into multiple steps
- **Tool Calling**: Search literature, run code, read/write files
- **Memory Retention**: Remember context across conversations
- **Self-Correction**: Adjust strategies based on execution results

In this tool, the Agent is your "intelligent research assistant".

### What is MCP (Model Context Protocol)?

MCP (Model Context Protocol) is an open standard led by Anthropic that enables AI models to securely access external data and tools.

**Simple Analogy:** MCP acts as both "translator" and "safety net" between AI and the external world.

**What it enables:**
- Connect to databases, file systems, API services
- Let AI read local files, query databases
- Provide tools to AI in a standardized way

**Security:** Users control which resources can be accessed, preventing dangerous AI operations.

### What is Claude Code?

Claude Code is an **Agentic Coding Tool** developed by Anthropic, running in terminals, capable of understanding entire codebases and executing complex development tasks.

**Core Capabilities:**
- Understand entire project codebases, edit and refactor across files
- Execute Shell commands, handle Git workflows
- Support MCP protocol, connect external tools and data sources
- Automatically execute "gather context → take action → verify results" loops

**Relationship with this project:**
- This plugin's Claude skills are installed in `.claude/skills/` directory for Claude Code to use
- Through MCP protocol, Claude Code can call this project's backend services

**Learn more:** [Claude Code Documentation](https://code.claude.com/docs/en/overview)

#### How to Configure Custom API for Claude Code

If you need to use third-party models, configure as follows:

**Method 1: Environment Variables (Temporary)**

```bash
export ANTHROPIC_BASE_URL="https://your-api-endpoint.com"
export ANTHROPIC_AUTH_TOKEN="your-api-key"
claude
```

**Method 2: Config File (Permanent)**

Add to `~/.claude/settings.json`:

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://your-api-endpoint.com",
    "ANTHROPIC_AUTH_TOKEN": "your-api-key"
  }
}
```

**Switching Models:**
- In session: type `/model` then select model
- At startup: `claude --model <model-name>`
- In config: add `"model": "your-model-name"` to `~/.claude/settings.json`

**Verify:** Run `/status` command to check current connection status

---

## System Overview

### What is this tool?

AI Social Scientist is an **AI-powered research assistant tool** that helps users leverage large language models for social science research.

**Core Positioning:**
- Intelligent workflow platform for social science researchers
- Supports literature review, hypothesis generation, experiment design, data analysis, paper writing
- Available as VSCode extension and CLI

### Typical Use Cases

| Scenario | Description |
|----------|-------------|
| Literature Review | Automatically search papers, extract key information, generate reviews |
| Hypothesis Generation | Propose testable research hypotheses from existing literature |
| Experiment Design | Generate experiment configurations, design research workflows |
| Data Analysis | Run analysis scripts, generate visualization reports |
| Paper Writing | Assist in writing paper sections, format output |

### Comparison with Direct LLM Chat

| Aspect | Direct LLM Chat | This Tool |
|--------|-----------------|-----------|
| Context | Single conversation, limited length | Long-term memory, persists across sessions |
| Tool Calling | Manual copy-paste | Automatic file read/write, API calls |
| Workflow | Self-organized | Built-in research workflow templates |
| Reproducibility | Hard to trace | Complete records, replayable |

---

## System Architecture

### Overall Architecture

```
User Interface Layer
├── VSCode Extension (this plugin)
├── CLI Command Line Tool
└── Web Frontend (optional)

Backend Service Layer
├── FastAPI Backend (localhost:8001)
├── AgentSociety Core Engine
└── Skill Management Service

Core Component Layer
├── PersonAgent (Intelligent Agent)
├── Environment Router
├── Research Skills
└── ReplayWriter (Storage & Replay)

External Service Layer
├── LLM API (OpenAI/Claude/Chinese Models)
├── Vector Database (ChromaDB)
└── Memory Service (mem0)
```

### Workflow

1. **Configuration Phase**: User fills in LLM API configuration
2. **Startup Phase**: Backend service starts, loads skills and environment modules
3. **Execution Phase**: Agent receives tasks, calls skills, interacts with environment
4. **Storage Phase**: All operations recorded to SQLite for replay

### Agent Workflow

PersonAgent is the core intelligent agent, using **Skill Pipeline** architecture:

1. **Skill Selection**: LLM selects appropriate skills based on task
2. **On-demand Loading**: Only selected skills are loaded
3. **Priority Execution**: Skills execute in priority order
4. **State Management**: Skills can store intermediate states

---

## Main Components

### Skills

Skills are Agent's "capability modules" that determine what the Agent can do.

**Built-in Research Skills:**

| Skill Name | Function | Description |
|------------|----------|-------------|
| literature | Literature Search & Management | Search academic papers, extract key information |
| hypothesis | Hypothesis Generation | Extract research hypotheses from literature |
| experiment | Experiment Design | Generate experiment configuration files |
| analysis | Data Analysis | Run analysis scripts, generate reports |
| paper | Paper Writing | Assist in writing paper sections |

**Skill Categories:**
- **Agent Runtime Skills**: Installed in `custom/skills/`, used during Agent simulation
- **Claude/Cursor Skills**: Installed in `.claude/skills/`, assist development in IDE

### Environment Modules

Environment modules provide toolsets that Agents can call:
- Social space simulation
- Economic environment simulation
- Custom environments

### Backend Service

FastAPI backend runs locally (default port 8001), providing:
- REST API endpoints
- Skill management API
- Experiment execution API
- Data replay API

### Storage System

- **SQLite Database**: Stores experiment data, Agent dialogs, state changes
- **Vector Database**: Stores long-term memory (via mem0 + ChromaDB)
- **Replay System**: Complete experiment recording for post-analysis

---

## Configuration

### Required Configuration

Open [Configuration Page](command:aiSocialScientist.openConfigPage) and fill in:

| Config Item | Description | Example |
|-------------|-------------|---------|
| API Key | LLM service key | `sk-xxx` |
| API Base | API service URL | `https://api.openai.com/v1` |

### Optional Configuration

| Config Item | Description | Default |
|-------------|-------------|---------|
| Model | Default model name | `gpt-5.4` |
| Coder Model | Code generation model | Same as default |
| Nano Model | High-frequency operation model | `gpt-5.4-nano` |
| Embedding Model | Vector embedding model | `text-embedding-3-large` |

### Skill Marketplace Source Configuration

Configure in VSCode settings:

- `agentSkills.skillSources`: Agent skill marketplace source list
- `agentSkills.claudeSkillSources`: Claude skill marketplace source list
- `agentSkills.githubToken`: GitHub Token (avoid API rate limits)

### Environment Variables

Or configure via environment variables (see `.env.example`):

```bash
AGENTSOCIETY_LLM_API_KEY=your-api-key
AGENTSOCIETY_LLM_API_BASE=https://api.openai.com/v1
AGENTSOCIETY_LLM_MODEL=gpt-5.4
AGENTSOCIETY_HOME_DIR=./agentsociety_data
```

---

## FAQ

### Backend Fails to Start / Status Shows Error

1. Click [View Backend Logs](command:aiSocialScientist.showBackendLogs) to see error details
2. Return to [Configuration Page](command:aiSocialScientist.openConfigPage) to check API settings
3. If port conflict: restart backend will auto-switch port

### API Validation Failed

Common causes:
- API Key expired or insufficient permissions
- API Base URL incomplete (missing `/v1` path)
- Network cannot access the service
- Model name doesn't match server-side

### Skill Marketplace Empty / Skills Not Showing After Install

1. Click "Refresh" in [Skill Management](command:aiSocialScientist.openSkillMarketplace)
2. Check if marketplace source is configured (see Configuration section)
3. Use "Scan Workspace Agent Skills" to rediscover existing skills

### Difference Between "Close/Archive/Delete" for Skills?

- **Close (Claude Skills)**: Doesn't delete files, just prevents Claude from loading that directory, can re-enable
- **Archive (Agent Skills)**: Moves from active directory, files remain on disk
- **Permanent Delete**: Deletes from disk, usually unrecoverable

---

## Resources

### Official Documentation

- [Project Repository](https://github.com/tsinghua-fib-lab/agentsociety)
- [Issue Tracker](https://github.com/tsinghua-fib-lab/agentsociety/issues)
- [Claude Code Docs](https://code.claude.com/docs/en/overview)

### LLM Provider Platforms

| Provider | Platform URL | API Base URL | Notes |
|----------|--------------|--------------|-------|
| OpenAI | [platform.openai.com](https://platform.openai.com/api-keys) | `https://api.openai.com/v1` | GPT series |
| Anthropic | [console.anthropic.com](https://console.anthropic.com/) | `https://api.anthropic.com` | Claude series |
| Kimi (Moonshot) | [platform.moonshot.cn](https://platform.moonshot.cn/console/api-keys) | `https://api.moonshot.cn/v1` | OpenAI-compatible |
| Zhipu GLM | [bigmodel.cn](https://bigmodel.cn/usercenter/proj-mgmt/apikeys) | `https://open.bigmodel.cn/api/paas/v4` | [GLM Coding Plan](https://www.bigmodel.cn/glm-coding) |
| DeepSeek | [platform.deepseek.com](https://platform.deepseek.com/api_keys) | `https://api.deepseek.com` | High value reasoning model |
| MiniMax | [platform.minimaxi.com](https://platform.minimaxi.com/user-center/basic-information/interface-key) | `https://api.minimax.chat/v1` | Multimodal models |
| Qwen (Alibaba) | [bailian.console.aliyun.com](https://bailian.console.aliyun.com/) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | Alibaba Cloud Bailian |

**Tips:**
- New users typically get free credits on each platform
- Most Chinese models are OpenAI SDK compatible - just change `base_url` and `api_key`
- Some providers offer Coding Plan subscriptions for long-term developer use

### Development Resources

- Development Guide: `extension/DEVELOPMENT.md`
- Project Architecture: `CLAUDE.md` / `AGENTS.md`

### Quick Links

- [Open Configuration Page](command:aiSocialScientist.openConfigPage)
- [Open Skill Management](command:aiSocialScientist.openSkillMarketplace)
- [Open Backend Menu](command:aiSocialScientist.backendStatusMenu)
- [Open Prefill Parameters](command:agentsociety.viewPrefillParams)
