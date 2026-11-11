# Changelog

本文件遵循 [Keep a Changelog](https://keepachangelog.com/en/2.0.0/) 格式，记录 **AgentSociety 2** 相关组件的可见变更。

| 组件         | 标识                    | 说明                                        |
| ------------ | ----------------------- | ------------------------------------------- |
| Python SDK   | `agentsociety2`         | `packages/agentsociety2`，PyPI / 私有源发版 |
| VS Code 扩展 | `ai-social-scientist`   | `extension/package.json` 中的版本号         |
| 分析技能     | `agentsociety-analysis` | 随扩展同步至工作区 `.claude/skills/`        |

SDK 与扩展各自遵循 [语义化版本](https://semver.org/spec/v2.0.0.html)，不要求版本号相同。稳定版 Git 标签为 `agentsociety2-v{major}.{minor}.{patch}`，对应 SDK 版本；每次发布列出所打包的扩展版本。未发布变更维护在 `Unreleased`，发版时填入 `YYYY-MM-DD` 日期，见 `CONTRIBUTING.md`。

---

## [Unreleased]

## [2.11.0] - 2026-11-11

- **agentsociety2** `2.11.0` · **extension** `1.9.0` · 标签 `agentsociety2-v2.11.0`

### Added

- **docs**：引入 sphinx-design 导航卡片与 sphinx-copybutton 复制按钮；增加公开记忆 API、离线配置与回放示例验证，以及定期外链和 API 文档覆盖报告。
- **extension**：支持 Codex 官方账户设备登录——通过设备认证接口获取验证码与登录地址，支持复制、取消与重试，令牌由官方 CLI 保存并复用出站代理；每个 CLI 以单选方式选择主供应商，前后端统一协议与订阅兼容性判断。
- **extension**：供应商卡片展示余额、已用额度、剩余比例与重置时间，区分账户余额、套餐额度、API Key 额度与本地调用统计；支持自动识别与自定义查询接口（同源 GET、JSON 字段路径、数值除数），查询结果缓存一分钟并随连接与凭据变化失效。
- **extension**：接入 MCP 官方 Registry API（自定义兼容地址、按名称搜索、游标翻页），按注册源元数据生成 HTTP / SSE / npm / PyPI / OCI 配置并先进入编辑器供核对；MCP 配置支持从 Claude Code、Codex、JSON / TOML 文件或粘贴内容预览导入，区分新增、相同、冲突与无效条目。
- **extension**：技能市场统一卡片布局（标题单行、标签摘要、三行描述与底部操作区）；MCP 市场提供官方与 GitHub 注册源，统一使用 Registry v0.1 查询、搜索及分页接口；HTTP 服务增加按客户端选择的 OAuth 授权入口，远程环境使用 `--no-browser` 回填流程。
- **发布维护**：增加 SDK、运行时、锁文件、插件和发版标签的一致性检查；GitLab 与 GitHub 从同一份 CHANGELOG 提取对应版本的发布说明。

### Changed

- **CI**：按改动触发质量检查，精简 SDK 与文档安装依赖，复用浏览器和镜像缓存；镜像发布等待完整相关检查，并串行更新正式镜像标签。
- **docs**：按任务组织研究助手、智能体、环境和技能指南，补充输入数据、回放、结果、API 及排错说明，统一中英文内容与内联格式并保留旧章节链接。
- **docs**：完善深浅色主题、手机导航、容器自适应卡片、长名称索引与键盘滚动；升级兼容的 Sphinx、修复中文搜索，增加真实示例、翻译、链接和页面回归检查。
- **backend**：完善 Swagger / ReDoc 的分组与参数说明，增加 Swagger 主题切换、分组导航及窄屏布局。
- **frontend**：按页面依赖拆分共享资源，避免首页预加载问卷等大型模块；保留地图与问卷的完整功能。
- **extension**：统一 Webview 按钮、输入框、卡片与弹窗的圆角、尺寸与间距，使用编辑器主题配色，支持高对比度主题与减少动态效果；状态卡片支持 Enter、空格及键盘焦点提示，修复窄窗口溢出。
- **extension**：MCP 管理支持编辑现有服务、按名称 / 地址 / 工具检索与工具列表探测（会话 ID、协议版本、分页工具列表、持续 SSE）；技能市场搜索覆盖中文描述、仓库、作者和标签并增加未安装 / 已安装 / 可更新筛选；文献库增加关键词 / 原文 / 笔记筛选、跨页选择与批量导出，CSV 全字段转义。
- **agentsociety2 / extension**：统一 LLM 推理控制——新增 `AGENTSOCIETY_LLM_THINKING_FORMAT` 按接口声明选择 reasoning_effort / thinking / enable_thinking / chat_template_kwargs / reasoning 字段；默认与 Coder 角色可独立配置协议和控制格式，设置随 LLMClient 序列化进入 Ray worker；配置页常用区只展示推理模式，协议与控制格式移入高级折叠区。

#### 性能记录

- **agentsociety2 / mobility**：附近 POI 观察共用一次空间查询并批量计算候选距离；路径请求复用 HTTP 会话。
- **agentsociety2 / codegen**：默认使用 `inprocess` 在环境进程内计算，保留代码许可和工具权限约束；设为 `process` 可开启独立计算进程、硬执行期限与内存限制。
- **agentsociety2**：短工具程序预先编译为受限操作计划，复用原事件循环的异步工具并发；数值进程复用策略绑定，准备结果缓存序列化程序。
- **agentsociety2**：缓存最多 128 项静态校验与编译结果；每次执行独立创建上下文、结果、运行时检查与期限，策略变化使准备缓存失效。

### Removed

- **依赖**：移除未启用的 autodoc2 及其 astroid 依赖，合并重复的开发和文档工具声明；清理前端未使用的直接依赖，将 Plotly 类型声明归入开发依赖。

### Fixed

- **docs**：修复中文搜索的词干器脚本引用与分词缺失，补充领域词典；增加中英文搜索、手机导航及主题交互的浏览器回归。
- **extension**：工作区已有 `custom/skills/` 时，初始化仍会补齐 Agent 与环境模块目录并保留用户文件；实验配置页兼容从 `profile.name` 显示人物姓名。
- **frontend**：技能页使用后端支持的扫描、创建、导入和查看接口，按带命名空间的技能 ID 查询，提交失败时保留草稿并说明错误。
- **agentsociety2 / mobility**：路由请求使用正确的驾车/步行 RouteType，拒绝未知交通方式；ETA 按实际仿真速度返回，并以一微米距离容差处理终点浮点残差。
- **agentsociety2**：写工具开始执行后，程序失败会停止单次 ask 内的整段纠错重试，返回写入尝试标记；只读限制在工具调用端执行。
- **agentsociety2**：技能元数据按实际读取内容生成指纹，修复等长编辑且文件时间戳相同时复用旧内容的问题。
- **agentsociety2**：统一 Python 代码围栏解析，提取说明文字后的代码并保留合法字符串中的 Markdown；按分支检查终态赋值，并在执行后核验实际分类，允许分类后的正常打印。
- **agentsociety2**：编译准备异常统一在入口返回，临时资源错误可在后续请求重新准备。
- **agentsociety2**：执行工具前拒绝重绑定结果容器，修复结果丢失后纠错重试重复产生副作用的问题。
- **agentsociety2 / agent**：创建、保存和恢复统一使用 `skills` 字段；环境技能发现后恢复已有激活状态，减少跨步重复激活。DailyMobility 初始化补充结构化 home/work AOI 并预激活移动技能。
- **extension**：仿真、CLI 与 EasyPaper 共用供应商模型目录服务，目录接口 404 不再误报成功，删除内置模型清单并保留手填模型 ID；EasyPaper 的 LLM 与 VLM 模型分别获取，复制 LLM 配置不再覆盖 VLM，新配置文件采用随插件发布的模板并原子保存（权限 0600）。
- **extension**：设备登录入口收归 Codex 配置页签，以弹窗展示启动、验证码、等待授权与完成状态；错误信息保留失败阶段、HTTP 状态与 Codex 错误码，区分请求拒绝、网络故障、证书、限流与验证码过期，403 提供网络设置入口。
- **extension**：文献库命令支持直接打开当前工作区索引，有工作区时显示于命令面板，保留项目树入口。

### Security

- **agentsociety2 / security**：完整 Python 与 NumPy 函数调用可显式选择带硬执行期限和地址空间限制的 Linux 工作进程；拒绝执行帧、代码对象及生成器/协程 frame/code 内省。
- **agentsociety2 / security**：限制生成代码访问 NumPy 文件、反序列化与原生接口，校验公开模块别名，并拒绝直接改写宿主对象属性。

## [2.10.1] - 2026-11-02

- **agentsociety2** `2.10.1` · **extension** `1.8.1` · 标签 `agentsociety2-v2.10.1`

### Fixed

- **CI**：VSIX 发版校验适配 webpack 打包布局——主进程入口改为 `dist/extension.js`，
  运行时依赖已内联、不再检查 `node_modules/js-yaml`；并补上 `helpPage` /
  `skillMarketplace` webview。2.10.0 的 PyPI 已发布，但 `Build VSCode extension`
  因旧路径误判失败、GitHub Release / VSIX 被跳过。本版无功能变更，重新发版以落成
  VSIX 与 Release。

## [2.10.0] - 2026-11-02

- **agentsociety2** `2.10.0` · **extension** `1.8.0` · 标签 `agentsociety2-v2.10.0`

### Changed

- **agentsociety2**：CLI 默认关闭环境路由 LLM 摘要阶段，以执行输出生成应答；保留摘要配置，
  并分别记录 codegen / summary 调用来源。配套 codegen 输出预算与截断检查、技能执行超时与
  子进程回收、跨进程 LLM 并发配额。实测多窗口 LLM 调用约降 30%–47%，环境摘要调用清零。
- **agentsociety2**：Agent / 环境路由 / 分析工具的 LLM JSON 解析收敛到 `loads_llm_json`
  （包装剥离、严格解析、jsonmend/json_repair 修复与工具参数归一）。
- **agentsociety2 / extension / docker**：工程基础加固——SDK 导入与技能运行时、扩展网关定价
  与用量追踪、Docker 文档模型依赖固定，以及示例博弈实验结构整理。

### Fixed

- **frontend**：清理检查警告；修复异步状态更新与回放加载。
- **extension**：复用已有后端进程；修复状态循环刷新；修复 minimatch 漏洞并升级 i18n /
  TypeScript ESLint 依赖。
- **ci / deps**：固化 GitHub 镜像同步工具链；修复传递依赖与 community 安全告警；清理
  CodeQL 代码质量告警。
- **examples**：修复环境干预与公共物品博弈验证路径。
- **agentsociety2**：多进程回放写入改用 spawn 验证，避免 fork 相关假阳性。

## [2.9.3] - 2026-09-24

- **agentsociety2** `2.9.3` · **extension** `1.7.3` · 标签 `agentsociety2-v2.9.3`

### Fixed

- **env**：`CodeGenRouter` 模板缓存复用判定改按「代码实际必读的变量」，不再使用
  `variable_keys` 键集互含关系（该字段只是创建条目时调用方传键的快照）。同指令
  多带无关键不再被否决回退全量 LLM codegen（实测同指令命中 6064ms → 1.4ms 量级）；
  缺必读变量的缓存代码不再被放行（缓存代码 `max_retries=0`，执行失败无回退）。
  `_lookup` 新增精确匹配快速路径（无需 embedding 计算），FAISS 相似度路径同步换用
  该判据；必读键经 AST 静态提取，不可静态分析的代码退回保守旧判据，无行为回归。

## [2.9.2] - 2026-09-23

- **agentsociety2** `2.9.2` · **extension** `1.7.2` · 标签 `agentsociety2-v2.9.2`

### Fixed

- **CI**：VSIX 发版校验适配 js-yaml 5 的 `dist/` 布局（CJS 入口从根 `index.js` 变为
  `dist/js-yaml.cjs.js`）。2.9.1 的 GitHub Actions `Build VSCode extension` 因此误判失败、
  `Create GitHub Release` 被跳过——VSIX 实际内容一直是完好的，PyPI 2.9.1 亦已正常发布。
  本版无任何功能变更，重新发版以落成 VSIX 工件与 GitHub Release。

## [2.9.1] - 2026-09-23

- **agentsociety2** `2.9.1` · **extension** `1.7.1` · 标签 `agentsociety2-v2.9.1`

#### Known issues

- **agentsociety2**：`exec` 仍同步阻塞事件循环（asyncio 单线程下生成代码无法真并行）；受 env
  模块线程安全约束，本版未改为线程池执行。

### Added

- **agentsociety2**：环境模块 `is_concurrency_safe()`；全部安全时 Env Ray actor 使用
  `AGENTSOCIETY_ENV_ACTOR_MAX_CONCURRENCY`（默认 64），否则 `max_concurrency=1`。
- **agentsociety2**：实验日志后端接口支持按行 `tail` 读取（非整文件）。
- **agentsociety2**：contrib onboarding 模块 `SpecialistAgent`、`WeatherEnvironment`（Ray 可发现）。
- **agentsociety2**：`AgentSocietyHelper` 计划/答案改为 XML；新增 `get_agent_profile` 工具。
- **agentsociety2**：`AGENT.json` 持久化 `world_description`，供 Ray 重建恢复。
- **agentsociety2**：新增 `AGENTSOCIETY_ENV_RESTORE_ALLOW_FRESH` 开关（见下方 Changed 的严格
  env resume 项）。
- **extension / frontend**：回放时间线可用性改善；前端路由懒加载；Console 日志截断。

### Changed

- **agentsociety2**：`AGENTSOCIETY_ENV_ACTOR_MAX_CONCURRENCY` 默认值 8 → 64。300-agent 实测在飞
  env ask 的 p50 ≈ 59，旧默认 8 会饿死 actor（同 run 形态下 env ask 均值 38.2s@8 vs 2.5s@64）；
  不安全模块栈仍强制 `max_concurrency=1`，不受影响。
- **agentsociety2**：模板缓存锁内不再 await embedding HTTP。`_lookup`（每次 ask）与
  `_add_to_cache` 曾共用 `_template_cache_lock` 且在锁内调 embedding 端点，把并行 ask 串行化到
  embedding 延迟上（配置 64× 实测并行度仅 5.6×）。现在 embedding 在锁外计算（自带缓存与独立锁，
  并发安全），锁内只剩纯 CPU 的 faiss 检索/写缓存，保持串行。
- **agentsociety2**：env resume 默认严格——任一模块 `restore()` 抛错即中止整个 resume（先尝试
  全部模块、汇总失败点后统一抛错）。静默降级（失败模块以初始状态继续跑）会让模块状态与
  `SOCIETY_STEP.json` 记录的步数脱钩，损坏只会在下游指标暴露。设置
  `AGENTSOCIETY_ENV_RESTORE_ALLOW_FRESH=1` 可恢复旧的降级行为（fresh 启动 + ERROR 汇总）。
- **agentsociety2**：`CodeGenRouter` 代码执行不再全局替换 `sys.stdout`——async 生成代码在
  `await` 环境工具期间让出事件循环，并发 ask 会互相换走进程级 stdout，恢复后 print 串进
  别人的 buffer（64 并发下实测串台）。改为向 exec globals 注入每次执行独立的 `print`
  （生成代码无法 import sys——sys 在 `DANGEROUS_MODULES`；exec globals 先于 builtins 解析，
  输出全部走注入路径，各自写入本次执行的 StringIO）。
- **agentsociety2**：`CodeGenRouter` FAISS 指令模板缓存仅在 `template_mode=True` 时生效；无
  observe/statistics 工具时 init 不再为了空集合跑 LLM 代码生成。
- **agentsociety2**：`society.step` 在任一 agent `ok=False` 时抛错；博弈/contrib agent 的 LLM
  失败改为上抛，不再静默默认出招。
- **agentsociety2**：`ask_env` 统一返回 `(ctx, answer)` 二元组。
- **agentsociety2**：examples onboarding 改为 `EnvRouterProxy` + contrib 模块路径。
- **agentsociety2**：`agentsociety2.__version__` 修正为随版本发布同步（此前停留在 2.8.3）。

#### 性能记录

| 场景 | Before | After | 收益 |
| ---- | ------ | ----- | ---- |
| env 锁拓扑（8×0.04s，2 模块） | 0.323s 全局锁 | 0.162s 模块锁 | ×1.996 |
| 实验日志 tail（2.5MB，tail=500） | 2.69ms / 2.5MB | 0.46ms / 104KB | 字节 4.2%；时间 ×5.8 |
| FAISS 模板缓存（`template_mode`，1 ask） | 14.9s / 2148 tok / 命中 0 | 0.049s / 0 tok / 命中率 1.0 | 墙钟 ×304；token→0 |
| Env actor 并发（4 并行 ask，c=1→8） | 433.8s | 120.6s | ×3.60 |
| env ask 均值（300-agent 生产 run：并发 8→64 且 embedding 出锁） | 38.20s | 3.29s | ×11.6；墙钟占比 42.9%→35.8% |

单元测试：`test_env_concurrency_and_log_tail`、`test_society_helper_xml`、`test_replay_timeline_and_skill_cache`；
examples basics/advanced/games 全量 LLM 回归均为 SUCCESS。本次新增回归：并发默认值断言
（`test_env_actor_max_concurrency_default_is_64`）、embedding 锁外并发
（`test_template_lookup_runs_embeddings_outside_cache_lock`）、严格 resume 与降级开关
（`test_partial_restore_aborts_by_default` / `test_partial_restore_degrades_only_with_allow_fresh`）、
exec print 并发隔离（`test_exec_print_capture_isolated_between_concurrent_asks`）；
全量 `pytest -m "not network"` 553 passed。

正确性抽检（2026-09-22 实跑）：`SpecialistAgent` onboarding SUCCESS（~30s）；
囚徒困境 2 轮 SUCCESS（~68s）；`PersonAgent` `step`+`ask` SUCCESS（~377s，`AGENT.json` 写出）。

## [2.9.0] - 2026-09-17

- **agentsociety2** `2.9.0` · **extension** `1.7.0` · 标签 `agentsociety2-v2.9.0`

### Added

- **extension**：工作区导出 / 导入。侧边栏可将研究项目打包发给同事，对方用同一入口打开；密钥不会进入压缩包，导入后需自行配置模型密钥。
- **extension** `1.7.0`：配置页适配推理（thinking）开关——默认 LLM 卡片与「代码生成」tab 各新增一个
  「跟随网关默认 / 开启 / 关闭」下拉，中英双语文案与 `.env` 模板注释同步。`AGENTSOCIETY_LLM_THINKING`
  等变量此前插件完全无感知（手写在 `.env` 里的值只能靠后端 `load_dotenv()` 再加载一遍才生效），
  现在由 `BackendManager` 显式透传。`AGENTSOCIETY_LLM_EXTRA_BODY` / `_REASONING_EFFORT` 不建表单，
  但同样纳入读取与透传，且配置页**永不重写** `_EXTRA_BODY` 行——`readEnv` 不去引号、
  `writeEnv` 的 `formatValue` 又会补引号转义，两者叠加会把 JSON 转义坏并导致后端静默忽略。
- **agentsociety2**：LLM 推理（thinking）开关，仅面向 OpenAI 兼容 chat-completions 接口。新增
  `AGENTSOCIETY_LLM_THINKING`（`on`/`off`，未设置时不发送任何新参数）、
  `AGENTSOCIETY_LLM_REASONING_EFFORT`、`AGENTSOCIETY_LLM_EXTRA_BODY`（网关私有开关的 JSON 逃生口），
  以及 `AGENTSOCIETY_CODER_LLM_*` 按角色覆盖。发送 `reasoning_effort` 时会显式附带
  `allowed_openai_params` —— litellm 的 `openai/` 适配器会按模型名过滤参数，对不在其模型表中的
  网关模型（即任何 OpenAI 兼容部署）会直接拒绝该参数。
- **agentsociety2**：prompt 缓存命中率埋点。解析各网关形态的 `cached_tokens`，逐轮写入
  `llm.completion` trace span，收尾写 `run_dir/LLM_STATS.json` 并在日志汇总（`AgentSociety.token_stats`
  / `cache_hit_rate()`）。

### Changed

- **extension**：导出、导入和入门文档改为面向研究者的说明，去掉清单、哈希、输出通道等开发用语。
- **agentsociety2**：prompt 分节按变化频率重排——system 去掉 agent 名、ask 规则移入 user 消息，
  `<recent_observations>` 从 user 消息开头移到末尾。同一 run 内所有 agent 共享同一段 system 前缀
  （实测命中率 43.2% → 69.1%）。
- **agentsociety2**：ReAct 循环改为**追加式对话历史**。一次 `run_react_loop` 只构建一个 thread，
  之后每轮的 assistant 工具调用与结果追加到末尾（原生 `role: "tool"` 消息，文本兜底路径为
  `<recent_observations>` user 块），不再每轮重渲染。每个请求因此成为上一个的严格前缀扩展，缓存
  随轮次增长（实测真实循环聚合命中率 84.7%）。**破坏性内部变更**：删除私有方法
  `AgentBase._call_react_llm`；`_call_react_llm_with_messages` 返回 `ReactTurn` 并原地扩展消息列表；
  `ReactDecision` 新增 `call_id` 字段。`run_react_loop` / `build_react_messages` 的签名与契约不变。
- **agentsociety2**：移除 litellm Router 上的 `cache_responses=True`——那是 litellm 自己的**响应**
  缓存（未配置全局 `litellm.cache` 时是空操作），而非 provider 的 prompt 前缀缓存；一旦有人配置了
  全局缓存，ReAct 循环会拿到陈旧回复。

## [2.8.7] - 2026-09-09

- **agentsociety2** `2.8.7` · **extension** `1.6.7` · 标签 `agentsociety2-v2.8.7`

### Changed

- **extension** `1.6.7`：CLI 网关的「Codex 本地代理」改为默认启用——在 Codex 供应商激活时刻（一键导入、新建/编辑/激活供应商），若用户没有自有 Codex 配置（无自建 provider、无官方 OAuth 登录、auth.json 也非仅 API Key），自动开启路由并启动本地网关；已有配置与登录一律不动，显式开关永远优先。系统级路由回退（供应商失效等）不再记录为用户选择，此后默认探测仍可生效。导入路径默认触发时补充 Codex 重启提示。

## [2.8.6] - 2026-09-09

- **agentsociety2** `2.8.6` · **extension** `1.6.6` · 标签 `agentsociety2-v2.8.6`

### Changed

- **CI**：npm audit 告警（传递依赖）不再阻断 extension lint job 与 `agentsociety2-v*` 发版流水线（GitLab 与 GitHub workflow 两侧对齐）。

### Fixed

- **extension** `1.6.6`：修复 AgentSociety Web 一键导入后 Claude Code 聊天报「There's an issue with the selected model (glm-5.2)」——直连模式写入 `~/.claude/settings.json` 的 `ANTHROPIC_BASE_URL` 带有 `/v1` 后缀，Claude Code 追加路径后实际请求 `/v1/v1/messages`（404）；现在写回退直连前统一剥离末尾 `/v1`，Codex 与网关链路不受影响。
- **extension** `1.6.5`：Codex 一键导入改用独立推荐模型并增加对已有 Codex / Claude Code 配置的覆盖保护。

## [2.8.3] - 2026-07-20

- **agentsociety2** `2.8.3` · **extension** `1.6.5` · 标签 `agentsociety2-v2.8.3`

### Added

- **研究工作流**：新增面向主流学术会议的多评审者论文评审技能，并支持带修订轮次、来源与转换历史的可审计阶段回退。
- **分析 Harness**：新增契约驱动的操作注册、统一 preflight、能力发现、执行回执、幂等准备与中断恢复机制。

### Changed

- **分析报告**：强化报告资产同步、交互式 EDA 嵌入、双语报告质量检查与发布门禁。
- **extension** `1.6.5`：完善研究工作区路由、模型供应商连接回退与错误诊断，并将新建工作区进度结构升级至 `1.3`。

### Fixed

- **extension**：规范化打包与文档（`check` / `package:check`、CHANGELOG 入口、收紧 `.vscodeignore`）；修正 walkthrough NLS 相关历史描述中的 `package.nls.en.json` 笔误。
- **extension** `1.6.3`：walkthrough 标题/描述改为直接写入 `package.json`（code-server 不解析 `%nls%`）。
- **agentsociety2**：`agent.runner` 延迟导入 ray，修复 Windows CI（ray 未安装于 win32）。
- **agentsociety2**：修复跨平台工作区命令、后端路径校验与错误信息泄漏问题，并更新北京地图下载地址。
- **extension**：修复 Codex 配置、Web 导入状态同步、Coder 代理打包。

## [2.8.1] - 2026-07-12

- **agentsociety2** `2.8.1` · **extension** `1.6.2` · 标签 `agentsociety2-v2.8.1`

### Fixed

- **extension** `1.6.2`：walkthrough `media.markdown` 改为直接相对路径，不再使用 `%walkthrough.media.*%` 占位符（code-server / VS Code 对该字段的 NLS 替换不可靠）。
- **extension**：修复 walkthrough 无法打开（`%walkthrough.media.*%` 占位符未解析）；将 `package.nls.json` / `package.nls.zh-cn.json` 纳入版本库并打包进 VSIX。

## [2.8.0] - 2026-07-12

- **agentsociety2** `2.8.0` · **extension** `1.6.0` · 标签 `agentsociety2-v2.8.0`

### Added

- **extension**：配置向导、就绪仪表盘与 Gateway 用量统计；恢复 EasyPaper 配置与 AgentSociety Web 导入。
- **extension**：Claude Gateway 1M 对齐 CC Switch（Sonnet/Opus/Fable/Haiku 四角色表格 + 手动声明 1M）。
- **extension**：技能市场 MCP 集成面板；`scripts/clean.js` 与 Gateway 单测。
- **scripts**：`llm_benchmark` 支持环境变量与 CLI 配置 API Key/Base/Model。

### Changed

- **extension**：重构 Gateway 供应商编辑、Codex 目录、故障转移与 Responses↔Anthropic 桥接。
- **agentsociety2**：示例与实验对齐 `agent_specs` / `enable_replay` 等新 API。
- **backend**：自定义模块测试 API 由 `ScriptGenerator` 更名为 `SafeModuleTester`。

### Fixed

- **agentsociety2**：CodeQL / Protocol 类型与抽象方法等 18+ 处修复。
- **scripts**：移除 benchmark 脚本中硬编码 API Key。
- **frontend**：同步 `package-lock.json` 与 `package.json`。

### Security

- 依赖安全升级（Python / extension / frontend）。

## [2.6.1] - 2026-06-19

- **extension** `1.5.5`

### Added

- **extension**：统一供应商管理面板，所有供应商共享一个列表，无需重复添加。
- **extension**：供应商卡片使用简洁的开关控制 Claude/Codex 角色激活，支持一键切换主供应商。
- **extension**：故障转移设置移至路由面板中，打开故障转移后显式选择备选供应商。
- **extension**：定价面板新增缓存读取/写入价格字段，支持手动刷新远程定价（OpenRouter / LiteLLM）。
- **extension**：论文工作区树视图全面优化，匹配 paper-toolkit 实际输出文件名（`paper_meta.yaml`、`claim_ledger.json`、`evidence_backlog.json` 等）。
- **extension**：新增 `PaperArtifactViewer` 专用查看器，根据文件名自动选择展示模式（论文状态、研究包、主张列表、审阅结果、证据图谱等）。
- **extension**：补充 `projectStructure` 缺失的 i18n 翻译（分析工作区、叙事线、图表-主张映射等）。

### Changed

- **extension**：移除 Claude/Codex 子 Tab，路由开关整合到统一的网关面板中。
- **extension**：优化 JSON/YAML/CSV 查看器：YAML 新增可折叠树形和搜索，CSV 新增列排序和搜索过滤。
- **extension**：论文/分析工作区节点图标全面应用语义色彩（紫色 paper、蓝色 analysis、橙色 flame 等）。
- **extension**：新增 `.tex`、`.bib`、`.cls`、`.bst`、`.cfg`、`.conf`、`.toml` 文件在树视图中的显示支持。

### Removed

- **extension**：移除 EasyPaper 配置页及相关代码（Python 后端已不再使用）。
- **extension**：移除 `AiCliToolProxySection` 组件（内联到路由面板中）。

### Fixed

- **extension**：修复 `paperArtifact` 文件节点 `resourceUri` 覆盖自定义 `command` 导致专用查看器被绕过的问题。
- **extension**：修复 `AiCliConfigSection` 中 `t`/`palette`/`providers` 解构导致子组件收到 `undefined` 的运行时错误。
- **extension**：修复论文工作区文件名与实际 paper-toolkit 输出不匹配导致文件不显示的问题。
- **extension**：修复配置页编译错误与 ESLint `curly` 警告。

### Security

- 升级依赖修复 26+ 个安全漏洞：`litellm`、`chromadb`、`urllib3`、`cryptography`、`tornado`、`aiohttp`、`starlette`、`python-multipart`、`pyjwt`、`idna`、`pytest`、`ray`、`filelock`、`python-dotenv`、`vite` 等。
- 修复 `path_security.py` 路径穿越检查顺序问题。
- 修复 `config.py` 敏感信息日志 CodeQL 告警。

## [2.5.4] - 2026-06-09

- **agentsociety2** `2.5.4` · **extension** `1.5.4` · 标签 `agentsociety2-v2.5.4`

### Added

- **extension**：配置页支持通过 Casdoor Device Flow 从 AgentSociety Web 导入 LiteLLM、Claude Code 与 EasyPaper 配置，登录凭据缓存至用户目录 `~/.fiblab/`。
- **extension**：导入模型列表后，默认 LLM、专用模型、Embedding、Claude Code 与 EasyPaper 模型字段提供可编辑候选项。
- **extension**：EasyPaper 导入时自动配置 LLM 与 VLM 的模型、Base URL 和 API Key。

### Changed

- **extension**：Web 导入配置需用户确认后才填入表单，仍需手动保存。
- **extension**：Claude Code 导入保留 LiteLLM Base URL 原值，不再自动追加 `/anthropic`。

### Fixed

- **extension**：修复 Webview 配置页导入按钮 i18n key 直出问题。
- **extension**：修复 EasyPaper VLM 开关无法正常操作的问题。
- **extension**：修复 Device Flow 默认 client id 导致线上 Casdoor 返回 `Invalid client_id` 的问题。
- **agentsociety2**：同步包内 `agentsociety2.__version__` 到发布版本。

## [2.5.3] - 2026-05-30

- **agentsociety2** `2.5.3` · **extension** `1.5.3` · 标签 `agentsociety2-v2.5.3`

本版本在 [2.5.2] 基础上进行 **依赖升级**、**分析 harness 增强** 与 **扩展 UX/健壮性改进**。

### Added

- **analysis**：CLI 新增 `guidance`、`payload-template`、`chart-scaffold` 子命令，内置分析指引与 JSON 模板。
- **analysis**：交互式 EDA 嵌入报告（`report_eda_embed.py`），支持在 HTML 报告中嵌入可视化图表。
- **analysis**：经验记忆闭环（experience memory），跨分析会话积累反馈。
- **analysis**：更严格的 phase gate 与扩展的 skill references。
- **analysis**：新增 `chart_export.py`（817 行）、`harness/guidance.py`（473 行）等模块。
- **docs**：中文 README（根目录 `README_zh.md` 与 `packages/agentsociety2/README_zh.md`）。
- **docs**：`AGENTS.md` 从符号链接改为独立文档，适配 Cursor 等编辑器。
- **extension**：新增 3 个 analysis support skills（`interactive-viz`、`report-blocks`、`scientific-visualization`）。

### Changed

- **extension**：默认 LLM 模型对齐为 `gpt-5.5`。
- **extension**：`engines.vscode` 降至 `^1.95.0`，兼容 Cursor（基于 VS Code 1.105.x）。
- **extension**：工作区缺失目录/文件时自动修复，不再显示修复按钮和确认对话框。
- **extension**：缺少 `.env` 时自动创建模板并引导配置 API key。
- **extension**：`initProject` 去掉已存在时的确认对话框（`init()` 本身幂等）。
- **extension**：技能同步成功时不再弹窗，仅失败/异常时提示。
- **extension**：扫描自定义模块时去掉多余的"Scanning..."开始通知。
- **extension**：后端配置错误时按钮直接打开配置页（而非手动编辑 `.env` 文件）。
- **deps**：刷新根 `uv.lock`、`agentsociety-community/uv.lock`、`package-lock.json` 等全部 lock 文件。

- **docs**：新增根目录与 `packages/agentsociety2` 的中英文 README（`README_zh.md`），同步 Sphinx 贡献指南与 API 示例。
- **docs**：将 `AGENTS.md` 从 `CLAUDE.md` 软链拆为独立 Cursor Agent 入口；修正 `cliff.toml` 对 `docs(...)` commit 的匹配。
- **docs**：更新 `README.md`、`CONTRIBUTING.md`、`SECURITY.md`，补充发版流程与 CI 范围说明。
- **analysis**：分析 harness 增加经验记忆闭环（`draft-reflection` / `promote-reflection` / `memory-context`）及更严格的 phase 门禁。
- **analysis**：分析技能 stages 补充外部工具调用链（integrations.md）与 Stage 6 必做经验沉淀；support 包在 explore/refine/produce 阶段显式启用。
- **extension**：默认 LLM 模型对齐为 `gpt-5.5`。
- **ci**：收窄检查范围至 AgentSociety2（`packages/agentsociety2`、`extension`、`frontend`）；legacy 包不纳入活跃 CI / Dependabot / CodeQL 扫描。
- **ci**：修复 frontend 全量 ESLint 错误（类型化、`unused-vars` 清理、Workflow 分支逻辑）；CI 保留 lint + build + audit。
- **ci**：发版前增加 validate 门禁；GitHub Release 说明改用 git-cliff。
- **deps**：刷新根 `uv.lock`（`sphinx-intl`、`urllib3`、`pytest` 等）；extension 升级 `ajv`、`@types/vscode`；frontend 升级 `typescript-eslint`、`@types/react-plotly.js`；GitHub Actions 升级 `dependency-review-action` v5、`download-artifact` v8。

### Fixed

- **extension**：`git clone` 操作现在检查返回状态码，失败时抛出明确错误。
- **extension**：`autoCommit` 的 git 操作改为返回 `boolean`，失败时提前终止并记录日志。
- **extension**：`autoCommit` 中 `git config user.name` 空字符串检测修复。
- **extension**：ZIP 导出本地文件时改为流式 `copyFile`，不再将整个 ZIP 读入内存。
- **extension**：ZIP 导出增加系统 `zip` 命令作为 Python 的后备方案。
- **extension**：导出扫描中的 `readdirSync` 增加 try-catch 保护。
- **extension**：孤立后端进程健康检查增加一次 2 秒延迟重试，避免误杀启动中的后端。
- **extension**：临时目录改用 `fs.mkdtempSync()`，消除竞态条件风险。

## [2.5.2] - 2026-05-29

- **agentsociety2** `2.5.2` · **extension** `1.5.2` · 标签 `agentsociety2-v2.5.2`

本版本在 [2.5.1] 基础上完成 **paper 技能外迁**、**安全加固** 与 **依赖漏洞修复**；Python 安装：`pip install agentsociety2==2.5.2`。

### Changed

- **docs**：根 `CLAUDE.md`、`workspace/CLAUDE.md`、`workspace/AGENTS.md` 指引由 `agentsociety-paper-orchestrator` 更新为引用外部 `paper-toolkit` plugin（确定性 CLI + companion Claude Code 写作 / 审阅 skill）。

### Removed

- **agentsociety2**：内置 `paper` 研究技能套件（`agentsociety-paper-adapter` / `agentsociety-paper-architecture` / `agentsociety-paper-evidence-architect`），论文生成迁移至独立的 `paper-toolkit` plugin。
- **extension**：移除 legacy paper skill 注册条目；`ags.py` 中已无 paper 子命令入口。

### Fixed

- **agentsociety2**：后端路径解析增加 `..` / 空字节校验，消除 CodeQL 路径注入告警（`path_security.py`）。
- **agentsociety2**：LLM Router 调试日志不再经含 API Key 的配置对象传递，避免敏感信息日志泄露。
- **extension**：`.env` 写入时对 API Key 等值做完整转义（`\`、`"`、换行、`$` 等）。
- **extension**：升级 `tmp`、`qs` 传递依赖，修复 `npm audit --audit-level=high` 失败。
- **frontend**：升级 `fast-uri`、`fast-xml-builder`，并通过 `path-to-regexp` override 修复高危 npm 审计项。
- **deps**：根 `uv.lock` 升级 `urllib3`、`idna`、`pytest`（仍使用清华 tuna 镜像源）。
- **ci**：新增 CodeQL 配置，排除 `frontend/public/monaco-editor` 第三方 vendor 扫描误报。

## [2.5.1] - 2026-05-21

- **agentsociety2** `2.5.1` · **extension** `1.5.1` · 标签 `agentsociety2-v2.5.1`

本版本在 [2.4.1] 基础上交付**自适应 LLM 并发控制**、**Agent 技能与认知增强**、**CodeGenRouter 安全加固**及 VS Code 扩展多项体验改进；Python 安装：`pip install agentsociety2==2.5.1`。

### Added

- **agentsociety2**：自适应 LLM 并发控制，优化大规模智能体仿真吞吐量。
- **agentsociety2**：Agent 技能（agent-skill）重构改善；认知（cognition）模块增强情绪与意图状态管理。
- **agentsociety2**：mobility_space 模块在地图文件缺失时给出下载提示。
- **extension**：Claude Code 权限模式配置页面；移除 Stop hook。
- **extension**：HYPOTHESIS.md 与 EXPERIMENT.md 作为树节点固定展示。
- **extension**：工作区文件变更时强制 git 追踪。
- **docker**：运行时依赖新增 `python-dotenv`。

### Changed

- **agentsociety2**：时间上下文移至 prompt 末尾以提升缓存命中率。
- **ci**：配置变更时始终构建 Docker 镜像并运行完整 CI；无 Python 代码变更时跳过 lint/test。

### Fixed

- **docker**：统一 `python3` 路径，修复 apt 拉入不同版本后命令不可用的问题；确保 `python` 命令指向系统 Python。
- **extension**：autoCommit 因缺少 git identity 静默失败的问题。
- **agentsociety2**：mobility_space 缺少 `json` 和 `Path` 导入。
- **agentsociety2**：CodeGenRouter 沙箱加固与安全基准测试。

## [2.4.1] - 2026-05-20

- **agentsociety2** `2.4.1` · **extension** `1.4.1` · 标签 `agentsociety2-v2.4.1`

本版本在 [2.4.0] 基础上交付**分阶段分析 Harness**、**双语报告（MD + HTML）门禁**及扩展侧配套体验；Python 安装：`pip install agentsociety2==2.4.1`（或贵司私有源等价版本）。

#### 升级说明

- 若工作区仍存在 `presentation/hypothesis_*/analysis/`，执行 `ags.py analysis intake --workspace . --hypothesis-id <ID> --experiment-id <ID>` 可将 harness 状态迁移至 `.agentsociety/analysis/`。
- 报告插图仅使用 `assets/` 路径；作图后运行 `sync-report-assets` 或 `collect-assets`，再执行 `validate-release`。

### Added

#### 分析 Harness（`agentsociety2` + `agentsociety-analysis`）

- 假设分析五阶段流水线：`frame` → `explore` → `claims` → `refine` → `produce`；机器状态位于 `.agentsociety/analysis/hypothesis_{id}/`，与用户可见目录 `presentation/hypothesis_{id}/` 分离。
- 结构性校验与 LLM 阶段 attestation 双层门禁；`validate-<phase>`、`record-attestation`、`gate-status`；未通过前置阶段时后续阶段阻断。
- `refine`：`validate-refine`、`validate-chart`；`produce`：`validate-release`（四份报告必交）、`validate-report-quality`、独立 `record-report-review`。
- 工作区综合阶段：`validate-synthesis`、`synthesis_brief.json`、双语综合报告；支持 `synthesis/charts/` 与 `synthesis/assets/`。
- CLI：`intake`、`build-report-context`、`sync-report-assets`、`advance`、`run-loop` 等；技能脚本 `ags.py analysis` 与 harness 对齐。
- 报告 HTML 由 LLM 按 `assets/report-shell.reference.html` 原生撰写；`support/frontend-design` 随分析技能同步至工作区。
- 测试套件 `tests/test_analysis_harness.py`。

#### VS Code 扩展

- 分析阶段进度树与 Harness 状态查看器（`analysisHarnessStatusViewer`）。
- 假设 / 综合报告树固定展示 MD、HTML 中英四件套；缺失项标记「必交 · 未生成」。
- HTML 报告经 `aiSocialScientist.openHtmlReport` 打开 Live Preview（不可用则回退编辑器）。
- 产物目录：`分析数据`；`报告图表`（`assets/`）；`charts/` 仅在含脚本或未同步图片时显示，避免与 `assets/` 重复列举。

#### 后端与其它

- `path_security`：工作区路径解析与越界访问防护，接入 custom、experiments、prefill_params、replay 等路由。
- `env_benchmark`：`CodeGenRouter` 统一 `code_format` 参数，便于对比各 env router。

### Changed

- **agentsociety-analysis**：技能文档重组为 `stages/`、`references/`（`harness-contract`、`html-export`、`report-embeddings` 等）、`subagent-prompts/`；禁止在 `presentation/` 下使用旧版 `analysis/` 布局。
- **extension**：Claude Code 配置迁入配置页「高级配置」；读写 `ANTHROPIC_AUTH_TOKEN` 与 `ANTHROPIC_BASE_URL`；第三方网关预设区分 **DeepSeek**（`https://api.deepseek.com/anthropic`）与 **火山方舟**（`https://ark.cn-beijing.volces.com/api/plan`）。
- **extension**：文献检索改为 MCP 调用；移除独立 Claude 配置 Webview 与冗余静态 HELP 页。
- **docs**：Walkthrough 中 API / Claude Code 说明与上述环境变量保持一致。

### Fixed

- **extension**：Claude Code 误用 `ANTHROPIC_API_KEY` 的问题。
- **agentsociety2**：CodeQL 静态分析问题；分析 harness 与后端相关 ruff 项。
- **extension / literature**：文献技能 lint 与 MCP 路径问题。

## [2.4.0] - 2026-05-19

- **agentsociety2** `2.4.0` · **extension** `1.4.0`

### Added

- **agentsociety2**：`CodeGenRouterV2`；Codex 技能符号链接；论文编排与分析图表能力增强；用户指南与中英文档补全。
- **extension**：AI Chat 多提供商集成；Claude Code 独立配置页（后续版本已并入高级配置）。
- **agentsociety2**：工作区引导与 `create-agent` / `create-env-module` 技能加固。

### Changed

- **agentsociety2**：Read the Docs 在 monorepo 下的构建配置与文档结构更新。
- **extension**：CSV 表格可视化；实验状态总览与步骤配置体验优化；项目树图标与右键菜单修正。

### Fixed

- **extension**：技能启动器工作区默认值；VS Code `when` 子句取反语法。
- **agentsociety2**：Agent 运行兜底，降低实验异常中断影响。
- **ci**：npm audit 阈值调整为 `high`，恢复流水线通过。

## [2.3.0] - 2026-05-08

- **agentsociety2** `2.3.0` · **extension** `1.2.0`

### Added

- **agentsociety2**：LaTeX 论文编排流水线（替代 EasyPaper）；PersonAgent 技能扩展；后端 API 与实验目录布局完善。
- **extension**：技能市场（GitHub 源）、Agent / Claude 技能分栏管理；前端 Skills 管理页。
- **agentsociety2**：Sphinx 文档站、技能文档与英文 locale；GitHub / GitLab CI 与扩展 CI 流水线。

### Changed

- **extension**：HTML 分析报告预览交互修复。
- **repo**：根目录说明、`.gitignore` 与 Docker 构建清理。

### Fixed

- **paper / literature**：技能与流水线若干缺陷修复。
- **ci**：MR 与主分支流水线稳定性改进。

## [2.2.0] - 2026-04-19

- **agentsociety2** `2.2.0` · **extension** `1.0.0`

### Added

- **extension**：技能市场；项目结构树增强；实验状态概览；环境 / 智能体预填充参数；中英国际化与用户向文案（详见 `extension/README.md`）。
- **agentsociety2**：对话历史持久化相关能力；社区文档（行为准则、贡献指南、安全策略）。

### Changed

- **agentsociety2**：自 `2.1.5` 对齐主分支能力后正式发版；安装示例：`pip install agentsociety2==2.2.0`。
- **extension**：技能管理界面重构。

### Fixed

- **extension**：分析报告展示问题。
- **agentsociety2**：速率限制与 JSON 工具类重复定义等 Agent 层问题。

## [2.1.5] - 2026-04-15

- **agentsociety2** `2.1.5` · **extension**（持续迭代，见同期 commit）

### Added

- **extension**：PID 状态可视化；文献路径复制与 @ 提及；数据集技能与树节点集成。
- **agentsociety2**：问卷与回复流增强；文献搜索 API 切换至新服务端点。
- **extension**：MinerU 相关能力调整为官方 Claude Office 技能方案。

### Changed

- **extension**：国际化与可视化查看器；构建配置与文档对齐。
- **ci**：发布流水线与 ruff 策略调整，保障发版通过。

### Fixed

- **ci**：MR 流水线仅做构建验证，避免多余 registry 登录。

## [2.1.0] - 2026-03-20

- **agentsociety2** `2.1.0`

### Added

- **agentsociety2**：分析 / 综合报告中英双语输出。
- **extension**：文献检索后端地址写入配置页。
- **extension**：文献库层级目录；树视图拖放导入 PDF / 文件。

### Changed

- **extension**：PDF 自动解析模式与状态栏开关。

### Fixed

- **agentsociety2**：实验启动流程；自定义模块测试脚本缩进与错误回传；`agent.init()` 调用方式。

## [2.0.2] - 2026-03-06

- **agentsociety2** `2.0.2`

### Added

- **extension**：项目树拖放与相关 i18n。
- **docs**：中英双语文档初版；PDF 自动解析。

### Fixed

- **extension**：预填充参数树图标；自定义模块集成测试错误字段。

## [2.0.1] - 2026-03-05

- **agentsociety2** `2.0.1`

### Added

- **docs**：自定义模块文档；Read the Docs 配置拆分（v1 / AgentSociety 2）。

### Changed

- **docs**：站点样式与导航（含 V2 Beta 入口）。

### Fixed

- **agentsociety2**：线程与重试相关边缘问题。
- **docs**：RTD 依赖路径与构建配置。

## [2.0.0] - 2026-03-05

- **agentsociety2** `2.0.0` · **extension** `0.0.1`（初始集成）

### Added

- **agentsociety2**：面向二次开发的自定义模块（Custom Agent / Env）扫描、生成与后端集成。
- **extension**：AI Social Scientist 工作区、项目树与实验工作流初版。

---

## AgentSociety 1.x 及更早版本

以下条目为 **AgentSociety 1.x**（及更早标签）的逐版本记录，与 2.x 包 `agentsociety2` 产品线分离。2.x 用户通常只需阅读上文 **2.0.0** 及以上章节。

## [1.4.0a0] - 2025-05-12

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Fixed
- N/A

## [1.3.7] - 2025-04-28

### Added
- N/A

### Changed
- Update wechat group QR code.

### Deprecated
- N/A

### Fixed
- N/A


## [1.3.6] - 2025-04-17

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Fixed
- Refactor chat history gathering to handle grouped data structure across multiple files, ensuring consistent data format for agent interactions.
- Fix the `from pyparsing import deque` error.


## [1.3.5] - 2025-04-14

### Added
- Add automatic monitoring of LLM requests, if a request is stuck for a long time, it will be logged.
    - To use this feature, you need to set `logging_level` to `DEBUG` in `AdvancedConfig`.

### Changed
- N/A

### Deprecated
- N/A

### Fixed
- Fix bug in survey dispatching.
- Fix bug in inconsistent schema when writing survey results to SQL.

## [1.3.4] - 2025-04-14

### Added
- Add docs for `reset` method in `Agent` and `Block`.

### Changed
- Return 404 rather than 200 for empty delete/update.
- Move webui config into database.

### Deprecated
- N/A

### Fixed
- Solve the problem of not being able to exit.
- Fix raising error when from memory.
- Enhance lock_decorator with exception logging for better error tracking.
- Fix bug in `NeedsBlock`.

## [1.3.3] - 2025-04-07

### Added
- Add `input_tokens` and `output_tokens` to experiment info.
- Add S3 storage support.
- Web API to export experiment data including agent profiles, agent statuses, agent dialogs, agent surveys, and global prompts.
- Add `NEXT_ROUND` step type, support multiple rounds of simulation.
- Add abstract method `reset` for `Agent` and implement it for all city agents.

### Changed
- Hide sensitive experiment information in AVRO and PostgreSQL storage.
- UI details.
- Removed `total_tick` in `EnvironmentConfig` - always 24 hours.
- Support float days in `RUN` step, for example, `RUN: 1.5 days`.

### Deprecated
- `Tool` abstract class.

### Fixed
- Bug in avro saver.

## [1.3.2] - 2025-04-02

### Removed
- Remove useless files due to merge error

## [1.3.1] - 2025-04-02

### Changed
- Update Python version requirements and cibuildwheel skip list.

## [1.3.0] - 2025-04-02

See [Version 1.3](https://agentsociety.readthedocs.io/en/latest/02-version-1.3/01.v1.3.0.html) for more details.

## [1.2.10] - 2025-03-18

### Added
- N/A

### Changed
- Add retry for syncer connections.

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Fix typo in `simulator.sence`

### Security
- N/A

## [1.2.9] - 2025-03-14

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Fixed bug for `update_environment` in `AgentGroup`.
- Bug for calling sequence of `agent.step` and `OnlyClientSidecar.step`.

### Security
- N/A

## [1.2.8] - 2025-03-14

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Fixed bug for `PlaceSelectionBlock.forward` when selecting POI.
- Bug for `OnlyClientSidecar` calling

### Security
- N/A

## [1.2.7] - 2025-03-14

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Fixed bug for `PlaceSelectionBlock.forward` when selecting POI.

### Security
- N/A

## [1.2.6] - 2025-03-12

### Added
- N/A

### Changed
- WeChat QR code.

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A
  
## [1.2.5] - 2025-03-07

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Removed
- Remove `Agent._uuid`

### Fixed
- Fixed bug for `simulation.init_agents` when creating group parameters for agents.

### Security
- N/A



## [1.2.4] - 2025-03-04

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Removed
- Remove `Agent._uuid`

### Fixed
- Fixed issue with `EconomyClient.update` when handling InstitutionAgent updates.
- Fixed bug for `MobilityBlock.MoveBlock.forward`.
- Added adjustment logic to ensure the sum of the returned employee counts exactly equals N in matching firms and employees.

### Security
- N/A


## [1.2.3] - 2025-03-03

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Fix typo in quick start docs.

### Security
- N/A



## [1.2.2] - 2025-03-02

### Added
- N/A

### Changed
- Change the download URL for `agentsociety-sim` to a publicly accessible address that does not require authentication in `setup.py`.

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Missed match between the dictionary and `economyv2.Firm` as input arguments in the `EconomyClient.update` method.

### Security
- N/A



## [1.2.1] - 2025-03-01

### Added
- Add docker compose for china user (use huawei cloud docker registry)

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Definition bug of `EconomyEntityType`

### Security
- N/A


## [1.2.0] - 2025-02-28

### Added
- N/A

### Changed
- Update `pycityproto` version to v2.2.8, splitting organization into bank, firm, government and statistical bureau.
- Adapt `environment.economy` to align with the new definitions of economic entities.

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A

## [1.1.5] - 2025-02-28

### Added
- N/A

### Changed
- Update doc at `05-custom-agents`.
- Add more comments in agentsociety.cityagent

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A



## [1.1.4] - 2025-02-27

### Added
- Add log of original LLM response during handling LLM calling error.

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A

## [1.1.3] - 2025-02-27

### Added
- N/A

### Changed
- The WeChat group chat QR code has been replaced to the second group. Welcome to join and participate in the discussions.

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Add retry for `syncer` server connecting, providing enough time for start.

### Security
- N/A


## [1.1.2] - 2025-02-26

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Calling `syncer` that didn't have time to start causes the gRPC service to report an error.

### Security
- N/A

## [1.1.1] - 2025-02-25

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Inconsistency of python 3.12 and current pydantic version. 

### Security
- N/A


## [1.1.0] - 2025-02-21

### Added
- N/A

### Changed
- The simulator has been converted to a synchronous mode, controlled by `ExpConfig.SimulatorConfig.steps_per_simulation_step` and `ExpConfig.SimulatorConfig.steps_per_simulation_day` parameters that determine the number of seconds per step for advancing the urban environment time in each simulation step and day.

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A

## [1.0.13] - 2025-02-21

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Removed
- Delete `enable_institution` in ExpConfig

### Fixed
- N/A

### Security
- N/A

## [1.0.12] - 2025-02-21

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Document typo on `agentsociety-ui` activation.

### Security
- N/A

## [1.0.11] - 2025-02-21

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Bug of inconsistent length of `agent_counts` and `agent_class` in `simulation.init_agents`.

### Security
- N/A

## [1.0.10] - 2024-02-21

### Added
- N/A

### Changed
- Example map data download link in the document.

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A

## [1.0.9] - 2024-02-20

### Added
- WeChat group QR code.

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A
  
## [1.0.8] - 2024-02-19

### Added
- N/A

### Changed
- Detailed document.

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A
 
## [1.0.7] - 2024-02-18

### Added
- N/A

### Changed
- Update agentsociety-ui to version v0.3.3.

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A
  
## [1.0.6] - 2024-02-18

### Added
- N/A

### Changed
- Detailed document.

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A
  
## [1.0.5] - 2024-02-15

### Added
- N/A

### Changed
- Set parent_id and lnglat of InstitutionAgent as NULL for pgsql

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A

## [1.0.4] - 2024-02-14

### Added
- N/A

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- Bug of incorrect experiment uid for MLflow tag.

### Security
- N/A

## [1.0.3] - 2024-02-13

### Added
- Social experiment use case document.

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- 

### Security
- N/A

## [1.0.2] - 2024-02-08

### Added
- Social experiment use case with our platform.

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A

## [1.0.1] - 2024-02-07

### Added
- Add `README.md`

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A

## [1.0.0] - 2024-02-06

### Added
- Initial commit.

### Changed
- N/A

### Deprecated
- N/A

### Removed
- N/A

### Fixed
- N/A

### Security
- N/A

[Unreleased]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.11.0...HEAD
[2.11.0]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.10.1...agentsociety2-v2.11.0
[2.10.1]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.10.0...agentsociety2-v2.10.1
[2.10.0]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.9.3...agentsociety2-v2.10.0
[2.9.3]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.9.2...agentsociety2-v2.9.3
[2.9.2]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.9.1...agentsociety2-v2.9.2
[2.9.1]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.9.0...agentsociety2-v2.9.1
[2.9.0]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.8.7...agentsociety2-v2.9.0
[2.8.7]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.8.6...agentsociety2-v2.8.7
[2.8.6]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.8.5...agentsociety2-v2.8.6
[2.8.3]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.8.2...agentsociety2-v2.8.3
[2.8.1]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.8.0...agentsociety2-v2.8.1
[2.8.0]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.7.0...agentsociety2-v2.8.0
[2.6.1]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.6.0...agentsociety2-v2.6.1
[2.5.4]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.5.3...agentsociety2-v2.5.4
[2.5.3]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.5.2...agentsociety2-v2.5.3
[2.5.2]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.5.1...agentsociety2-v2.5.2
[2.5.1]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.5.0...agentsociety2-v2.5.1
[2.4.1]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.4.0...agentsociety2-v2.4.1
[2.4.0]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.3.0...agentsociety2-v2.4.0
[2.3.0]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.2.0...agentsociety2-v2.3.0
[2.2.0]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.1.5...agentsociety2-v2.2.0
[2.1.5]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.1.4...agentsociety2-v2.1.5
[2.1.0]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.0.2...agentsociety2-v2.1.0
[2.0.2]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.0.1...agentsociety2-v2.0.2
[2.0.1]: https://github.com/tsinghua-fib-lab/AgentSociety/compare/agentsociety2-v2.0.0...agentsociety2-v2.0.1
[2.0.0]: https://github.com/tsinghua-fib-lab/AgentSociety/releases/tag/agentsociety2-v2.0.0
