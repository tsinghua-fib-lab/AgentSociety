# AI Social Scientist 使用指南

面向用户的"最短路径"：**先把配置填好 → 启动后端 → 装/管理技能 → 开始使用**。

---

## 目录

- [基础知识入门](#基础知识入门)
- [系统概述](#系统概述)
- [系统原理](#系统原理)
- [主要组件](#主要组件)
- [配置说明](#配置说明)
- [常见问题](#常见问题)
- [参考资源](#参考资源)

---

## 基础知识入门

如果你是第一次接触 AI Agent 或 LLM 相关领域，这一节会帮你快速理解核心概念。

### 什么是 LLM（大语言模型）？

LLM（Large Language Model，大语言模型）是一种经过海量文本训练的 AI 系统。

**它能做什么？**
- 理解自然语言提出的问题或任务
- 生成连贯、有逻辑的文本回答
- 执行复杂的推理、翻译、总结等任务

**常见的 LLM 服务：**
- OpenAI：GPT-5.5、GPT-5.4、GPT-5.5 Thinking 等
- Anthropic：Claude Opus 4.7、Claude Sonnet 等
- Google：Gemini 3.1 Pro、Gemini 3.1 Flash 等
- 国产模型：通义千问 Qwen3.6、DeepSeek-V4、智谱 GLM-5、文心 Ernie-5.0、Kimi K2.6 等

### 什么是 Token（词元）？

Token 是 LLM 处理文本的最小单位。可以简单理解为"片段"——一个英文单词可能被拆成 1-2 个 token，一个中文字通常是 1-2 个 token。

**为什么关注 Token？**
- LLM 按 token 计费，token 越多费用越高
- 每个 LLM 有上下文长度限制（比如 128K、400K 甚至更高），超出就无法处理
- 对话越长，消耗的 token 越多

**实用建议：**
- 重要的内容放前面，避免被截断
- 长对话定期总结精简，节省 token

### 什么是 Agent（智能体）？

Agent 是"有行动能力的 AI"。普通 LLM 只能回答问题，而 Agent 可以：

- **自主规划**：把复杂任务拆解成多个步骤
- **调用工具**：搜索文献、运行代码、读写文件等
- **保持记忆**：记住上下文，跨对话保持连贯
- **反思调整**：根据执行结果修正策略

在这个工具里，Agent 就是帮你做研究的"智能助手"。

### 什么是 MCP（模型上下文协议）？

MCP（Model Context Protocol）是由 Anthropic 主导开发的开放标准，让 AI 模型能够安全地访问外部数据和工具。

**简单理解：** MCP 就像是 AI 和外部世界之间的"翻译官"和"安全网"。

**它能做什么：**
- 连接数据库、文件系统、API 服务
- 让 AI 读取本地文件、查询数据库
- 以标准化的方式提供工具给 AI 调用

**安全机制：** 用户可以控制哪些资源可以被访问，避免 AI 做出危险操作。

### 什么是 Claude Code？

Claude Code 是 Anthropic 开发的**代理式编码工具（Agentic Coding Tool）**，运行在终端中，能够理解整个代码库并执行复杂开发任务。

**核心能力：**
- 理解整个项目代码库，跨文件进行编辑和重构
- 执行 Shell 命令、处理 Git 工作流
- 支持 MCP 协议，连接外部工具和数据源
- 自动执行"收集上下文 → 采取行动 → 验证结果"的循环

**与本项目的关系：**
- 本插件的 Claude 技能安装在 `.claude/skills/` 目录，供 Claude Code 使用
- 通过 MCP 协议，Claude Code 可以调用本项目的后端服务

**了解更多：** [Claude Code 官方文档](https://code.claude.com/docs/zh-CN/overview)

#### 如何给 Claude Code 换源（配置自定义 API）

如果你需要使用第三方模型或国产模型，可以通过以下方式配置：

**方法一：环境变量（临时生效）**

```bash
export ANTHROPIC_BASE_URL="https://your-api-endpoint.com"
export ANTHROPIC_AUTH_TOKEN="your-api-key"
claude
```

**方法二：配置文件（永久生效）**

在 `~/.claude/settings.json` 中添加：

```json
{
  "env": {
    "ANTHROPIC_BASE_URL": "https://your-api-endpoint.com",
    "ANTHROPIC_AUTH_TOKEN": "your-api-key"
  }
}
```

**常用国产模型配置示例：**

| 服务商 | ANTHROPIC_BASE_URL | 说明 |
|-------|-------------------|------|
| Kimi | `https://api.moonshot.cn/v1` | 月之暗面 |
| DeepSeek | `https://api.deepseek.com` | 深度求索 |
| 智谱 GLM | `https://open.bigmodel.cn/api/paas/v4` | 智谱 AI |
| 通义千问 | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 阿里云 |

**切换模型：**
- 会话内输入 `/model` 后选择模型
- 启动时指定：`claude --model <model-name>`
- 配置文件固定：在 `~/.claude/settings.json` 添加 `"model": "your-model-name"`

**验证配置：** 运行 `/status` 命令查看当前连接状态

---

## 系统概述

### 这个工具是什么？

AI Social Scientist 是一个**AI 驱动的研究助手工具**，帮助用户利用大语言模型完成社会科学研究工作。

**核心定位：**
- 面向社会科学研究者的智能工作流平台
- 支持文献综述、假设生成、实验设计、数据分析、论文写作等研究环节
- 提供 VSCode 扩展和 CLI 两种使用方式

### 典型使用场景

| 场景 | 说明 |
|------|------|
| 文献综述 | 自动检索论文、提取关键信息、生成综述 |
| 假设生成 | 基于已有文献提出可验证的研究假设 |
| 实验设计 | 生成实验配置、设计研究流程 |
| 数据分析 | 运行分析脚本、生成可视化报告 |
| 论文写作 | 辅助撰写论文各章节、格式化输出 |

### 与直接使用 LLM 聊天的区别

| 方面 | 直接用 LLM 聊天 | 用本工具 |
|------|----------------|---------|
| 上下文 | 单次对话，有长度限制 | 长期记忆，跨会话保持 |
| 工具调用 | 手动复制粘贴 | 自动读写文件、调用 API |
| 工作流 | 需自己组织 | 内置研究工作流模板 |
| 可复现性 | 难以追溯 | 完整记录，可回放 |

---

## 系统原理

### 整体架构

```
用户界面层
├── VSCode 扩展（本插件）
├── CLI 命令行工具
└── Web 前端（可选）

后端服务层
├── FastAPI 后端（localhost:8001）
├── AgentSociety 核心引擎
└── 技能管理服务

核心组件层
├── PersonAgent（智能体）
├── Environment Router（环境路由）
├── Research Skills（研究技能）
└── ReplayWriter（存储回放）

外部服务层
├── LLM API（OpenAI/Claude/国产模型）
├── 向量数据库（ChromaDB）
└── 记忆服务（mem0）
```

### 工作流程

1. **配置阶段**：用户填写 LLM API 配置
2. **启动阶段**：后端服务启动，加载技能和环境模块
3. **执行阶段**：Agent 接收任务，调用技能，与环境交互
4. **存储阶段**：所有操作记录到 SQLite，支持回放

### Agent 工作原理

PersonAgent 是本项目的核心智能体，采用**技能流水线（Skill Pipeline）**架构：

1. **技能选择**：LLM 根据任务选择合适的技能
2. **按需加载**：只加载被选中的技能，节省资源
3. **优先级执行**：按技能优先级顺序执行
4. **状态管理**：技能可以存储中间状态

---

## 主要组件

### 技能（Skills）

技能是 Agent 的"能力模块"，决定了 Agent 能做什么。

**内置研究技能：**

| 技能名称 | 功能 | 说明 |
|---------|------|------|
| literature | 文献检索与管理 | 搜索学术论文、提取关键信息 |
| hypothesis | 假设生成 | 从文献中提炼研究假设 |
| experiment | 实验设计 | 生成实验配置文件 |
| analysis | 数据分析 | 运行分析脚本、生成报告 |
| paper | 论文写作 | 辅助撰写论文各章节 |

**技能分类：**
- **Agent 运行时技能**：安装在 `custom/skills/`，Agent 在模拟运行时使用
- **Claude/Cursor 技能**：安装在 `.claude/skills/`，在 IDE 环境中辅助开发

### 环境模块（Environment Modules）

环境模块提供 Agent 可调用的工具集，如：
- 社交空间模拟
- 经济环境模拟
- 自定义环境

### 后端服务（Backend）

FastAPI 后端运行在本地（默认端口 8001），提供：
- REST API 接口
- 技能管理 API
- 实验运行 API
- 数据回放 API

### 存储系统（Storage）

- **SQLite 数据库**：存储实验数据、Agent 对话、状态变更
- **向量数据库**：存储长期记忆（通过 mem0 + ChromaDB）
- **回放系统**：完整记录实验过程，支持事后分析

---

## 配置说明

### 必填配置

打开 [配置页面](command:aiSocialScientist.openConfigPage)，填写以下必填项：

| 配置项 | 说明 | 示例 |
|-------|------|------|
| API Key | LLM 服务密钥 | `sk-xxx` |
| API Base | API 服务地址 | `https://api.openai.com/v1` |

### 可选配置

| 配置项 | 说明 | 默认值 |
|-------|------|-------|
| Model | 默认模型名称 | `gpt-5.4` |
| Coder Model | 代码生成模型 | 与默认相同 |
| Nano Model | 高频操作模型 | `gpt-5.4-nano` |
| Embedding Model | 向量嵌入模型 | `text-embedding-3-large` |

### 技能市场源配置

在 VSCode 设置中配置：

- `agentSkills.skillSources`：Agent 技能市场源列表
- `agentSkills.claudeSkillSources`：Claude 技能市场源列表
- `agentSkills.githubToken`：GitHub Token（避免 API 限流）

### 环境变量

也可通过环境变量配置（参见 `.env.example`）：

```bash
AGENTSOCIETY_LLM_API_KEY=your-api-key
AGENTSOCIETY_LLM_API_BASE=https://api.openai.com/v1
AGENTSOCIETY_LLM_MODEL=gpt-5.4
AGENTSOCIETY_HOME_DIR=./agentsociety_data
```

---

## 常见问题

### 后端启动失败/状态是 Error

1. 点击 [查看后端日志](command:aiSocialScientist.showBackendLogs) 查看错误信息
2. 回到 [配置页面](command:aiSocialScientist.openConfigPage) 检查 API 配置
3. 若提示端口占用：重启后端会自动换端口

### API 验证失败

常见原因：
- API Key 过期或权限不足
- API Base URL 不完整（缺少 `/v1` 路径）
- 网络无法访问对应服务
- Model 名称与服务端不匹配

### 技能市场为空/装完不显示

1. 在 [技能管理](command:aiSocialScientist.openSkillMarketplace) 点击"刷新"
2. 检查是否已配置市场源（见配置说明）
3. 使用"扫描工作区 Agent 技能"重新发现已有技能

### 技能"关闭/归档/删除"有什么区别？

- **关闭（Claude 技能）**：不删除文件，只是让 Claude 不加载该目录，可再启用
- **归档（Agent 技能）**：从常用目录移走，文件仍保留在磁盘
- **永久删除**：从磁盘删除，通常不可恢复

---

## 参考资源

### 官方文档

- [项目仓库](https://github.com/tsinghua-fib-lab/agentsociety)
- [问题反馈](https://github.com/tsinghua-fib-lab/agentsociety/issues)
- [Claude Code 文档](https://code.claude.com/docs/zh-CN/overview)

### LLM 服务商平台

以下是国内主流 LLM 服务商的开发者平台，可获取 API Key 和查看 Coding Plan：

| 服务商 | 平台地址 | API Base URL | 说明 |
|-------|---------|--------------|------|
| OpenAI | [platform.openai.com](https://platform.openai.com/api-keys) | `https://api.openai.com/v1` | GPT 系列模型 |
| Anthropic | [console.anthropic.com](https://console.anthropic.com/) | `https://api.anthropic.com` | Claude 系列模型 |
| Kimi（月之暗面） | [platform.moonshot.cn](https://platform.moonshot.cn/console/api-keys) | `https://api.moonshot.cn/v1` | 兼容 OpenAI 格式 |
| 智谱 GLM | [bigmodel.cn](https://bigmodel.cn/usercenter/proj-mgmt/apikeys) | `https://open.bigmodel.cn/api/paas/v4` | [GLM Coding Plan](https://www.bigmodel.cn/glm-coding) |
| DeepSeek | [platform.deepseek.com](https://platform.deepseek.com/api_keys) | `https://api.deepseek.com` | 高性价比推理模型 |
| MiniMax | [platform.minimaxi.com](https://platform.minimaxi.com/user-center/basic-information/interface-key) | `https://api.minimax.chat/v1` | 多模态模型 |
| 通义千问 | [bailian.console.aliyun.com](https://bailian.console.aliyun.com/) | `https://dashscope.aliyuncs.com/compatible-mode/v1` | 阿里云百炼平台 |

**提示：** 
- 新用户通常有免费额度，可在各平台控制台查看
- 国产模型大多兼容 OpenAI SDK 格式，只需修改 `base_url` 和 `api_key`
- 部分服务商提供 Coding Plan 订阅，适合开发者长期使用

### 开发资源

- 开发指南：`extension/DEVELOPMENT.md`
- 项目架构：`CLAUDE.md` / `AGENTS.md`

### 快捷入口

- [打开配置页面](command:aiSocialScientist.openConfigPage)
- [打开技能管理](command:aiSocialScientist.openSkillMarketplace)
- [打开后端菜单](command:aiSocialScientist.backendStatusMenu)
- [打开预填充参数](command:agentsociety.viewPrefillParams)
