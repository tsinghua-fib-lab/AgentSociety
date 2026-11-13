# CI 与本地检查

GitLab 和 GitHub 共用根目录 Makefile 与 npm 脚本的检查入口。修改检查内容时优先修改这些目标；`make ci-config` 会检查两边是否漏调用必需步骤，以及 Node、CodeQL 版本与语言矩阵是否一致。

| 入口 | 检查内容 |
| --- | --- |
| `make ci-python-lint` | SDK 与 CI 脚本 Ruff、SDK 测试代码 mypy |
| `make ci-python-test` | 无需真实模型的 SDK 回归，排除 `network` 用例 |
| `make ci-extension` | 扩展 lint、测试、类型检查与构建 |
| `make ci-frontend` | 前端 lint、类型检查与生产构建 |
| `make check-frontend` | 本地前端 lint、构建与浏览器回归 |
| `make ci-docs-build` | 双语严格构建、翻译与英文页面、离线示例、本地资源与链接 |
| `make ci-docs-browser` | 本地中英文搜索、导航、复制、主题和关键布局的六项检查 |
| `make ci-release-check` | 标签发版前校验 SDK、运行时、锁文件、插件版本和 CHANGELOG；读取 `AS2_RELEASE_TAG` 或 `CI_COMMIT_TAG` |
| `make ci-package` | SDK 源码包与 wheel 构建、Twine 元数据校验 |

Python 环境默认使用根目录 `.venv`，可用 `AS2_PYTHON=/absolute/path/to/python` 指定已有环境。先按 CONTRIBUTING.md 安装对应依赖与浏览器。`make check` 组合执行配置、Python、扩展与前端检查；文档和分发包检查可单独运行。

## 流水线顺序

| 触发方式 | 执行流程 |
| --- | --- |
| 合并请求、main/develop 更新 | 根据路径选择 Python、插件、前端、文档与 CodeQL 检查 |
| Python 变更 | lint → 三版本测试和分发包构建并行 |
| 文档变更 | 中英文严格构建、翻译、链接与离线示例检查 |
| 镜像输入变更 | SDK 输入等待 Python 3.12，插件输入等待插件检查，镜像元数据直接构建；每次只选一个镜像构建入口 |
| main 镜像发布 | 先保存本次流水线的候选镜像，再等待所有已触发的相关检查通过，最后更新 `:v2`；发布入口共用资源组 |
| develop 镜像发布 | 复用相同构建和检查流程，通过后更新 `:v2-beta`，供 Coder 测试模板使用 |
| main 同步 GitHub | 前序阶段成功后同步 main；镜像发布与同步属于同一阶段 |
| 人工推送 `agentsociety2-vX.Y.Z` | 校验版本与变更日志，运行发布检查并创建 GitLab Release；同步标签后由 GitHub 打包、发布 PyPI 和 GitHub Release |

创建 MR 触发检查和构建；合并到 main 后，配置中的镜像发布与 GitHub 同步会自动执行。版本号与标签由维护者决定；推送发布标签会启动正式发版流程。

Coder 正式模板使用 `registry.fiblab.net/llmsim/agentsociety:v2`，测试模板使用 `registry.fiblab.net/llmsim/agentsociety:v2-beta`。镜像发布标签由 `DOCKER_RELEASE_TAG` 统一控制：默认值为 `v2`，develop 分支流水线通过 `workflow:rules:variables` 覆盖为 `v2-beta`。两条分支均先推送独立的 `pipeline-${CI_PIPELINE_ID}` 候选标签，通过检查后再发布对应的滚动标签和包含提交短 SHA、时间戳的版本标签；MR 只验证构建，不推送镜像。develop 不触发 GitHub 同步或正式 Release。

镜像仍按输入路径变化构建，仅修改 `.gitlab-ci.yml` 不会触发镜像构建；新建 develop 分支时，GitLab 的 `rules:changes` 会匹配并触发首次构建。测试镜像发布成功后，停止并重新启动 Coder 测试工作区，使新容器按 `image_pull_policy = "Always"` 使用当前镜像。

## 平台配置

| 配置 | 何时需要 | 配置位置 |
| --- | --- | --- |
| 普通 Runner 与带 `dind` 标签的 Docker 构建 Runner | 常规检查、镜像构建 | GitLab Runner；镜像构建任务需要能调用 Docker |
| 项目 Container Registry | 候选镜像、镜像缓存及 `:v2` / `:v2-beta` 发布 | GitLab 项目设置；`CI_REGISTRY_*` 使用平台内置凭据 |
| `GITHUB_DEPLOY_KEY` | main 和版本标签同步到 GitHub | GitLab CI/CD 变量，建议使用文件类型；对应 GitHub 仓库 Deploy key 需启用写权限 |
| main 与 `agentsociety2-v*` 的保护规则 | 限制正式发布入口、向发布任务提供 protected 变量 | GitLab 受保护分支与标签设置 |
| PyPI Trusted Publisher | 正式标签发版后发布 Python 包 | PyPI 配置 GitHub owner/repository、`agentsociety2-publish.yml`、环境 `pypi` |
| Read the Docs 项目、语言关联与 PR 预览 | 在线托管文档 | Read the Docs 项目后台，使用 AS2 的配置路径；仓库 CI 上传的预览产物可独立下载 |
| Runner 共享缓存 | 减少跨并发槽、跨 Runner 的冷下载 | Runner 管理员配置 S3/MinIO 等缓存后端 |
| 资源组 process mode | 需要严格按流水线先后发布镜像时 | GitLab Resource groups API；可选择 `oldest_first` 按旧到新执行 |
| registry cache `mode=max` | 跨构建器复用所有中间层时 | Docker Buildx/BuildKit 与镜像仓库；当前使用 inline cache |
| `CODEQL_BUNDLE_URL` | 需要固定的内网工具下载入口时 | GitLab CI/CD 变量，内容仍需匹配固定 SHA256 |

普通 MR 的功能测试使用占位凭据；PyPI OIDC 与 GitHub 自动提供的 `GITHUB_TOKEN` 用于对应发布任务。当前 VSIX 作为 Release 附件发布，未配置 Marketplace 自动上传。

## 依赖、缓存与调度

CI 固定 uv 0.13.6，与 Docker 使用同一版本。任务按用途安装依赖，避免同时加载根开发组中的 Jupyter 和文档工具：

```bash
# SDK lint / test
uv sync --frozen --package agentsociety2 --no-default-groups --extra dev
# 双语文档
uv sync --frozen --package agentsociety2 --no-default-groups --extra docs
```

uv 缓存按用途、Python 版本与锁文件分开，npm 下载单独缓存；仅缓存下载内容，环境仍按锁文件重新创建。npm 安装使用 `--prefer-offline --no-audit --fund=false`，安全审计保留独立步骤。

普通文档修改只触发文档相关任务；SDK 源码、示例和运行时 Skill 变化会触发相应检查。SDK 打包在 lint 后与测试并行，正式发布仍等待完整检查。仅需要等待检查结果的任务通过 `artifacts: false` 避免下载文档预览和测试报告。

镜像构建按变动范围只选择一条路径：SDK 变更等待 Python 3.12 测试，插件变更等待插件检查，镜像元数据变更直接构建。正式与测试镜像发布统一等待本次实际触发的 Python 全版本测试、前端、CodeQL、分发包及文档检查；因此混合变更也会等待相关检查完成。三个镜像发布入口共用一个 [resource group](https://docs.gitlab.com/ci/resource_groups/)，串行更新 main 的 `:v2` 与 develop 的 `:v2-beta` 标签。资源组默认不保证按流水线新旧排序；需要严格发布顺序时，应在 GitLab 设置相应 process mode。

Docker 使用锁文件内的本地 vsce；翻译文本位于 npm 依赖层之后。构建前登录镜像仓库，读取现有 `:v2` 缓存，构建时写入 inline cache 元数据。构建上下文排除独立构建的前端、SDK 文档与测试；APT、uv 和 npm 的 BuildKit 缓存分别复用下载。 Python 依赖安装位于 Node/Claude/Codex 文件复制之前，使 CLI 更新复用 Python 依赖层。

当前使用 inline 镜像缓存及构建器本地下载缓存。跨构建器完整复用多阶段中间层需要另行配置 [registry cache 的 max 模式](https://docs.docker.com/build/cache/backends/registry/)；APT、uv、npm 的缓存挂载也不会随最终镜像分发。

Runner 日志出现 `No URL provided` 表示没有配置共享缓存服务，任务会使用 Runner 本地缓存。不同主机或并发槽的本地缓存可能互不相通；管理员可按 [GitLab 缓存文档](https://docs.gitlab.com/ci/caching/) 配置对象存储或共享缓存目录。仓库里的缓存键负责分类，Runner 配置负责实际存储与共享。

单元测试使用占位凭据，不依赖 CI Secret 或付费模型。需要公网的测试单独执行 `pytest -m network`，不参与普通合并请求的确定性检查。Python 与 npm 沿用现有源配置；不要为对齐检查擅自更换镜像。

## 本地浏览器检查

浏览器交互回归在开发阶段完成，GitHub、GitLab 和标签发布任务均不下载或运行 Playwright 浏览器。`make check` 仍包含前端浏览器回归；修改文档交互后，先运行 `make ci-docs-build`，再运行 `make ci-docs-browser`。

只检查文档时，可安装轻量 workspace，与仪表盘共用 `frontend/package-lock.json`：

```bash
cd frontend
npm ci --workspace tests/docs --include-workspace-root=false --prefer-offline --no-audit --fund=false
npx --no-install playwright install --with-deps --only-shell chromium
npm run test:docs
```

前端检查使用完整的 `npm ci` 和 `make check-frontend`。浏览器安装只需在首次使用或升级 Playwright 后执行，也可通过 `PLAYWRIGHT_CHROMIUM_EXECUTABLE` 复用本机已有的 Chromium。文档测试覆盖中英文搜索、手机导航、复制与主题，套件总时限为两分钟。

HTML 与 doctest 继续复用按语言隔离的 Sphinx doctrees，缓存位于 `docs-gettext/.doctrees/{zh,en}`，不随网页预览产物上传。

## CodeQL

`codeql-bundle.json` 固定官方 Bundle 的版本、下载地址与 SHA256。GitHub CodeQL Action 读取该地址；GitLab 和本地通过 `codeql.py` 使用同一版本与 `.github/codeql/codeql-config.yml`，输出 SARIF 报告。GitHub 发布安全分析结果，GitLab 将 SARIF 保留为检查产物。

```bash
python scripts/ci/codeql.py --language all
```

GitLab 在一个任务中依次扫描三种语言，共用一次工具安装；Python 镜像通过清华 HTTPS APT 源补齐 [TypeScript 提取所需的 Node.js](https://docs.github.com/en/code-security/tutorials/customize-code-scanning/prepare-code-for-analysis#javascript-and-typescript)。下载共用 300 秒总预算（含重试、跳转和慢速传输），单次网络等待默认 30 秒，每个地址最多尝试两次。任务最多 20 分钟，脚本最多 17 分钟，为缓存和报告上传预留时间；超出下载预算会明确失败并保留下载进度，避免一直等到 Runner 杀死任务。

缓存仅保存压缩包和下载进度，失败时也保存，支持重试与续传。默认在官方发布地址与官方资产 API 之间重试，最终 SHA256 必须与清单一致。内网已有同一压缩包时可配置 `CODEQL_BUNDLE_URL`，或使用 `--bundle-url`；已有对应版本工具时可加 `--codeql /path/to/codeql`，避免重复下载。`--databases` 和 `--output` 可指定临时磁盘目录；默认线程数为 2、内存预算为 4096 MB。下载失败、版本不符或校验失败会使检查失败；`codeql-results/runner.log` 和 `status.json` 记录阶段及结果。

更新版本时同步修改清单的发布地址、API 资产 ID 与校验值，并在三个语言上重新验证。扫描保留 SDK、扩展、前端、CI 工具和维护中的工作流，旧包的运行时代码与发布工作流不加入 AS2 的扫描范围。

## 版本与发布说明

`release.py check` 在普通配置检查中验证组件版本和 AS2 CHANGELOG 格式；`make ci-release-check` 在两端发版时强制校验标签。`release.py notes --release --output release_notes.md` 只提取该版本已审阅的条目，并补齐使用到的引用链接。GitHub 和 GitLab 共同使用这份脚本，避免分别生成提交日志而出现说明差异。git-cliff 仅用于维护者起草内容，不在发布流水线中安装。

SDK 与插件分别使用语义化版本，当前发布流程仅支持稳定标签 `agentsociety2-vX.Y.Z`。不会自动决定版本号、创建标签或提交 CHANGELOG；维护者审阅版本及日期后，推送标签触发后续打包与发布。完整步骤与外部权限要求见根目录 CONTRIBUTING.md。

## CI 范围

日常 CI 保留 SDK 与插件回归、静态检查、构建、双语文档、资源检查、安全扫描和发版校验。前端和文档浏览器回归、全站屏宽矩阵、下载故障注入及检查器自身的测试在本地开发和维护排障时运行。定期外链和 API 覆盖报告合并在 `docs-ci.yml` 的计划任务中。

GitLab 的 Debian bookworm 容器共用清华 HTTPS 软件源设置，安装 Graphviz 与 CodeQL 的 Node.js；自定义源配置保持原样。npm 下载保存在 `.cache/npm`。Runner 缺少分布式缓存时会从空缓存开始，缓存缺失本身不影响检查逻辑。
