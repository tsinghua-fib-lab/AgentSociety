## Claude Code 与 Codex

**Claude Code** / **Codex** 是 AI Social Scientist 的两类终端与编辑器协作入口。初始化项目后，工作区会带上：

```text
workspace-root/
├── .claude/skills/   # 开发技能
├── CLAUDE.md
└── AGENTS.md
```

### 先选择连接方式

| 使用方式 | 配置建议 |
|----------|----------|
| **官方 Claude / Codex 账户** | 保持对应的本地代理开关关闭，在 CLI 中完成官方登录，或在配置页用 **「登录 Codex 官方账户」** 设备登录面板直接登录 |
| **第三方 API 直连** | 在配置页添加带 API Key 的供应商并设为对应默认项 |
| **第三方 API 经 Gateway** | 添加供应商后开启 Claude / Codex 路由，用于协议转换、故障转移和用量统计 |

官方登录与第三方供应商配置可以共存。Codex 将登录凭据保存在 `auth.json` 或系统凭据库中，供应商路由则位于 `config.toml`；AgentSociety 只改写自己负责的路由字段，不覆盖官方登录缓存。

### Codex 切换与重启行为

- **切到官方模式：** 自动关闭 Codex Gateway 路由，并删除 AgentSociety 管理的供应商字段；已有官方凭据继续保留。
- **开启 Gateway 路由：** 实时 `config.toml` 指向本地 Gateway，同时用受保护的恢复快照记录直连配置。
- **路由中切换供应商：** 本地路由保持工作，恢复目标会同步为新选中的供应商。
- **关闭路由或卸载扩展：** 恢复一份可直接使用的配置；若路由状态仍为开启，下次扩展激活会启动 Gateway 并重新应用本地路由。
- **Gateway 启动失败：** Codex 回退到直连配置，不会停留在不可用的 localhost 地址。

Codex 会在启动时读取供应商与模型目录等设置。修改供应商、模型、目录或出站代理后，应从配置页重启 Codex。只有仿真 `.env` 发生变化时，才需要重启 AgentSociety 后端。

### 推荐配置路径

1. **配置页** — 仿真 LLM、可选 CLI Gateway、供应商与出站代理
2. **技能管理 → MCP** — 同步文献 MCP 到 Claude / Codex
3. 在终端启动 `claude` 或 `codex`，用 `/status`、`/mcp` 检查连接

[打开配置页](command:aiSocialScientist.openConfigPage) · [打开技能管理](command:aiSocialScientist.openSkillMarketplace) · [Claude 技能源设置](command:aiSocialScientist.openClaudeSkillSourcesSettings)

### 接下来还可以做什么

| 功能 | 入口 |
|------|------|
| 仿真回放 | 在侧边栏右键实验目录 |
| 论文 / 分析结果 | `paper/`、`presentation/`、`synthesis/` |
| 使用指南 | 命令面板：`AI Social Scientist: 使用指南` |
| 术语附录 | 本快速入门最后一步 |

文档：[agentsociety2.readthedocs.io](https://agentsociety2.readthedocs.io/) · 论文：[arXiv:2607.11895](https://arxiv.org/abs/2607.11895) · 反馈：[GitHub Issues](https://github.com/tsinghua-fib-lab/agentsociety/issues)
