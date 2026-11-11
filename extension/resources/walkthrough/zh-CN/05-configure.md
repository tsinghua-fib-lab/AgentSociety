## 配置 LLM 与后端

**请先打开项目文件夹。** API Key 写入该文件夹的 `.env`；未打开文件夹时无法保存。

推荐顺序：**打开文件夹 → 配置并保存仿真 LLM → 初始化工作区 → 启动后端**。

打开配置页，首次使用时按 **配置向导** 操作：

1. **一键导入**（可选）— 从 AgentSociety Web 导入 API Key、默认模型等配置
2. **仿真 LLM** — API 地址、密钥与模型；可选设置推理（thinking）开/关
3. **保存配置** — 写入工作区 `.env`
4. **启动后端** — 一键保存并启动本地服务
5. **文献 MCP**（可选）
6. **EasyPaper**（可选）— 论文生成所用的 LLM 与可选 VLM
7. **CLI 网关**（可选）— Claude Code / Codex

也可点 **「全部设置」** 切换到完整的标签页视图。

仿真 LLM 的推理下拉会写入 `AGENTSOCIETY_LLM_THINKING`（`on` / `off`）；留空表示不额外发送该参数，行为与旧版一致。旁边的高级折叠区还可选择接口协议（OpenAI Chat Completions / Anthropic Messages，`AGENTSOCIETY_LLM_API_TYPE`）与推理控制格式（`AGENTSOCIETY_LLM_THINKING_FORMAT`）；实际发送的参数随协议而定。完整设置的「代码生成」标签页可独立设置 `AGENTSOCIETY_CODER_LLM_THINKING` 及上述相关选项。

### 必填项

| 配置项 | 说明 | 示例 |
|--------|------|------|
| **API Key** | 服务商密钥 | `sk-...` |
| **API Base** | 服务地址 | `https://api.openai.com/v1` |

Fiblab 用户可选用预设 **Fiblab LLM API**（`https://llmapi.fiblab.net/v1`）。填写后先 **验证**，再 **保存**。

### 分清三层连接配置

| 层级 | 控制范围 | 不会控制 |
|------|----------|----------|
| **仿真 LLM** | AgentSociety 仿真与后端的模型调用；写入工作区 `.env` | Claude Code / Codex 的供应商路由 |
| **CLI 供应商 / 本地 Gateway** | Claude Code / Codex 的直连或网关路由 | 仿真 LLM 配置 |
| **出站代理** | Gateway 与从配置页重新启动的新 Codex 终端的网络出口，包括在该终端发起的登录 | 供应商选择或本地 Gateway 路由 |

出站代理不等于本地 Gateway。Codex Gateway 路由关闭时，官方 Codex 模型请求不会经过 AgentSociety Gateway。若配置了出站代理并从本页重启 Codex，新终端会继承代理环境变量；登录时打开的浏览器仍遵循浏览器或系统自身的网络设置。

### 后端服务

后端是本地 FastAPI 服务，技能管理、模块探测、回放 API、API 文档等依赖它。未启动时仍可编辑配置、浏览项目树，或通过 CLI / Claude Code 运行实验。

| 入口 | 操作 |
|------|------|
| 状态栏 | 点击 AI Social Scientist 状态 → Start / Restart / Show Logs |
| 配置页 | 页头的「保存并启动后端」按钮 |
| 命令面板 | `Start Backend` |
| 配置向导 | 第 4 步 |

默认端口多为 `localhost:8001`。修改 `.env` 后建议重启后端。

[打开配置页面](command:aiSocialScientist.openConfigPage) · [启动后端](command:aiSocialScientist.startBackend) · [查看日志](command:aiSocialScientist.showBackendLogs)
