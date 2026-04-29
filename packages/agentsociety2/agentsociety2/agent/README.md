# Agent 模块

面向基于 Agent 建模（ABM）研究的 Skills-first 智能体框架。

## 设计理念

### 核心原则

1. **技能优先架构**
   Agent 能力通过 Skill 模块动态扩展，而非硬编码。用户可定义自定义 Skill，系统自动发现并集成。

2. **统一配置管理**
   所有配置集中于 `AgentConfig`，支持环境变量覆盖和运行时调整。

3. **长时间运行支持**
   内置检查点、预写日志（WAL）和工作区清理机制，支持崩溃恢复和长时间仿真。

4. **上下文窗口管理**
   借鉴 Claude Code 最佳实践：简洁上下文、渐进式技能披露、自动压缩。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│                      PersonAgent                            │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │ AgentConfig │  │ SkillRuntime │  │   PromptBuilder  │   │
│  │ (配置)       │  │ (技能执行)    │  │   (模块化Prompt) │   │
│  └─────────────┘  └──────────────┘  └──────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Persistence Layer                       │   │
│  │  Checkpoint │ WriteAheadLog │ WorkspaceCleaner      │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Concurrency Control                     │   │
│  │  PriorityScheduler │ RateLimiter │ DeadlockDetector │   │
│  └─────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

## 目录结构

```
agent/
├── person.py          # PersonAgent 实现
├── base.py            # Agent 抽象基类
├── config.py          # 统一配置
├── prompt_builder.py  # 模块化 Prompt 构建
├── persistence.py     # 检查点、WAL、清理
├── concurrent.py      # 优先级调度、限流
├── context.py         # 上下文管理、Token 计数
├── tool/              # 工具模块
│   ├── decision.py    # ToolDecision 模型
│   ├── loop_detection.py  # 循环检测
│   ├── security.py    # bash 命令安全检查（黑名单 token/模式/危险子串）
│   └── utils.py       # 工具函数
├── skills/            # 技能系统
│   ├── __init__.py    # SkillRegistry
│   ├── runtime.py     # AgentSkillRuntime
│   ├── observation/   # 环境感知
│   ├── cognition/     # 情绪、需求、意图
│   ├── memory/        # 长期记忆、关系
│   └── plan/          # 行动执行
```

## 核心组件

### 1. AgentConfig - 统一配置

```python
from agentsociety2.agent import AgentConfig

config = AgentConfig()
config.model.context_window          # 200000
config.loop.max_rounds               # 24
config.persistence.checkpoint_interval  # 10
```

### 2. Persistence - ACID 保证

```python
from agentsociety2.agent import Checkpoint, WriteAheadLog

checkpoint = Checkpoint(workspace, config)
checkpoint.save(tick=100, state={"step_count": 42})

wal = WriteAheadLog(workspace)
intent_id = wal.log_intent("execute_skill", {"skill": "cognition"}, tick=1)
wal.log_result(intent_id, {"ok": True})
```

### 3. Concurrency - 优先级调度

```python
from agentsociety2.agent import PriorityScheduler, RateLimiter, DeadlockDetector

scheduler = PriorityScheduler(max_concurrent=5)
await scheduler.submit("task1", my_coro(), Priority.HIGH)

limiter = RateLimiter(rps=10, burst=20)
await limiter.acquire()

detector = DeadlockDetector(timeout=60.0)
detector.register("operation1")
```

### 4. Context Management - AGENT.md

`AGENT.md` 由运行时组件 `AgentSkillRuntime` 自动维护（包含 YAML frontmatter 与自动生成的文件索引区块）。
Agent 可通过 `workspace_read("AGENT.md")` 获取当前上下文与文件索引。

## 内置技能

| 技能 | 功能 | 输入 | 输出 |
|-----|------|-----|------|
| observation | 环境感知 | - | observation.txt |
| cognition | 情绪、需求、意图生成 | observation.txt | emotion.json, needs.json, intention.json |
| memory | 长期记忆、人际关系 | observation.txt | memory.jsonl, relationships.json |
| plan | 行动执行 | intention.json | plan_state.json |

### 技能元数据

```yaml
---
name: cognition
description: 核心认知技能，生成情绪、需求和意图。
inputs:
  - state/observation.txt
outputs:
  - state/emotion.json
  - state/needs.json
  - state/intention.json
---
```

## 工作区结构

```
agent_0001/
├── state/              # 技能状态文件
│   ├── emotion.json    # 情绪状态
│   ├── needs.json      # 生理/社交需求
│   ├── intention.json  # 当前目标
│   └── memory.jsonl    # 长期记忆日志
├── logs/               # 执行日志
│   ├── tool_calls.jsonl
│   └── thread_messages.jsonl
├── checkpoints/        # 恢复快照
├── wal/               # 预写日志
│   ├── wal.jsonl
│   └── index.json
└── AGENT_CONTEXT.md   # 动态上下文（CLAUDE.md 风格）
```

## AGENT_CONTEXT.md 设计

借鉴 Claude Code 的 CLAUDE.md 最佳实践：

- **简洁**：不超过 2000 字符
- **结构化**：YAML frontmatter + Markdown 章节
- **活文档**：每 tick 更新
- **焦点优先**：当前任务醒目展示

示例：

```markdown
---
current_focus: 在咖啡馆吃午餐
tick: 42
location: downtown_cafe
energy: 0.65
mood: content
---

# Agent Context

## Current Focus
正在主街的咖啡馆吃午餐。

## Key Decisions
- 选择步行而非乘坐公交
- 点了今日特餐

## Patterns
- 1 公里内的距离偏好步行

## Known Issues
- 钱包现金不足
```

## 快速开始

```python
from agentsociety2.agent import PersonAgent, AgentConfig
from datetime import datetime

agent = PersonAgent(
    id=1,
    profile={"name": "Alice", "age": 25},
)
await agent.init(env)
result = await agent.step(tick=300, t=datetime.now())
```

## 环境变量

| 变量 | 默认值 | 说明 |
|-----|-------|------|
| AGENT_MODEL | "" | 模型名称 |
| AGENT_CONTEXT_WINDOW | 200000 | 上下文窗口大小 |
| AGENT_MAX_TOOL_ROUNDS | 24 | 最大工具循环轮数 |
| AGENT_CHECKPOINT_INTERVAL | 10 | 检查点间隔（ticks） |

## 测试

```bash
# 运行单元测试
pytest tests/test_agent_modules.py -v

# 运行覆盖率测试
pytest tests/ --cov=agentsociety2.agent
```
