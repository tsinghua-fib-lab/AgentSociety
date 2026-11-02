# AgentSociety UI

[![License](https://img.shields.io/badge/License-MIT-green)](../LICENSE)

<p align="center">
  <a href="#agentsociety-ui">English</a> · <a href="#agentsociety-ui-1">中文</a>
</p>

---

## AgentSociety UI

AgentSociety UI is the **React + Vite** web dashboard for the AgentSociety 2 simulation platform. It provides a web-based interface for managing experiments, viewing simulation results, and configuring research workflows.

### Tech Stack

- **React 19** + **TypeScript**
- **Vite** (build tool)
- **Ant Design 6** / **Ant Design Pro Components** (UI framework)
- **Monaco Editor** (code editing)
- **Plotly.js** (data visualization)
- **Deck.gl** / **Mapbox GL** (geospatial visualization)
- **i18n** (internationalization support)

### Getting Started

```bash
# Install dependencies
cd frontend
npm ci

# Start development server
npm run dev

# Build for production
npm run build

# Lint (zero warnings)
npm run lint

# Browser regressions against the production build, with mocked API responses
npx playwright install chromium
npm run build
npm run test:e2e
```

The dev server runs at `http://localhost:5173` by default.

### Backend API

The frontend communicates with the AgentSociety 2 backend (FastAPI) running at `http://localhost:8001`. API documentation is available at `http://localhost:8001/docs` when the backend is running.

### Project Structure

```
frontend/
├── src/
│   ├── main.tsx              # Entry point
│   ├── Layout.tsx            # App layout
│   ├── Menu.tsx              # Navigation menu
│   ├── pages/                # Route pages
│   ├── components/           # Shared components
│   ├── i18n/                 # i18n configuration
│   ├── utils/                # Utilities
│   └── types/                # TypeScript type definitions
├── public/                   # Static assets
├── index.html
├── vite.config.ts
└── package.json
```

---

## AgentSociety UI

AgentSociety UI 是 **AgentSociety 2** 仿真平台的 **React + Vite** Web 仪表盘，提供基于 Web 的实验管理、结果查看和研究工作流配置界面。

### 技术栈

- **React 19** + **TypeScript**
- **Vite**（构建工具）
- **Ant Design 6** / **Ant Design Pro Components**（UI 框架）
- **Monaco Editor**（代码编辑器）
- **Plotly.js**（数据可视化）
- **Deck.gl** / **Mapbox GL**（地理空间可视化）
- **i18n**（国际化支持）

### 快速开始

```bash
# 安装依赖
cd frontend
npm ci

# 启动开发服务器
npm run dev

# 生产构建
npm run build

# 代码检查（零警告）
npm run lint

# 生产构建的浏览器回归测试，API 使用本地模拟响应
npx playwright install chromium
npm run build
npm run test:e2e
```

开发服务器默认运行在 `http://localhost:5173`。

### 后端 API

前端与 AgentSociety 2 后端（FastAPI）通信，后端运行在 `http://localhost:8001`。后端启动后，API 文档可访问 `http://localhost:8001/docs`。

### 项目结构

```
frontend/
├── src/
│   ├── main.tsx              # 入口文件
│   ├── Layout.tsx            # 应用布局
│   ├── Menu.tsx              # 导航菜单
│   ├── pages/                # 路由页面
│   ├── components/           # 共享组件
│   ├── i18n/                 # 国际化配置
│   ├── utils/                # 工具函数
│   └── types/                # TypeScript 类型定义
├── public/                   # 静态资源
├── index.html
├── vite.config.ts
└── package.json
```