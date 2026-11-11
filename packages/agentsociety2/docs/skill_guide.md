# Skill 编写指南

先让一个最小技能被发现并产生可检查的文件，再增加脚本、依赖与 hook。

本页保留从零编写技能的最短流程。发现、激活、脚本执行与 hook 契约统一维护在 {doc}`agent_skills`，避免两份说明随实现变化而不一致。

## 创建最小技能

在研究工作区创建目录：

```text
custom/skills/social-reflection/
└── SKILL.md
```

`SKILL.md` 同时包含用于发现的元数据和激活后读取的行为说明：

```markdown
---
name: social-reflection
description: Reflect on a recent social interaction and record a short explanation.
---

# Social Reflection

## When to use
After a meaningful social interaction.

## Inputs
Use the current step context. Read state/relationships.json if it exists.

## Steps
1. Read the available relationship state; use an empty state if the file is absent.
2. Explain how the interaction may change trust, using evidence from the current step.
3. Write a short reflection to state/social_reflection.json.

## Outputs
state/social_reflection.json, containing reflection and supporting evidence.
```

在工作台的“技能管理 → 运行时”扫描工作区。技能出现在目录中后，由智能体在运行时按需激活；目录可见不代表已经执行。

## 何时添加脚本

确定性计算、格式转换和数据校验适合脚本；开放判断可先使用纯提示技能。脚本的 `entrypoint(argv, ctx)`、`ctx.workspace_root`、返回值和超时规则见 {doc}`agent_skills`，API 见 {doc}`api/skills`。

`SKILL.md` 只声明受支持的 `name`、`description`、可选 `script` 与 `hooks`。依赖、输入、输出和环境交互步骤写在正文中，不添加没有解析器支持的配置字段。

## 检查与调试

- 用独立测试工作区放置输入，检查缺失输入和重复执行时的行为。
- 对照实际工具名编写步骤；与环境交互使用 `ask_env`。
- 检查输出文件与 `<run_dir>/trace/trace_*.jsonl`，区分“技能被发现”“技能被激活”和“脚本已完成”。
- 需要维护运行时或内置技能时，阅读源码中的 `agentsociety2/agent/skills/README.md`。
