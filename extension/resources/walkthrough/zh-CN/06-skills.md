## 用技能扩展研究能力

AgentSociety² 将可复用的方法、工具与行为过程封装为技能。AI Social Scientist 会按任务逐步加载研究技能，硅基参与者则在仿真中激活行为技能；这样不必把全部规则塞进一个超长 Prompt，也更容易审计每一步使用了什么能力。

在侧边栏项目树中点 **技能** 条目，或从命令面板打开技能管理。页内分为四个标签页（运行时 / Claude / 市场 / MCP）；详细说明见各标题旁的 **?** 图标与页内帮助。市场源与 Token 在页头 **设置** 统一配置。

### 作为硅基参与者的 PersonAgent

`PersonAgent` 是内置的、由人物画像驱动的硅基参与者（Silicon Participant）。它采用论文中的 workspace-backed Social Generative Agent 架构：Profile、State、Memory、Logs 与 Checkpoints 都以可检查的形式保存；ReAct 循环连接观察、意图、行动与反思；工具和技能则根据当前环境与实验需要按需加载。

![PersonAgent 使用的 workspace-backed Social Generative Agent 架构](../images/person-agent-architecture.png)

*图：来自 [AgentSociety 2 论文](https://arxiv.org/abs/2607.11895) 的 Social Generative Agent 架构；`PersonAgent` 是运行在这套架构上的内置 profile-based 实现。*

### Agent 运行时

**运行时**标签页管理仿真 Agent 使用的工作区技能（位于 `custom/skills/`，通常需后端注册）：

![Agent 运行时技能](../images/agent-skills.png)

*运行时目录：查看内置、环境和工作区技能。*

PersonAgent 内置行为技能目前主要为 `daily-guidance`；工作区还可安装自定义技能，环境模块也可提供 `env` 技能。它们改变的是**仿真参与者如何行动**。

### Claude 目录

**Claude**标签页管理 Claude Code / Codex 使用的技能模板（同步到 `.claude/skills/`）：

![Claude 目录技能](../images/claude-skills.png)

先把扩展模板同步到工作区，再核对客户端是否加载；已安装 Claude 技能可在其支持的范围内启用/关闭或重新同步，也可导入外部技能。文献检索、假设管理、实验配置、运行和分析等研究流程主要由这一层驱动。

### 对照

| 类型 | 位置 | 用途 |
|------|------|------|
| **Agent 运行时** | `custom/skills/` | 硅基参与者的行为能力 |
| **Claude / Codex 目录** | `.claude/skills/` | AI Social Scientist 的研究与工程能力 |

### 技能市场

**市场**标签页可浏览远程仓库中的技能，并安装到运行时（`custom/skills/`）或 Claude 目录（`.claude/skills/`）。

### MCP

文献 MCP 在 **配置页 → 文献 MCP** 填写；在 **技能管理 → MCP** 同步到 Claude / Codex。MCP 提供外部工具与数据入口；技能则规定何时调用、如何核对结果以及产出什么产物。

**MCP**标签页还负责自定义服务与 MCP 市场：

- **推荐一键添加** — 一键添加 AgentSociety 后端、Context7 等预设
- **浏览外部源** — 从 MCP 官方市场、GitHub MCP 市场或自定义 Registry v0.1 地址搜索并安装；写入前可核对生成的配置并选择启用的客户端
- **自定义 MCP** — 本地 stdio 子进程或远程 HTTP 服务
- **导入配置** — 从当前 Claude Code / Codex 配置、JSON / TOML 文件或粘贴内容导入
- **授权** — 需要 OAuth 的 HTTP 服务可按客户端（Claude Code / Codex）发起登录授权

[打开技能管理](command:aiSocialScientist.openSkillMarketplace)
