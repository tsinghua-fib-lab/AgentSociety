# Agent Skill 技术方案

> 适用范围：`agentsociety2`（v2.x）。本文描述 `PersonAgent` 的 Skill 子系统——
> 从目录结构、发现机制、可见性/激活模型，到**脚本执行模型（按信任级分流）**
> 与生命周期 hook 的注入方式。文档面向 Skill 作者与二次开发者；用户侧指南见
> ReadTheDocs 的 `agent_skills` / `skill_guide` 两页，本文与它们保持同一套术语。
>
> 架构位置：Skill **基础设施**（registry / runtime / context / worker / workspace_fs）
> 位于 `agentsociety2/agent/base/`；本目录 `agent/skills/` 只承载 Skill **内容**
> （当前唯一内置技能是 `daily-guidance`）。

## 1. 概述

PersonAgent 是 `AgentBase` 之上的轻量编排器；`AgentBase` 直接持有 workspace 绑定、
ReAct 工具循环与 `AgentSkillRuntime`。Skill 遵循 **metadata-first、selected-only** 模型：

- **选择阶段**：LLM 只看到 Skill 目录（`name` + `description`），据此决定激活哪些。
- **执行阶段**：只有被 LLM 选中的 Skill 才会被加载、读取、执行（惰性加载）。

这样做的好处是：提示词体积可控（未选中的 Skill 不进上下文），且 Skill 可独立
演进、热加载。

一个 Skill 是一个自包含目录，至少包含一个 `SKILL.md`（YAML frontmatter + 行为
文档），可选地包含 `scripts/`（可执行脚本）和 `references/`（参考资料）。

```
agent/skills/                     # 内容目录（基础设施在 agent/base/）
└── daily-guidance/               # 一个 Skill = 一个目录
    ├── SKILL.md                  # frontmatter（name/description/script/hooks）+ 行为说明
    ├── scripts/
    │   └── daily_guidance.py     # 可执行脚本（提供 entrypoint 与原生 pre_step hook 函数）
    └── references/
        ├── examples.md           # SKILL.md 引用、按需读取的参考资料
        └── story_schema.yaml
```

## 2. 目录结构与 SKILL.md 规范

### 2.1 目录约定

| 路径 | 是否必需 | 说明 |
| --- | --- | --- |
| `SKILL.md` | 必需 | YAML frontmatter + Markdown 行为文档。是 Skill 的入口。 |
| `scripts/*.py` | 可选 | 可执行脚本。`script:` 指向默认脚本；`hooks:` 指向生命周期脚本。 |
| `references/*` | 可选 | SKILL.md 中引用的补充材料，按需被 agent 读取（渐进式披露）。 |

### 2.2 SKILL.md frontmatter

frontmatter 目前识别以下字段（解析逻辑见 `agent/base/skill_registry.py` 的
`_parse_frontmatter` / `_parse_hooks`）：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `name` | str | Skill 显示名，与命名空间组合成 `skill_id`（`namespace@name`）。 |
| `description` | str | **目录描述**——选择阶段 LLM 唯一可见的文本，决定是否激活。务必精炼、可操作。 |
| `script` | str | 可选，默认脚本相对路径（如 `scripts/daily_guidance.py`）。`execute_skill_script` 不传 `script_path` 时用它。 |
| `hooks` | dict | 可选，生命周期 hook 脚本映射，键为 hook 类型（如 `pre_step`、`post_step`），值为相对脚本路径。旧式单字段 `hook` + `hook_script` 也兼容。 |

示例（取自 `daily-guidance`）：

```markdown
---
name: daily-guidance
description: 强制使用：凡是时间尺度在小时及以下的日常行为模拟，必须使用本 Skill 生成、评估、执行和修正每日 Story。
script: scripts/daily_guidance.py
hooks:
  pre_step: scripts/daily_guidance.py
---

# Daily Guidance

（Markdown 行为文档：告诉 LLM 何时、如何使用本 Skill……）
```

> frontmatter 之后的 Markdown 正文，是 Skill 被**激活后**注入到 system prompt 的
> 行为说明（`<skill_content>` 块）。未激活时不进上下文。

## 3. 发现机制（内置 / 自定义 / 环境模块）

`SkillRegistry` 按目录扫描，用 `namespace@name` 作为稳定 `skill_id`。registry 是
**共享只读单例**（`get_skill_registry()`，见 `agent/base/skill_registry.py`），
frontmatter 按内容哈希缓存，不再每 agent 复制：

- **内置 Skill**：扫描 `agentsociety2/agent/skills/`，命名空间 `built-in`
  （如 `built-in@daily-guidance`），仅扫描一次。
- **自定义 Skill**：扫描 agent 工作区下的 `custom/skills/`，命名空间 `custom`
  （如 `custom@my-skill`）。**热加载**——放进去即可在运行时被发现，无需改框架代码。
- **环境模块 Skill**：环境模块可携带 `skills/` 目录，由 `scan_env` 注册，
  命名空间 `env:<模块类名>`（如 `env:EconomySpace@market-quote`）。

扫描规则（见 `skill_registry._scan_root`）：

- 每个子目录必须含 `SKILL.md`，否则跳过。
- 以 `.` 或 `_` 开头的目录被忽略（缓存、内部目录）。
- 同名（同 `skill_id`）先到先得，后扫描的不会覆盖。

agent 启动时通过 `default_activated_skill_ids` 配置默认激活哪些 Skill（例如
daily-mobility 默认激活 `built-in@daily-guidance`）。registry 变更（扫描自定义 /
环境技能）后由 `AgentBase._refresh_visible_skills` 刷新可见集合；agent 的可见 /
激活子集持久化在 `AGENT.json`，恢复时还原。

## 4. 可见性与激活

- **可见（visible）**：Skill 出现在目录里，LLM 能看到、能选择激活。
- **激活（activated）**：Skill 的 `SKILL.md` 正文被注入 system prompt，其脚本/hook
  可被调用。

LLM 通过下列工具操作 Skill（schema 见 `agent/base/tool_schema.py`，分发在
`agent/base/agent.py` 的 ReAct 工具循环里；工具参数既接受显示名也接受
`namespace@name`）：

| 工具 | 作用 | 改变状态？ |
| --- | --- | --- |
| `activate_skill` | 加载某 Skill 的 SKILL.md 进上下文 | 是 |
| `deactivate_skill` | 从上下文移除某 Skill | 是 |
| `read_skill_file` | 读取 Skill 内的文件（渐进式披露） | 否 |
| `execute_skill_script` | 执行 Skill 脚本 | 否（脚本内部可能写工作区） |

> ask 模式下（外部问答）只暴露只读工具子集；agent 经由通用 workspace `read`
> 工具读 Skill 内嵌文件时，runtime 会把路径映射回 `read_skill_file`
> （`AgentSkillRuntime.resolve_skill_path`），避免被当作越界路径拒绝。

## 5. 脚本执行模型（按信任级分流）⭐

这是当前实现的**核心**。历史上 Skill 脚本一律以子进程方式执行（`python
script.py <argv>`），每个 agent 每步都要 fork 一个新解释器，冷启动开销巨大。
v2.10.0 起执行路径按 Skill 的信任级别分流（见 `agent/base/skill_runtime.py`
的 `_run_skill_path`）：

```
built-in 技能（可信，进程内热路径）:
  ① 原生 hook 函数              ← hook 脚本顶层定义同名无参函数（如 pre_step）时直接调用
  ② entrypoint(argv, ctx)       ← 缓存 import 后进程内直调，毫秒级，完全并发安全
  ③ 子进程（python script.py）  ← 无 entrypoint / 模块导入失败时的回退

custom / env 技能（不可信，子进程隔离）:
  ① skill_worker.py 单次子进程  ← 提供 entrypoint 或原生 hook 函数时，worker 导入并只调用该函数
  ② 子进程（python script.py）  ← 无任何可调用函数时的回退，仅使用环境变量白名单
```

> 旧的"动态包装器"（无 `entrypoint` 时以 `__name__ == "__main__"` 就地 `exec`
> 脚本、由全局锁串行）已在 v2.10.0 **删除**；无 `entrypoint` 的脚本一律走子进程，
> 超时后可终止且不改变父进程状态。

要点：

- **契约不变**：无论进程内还是 worker 子进程，`entrypoint(argv, ctx)` 的签名与
  `ctx.workspace_root` 等上下文保持一致——Skill 作者按同一契约编写即可，信任级
  分流对作者透明。
- **隔离而非就地执行**：自定义 / 环境技能即使提供 `entrypoint` 或原生 hook 函数，
  也在 `skill_worker.py` 启动的**单次子进程**中执行——每次调用独立导入模块，
  故障与状态不外溢。
- **静态可调用检测**：runtime 用 `ast` 静态判断脚本顶层是否定义了目标可调用
  （`_source_defines_callable`），**不执行代码**。无 `entrypoint` 的脚本完全不被
  import——顶层副作用不会被双执行，事件循环也不会被无超时保护的导入挂死。

### 5.1 `entrypoint` 契约（推荐所有 Skill 脚本遵循）

Skill 脚本可在模块顶层定义一个 `entrypoint`（内置技能进程内直调；自定义技能经
`skill_worker.py` 子进程调用）：

```python
def entrypoint(argv: list[str], ctx) -> str:
    """技能入口。

    Args:
        argv: 命令行参数（去掉脚本名之后的部分），与子进程方式的 sys.argv[1:] 一致。
        ctx:  SkillScriptContext，携带本 agent 的运行上下文（见 5.2）。

    Returns:
        str: 脚本原本会打印到 stdout 的文本（通常是 YAML/JSON 结果块）。
    """
```

要点：

- **签名兼容**：runtime 检测形参数量，`entrypoint(argv)` 与 `entrypoint(argv, ctx)`
  都支持（同步或 `async def` 皆可，异步入口用 `asyncio.wait_for` 加超时）。
  **强烈建议接受 `ctx`**（见 5.2 的并发安全要求）。
- **返回 stdout**：不要依赖 `print` 被 capture；直接 `return` 结果字符串。
  也可返回 `(stdout, stderr)` 二元组（当前实现取第一个元素作为 stdout）。
- **异常即失败**：`entrypoint` 抛异常 → 该次执行记为失败（`exit_code=1`，
  `stderr=traceback`）。不要用 `sys.exit()`；如需表达“逻辑失败”，在返回的文本里
  写 `ok: false`（和 CLI 语义一致）。
- **幂等加载（内置技能）**：进程内路径按 `(路径, mtime)` 缓存模块，模块顶层代码
  只执行一次，文件变化自动重载。把可变状态放进函数内或 contextvar，**不要放
  模块级全局**（见 5.5）。`skill_worker.py` 子进程每次调用重新导入，无此语义。

CLI 与 `entrypoint` 共用同一套派发逻辑，是最佳实践（参见 5.7 的 daily-guidance 示例）。

### 5.2 `SkillScriptContext`

进程内执行不依赖进程全局的环境变量，上下文通过 `ctx` 显式传入（定义在
`agent/base/skill_script_context.py`；内置技能由 runtime 构造，自定义技能在
`skill_worker.py` 子进程内构造）：

| 字段 | 说明 | 纯子进程时代的对应物 |
| --- | --- | --- |
| `ctx.workspace_root` | 本 agent 的工作区根目录 | 环境变量 `AGENT_WORK_DIR` |
| `ctx.skill_dir` | 本 Skill 的包根目录 | 环境变量 `SKILL_DIR` |
| `ctx.skill_id` | 注册 id（`namespace@name`） | 环境变量 `SKILL_ID` |
| `ctx.skill_name` | 显示名 | 环境变量 `SKILL_NAME` |
| `ctx.env` | 子进程方式本会设置的 env 快照（dict） | 进程 `os.environ` |

> 用 `Path(str(getattr(ctx, "workspace_root")))` 取工作区根，**不要**读
> `os.environ["AGENT_WORK_DIR"]`。

### 5.3 原生 hook 函数快速路径

hook 脚本可在模块顶层定义一个与 hook 同名的**无参函数**（`def` 或 `async def`），
runtime 静态检测到后**直接调用该函数**——不打 argparse、不跑脚本其余部分、不
阻塞事件循环。这是热路径 hook（如 daily-guidance 的 `pre_step`）的推荐写法。

上下文不经过参数传入，而是经 contextvars 的 `get_hook_context()` 读取（定义在
`agent/base/skill_hook_context.py` 的 `HookContext`）：

| 字段 | 说明 |
| --- | --- |
| `ctx.workspace_root` | 本 agent 的工作区根目录。 |
| `ctx.skill_dir` | 本 Skill 的包根目录。 |
| `ctx.skill_id` | 注册 id（`namespace@name`）。 |
| `ctx.hook_type` | 生命周期 hook 名（`pre_step` / `post_step`）。 |
| `ctx.payload` | 生命周期 payload dict（`hook_type` / `tick` / `time` / `agent_id` / `step_count`）。 |

内置技能的 hook 函数在 agent 进程内直调（同步函数保持内联热路径；异步函数用
`asyncio.wait_for` 加超时）；自定义技能的同名函数在 `skill_worker.py` 子进程内以
相同的 `HookContext` 契约执行。函数返回值即 hook 输出（非字符串会序列化为 JSON）。

### 5.4 `skill_worker.py` 隔离子进程

自定义 / 环境技能的可调用（`entrypoint` 或原生 hook 函数）由
`agent/base/skill_worker.py` 以**单次子进程**执行：

- 父进程把 `{path, name, argv, skill_id, skill_name}` 以 JSON 从 stdin 传入；
  worker 导入模块、只调用目标函数，把返回值按 stdout 约定结构化返回（JSON）；
  技能自身的 `print` 输出转入 stderr，不会污染结果。
- **每次调用独立导入**：启动和导入都计入调用超时；跨调用状态应写入 workspace，
  不要依赖模块全局变量。
- 子进程**保留宿主 `os.environ`**（自定义函数原先可读取的 SDK、代理等配置可用），
  并叠加技能上下文（`SKILL_ID` / `SKILL_NAME` / `SKILL_DIR` / `AGENT_WORK_DIR`）。
- 无任何可调用函数的普通脚本回退为 `python script.py <argv>` 子进程，仅使用
  环境变量白名单（`PATH` / `HOME` / `USER` / `SHELL` / `PYTHONUNBUFFERED` /
  `LITELLM_MODEL` / `LITELLM_BASE_URL` / `AGENT_MEMORY_*`，见
  `skill_runtime.ALLOWED_ENV_VARS`）。

### 5.5 并发安全要求（重要）

一次模拟里多个 agent 在**同一个进程**内并发跑各自**内置技能**的 `entrypoint` /
hook 函数（自定义技能已由 worker 子进程按调用隔离）。下列进程级状态是**共享**的，
绝不能在内置技能的可调用里直接读写，否则会产生数据竞争：

| ❌ 禁止 | ✅ 替代方案 |
| --- | --- |
| `os.environ["AGENT_WORK_DIR"] = ...` | 用 `ctx.workspace_root` |
| `os.chdir(workspace)` | 用绝对路径（`ctx.workspace_root / ...`） |
| `print(...)` 并依赖 stdout 捕获 | 在 entrypoint 里 `return` 字符串 |
| 模块级可变全局当作“本次调用状态” | 用 `contextvars.ContextVar`（任务级隔离） |

`daily_guidance.py` 的做法：用两个 `ContextVar` 分别承载“本次调用的工作区根”
和“本次调用的 emit 缓冲”，`entrypoint` 设置后、`dispatch` 内全程可见，调用结束
`reset`——天然并发安全（见 5.7）。

### 5.6 生命周期 payload 与超时

- **payload**：hook 以 `["--args-json", <json>]` 形式接收
  `hook_type` / `tick` / `time` / `agent_id` / `step_count`（`AgentBase._run_lifecycle_hooks`
  构造）。脚本形态从中取参；函数形态经 `ctx.payload` 读取。
- **超时**：脚本与 hook 调用默认 30s。子进程路径超时后可终止；内置进程内路径
  的同步 `entrypoint` / 同步 hook 函数保持内联调用（异步入口才有 `wait_for` 硬
  超时），因此**内置技能的可调用必须自行保证及时返回**，不要长阻塞。

### 5.7 完整示例：daily-guidance

`daily_guidance.py` 是当前唯一内置技能，同时示范了三条路径：原生 `async def
pre_step()` hook 函数（热路径）、`entrypoint`（CLI 命令）与 CLI `main()` 共用
同一个 `dispatch`：

```python
_WORKSPACE_ROOT: contextvars.ContextVar[Path | None] = contextvars.ContextVar(
    "dg_workspace_root", default=None
)
_EMIT_BUFFER: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "dg_emit_buffer", default=None
)


def agent_work_dir() -> Path:
    override = _WORKSPACE_ROOT.get()
    if override is not None:
        return override
    raw = os.environ.get("AGENT_WORK_DIR")  # 纯子进程路径才用
    return Path(raw).resolve() if raw else Path.cwd().resolve()


async def pre_step() -> str:
    """原生无参 hook 函数：runtime 检测到同名函数后直接调用（快速路径）。"""
    from agentsociety2.agent.base.skill_hook_context import get_hook_context

    ctx = get_hook_context()  # HookContext：workspace_root / payload / ...
    result = _build_hook_result(ctx.workspace_root, ctx.payload)
    return yaml.safe_dump(result, allow_unicode=True, sort_keys=False)


def dispatch(args: argparse.Namespace) -> int:
    if args.cmd == "plan":
        return command_plan(args)
    if args.cmd == "current":
        return command_current(args)
    # …其余命令…
    return command_hook_init(args)


def entrypoint(argv: list[str], ctx: Any) -> str:
    workspace_root = Path(str(ctx.workspace_root)).resolve()
    ws_token = _WORKSPACE_ROOT.set(workspace_root)
    buf_token = _EMIT_BUFFER.set([])
    try:
        args = parse_args(list(argv))  # parse_args 接受显式 argv
        dispatch(args)
        return "".join(_EMIT_BUFFER.get() or [])  # 把 emit 累积的 YAML 文本返回
    finally:
        _EMIT_BUFFER.reset(buf_token)
        _WORKSPACE_ROOT.reset(ws_token)


def main() -> int:
    return dispatch(parse_args())


if __name__ == "__main__":
    raise SystemExit(main())  # 纯子进程回退路径仍可用
```

`emit()` 写入 ContextVar 缓冲（entrypoint 模式）或 `print`（子进程模式）：

```python
def emit(payload: dict[str, Any]) -> None:
    text = yaml.safe_dump(payload, allow_unicode=True, sort_keys=False)
    buffer = _EMIT_BUFFER.get()
    if buffer is not None:
        buffer.append(text)
    else:
        print(text)
```

## 6. 生命周期 Hook（pre_step / post_step）

在 `SKILL.md` 的 `hooks:` 里声明，每个仿真步自动触发（由
`AgentBase._run_lifecycle_hooks` 编排，只对**可见且已激活**的 Skill 运行）：

- **`pre_step`**：`agent.step()` 开头、ReAct 循环之前运行。典型用途：根据仿真时钟
  推导当前状态（如 daily-guidance 的 `active_segment`），**注入到首轮上下文**。
- **`post_step`**：ReAct 循环之后运行。典型用途：记录实际行为、收尾。

hook 有两种形态：

1. **函数形态（推荐）**：脚本顶层定义同名无参函数（如 `async def pre_step()`），
   经 `get_hook_context()` 读取 `HookContext`（见 5.3）。
2. **脚本形态**：整个脚本按 CLI 运行，以 `--args-json <json>` 接收 payload。

**注入方式**：`pre_step` 的输出渲染为**专用的 `<skill_hooks>` XML 分块**
（`agent/person_prompt.py` 的 `_render_skill_hooks_xml`），出现在 ReAct 首条 user
消息中——而不是被塞进通用 observation dump（那容易被 LLM 忽略）。例如：

```xml
<skill_hooks>
<skill_hook skill="built-in@daily-guidance" hook="pre_step" ok="true">
ok: true
active_segment:
  activity: sleep
  location_policy: home_aoi
guidance: Your intended activity now is 'sleep' …
</skill_hook>
</skill_hooks>
```

这样 agent 不必再花一轮 `observe` + `execute_skill_script` 去“重新发现”状态。

## 7. 环境类 Skill（`env:` 前缀）

以 `env:` 开头的 skill_id 会被 `execute_skill_script` **重定向到 `ask_env`**
（走环境路由 `RouterBase`），而非执行脚本。用于把“查询/操作仿真环境”包装成
Skill 暴露给 LLM。这类 Skill 不需要 `entrypoint`；readonly（ask）模式下变更类
指令会被拒绝。

## 8. 性能

进程内路径的动机是消掉旧实现每步 fork 解释器的冷启动。v2.10.0 改版时 50-agent
daily-mobility 的 trace 聚合实测（子进程 → 进程内 `entrypoint`）：

| 指标 | 子进程方式（旧） | 进程内 entrypoint | 提速 |
| --- | --- | --- | --- |
| `pre_step` hook 单次 | ~8933 ms | ~95 ms | ~93× |
| `execute_skill_script` 单次 | ~4023 ms | ~50 ms | ~80× |
| ReAct 轮数 / 步 | 4.02（36% 撞 6 轮上限） | 2.44（14% 撞顶） | 轮数 ↓39% |
| `agent.step` 整体 | ~75 s | ~31 s（median） | ~2.4× |

在此之上，原生 hook 函数快速路径（5.3）进一步跳过 argparse / exec / argv 解析，
是当前 daily-guidance `pre_step` 实际走的路径。当前的代价结构：

- **内置技能**：`entrypoint` / hook 函数进程内直调，毫秒级、并发安全；同步
  `entrypoint` 内联调用（不经线程池——默认 executor + GIL 争用反而让并发 hook
  膨胀），异步入口由 `wait_for` 加超时。
- **自定义 / 环境技能**：按调用付出一次子进程启动（隔离换安全），启动与导入
  计入超时；热路径能力应尽量提交为内置技能或改为读 workspace 状态文件。

## 9. 编写 Skill 的检查清单

新建一个 Skill 时，对照以下清单：

- [ ] 目录放在 `agent/skills/<name>/`（内置）或工作区 `custom/skills/<name>/`（自定义）。
- [ ] 有 `SKILL.md`：frontmatter 含 `name`、`description`（精炼可操作）、可选 `script`/`hooks`；
      正文是激活后注入的行为说明。
- [ ] 若有脚本：
  - [ ] 提供 `def entrypoint(argv, ctx) -> str`，**接受 `ctx`**。
  - [ ] 工作区根取自 `ctx.workspace_root`，不读 `os.environ`/不 `os.chdir`。
  - [ ] 结果用 `return` 返回，不依赖 `print` 捕获。
  - [ ] 用 `contextvars` 承载“本次调用状态”，不用模块级可变全局。
  - [ ] CLI 派发与 `entrypoint` 共用同一函数（`main()` 调 `dispatch(parse_args())`）。
  - [ ] 自定义技能每次调用都在独立子进程执行——跨调用状态写 workspace 文件。
- [ ] 若声明 `pre_step` hook：优先写**同名无参函数**（`def` / `async def`），
      经 `get_hook_context()` 取上下文；输出要自包含、可直接作为 agent 指引
      （会被包进 `<skill_hooks>`）。
- [ ] 参考资料放 `references/`，SKILL.md 里点名引用，按需被读取（控制上下文体积）。

## 10. 相关代码索引

| 关注点 | 位置 |
| --- | --- |
| Skill 元数据与发现 | `agent/base/skill_registry.py`（`SkillRegistry`、`SkillDescriptor`、`_parse_frontmatter`、`_parse_hooks`、`get_skill_registry`） |
| 可见性/激活/脚本执行/hook 调度 | `agent/base/skill_runtime.py`（`AgentSkillRuntime`、`_run_skill_path`、`_run_in_process`、`_call_entrypoint`、`_run_hook_function`、`_source_defines_callable`、`ScriptRunResult`） |
| `SkillScriptContext` 定义 | `agent/base/skill_script_context.py` |
| `HookContext` 与 `get_hook_context()` | `agent/base/skill_hook_context.py` |
| 自定义/环境技能隔离子进程 | `agent/base/skill_worker.py` |
| 工作区文件系统门面（子进程执行） | `agent/base/workspace_fs.py`（`WorkspaceFS`、`CommandResult`） |
| ReAct 工具 schema | `agent/base/tool_schema.py`（`activate_skill` / `deactivate_skill` / `read_skill_file` / `execute_skill_script`） |
| 工具分发、生命周期 hook 编排、`env:` 重定向 | `agent/base/agent.py`（工具循环、`_run_lifecycle_hooks`、`_refresh_visible_skills`） |
| ReAct 提示词与 `<skill_hooks>` 渲染 | `agent/person_prompt.py`（`build_react_messages`、`_render_skill_hooks_xml`、`skill_content_xml`） |
| step 编排（hook 时机） | `agent/person.py`（`step`，收集 `skill_hooks` 后传入首轮 prompt） |
| 参考实现（原生 hook 函数 + entrypoint + CLI） | `agent/skills/daily-guidance/scripts/daily_guidance.py`（`async pre_step`、`entrypoint`、`dispatch`、`agent_work_dir`、`emit`） |
