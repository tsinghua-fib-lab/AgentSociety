# AI Social Scientist 使用指南

AI Social Scientist 是一个基于大语言模型的智能体模拟框架，支持构建复杂的城市模拟和社会实验。

## 快速开始

### 1. 配置 API 密钥

首次使用需要配置 LLM API 密钥。点击状态栏或运行命令 [打开配置页面](command:aiSocialScientist.openConfigPage)，填写必填的 API Key 和 API Base。

> **必填项**：Default LLM 的 API Key 和 API Base

### 2. 启动后端服务

配置完成后，点击状态栏的"启动后端"按钮，或运行 [后端状态菜单](command:aiSocialScientist.backendStatusMenu)。后端服务是运行实验和管理数据的核心。

- 默认端口：`8001`
- API 文档：`http://localhost:8001/docs`

### 3. 管理技能

通过 [技能市场](command:aiSocialScientist.openSkillMarketplace) 查看和安装 Agent 技能或 Claude 技能。技能是插件的核心功能单元。

- **Agent 技能**：用于模拟实验中的智能体行为
- **Claude 技能**：用于扩展 Claude Code 的能力

### 4. 配置实验

在 [环境和智能体页面](command:aiSocialScientist.openEnvAgentPage) 选择要使用的模块，然后配置 [初始化配置](command:aiSocialScientist.openInitConfig) 和 [预填充参数](command:agentsociety.viewPrefillParams)。

### 5. 运行与回放

实验运行后，可以通过 [回放功能](command:aiSocialScientist.openReplay) 查看 Agent 的行为轨迹和对话记录。

---

## 主要功能

### 技能管理

管理 Agent 技能和 Claude 技能。

- 可以从远程仓库安装技能
- 支持本地自定义技能开发
- 技能可以启用/禁用/更新

### 后端服务管理

管理实验后端服务，包括启动、停止、重启、查看日志等操作。

- 状态栏显示当前服务状态
- 支持一键打开 API 文档
- 可以复制服务 URL 到剪贴板

### 实验配置

配置实验的环境模块和 Agent 参数。支持预填充参数配置，简化实验初始化流程。

### 模拟回放

可视化回放实验过程，查看 Agent 的位置移动、对话记录和行为轨迹。

---

## 页面说明

| 页面 | 说明 | 快捷入口 |
|------|------|----------|
| 配置页面 | 配置 LLM API、Python 环境、文献检索等服务 | [打开](command:aiSocialScientist.openConfigPage) |
| 技能市场 | 浏览和管理技能，支持搜索、安装、更新 | [打开](command:aiSocialScientist.openSkillMarketplace) |
| 环境和智能体 | 选择实验中要使用的环境模块和 Agent 类型 | [打开](command:aiSocialScientist.openEnvAgentPage) |
| 初始化配置 | 查看和编辑实验的初始化配置 | [打开](command:aiSocialScientist.openInitConfig) |
| 预填充参数 | 为环境模块和 Agent 配置预填充参数 | [打开](command:agentsociety.viewPrefillParams) |
| 回放页面 | 可视化回放实验过程 | [打开](command:aiSocialScientist.openReplay) |

---

## 使用技巧

### 命令面板快捷访问

按 `Ctrl+Shift+P` (Windows/Linux) 或 `Cmd+Shift+P` (Mac) 打开命令面板，输入 `AI Social` 或 `AgentSociety` 快速找到所有相关命令。

### 状态栏快速操作

点击状态栏的 AI Social Scientist 图标，可以快速访问后端服务菜单，包括启动/停止/重启/查看日志等。

### 自定义 Python 环境

如果需要使用特定的 Python 环境，可以在配置页面设置 Python 路径。留空则使用系统默认 Python。

### 验证配置

在配置页面中，每个服务配置旁边都有验证按钮，可以快速检测配置是否正确。

### 自定义技能开发

在 `workspace/custom/` 目录下可以开发自定义技能，插件会自动扫描并加载。

---

## 常见问题

### 后端启动失败怎么办？

1. 检查 Python 环境是否正确安装
2. 检查端口是否被占用
3. 查看后端日志获取详细错误信息
4. 确保所有依赖包已安装

### API 验证失败怎么办？

1. 检查 API Key 是否正确
2. 检查 API Base URL 是否正确（一些 API 服务需要添加 `/v1` 后缀）
3. 检查网络连接是否正常
4. 确认 API 服务是否支持配置的模型

### 技能安装后不显示？

1. 点击刷新按钮重新扫描
2. 检查技能目录结构是否正确
3. 查看 `SKILL.md` 文件是否包含正确的元数据

---

## 更多资源

- [项目文档](https://github.com/tsinghua-fib-lab/agentsociety)
- [问题反馈](https://github.com/tsinghua-fib-lab/agentsociety/issues)
