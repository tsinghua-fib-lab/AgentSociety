# AI Social Scientist Extension - Development Guide

## 目录

- [开发环境设置](#开发环境设置)
- [项目结构](#项目结构)
- [核心模块](#核心模块)
- [后端开发](#后端开发)
- [React Webview 开发](#react-webview-开发)
- [帮助页面维护](#帮助页面维护)
- [打包发布](#打包发布)
- [代码规范](#代码规范)

## 开发环境设置

### 前置要求

- Node.js >= 16.x
- Python >= 3.11
- uv (Python 包管理器)
- VSCode >= 1.80.0

### 安装依赖

```bash
cd extension
npm install
```

### 编译项目

```bash
npm run build        # 生产构建（打包扩展和 webview）
npm run compile      # 开发构建
npm run watch        # 监听模式
```

### 调试

1. 在 VSCode 中打开 `extension` 文件夹
2. 按 `F5` 启动调试会话
3. 新的 Extension Development Host 窗口将打开

## 项目结构

```
extension/
├── src/                              # 源代码目录
│   ├── extension.ts                  # 主入口文件
│   ├── projectStructureProvider.ts   # 项目结构树视图提供者
│   ├── apiClient.ts                  # API 客户端
│   ├── configPageViewProvider.ts     # 配置页面 Webview
│   ├── helpPageViewProvider.ts       # 帮助页面 Webview
│   ├── prefillParamsViewProvider.ts  # 预填充参数查看器
│   ├── replayWebviewProvider.ts      # 回放可视化 Webview
│   ├── simSettingsEditorProvider.ts  # SIM_SETTINGS 自定义编辑器
│   ├── initConfigEditorProvider.ts   # init_config 自定义编辑器
│   ├── skillMarketplaceProvider.ts   # 技能市场面板
│   ├── envManager.ts                 # 环境变量(.env)管理
│   ├── i18n.ts                       # 国际化字符串
│   ├── jsonViewer.ts                 # JSON 可视化查看器
│   ├── yamlViewer.ts                 # YAML 可视化查看器
│   ├── stepsViewer.ts                # 步骤时间线查看器
│   ├── pidStatusViewer.ts            # 实验状态监控查看器
│   ├── literatureIndexViewer.ts      # 文献索引查看器
│   ├── experimentResultsViewer.ts    # 实验结果查看器
│   ├── dragAndDropController.ts      # 拖放控制器
│   ├── runtimeConfig.ts              # 运行时配置读取
│   ├── atReference.ts                # @引用格式工具
│   ├── aiChatInvoker.ts              # AI Chat 调用器
│   ├── portUtils.ts                  # 动态端口分配
│   ├── workspaceManager.ts           # 工作区管理
│   ├── services/                     # 服务模块
│   │   ├── backendManager.ts         # 后端进程管理
│   │   ├── backendService.ts         # 后端服务接口
│   │   ├── llmValidator.ts           # LLM 配置验证
│   │   └── workspaceExportManager.ts # 工作区导出
│   ├── webview/                      # React Webview 组件
│   │   ├── components/               # 共享组件
│   │   ├── configPage/               # 配置页面
│   │   ├── helpPage/                 # 帮助页面
│   │   ├── initConfig/               # 初始化配置
│   │   ├── prefillParams/            # 预填充参数界面
│   │   ├── replay/                   # 实验回放界面
│   │   ├── simSettings/              # SIM 设置界面
│   │   ├── skillMarketplace/         # 技能市场
│   │   ├── i18n/                     # 国际化资源
│   │   └── theme.ts                  # VSCode 主题适配
│   ├── platforms/                    # 多平台适配器
│   │   ├── PlatformAdapter.ts        # 平台适配器基类
│   │   ├── GitHubAdapter.ts          # GitHub API 适配器
│   │   ├── GitLabAdapter.ts          # GitLab API 适配器
│   │   └── GiteeAdapter.ts           # Gitee API 适配器
│   ├── skillMarketplace/             # 技能市场工具
│   │   ├── security.ts               # 安全验证
│   │   └── utils.ts                  # 工具函数
│   └── shared/                       # 共享模块
│       ├── messages.ts               # 消息类型定义
│       └── protocol.ts               # 通信协议
├── skills/                           # Claude Code Skills
│   ├── agentsociety-analysis/        # 数据分析
│   ├── agentsociety-create-agent/    # 创建 Agent
│   ├── agentsociety-create-env-module/ # 创建环境模块
│   ├── agentsociety-create-dataset/  # 创建数据集
│   ├── agentsociety-use-dataset/     # 使用数据集
│   ├── agentsociety-experiment-config/ # 实验配置
│   ├── agentsociety-hypothesis/      # 假设管理
│   ├── agentsociety-literature-search/ # 文献检索
│   ├── agentsociety-run-experiment/  # 运行实验
│   ├── agentsociety-scan-modules/    # 扫描模块
│   ├── agentsociety-synthesize/      # 结果综合
│   ├── agentsociety-web-research/    # 网络研究
│   ├── agentsociety-generate-paper/  # 论文生成
│   ├── docx/                         # Word 文档处理
│   ├── pdf/                          # PDF 文档处理
│   ├── pptx/                         # PPT 文档处理
│   └── xlsx/                         # Excel 文档处理
├── HELP.md                           # 帮助文档（Markdown 格式）
├── README.md                         # 项目说明
├── package.json                      # 插件配置
├── tsconfig.json                     # TypeScript 配置
├── webpack.config.js                 # Webpack 构建配置
└── out/                              # 编译输出（自动生成）
```

## 核心模块

### 1. 项目结构视图 (ProjectStructureProvider)

**文件**: `src/projectStructureProvider.ts`

提供左侧树视图，展示工作区文件结构：

- **研究话题 (Topic)** - TOPIC.md 文件
- **假设 (Hypotheses)** - hypothesis_xxx/ 目录
- **实验 (Experiments)** - experiment_xxx/ 目录
- **论文 (Papers)** - papers/ 目录

支持特性：
- 拖放操作（文件拖入 papers/ 目录）
- 上下文菜单操作
- 自动刷新
- 实验状态概览显示
- 自定义模块扫描和测试

### 2. 配置页面 (ConfigPageViewProvider)

**文件**: `src/configPageViewProvider.ts`, `src/webview/configPage/`

提供可视化配置界面，配置保存在工作区的 `.env` 文件中：

- **LLM API 配置**
  - Default LLM（必填）
  - Coder LLM（代码生成，可选）
  - Nano LLM（高频操作，可选）
  - Analysis LLM（数据分析，可选）
  - Embedding 模型（可选）

- **Python 环境配置**
- **文献检索配置**
- **EasyPaper 配置**
- **配置验证功能**

### 3. 帮助页面 (HelpPageViewProvider)

**文件**: `src/helpPageViewProvider.ts`, `src/webview/helpPage/`, `HELP.md`

从 `HELP.md` 读取 Markdown 内容并渲染：

- 支持命令链接跳转 (`[文字](command:命令ID)`)
- 支持外部 URL 打开
- 自定义 Markdown 样式适配 VSCode 主题

实现要点：

- Webview 通过 `window.HELP_CONTENT` 注入 `HELP.md` 文本，再由 React 渲染
- 由于 CSP 默认禁用内联脚本，注入脚本需使用 `nonce`（见 `helpPageViewProvider.ts`）

### 4. 后端管理器 (BackendManager)

**文件**: `src/services/backendManager.ts`

管理 FastAPI 后端进程的生命周期：

- 启动/停止/重启后端服务
- 动态端口分配
- 健康检查（每 10 秒）
- 进程 PID 管理
- 状态栏显示服务状态和端口
- 日志输出到专用 OutputChannel

#### 端口与状态检测逻辑

- **端口来源**：工作区 `.env` 的 `BACKEND_PORT`
- **插件启动后端**：若 `BACKEND_PORT` 可用就使用；若被占用则自动分配可用端口，并写回 `.env`
- **手动启动后端**：插件不会扫描端口；只会按 `.env` 的 `BACKEND_PORT` 进行 `/health` 检测与连接

#### 后端状态查询命令

- `aiSocialScientist.showBackendStatus`：弹出信息提示（用于交互提示）
- `aiSocialScientist.getBackendStatus`：返回结构化状态对象（用于 Webview/配置页等需要“数据源一致”的场景）

### 5. 技能市场 (SkillMarketplaceProvider)

**文件**: `src/skillMarketplaceProvider.ts`, `src/webview/skillMarketplace/`

管理 Agent 技能和 Claude 技能：

- **Agent 运行时** - 安装到 `custom/skills`
- **Claude 目录** - 安装到 `.claude/skills`
- 支持从 GitHub/GitLab/Gitee 仓库安装
- 技能启用/禁用/更新/归档
- 内置模板同步到工作区

### 6. 可视化查看器

| 查看器 | 文件 | 功能 |
|--------|------|------|
| JSON Viewer | `jsonViewer.ts` | 语法高亮、折叠展开、搜索、复制 |
| YAML Viewer | `yamlViewer.ts` | 语法高亮、复制内容、转换为 JSON |
| Steps Viewer | `stepsViewer.ts` | 时间线视图、编辑保存 |
| PID Status Viewer | `pidStatusViewer.ts` | 实验状态监控、自动刷新 |
| Literature Index Viewer | `literatureIndexViewer.ts` | 文献列表、搜索、批量操作 |
| Experiment Results Viewer | `experimentResultsViewer.ts` | 实验结果可视化 |

### 7. API 客户端 (ApiClient)

**文件**: `src/apiClient.ts`

处理与 FastAPI 后端的 HTTP 通信：

- 支持 SSE 流式响应
- 自动重连机制
- 错误处理
- 连接状态管理

## 后端开发

### 后端项目位置

后端代码位于 `packages/agentsociety2/agentsociety2/backend/`：

```
backend/
├── app.py              # FastAPI 应用主入口
├── run.py              # 启动脚本
├── routers/            # API 路由
│   ├── agent_skills.py # Agent Skills 管理
│   ├── custom.py       # 自定义模块管理
│   ├── experiments.py  # 实验数据接口
│   ├── modules.py      # 模块信息接口
│   ├── prefill_params.py # 预填充参数
│   └── replay.py       # 回放数据接口
└── services/           # 服务层
```

### 启动后端服务

```bash
cd packages/agentsociety2
uv run python -m agentsociety2.backend.run
```

服务启动后：
- 默认地址：`http://localhost:8001`
- API 文档：`http://localhost:8001/docs`
- ReDoc：`http://localhost:8001/redoc`

### 主要 API 端点

#### 基础接口
| 端点 | 方法 | 说明 |
|------|------|------|
| `/health` | GET | 健康检查 |
| `/docs` | GET | Swagger API 文档 |

#### Agent Skills 接口 (`/api/v1/agent-skills`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/list` | GET | 列出所有 Agent Skills |
| `/enable` | POST | 启用 Skill |
| `/disable` | POST | 禁用 Skill |
| `/scan` | POST | 扫描自定义 Skill |
| `/import` | POST | 从路径导入 Skill |
| `/create` | POST | 创建新 Skill |
| `/upload` | POST | 上传 zip 包导入 Skill |
| `/reload` | POST | 热重载 Skill |
| `/remove` | POST | 移除自定义 Skill |
| `/{name}/info` | GET | 获取 Skill 详情 |

#### 模块接口 (`/api/v1/modules`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/agent_classes` | GET | 获取所有 Agent 类 |
| `/env_module_classes` | GET | 获取所有环境模块类 |
| `/all` | GET | 获取所有模块（一次性返回） |

#### 预填充参数接口 (`/api/v1/prefill-params`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 获取全局预填充参数 |
| `/{class_kind}/{class_name}` | GET | 获取特定类的预填充参数 |

#### 实验数据接口 (`/api/v1/experiments`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/{hypothesis_id}/{experiment_id}/info` | GET | 获取实验信息 |
| `/{hypothesis_id}/{experiment_id}/artifacts` | GET | 获取产出文件列表 |
| `/{hypothesis_id}/{experiment_id}/artifacts/{name}` | GET | 获取产出文件内容 |

#### 回放数据接口 (`/api/v1/replay`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/{hypothesis_id}/{experiment_id}/info` | GET | 获取实验基本信息 |
| `/{hypothesis_id}/{experiment_id}/timeline` | GET | 获取时间线数据 |
| `/{hypothesis_id}/{experiment_id}/agents` | GET | 获取所有 Agent 列表 |
| `/{hypothesis_id}/{experiment_id}/agent/{agent_id}` | GET | 获取 Agent 详情 |

#### 自定义模块接口 (`/api/v1/custom`)
| 端点 | 方法 | 说明 |
|------|------|------|
| `/scan` | POST | 扫描自定义模块 |
| `/clean` | POST | 清理自定义模块配置 |
| `/test` | POST | 测试自定义模块 |
| `/list` | GET | 列出已注册的自定义模块 |
| `/status` | GET | 获取自定义模块状态 |

## React Webview 开发

### 技术栈

- React 18
- Ant Design 6
- @ant-design/x-markdown
- TypeScript
- Webpack

### 与扩展通信

**发送消息到扩展：**

```tsx
vscode.postMessage({
  command: 'openCommand',
  commandId: 'aiSocialScientist.openConfigPage'
});
```

**接收扩展的消息：**

```tsx
React.useEffect(() => {
  const handleMessage = (event: MessageEvent) => {
    const message = event.data;
    switch (message.command) {
      case 'initialConfig':
        // 处理消息
        break;
    }
  };
  
  window.addEventListener('message', handleMessage);
  return () => window.removeEventListener('message', handleMessage);
}, []);
```

### 主题适配

使用 `useVscodeTheme` Hook 适配 VSCode 主题：

```tsx
import { useVscodeTheme } from '../theme';

const { isDark, palette, themeConfig } = useVscodeTheme();

// 使用主题颜色
<div style={{
  background: palette.editorBackground,
  color: palette.editorForeground,
  border: `1px solid ${palette.panelBorder}`,
}}>
  {/* 内容 */}
</div>
```

### 可用主题颜色

| 变量 | 说明 |
|------|------|
| `editorBackground` | 编辑器背景色 |
| `editorForeground` | 编辑器前景色 |
| `panelBorder` | 面板边框色 |
| `linkForeground` | 链接颜色 |
| `descriptionForeground` | 描述文字颜色 |
| `successForeground` | 成功状态颜色 |
| `errorForeground` | 错误状态颜色 |

## 帮助页面维护

帮助页面内容存储在 `HELP.md` 文件中，使用 Markdown 格式。

帮助页建议保持“上手路径 + 一键入口 + 排错”这三块为主，避免把过多细节（如回放的完整说明）堆在帮助页里，必要时再拆分到独立文档。

### 特殊链接语法

**命令链接**：点击执行 VSCode 命令

```markdown
[打开配置页面](command:aiSocialScientist.openConfigPage)
```

**外部链接**：点击在浏览器打开

```markdown
[项目文档](https://github.com/tsinghua-fib-lab/agentsociety)
```

### 更新帮助页面

1. 编辑 `HELP.md` 文件
2. 重新编译插件：`npm run compile`
3. 刷新帮助页面即可看到更新

### 添加新入口

在 Markdown 中添加命令链接即可创建快捷入口：

```markdown
| 页面 | 说明 | 快捷入口 |
|------|------|----------|
| 配置页面 | 配置 LLM API | [打开](command:aiSocialScientist.openConfigPage) |
```

## 打包发布

### 安装 vsce

```bash
npm install -g @vscode/vsce
```

### 打包插件

```bash
npm run package
# 或
vsce package
```

生成 `.vsix` 文件，可在 VSCode 中安装。

### 发布到市场

```bash
vsce publish
```

## 代码规范

### Linting

```bash
npm run lint
```

### 注释规范

文件头部注释格式：

```typescript
/**
 * 模块说明
 *
 * 关联文件：
 * - @extension/src/xxx.ts - 说明
 *
 * 后端API：
 * - @packages/agentsociety2/agentsociety2/backend/xxx.py - 说明
 */
```

函数注释格式：

```typescript
/**
 * 函数说明
 * @param param1 参数说明
 * @returns 返回值说明
 */
```

### 命名约定

- 文件名：小写驼峰 (`configPageViewProvider.ts`)
- 类名：大写驼峰 (`ConfigPageViewProvider`)
- 接口名：大写驼峰，可带 `I` 前缀
- 常量：全大写下划线 (`DEFAULT_VALUES`)
- 私有成员：下划线前缀 (`_panel`)

## 参考资料

- [VSCode Extension API](https://code.visualstudio.com/api)
- [VSCode Extension Samples](https://github.com/Microsoft/vscode-extension-samples)
- [React Documentation](https://react.dev/)
- [Ant Design Documentation](https://ant.design/)
- [Ant Design X Documentation](https://x.ant.design/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [AgentSociety2 Documentation](../packages/agentsociety2/README.md)
