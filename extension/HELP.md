# AI Social Scientist 使用指南

面向用户的“最短路径”：**先把配置填好 → 启动后端 → 装/管理技能 → 开始使用**。

## 一键入口（推荐先点这里）

- **配置页面**：[打开配置页面](command:aiSocialScientist.openConfigPage)
- **技能管理/市场**：[打开技能管理](command:aiSocialScientist.openSkillMarketplace)
- **后端状态菜单**：[打开后端菜单](command:aiSocialScientist.backendStatusMenu)
- **预填充参数**：[打开预填充参数](command:agentsociety.viewPrefillParams)

## 3 分钟上手

### 1) 先完成配置（必做）

打开 [配置页面](command:aiSocialScientist.openConfigPage)，按页面提示填写 **Default LLM** 的 3 项：

- **API Key（必填）**：你的模型服务密钥
- **API Base（必填）**：例如 `https://api.openai.com/v1`
- **Model（可选）**：不填会使用默认值（如 `gpt-5.4`）

填完后，建议点击一次“验证”，确认 API 可用。

### 2) 启动后端（必做）

配置完成后，通过 [后端状态菜单](command:aiSocialScientist.backendStatusMenu) 启动后端。

你会在状态栏看到类似提示：

- `✓ Backend:xxxx`：已运行（端口可能不是 8001，属正常）
- `○ Backend: Stopped`：未运行
- `✕ Backend: Error`：启动失败（先点“查看日志”，再回到配置页检查）

### 3) 打开技能管理（常用）

在 [技能管理](command:aiSocialScientist.openSkillMarketplace) 里你会看到三块内容：

- **Agent 运行时技能**：模拟运行时使用（安装在 `custom/skills/`）
- **Claude 目录技能**：写入 `.claude/skills/`，用于 IDE/Claude 工作流
- **市场**：从你配置的仓库源拉取可安装技能

## 技能管理：最常用的几个动作

### 安装来源（市场源）怎么配？

技能市场条目来自 VSCode 设置里的两个列表（互不影响）：

- `agentSkills.skillSources`：Agent 技能市场源（安装到 `custom/skills/`）
- `agentSkills.claudeSkillSources`：Claude 技能市场源（安装到 `.claude/skills/`）

若遇到 GitHub API 限流，可在设置里填写 `agentSkills.githubToken`。

### “关闭/归档/删除”分别是什么意思？

- **关闭（Claude 技能）**：不删除文件，只是让 Claude 不加载该目录（可再启用）
- **归档（Agent 技能）**：从常用目录移走并停止使用（文件仍保留在磁盘）
- **永久删除**：从磁盘删除，通常不可恢复（谨慎使用）

## 预填充参数：什么时候需要？

当你需要为某些 Agent/环境模块设置默认参数时，打开 [预填充参数](command:agentsociety.viewPrefillParams)。

- 这里是 **只读预览 + 快速打开配置文件** 的组合
- 如果页面提示后端未连接，先去 [后端状态菜单](command:aiSocialScientist.backendStatusMenu) 启动后端

## 常见问题（先看这几条）

### 后端启动失败/状态是 Error

1. 先点 [查看后端日志](command:aiSocialScientist.showBackendLogs)
2. 再回到 [配置页面](command:aiSocialScientist.openConfigPage) 检查：API Key/Base/Model 是否正确
3. 若提示端口占用：重启后端即可自动换端口

### API 验证失败

常见原因：

- Key 过期/权限不足
- Base URL 不完整（缺 `/v1` 等路径）
- 网络无法访问对应域名
- Model 名称与服务端不匹配

### 技能市场为空 / 装完不显示

1. 打开 [技能管理](command:aiSocialScientist.openSkillMarketplace) 点“刷新”
2. 检查是否已配置市场源（见上文“安装来源怎么配？”）
3. 若技能在磁盘上已存在：可用“扫描工作区 Agent 技能”重新发现

## 更多资源

- [项目仓库](https://github.com/tsinghua-fib-lab/agentsociety)
- [问题反馈](https://github.com/tsinghua-fib-lab/agentsociety/issues)
- 开发指南：`extension/DEVELOPMENT.md`
