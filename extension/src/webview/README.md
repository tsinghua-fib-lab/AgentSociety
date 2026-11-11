# Webview 前端

此目录包含扩展内嵌的 React 界面，与仓库的独立 `frontend/` 网页应用分开构建。

- 页面入口和 bundle 名称以 [webpack.config.js](../../webpack.config.js) 的 webview entries 为准。
- 共享组件位于 `components/`，翻译资源位于 `i18n/`。
- 宿主端的 `*ViewProvider.ts` / `*EditorProvider.ts` 负责消息、文件访问和后端请求；页面通过 Webview 消息协议与宿主交互。
- 构建命令：在 `extension/` 执行 `npm ci`、`npm run build-webview`，产物写入 `out/webview/`。
- 页面清单、消息协议、开发调试与截图流程统一维护在[扩展开发指南](../../docs/DEVELOPMENT.md)。

新增页面时同时更新 webpack entry 和宿主加载路径，并核对命令、消息、翻译以及打包后的资源；不在此重复维护随页面变化的完整清单。
