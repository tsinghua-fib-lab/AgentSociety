# AI Social Scientist

[![VS Code Version](https://img.shields.io/badge/VS%20Code-1.80%2B-blue)](https://code.visualstudio.com/)
[![License](https://img.shields.io/badge/License-MIT-green)](LICENSE)

AI Social Scientist 是 LLM 驱动的智能自主社会科学研究智能体，提供完整的 VSCode 插件支持。

## 核心能力

- **社会科学文献检索** - 多源学术文献搜索与管理
- **Agent 模拟实验** - 基于 AgentSociety2 的智能体模拟
- **实验配置与执行** - 可视化配置、一键运行
- **数据总结与分析** - LLM 驱动的数据分析与报告生成

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                    VSCode 插件                          │
├─────────────────────────────────────────────────────────┤
│  项目结构视图  │  技能市场  │  配置页面  │  回放视图   │
├─────────────────────────────────────────────────────────┤
│                    FastAPI 后端                         │
├─────────────────────────────────────────────────────────┤
│         AgentSociety2 核心模拟框架                      │
└─────────────────────────────────────────────────────────┘
```

## 快速开始

### 前置要求

- Node.js >= 16.x
- Python >= 3.11
- uv (Python 包管理器)
- VSCode >= 1.80.0

### 安装步骤

1. **安装插件依赖**

   ```bash
   cd extension
   npm install
   ```

2. **编译插件**

   ```bash
   npm run build
   ```

3. **配置后端**

   在 `packages/agentsociety2` 目录下创建 `.env` 文件：

   ```env
   # 必填配置
   AGENTSOCIETY_LLM_API_KEY=your_api_key
   AGENTSOCIETY_LLM_API_BASE=https://api.openai.com/v1
   AGENTSOCIETY_LLM_MODEL=gpt-5.4

   # 后端服务
   BACKEND_HOST=127.0.0.1
   BACKEND_PORT=8001
   ```

4. **启动后端服务**

   ```bash
   cd packages/agentsociety2
   uv run python -m agentsociety2.backend.run
   ```

5. **调试插件**

   - 在 VSCode 中打开 `extension` 文件夹
   - 按 `F5` 启动调试

## 功能特性

### 项目结构管理

```
workspace/
├── TOPIC.md                    # 研究话题
├── papers/                     # 论文目录
│   ├── literature_index.json   # 文献索引
│   ├── pdf/                    # PDF 文献
│   └── md/                     # Markdown 笔记
├── hypothesis_xxx/             # 假设目录
│   ├── HYPOTHESIS.md          # 假设描述
│   └── experiment_xxx/        # 实验目录
│       ├── init/              # 初始化配置
│       └── run/               # 运行结果
```

### 可视化文件查看器

| 文件类型 | 功能 |
|---------|------|
| JSON | 语法高亮、折叠展开、搜索、复制 |
| YAML | 语法高亮、时间线视图 |
| pid.json | 实验状态监控、自动刷新 |
| literature_index.json | 文献列表、搜索、批量操作 |

### 技能管理

- **Agent 技能** - 安装到 `custom/skills`
- **Claude 技能** - 安装到 `.claude/skills`
- 支持从 GitHub 仓库安装
- 支持本地自定义开发

### 后端服务管理

- 状态栏实时显示服务状态和端口
- 一键启动/停止/重启
- 快速打开 API 文档
- 复制服务 URL

## 配置说明

### 插件设置

| 设置项 | 说明 | 默认值 |
|--------|------|--------|
| `aiSocialScientist.backend.autoStart` | 自动启动后端 | `false` |
| `aiSocialScientist.chat.viewColumn` | Chat 面板位置 | `beside` |
| `agentSkills.githubToken` | GitHub Token (可选) | `""` |
| `agentSkills.skillSources` | Agent 技能源 | `[]` |
| `agentSkills.claudeSkillSources` | Claude 技能源 | 内置列表 |

### 环境变量

详见 [HELP.md](HELP.md) 或配置页面。

## 开发指南

### 项目结构

```
extension/
├── src/
│   ├── extension.ts              # 主入口
│   ├── projectStructureProvider.ts # 树视图
│   ├── apiClient.ts              # API 客户端
│   ├── services/                 # 服务层
│   └── webview/                  # React 组件
├── skills/                       # Claude Code Skills
├── HELP.md                       # 帮助文档
└── package.json
```

### 开发命令

```bash
npm run compile      # 编译 TypeScript
npm run watch        # 监听模式
npm run build        # 生产构建
npm run lint         # ESLint 检查
npm run package      # 打包 vsix
```

### 技术栈

- TypeScript
- React 18 + Ant Design 6
- Webpack
- VSCode Extension API

## 故障排除

### 后端连接问题

1. 检查后端服务是否运行
2. 检查 `.env` 配置是否正确
3. 查看输出面板日志

### 编译错误

```bash
rm -rf out node_modules
npm install && npm run compile
```

## 相关链接

- [AgentSociety 项目](https://github.com/tsinghua-fib-lab/agentsociety)
- [问题反馈](https://github.com/tsinghua-fib-lab/agentsociety/issues)
- [开发指南](DEVELOPMENT.md)

## 许可证

[MIT License](LICENSE)
