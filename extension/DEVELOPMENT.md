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
npm run build        # 生产构建
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
├── src/
│   ├── extension.ts              # 主入口
│   ├── projectStructureProvider.ts # 项目结构树视图
│   ├── apiClient.ts              # API客户端
│   ├── configPageViewProvider.ts # 配置页面
│   ├── helpPageViewProvider.ts   # 帮助页面
│   ├── services/                 # 服务层
│   │   ├── backendManager.ts     # 后端进程管理
│   │   ├── backendService.ts     # 后端服务接口
│   │   ├── llmValidator.ts       # LLM配置验证
│   │   └── workspaceExportManager.ts # 工作区导出
│   ├── webview/                  # React Webview组件
│   │   ├── components/           # 共享组件
│   │   ├── configPage/           # 配置页面
│   │   ├── helpPage/             # 帮助页面
│   │   ├── skillMarketplace/     # 技能市场
│   │   └── ...
│   └── i18n.ts                   # 国际化
├── skills/                       # Claude Code Skills
├── HELP.md                       # 帮助文档（Markdown）
├── package.json
└── tsconfig.json
```

## 核心模块

### 1. 项目结构视图

**文件**: `src/projectStructureProvider.ts`

提供左侧树视图，展示工作区文件结构：
- 研究话题 (Topic)
- 假设 (Hypotheses)
- 实验 (Experiments)
- 论文 (Papers)

支持拖放操作、上下文菜单、自动刷新。

### 2. 配置页面

**文件**: `src/configPageViewProvider.ts`, `src/webview/configPage/`

提供可视化配置界面：
- LLM API 配置
- Python 环境配置
- 文献检索配置
- 配置验证

### 3. 帮助页面

**文件**: `src/helpPageViewProvider.ts`, `src/webview/helpPage/`, `HELP.md`

从 `HELP.md` 读取 Markdown 内容并渲染，支持：
- 命令链接跳转 (`command:xxx`)
- 外部 URL 打开
- 自定义样式

### 4. 后端管理器

**文件**: `src/services/backendManager.ts`

管理 FastAPI 后端进程：
- 启动/停止/重启
- 健康检查
- 日志输出
- 状态栏显示

### 5. API 客户端

**文件**: `src/apiClient.ts`

处理与 FastAPI 后端的 HTTP 通信：
- 支持 SSE 流式响应
- 自动重连
- 错误处理

## 后端开发

### 启动后端服务

```bash
cd packages/agentsociety2
uv run python -m agentsociety2.backend.run
```

### 主要 API 端点

| 端点 | 说明 |
|------|------|
| `GET /health` | 健康检查 |
| `GET /docs` | API 文档 |
| `GET /api/v1/modules/all` | 获取所有模块 |
| `GET /api/v1/prefill-params` | 预填充参数 |
| `POST /api/v1/custom/scan` | 扫描自定义模块 |

## React Webview 开发

### 技术栈

- React 18
- Ant Design 6
- @ant-design/x-markdown
- TypeScript
- Webpack

### 与扩展通信

```tsx
// 发送消息
vscode.postMessage({ command: 'openCommand', commandId: 'xxx' });

// 接收消息
window.addEventListener('message', (event) => {
  const message = event.data;
  // 处理消息
});
```

### 主题适配

```tsx
const { isDark, palette, themeConfig } = useVscodeTheme();
```

## 帮助页面维护

帮助页面内容存储在 `HELP.md` 文件中，使用 Markdown 格式。

### 特殊链接

- **命令链接**: `[文字](command:命令ID)`
- **外部链接**: `[文字](https://...)`

### 更新帮助页面

1. 编辑 `HELP.md` 文件
2. 重新编译插件：`npm run compile`
3. 刷新帮助页面即可看到更新

### 添加新入口

在 Markdown 中添加命令链接：

```markdown
[打开配置页面](command:aiSocialScientist.openConfigPage)
```

## 打包发布

### 安装 vsce

```bash
npm install -g @vscode/vsce
```

### 打包插件

```bash
vsce package
```

生成 `.vsix` 文件，可在 VSCode 中安装。

## 代码规范

### Linting

```bash
npm run lint
```

### 注释规范

使用 JSDoc 风格注释：

```typescript
/**
 * 函数说明
 * @param param1 参数说明
 * @returns 返回值说明
 */
```

### 文件头部注释

```typescript
/**
 * 模块说明
 *
 * 关联文件：
 * - @extension/src/xxx.ts - 说明
 */
```

## 参考资料

- [VSCode Extension API](https://code.visualstudio.com/api)
- [React Documentation](https://react.dev/)
- [Ant Design Documentation](https://ant.design/)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
