# AgentSociety 2 文档指南

AgentSociety 2 的 ReadTheDocs 站点使用 **Sphinx + Furo + MyST** 构建。文档源文以中文编写，英文翻译通过 Sphinx i18n 维护；线上默认语言与翻译站点关联由 ReadTheDocs 项目设置控制。

本仓库有多套 ReadTheDocs 站点。仓库根目录的 `.readthedocs.yaml` 保留给 `packages/agentsociety/docs/` 旧版文档；AgentSociety 2 的独立配置放在 `packages/agentsociety2/.readthedocs.yaml`，构建入口为 `packages/agentsociety2/docs/conf.py`。在 ReadTheDocs 的 AgentSociety 2 项目设置中，应把 config file 指向这份包内配置，避免影响旧站点。

## 文档结构

```text
packages/agentsociety2/docs/
├── conf.py              # Sphinx 配置文件
├── index.rst            # 主文档入口（中文源文）
├── locale/              # 国际化翻译文件
│   ├── en/              # 英文翻译
│       └── LC_MESSAGES/
│           ├── index.po
│           └── ...
├── _static/             # 静态资源（图片、CSS等）
├── _templates/          # Sphinx 模板
├── _build/              # 构建输出目录
├── requirements.txt     # Python 依赖
├── agents.rst           # Agent / PersonAgent / create-agent 技能说明
├── agent_skills.rst     # PersonAgent skills-first 架构
├── skills.rst           # 研究技能、实验/分析/文献检索工作流
├── skill_guide.md       # 编写 Agent 行为技能
├── research_workflow.rst # 从研究问题到实验与报告
├── datasets.rst         # 输入数据、数据集使用与打包
├── results.rst          # 回放、分析阶段与产物核对
├── user_guide/          # 工作台指南的任务子页面
├── docutils.conf        # 中文内联标记的解析配置
├── api/                 # Python SDK 参考与 HTTP API 使用说明
└── ...
```

## 支持的语言

- **中文（zh）**: 文档源文语言（`.rst` 源文件以中文编写）
- **英文（en）**: 翻译语言（`locale/en/LC_MESSAGES/` 下的 `.po` 文件）

本地配置默认使用中文；`make html-en` 构建英文翻译，未翻译的内容会回退为中文源文。线上站点 `agentsociety2.readthedocs.io` 的默认语言和语言路径，以 ReadTheDocs 项目设置中的语言与翻译关联为准。

## 文档编写工作流

### 1. 编写新文档

所有新文档应该用中文编写，使用 reStructuredText (.rst) 或 Markdown (.md) 格式：

```bash
# 在 v2 文档目录下创建新文档
packages/agentsociety2/docs/new-feature.rst
```

### 2. 提取翻译文本

中文段落按自然语义组织，避免在词语中间手动断行。`docutils.conf` 已启用中文字符级内联解析，加粗与行内代码可紧接中文标点；不要将行内代码嵌入加粗标记。标识符、路径和环境变量用行内代码，示例保留为代码块。修改后还需检查生成页面是否出现原样显示的星号或反引号。

较长的功能指南使用概览页与任务子页面，保留已有锚点的跳转。新增正文和 API docstring 后同步英文翻译；HTTP 入口与使用说明放在 `api/http.rst`，具体请求结构由运行中后端的 Swagger/OpenAPI 自动提供。

在编写或修改文档后，运行以下命令提取需要翻译的文本：

```bash
# 推荐在 v2 文档目录执行
cd packages/agentsociety2/docs
make gettext
```

这会在 `packages/agentsociety2/docs/_build/gettext/` 目录下生成 `.pot` 文件。

### 3. 更新翻译文件

更新或创建翻译文件：

```bash
cd packages/agentsociety2/docs
make update-po
```

这会在 `packages/agentsociety2/docs/locale/en/LC_MESSAGES/` 目录下创建或更新 `.po` 文件。

### 4. 翻译文档

编辑 `.po` 文件进行翻译：

```bash
# 编辑英文翻译
vim packages/agentsociety2/docs/locale/en/LC_MESSAGES/index.po
```

示例 `.po` 文件内容：

```po
# Chinese translations for AgentSociety project.
msgid ""
msgstr ""
"Project-Id-Version: AgentSociety 2 2.3.0\n"
"Language: en\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"

#: ../../index.rst:4
msgid "AgentSociety 2"
msgstr "AgentSociety 2"

#: ../../index.rst:6
msgid "**AgentSociety 2** 是一个现代化的、LLM 原生的智能体模拟平台..."
msgstr "**AgentSociety 2** is a modern, LLM-native agent simulation platform..."
```

注：`Project-Id-Version` 等头部字段由 sphinx-intl 按 `conf.py` 从 `pyproject.toml` 读取的版本号自动生成，无需手工同步。

### 5. 构建文档

构建不同语言版本的文档：

```bash
cd packages/agentsociety2/docs

# 构建中文文档（默认）
make html
# 或
make html-zh

# 构建英文文档
make html-en

# 构建所有语言版本
make html-all
```

构建的文档将保存在：
- 中文版本：`packages/agentsociety2/docs/_build/html/zh/`
- 英文版本：`packages/agentsociety2/docs/_build/html/en/`

## Makefile 命令说明

| 命令 | 描述 |
|------|------|
| `make help` | 显示帮助信息 |
| `make gettext` | 提取可翻译的文本 |
| `make update-po` | 更新翻译文件 |
| `make build-po` | 编译翻译文件 |
| `make html` | 构建中文文档（默认） |
| `make html-zh` | 构建中文文档 |
| `make html-en` | 构建英文文档 |
| `make html-all` | 构建所有语言版本 |
| `make clean` | 清理构建文件 |

## ReadTheDocs 配置

项目已配置为在 ReadTheDocs 上构建 AgentSociety 2 文档：

1. **AS2 项目**：使用 `packages/agentsociety2/.readthedocs.yaml`；不要修改供 v1 使用的根目录配置。
2. **构建语言**：由 Read the Docs 项目语言与构建命令决定。本地 `conf.py` 默认中文，英文构建使用 `-D language=en`。
3. **发布版本**：在 Read the Docs 项目中确认构建分支或标签；本地预览成功不会自动更新线上站点。

`packages/agentsociety2/.readthedocs.yaml` 的完整内容（路径相对仓库根目录）：

```yaml
# Paths are relative to the repository root (monorepo).
version: 2

build:
  os: ubuntu-22.04
  tools:
    python: "3.12"
  apt_packages:
    - graphviz

python:
  install:
    - requirements: packages/agentsociety2/docs/requirements.txt
    - method: pip
      path: packages/agentsociety2
      extra_requirements:
        - docs

sphinx:
  configuration: packages/agentsociety2/docs/conf.py
  fail_on_warning: true
```

### ReadTheDocs 多语言设置步骤

每种语言对应独立的 Read the Docs 项目，再把翻译项目关联到主项目的 **Translations**。这些语言可以通过主站同一域名的语言路径访问，不需要给用户分发不同子域名。

1. 在主项目与翻译项目中分别设置正确的语言、仓库及 AS2 配置文件路径。
2. 将翻译项目关联到主项目，确认目标版本均已成功构建。
3. 检查站点语言菜单与对应语言路径；仅在仓库增加 `.po` 不会创建线上翻译项目。

具体设置见 [Read the Docs 多语言文档](https://docs.readthedocs.com/platform/stable/localization.html)；Sphinx 翻译步骤见[官方维护指南](https://docs.readthedocs.com/platform/stable/guides/manage-translations-sphinx.html)。

### 发布前核对

在仓库根目录执行（Python 环境需安装文档依赖）：

```bash
make clean-docs
make html-zh SPHINXOPTS="-n -W --keep-going"
make html-en SPHINXOPTS="-n -W --keep-going"
node extension/scripts/check-doc-assets.mjs --html-root packages/agentsociety2/docs/_build/html
```

GitHub 的 `Documentation CI` 从官方 PyPI 按冻结锁文件安装依赖，分别严格构建中英文并上传预览产物；Read the Docs 也启用 `fail_on_warning`。修改主题时，请检查浅色、深色以及系统自动模式、键盘焦点和窄屏表格滚动。主题样式位于 `_static/custom.css`；`_static/docs-ui.js` 维护中英文控件名称、手机导航键盘操作，以及溢出表格和代码块的焦点。

浏览器交互回归在本地开发时运行，使用 `frontend` 的 `npm run test:docs`，可通过 `npm ci --workspace tests/docs --include-workspace-root=false` 只安装测试所需依赖，并与前端共用锁文件。它默认读取仓库根目录的 `docs-preview/{zh,en}`，也可以通过 `DOCS_PREVIEW_URL` 指向已启动、包含 `/zh/` 与 `/en/` 的本地预览地址。测试覆盖实际中英文搜索、手机导航、卡片点击与主题记忆；`npm run test:e2e` 继续只运行仪表盘测试。

中文构建参数 `zh` 会使用标准 `zh_CN` 语言目录，包含搜索进度、结果等浏览器端提示的中文翻译。中文搜索依赖 `jieba` 和 `search-terms.dict` 中的领域词；新增较长的中文功能名称时，可在词典中补充，并检查搜索结果。Python 3.12 及以上使用已修复中文词干器引用的 Sphinx 9.1.1，Python 3.11 保留兼容的 8.2 系列。

先清理文档输出，避免旧图片或源码页残留。`--html-root` 除检查源文档配图外，还检查实际生成页面的本地链接与章节锚点，包括 API 的源码链接；不传该参数时只检查源文档资源。

新增页面要加入 `index.rst` 的导航并补齐英文翻译；修改技能或产物目录时，同时核对用户指南、相关专题和 API 入口。预览时检查桌面与窄屏、明暗主题、图片加载及章节链接。截图沿用原始有效素材，论文中的设计说明不能替代对当前代码行为的核对。

## 文档编写规范

- 文件使用小写名称和连字符；一个页面只有一个主标题，较长指南按任务拆分。
- 图片放在 `_static/`，使用相对路径、替代文本和简短图注；论文图附来源与许可。
- 标识符、路径、环境变量使用行内代码。中文段落避免词中断行，代码与加粗不嵌套。
- 跨页面链接使用 Sphinx 的 `doc` / `ref` 角色，让严格构建检查目标；链接显示文字随页面语言翻译。
- 公开 API 由 docstring 生成，参数名与行为应和代码一致。复杂字段说明放在所属模块页，入门页保留可运行的最短示例。
- `code-block` 表示示例片段；完整、确定性且无需模型的示例使用 `testcode` / `testoutput`，并运行 doctest。

reST 页面使用 `:doc:`，MyST 页面使用 `{doc}`，例如：

````markdown
# 页面标题

参见 {doc}`agent_skills` 与 {doc}`api/skills`。

```{note}
说明使用条件，避免重复整页操作步骤。
```
````

完整语法见 [MyST 文档](https://myst-parser.readthedocs.io/en/latest/syntax/typography.html) 与 [Sphinx reStructuredText 入门](https://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html)。本站的组件、双语检查与后台设置见下方对应章节。

## 常见问题

### 1. 翻译文件更新问题

如果翻译文件没有正确更新，尝试：

```bash
cd packages/agentsociety2/docs
make clean
make gettext
make update-po
```

### 2. 构建错误

检查文档语法：

```bash
cd packages/agentsociety2/docs
sphinx-build -b dummy . _build/dummy
```

### 3. 图片显示问题

确保图片路径正确且文件存在：

```bash
ls packages/agentsociety2/docs/_static/
```

## 文档质量检查

GitHub 的 `Documentation CI` 在相关 PR 和 main/develop 更新时执行，并支持手动运行；GitLab 的 `documentation` 在相关合并请求、main/develop 更新和 AS2 发布标签上执行。两处使用 `make ci-docs-build` 检查中英文严格构建、gettext 翻译完整度、英文页面文本（包括示例注释和可访问性标签）、本地链接与资源，以及明确标记的离线示例，并保留可下载的双语构建产物。搜索、手机导航、主题和复制按钮的浏览器交互检查放在本地开发阶段，使用 `make ci-docs-browser` 执行；普通流水线和标签发布流程均不下载或运行浏览器。

在仓库根目录安装 docs 依赖后，可复现核心检查：

```bash
uv sync --frozen --package agentsociety2 --extra docs
make ci-docs-build
cd frontend && npm ci && npx playwright install chromium
cd ..
make ci-docs-browser
```

英文目录中每条活动消息都应有明确且非 fuzzy 的翻译，包含本身就是英文的消息。启用了 `gettext_additional_targets = ["literal-block"]`，因此代码示例的中文注释、目录树说明与示例自然语言也需翻译；保留命令、字段名和参数语义。原始源码查看器 `_modules/` 保持源码原文，检查脚本有意排除它；原有插件截图也保留实际界面内容。

用 `testcode` / `testoutput` 维护无需模型的完整示例，测试代码直接取自文档正文。普通 `code-block` 可以是说明片段，不会被冒充为已执行示例。当前离线检查覆盖配置校验与临时目录中的 Replay 读写；完整 Ray/LLM 仿真需要单独的受控验证。

`docs-ci.yml` 的 `maintenance` 任务每周及手动执行外链 `linkcheck` 与 API 文档覆盖报告，上传 `docs-reports/`。外链失败会让该维护任务失败，但不依赖普通 PR 的即时网络检查。覆盖报告说明哪些公开对象尚未进入文档，不代表单元测试覆盖率，也不作为整个仓库的强制百分比门槛。

## 组件与页面约定

继续使用 Furo、MyST、autodoc、Napoleon 与 Graphviz。`sphinx-design` 提供响应式入口卡片与 FAQ 折叠面板；`sphinx-copybutton` 仅为适合复制的代码块添加按钮，排除控制台提示符和输出。无需为现有 Graphviz 图额外引入 Mermaid，也不迁移到 autodoc2。参考 [Sphinx Design](https://sphinx-design.readthedocs.io/en/latest/)、[Copybutton](https://sphinx-copybutton.readthedocs.io/en/latest/use.html)、[Doctest](https://www.sphinx-doc.org/en/master/usage/extensions/doctest.html)。

常见问题应说明现象、原因和处理方法，并链接到详细配置，避免只写“重试”。配图用于解释角色或操作，保持原始插件截图；论文图保留出处与原许可，不将论文设计图当作当前界面截图。

智能体、环境、运行时技能和研究技能采用“概览页 + 任务子页”：入口分别是 `agents.rst`、`env_modules.rst`、`agent_skills.rst` 和 `skills.rst`，详细内容放在同名目录。概览页只解释职责和阅读顺序，避免复制子页的长示例。移动章节时保留公开的 `:ref:` 标签；旧页面的片段链接由 `.guide-redirects` 中的映射转向对应子页，调整后在本地验证旧链接跳转。新增示例能离线执行时，使用 `testcode` / `testoutput` 直接测试正文中的代码。

会进入 autodoc 的模块 docstring 应说明模块职责，引用 Python 对象使用 `:mod:`、`:class:` 等 Sphinx 角色，链接用户指南使用 `:doc:`。编辑器专用的 `@packages/...` 标记不是文档链接，不应放进公开 API 说明。HTTP 方法、路径和参数由 OpenAPI / Swagger 维护，避免在多个模块头部复制接口清单。中文 docstring 的英文输出通过翻译目录维护，并由语言检查器验证。

Swagger `/docs` 与 ReDoc `/redoc` 共用后端生成的 `/openapi.json`。其 Markdown 简介、分组、接口摘要、参数示例与字段说明集中在 `packages/agentsociety2/agentsociety2/backend/api_documentation.py`，与 Sphinx 的 reStructuredText docstring 分开维护，避免在 Swagger 中显示 `:param:` 等标记。新增接口后同步补充对应说明；`tests/test_backend_openapi.py` 检查接口说明覆盖、反向代理路径，以及参数、模型和响应的原生结构未被说明层改变。这些测试随两处 SDK CI 自动执行。

Swagger 页面外观由 `backend/docs_ui.py` 和 `backend/static/api-docs.css`、`api-docs.js` 维护，继续复用 FastAPI 的 Swagger 初始化与原生请求控件。页面资源通过 `/docs-assets/` 提供，不进入业务接口目录；反向代理前缀同时用于资源、ReDoc、OpenAPI 和 OAuth 回调链接。发布前检查 wheel 与源码包是否包含这两个静态文件，并在深浅色、手机宽度下验证分组跳转、筛选和只读请求。ReDoc 保持阅读视图，两处展示同一份接口定义。

## 示例与维护工具

`literalinclude` 直接展示仓库中的脚本，避免复制后与实现脱节。`storage.rst` 引用并提供下载的 `examples/offline/replay_round_trip.py` 在文档构建中直接运行，SDK pytest 另检查产物与无模型凭据执行；需要模型的基础示例只引用真实代码片段，不在普通 CI 中访问模型。

严格构建前仅清理双语输出中的 `_modules/` 源码查看页，使其根据当前公开成员重新生成；其他输出继续复用，避免 Sphinx 的时间戳缓存留下失效锚点。输出目录校验保护语言目录及符号链接目标；清理逻辑的故障验证在本地完成。

根目录 `make docs-live` 使用已有的 sphinx-autobuild，在 `127.0.0.1:8000` 提供中文实时预览。可用 `DOCS_LANGUAGE=en`、`DOCS_PORT=8002`、`AS2_DOCS_OUTPUT=...` 修改语言、端口和输出目录。`make update-po` / sphinx-intl 更新翻译后，严格检查会拒绝缺失、fuzzy 和未使用的活动消息；不允许直接把中文原文当作英文翻译。

Ruff 的文档规则先约束公开的 `ReplayReader`：检查类与方法文档是否缺失、段落和引号格式是否规范，具体规则见 `make ci-python-lint`。继续保留中文 reST 字段和现有 NumPy 风格，不使用只适合英文标点的规则批量改写注释。后续扩展规则范围时，先补有用的说明，再增加检查。

现有独立文档 CI、sphinx-design、copybutton、doctest、linkcheck、Graphviz 与 git-cliff 继续复用。当前引用数量和教程形态无需引入 BibTeX、Notebook、Gallery 或第二套变更日志工具；需要这些能力时，再用实际内容评估维护成本。

## Read the Docs 后台设置

仓库中的 YAML 控制构建，不能证明托管后台的 PR 预览、版本激活或访问统计已启用。发布前在 AS2 项目后台逐项确认：

| 设置 | 位置与建议 |
| --- | --- |
| PR 预览 | Settings → Pull request builds；启用并用真实 PR 验证状态回报与预览链接。GitHub CI 的预览附件可独立使用。 |
| 版本 | Versions；`latest` 跟踪维护分支，`stable` 指向最新正式发布，保留需要支持的 `agentsociety2-vX.Y.Z` 标签。不要把 main 的文档当作所有旧版本的说明。 |
| 中英文 | 将英文翻译项目关联到主项目；确认语言路径、默认语言与搜索行为。 |
| 旧链接 | Redirects；跨版本目录重构使用平台重定向。当前工作台旧锚点由站点自身保留。 |
| 访问与搜索 | 按账号支持的功能查看 404、搜索词和阅读页面，作为后续调整依据。 |

平台是否启用以上选项应以后台实际状态为准。操作说明见 [PR Preview](https://docs.readthedocs.com/platform/stable/pull-requests.html) 与 [版本管理](https://docs.readthedocs.com/platform/stable/versions.html)。

2026-11-10 只读核查：公开项目 API 显示 `agentsociety2` 的语言为 `en`，默认版本为 `latest`、默认分支为 `main`，配置入口为 `packages/agentsociety2/docs/.readthedocs.yaml`。仓库保留此兼容入口并与包级配置保持严格构建一致。`stable` 已激活但 API 标记为未构建，正式版本仍需在后台确认与完成构建。公开字段未提供 PR 构建是否启用的开关，不能从 `external_builds_privacy_level=public` 推断已经启用；本次未修改托管设置。

同次公开核查确认，中文翻译项目 `agentsociety2-zhcn` 已关联主项目，语言为 `zh-cn`。中英文项目的版本构建状态仍应分别检查；关联存在不代表每个版本均已成功构建。
