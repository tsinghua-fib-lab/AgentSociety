---
name: agentsociety-maintain
description: 在 AgentSociety 仓库执行维护巡检。用于审查 GitHub 机器人 PR、Dependabot 或 CodeQL 告警，在本地维护分支修复并验证，按改动完成镜像实测、性能对照及提交整理。
---

# AgentSociety 维护巡检

从仓库根目录执行。范围见 [AGENTS.md](../../../AGENTS.md)，两端 CI、镜像与发布流程见 [CI 维护说明](../../../scripts/ci/README.md)。

## 先建本地分支

用 `git status -sb`、`git branch -vv` 确认工作区和本轮基线，记录基线 SHA。从 `develop` 创建本地维护分支，例如 `git switch -c fix/replay-pagination develop`。保留基线已有的本地提交。当前目录有其他任务的修改时，用独立 worktree。若本轮已在专用分支，继续使用它。

GitHub 是镜像，GitLab 是主仓库。机器人 PR 用作审查输入，**禁止直接合并**。推送、发起 MR、关闭 PR、处置线上告警或发布镜像均按维护者对本轮的授权执行。

## 逐项判读

从仓库根目录运行只读查询：

```bash
bash .agents/skills/agentsociety-maintain/scripts/github-inbox.sh
```

- 对机器人 PR，查看 `gh pr diff NUMBER --repo tsinghua-fib-lab/AgentSociety`，比较目标分支、清单、锁文件和当前实现。镜像上还开着的修复可能已在本地完成。分析实际依赖路径、版本范围、Python 标记、可选 extra 和兼容风险。
- 对 CodeQL，按规则 ID、分析 ref、文件与行号定位到本地对应 revision，检查调用路径、输入来源与已有校验。区分代码告警与扫描作业自身的失败。修复后用相同语言和仓库查询配置重扫，核对 SARIF 中对应规则和位置。离线或缺少 GitHub 权限时，可读取提供的 PR diff、SARIF、CI 日志，并注明尚未取得的结果。
- 每项给出处置和依据，例如“修复”“本地已覆盖”“不适用”“暂缓及原因”。将有价值的改动移植到本地分支。需要改安装门槛或公共接口时，说明受影响用户和迁移路径。

## 修复、文档和依赖

- Python 对外接口及语义复杂处用中文 docstring 说明契约。采用 **Sphinx/reStructuredText 信息字段列表**，用 `:param name:`、`:returns:`、`:raises ErrorType:` 记录单位、边界、返回值或异常条件；已有类型注解提供字段类型。同步受影响的 HTTP/OpenAPI、Sphinx 页面及英文译文。
- Python 直接依赖在 SDK 的 `pyproject.toml` 维护，从仓库根目录运行 `uv lock`。单包升级用 `uv lock --upgrade-package NAME`，检查传递依赖和所有受支持解释器的分支，再运行 `uv lock --check`。文档依赖还要核对 Read the Docs 的 `docs/requirements.txt`。扩展和前端分别在对应目录用 `npm ci` 验证锁文件。
- 先跑覆盖故障的最小行为用例，再执行受影响栈的检查。完整本地验收为 `make check`，文档变更加 `make ci-docs-build`。CodeQL 使用 `scripts/ci/codeql.py` 和仓库固定的 bundle。修复失败后重跑对应检查。保留能捕获真实回归的测试；一次性采样脚本、答卷、日志放在临时工作区。

## 服务和工作区排查

- **服务不可达或变慢。** 从部署配置或 `docker port CONTAINER` 确认实际端口。分别从容器内和用户的代理入口请求 `/health`，记录状态码和耗时，再用同一凭据查询出问题的业务接口。检查进程、最近日志、磁盘及内存占用；报告中隐去令牌和工作区原始数据。
- **任务卡住或产物缺失。** 对齐工作区、假设、实验和 run ID，核对模拟进程与 `run/pid.json`、`run/stderr.log`、`run/replay/_schema.json`、`run/artifacts/`。恢复或复跑使用独立目录，保留原始失败现场。插件问题同时记录已安装 VSIX 版本、后端地址、浏览器代理路径和实际点击结果。
- **容器里的 Ray worker 注册超时。** 对照容器 CPU 配额与 SDK 默认读取的宿主机逻辑核数。若预算过大，在临时容器按实际配额设置 `AGENTSOCIETY_LLM_RAY_MAX_WORKERS`（例如 2 核设为 `2`）并复跑。Ray 会话目录需要运行用户可写，必要时用 `RAY_TMPDIR` 指向可写的临时目录。
- **需要切换服务。** 记下当前镜像 ID、版本和持久化挂载，在临时容器复核修复。共享环境的重启、替换和回退由本轮授权决定；操作后通过同一入口复测健康和业务请求。

## 镜像和小实验

涉及运行时、依赖、Dockerfile 或扩展交付时，若本机有构建环境，用候选代码构建带本地标签的镜像。记录候选提交或工作树差异、镜像 ID。以下命令验证镜像内的依赖和回放读写：

```bash
image="agentsociety-maintenance:$(git rev-parse --short HEAD)"
bash scripts/build_docker.sh --tag "$image"
docker run --rm "$image" uv pip check --system
docker run --rm \
  -v "$PWD/packages/agentsociety2/examples/offline/replay_round_trip.py:/tmp/check_replay.py:ro" \
  "$image" python /tmp/check_replay.py
```

镜像缺包时修正清单、锁文件或构建层，重建后用新容器重试。真实仿真使用独立的可写工作区，通过工作区启动器的 `run-experiment start/status` 或 `python -m agentsociety2.society.cli` 运行。选能覆盖改动的最小配置，例如 2–4 个智能体、一两步。即使智能体本身可以离线作答，环境路由初始化时也可能调用模型生成世界描述。使用测试环境提供的模型连接和凭据，核对终态、实际模型调用、回放和产物条数。涉及 UI 时在目标 Coder 代理实际点开相关节点。没有镜像环境或模型凭据时，完成可执行的检查，列清未验证项。

## 性能、提交与交付

性能改动在同机、同依赖、同数据与并发设置下交替测基线和候选。先核对输出相等，再记录输入规模、预热次数、采样数、P50/P95、吞吐量和退化场景。区分 HTTP 往返、页面就绪和模型执行。把关键数据和复测条件写进 `perf(scope): ...` 的提交正文。

按可独立复核的改动拆分 Conventional Commits。标题描述行为，正文写明原因、验证命令和结果，必要时注明告警编号。更新 [CHANGELOG.md](../../../CHANGELOG.md) 的 `Unreleased`，性能变化放在 `Changed`，兼容性变化附迁移方法。交付时报告分支、提交、检查结果、实测范围和遗留项；需要 MR 时沿用 [贡献指南](../../../CONTRIBUTING.md)。

## 从 develop 验证后合入 main

1. 在维护分支通过本地测试并复核 diff 后，将已验证的提交并入本地 `develop`。若整合时解决了冲突，在合并结果上重跑受影响的检查。仅授权本地提交时，在此交付 `develop` 的提交 SHA。
2. `develop` 专用于线上打包测试。推送后核对该 SHA 对应的 GitLab 流水线；涉及镜像的变更还要确认测试镜像已发布，在 Coder 测试工作区使用该候选镜像验证受影响的功能。记录流水线和实测结果。
3. 线上验证通过后，从已验证的 `develop` 向 `main` 提 GitLab MR。若源分支有新提交，先完成新候选的验证，再合入 `main`。
