# 工作区导入导出设计

面向“把研究项目打包给别人，或在另一台机器恢复”的场景。目标是可验证、默认不泄露密钥、失败不留下半装工作区。

## 目标与非目标

**目标**

- 导出选中的研究内容（TOPIC、假设/实验、文献、数据、自定义模块、技能、项目设置）。
- 清单可机读，内容可用 SHA-256 校验。
- 导入前就知道包里有什么；导入失败不留残缺目录。
- 跨平台可用，不依赖 symlink 权限。

**非目标**

- 不做双向同步、增量合并或云存储。
- 不导出 `.env`、密钥、凭证、本机 IDE 状态。
- 不在导入时执行包内代码；技能只是文件，是否加载由 Claude Code 决定。

## 数据流

```text
导出：选择 roots → staging 复制/过滤 → 计算内容 hash → 写 manifest+SHARE.md → ZIP → 原子写入目标
导入：读取 ZIP 内 manifest → 选父目录/项目名 → 确认 → 同盘 staging 解压 → 校验 hash → 移除排除项 → rename 为项目目录
```

## 导出

### 选择与分层

- `core`：`TOPIC.md`、`papers/`、`paper/`、`hypothesis_*`、`presentation/`、`synthesis/`、`datasets/`、`user_data/`、`custom/`、`.agentsociety/`。
- `agent`：`CLAUDE.md`、`AGENTS.md`、`.claude/`。
- `optional`：工作区里其他未排除的顶层条目。
- `external`：`~/.claude/projects/<encoded>`、`~/.claude/history.jsonl`、`~/.codex/projects/<encoded>`，默认不勾选。

默认勾选 `core + agent`；缺少研究内容或项目技能时给出警告，而不是静默导出空壳。

### 内容哈希

`contentHash = sha256(sorted("relativePath\tsha256" lines))`，只覆盖实际文件，不覆盖目录和 `_agentsociety/export-manifest.json` / `_agentsociety/SHARE.md` 两个 sidecar。导入端重新计算同一算法并比对。

### 排除规则

- 目录：`.git`、`node_modules`、`.venv`、`__pycache__`、`.pytest_cache`、`.cursor`、`.vscode`、`agentsociety_data`、`mineru_output`。
- 文件：`.env*`、`.netrc`、`.npmrc`、`.pypirc`、`id_rsa`、`id_ed25519`、`*.pem`、`*.key`、`auth.json`、`credentials.json`、`secrets.json`、`easypaper_config.yaml`、`.DS_Store`、`*.pyc`。
- 导入端使用同一规则再过滤一次，不信任归档方声明。

### symlink

- 只接受解析后仍在允许根内的链接。
- 文件链接复制目标内容；目录链接递归复制。
- 用 realpath 祖先链和“链接目标不能是自身祖先”双重检查防循环。
- size / fileCount 统计与复制使用同一套规则，避免清单数字和实际内容不一致。

### 归档与限额

- 单文件 ≤ 4 GiB，解压总量 ≤ 8 GiB，条目 ≤ 100,000。
- 不按压缩比拒绝条目：真实 JSONL 日志可被压缩 1000× 以上，比值规则会误伤合法数据；绝对大小与条目数上限已覆盖 zip bomb 的主要风险。
- ZIP 先写同目录临时文件，再 rename 到用户选择的位置。

## 导入

1. **预检**：只读取 ZIP 内的 `_agentsociety/export-manifest.json`（≤ 1 MiB），校验 kind/generator/formatVersion/hash 格式/roots/notice。此阶段不解压。
2. **选择目标**：父目录 + 项目名；项目名按跨平台安全规则校验；目标必须不存在，导入不合并、不覆盖。
3. **同盘 staging**：在父目录创建 `.<name>.import-<pid>-<timestamp>/`，解压到 staging。
4. **一致性**：重新读取 staging 内 manifest，比对 `contentHash` 与 `workspaceName`，再对 staging 全量计算 hash；任一不一致即失败。
5. **过滤**：删除 `_agentsociety/` sidecar 与所有排除项；记录 skipped 路径到日志。
6. **原子落位**：`rename(staging, target)`。失败或取消时删除 staging，目标目录从不存在变成完整目录，不会出现半装状态。

## 安全边界

- 路径穿越：归档条目必须是相对路径，拒绝 `..`、绝对路径、盘符、空段；解压后再次用 `commonpath` 校验。
- 加密条目不支持；损坏 ZIP 在预检/解压阶段报错。
- 导入不执行脚本、不自动 `pip install`、不自动打开工作区（用户点“打开文件夹”才打开）。
- 分享包仍可能包含有版权的文献/数据；确认对话框展示版权与再分发提示。

## 性能

实测（macOS，Python 3.12）：

| 样本 | 结果 |
| --- | --- |
| 4 文件 / 56 B | 111 ms，hash 一致 |
| 201 文件 / 5.12 MB | manifest 预检 52 ms；ZIP 36,958 B；打包 87 ms，解包 95 ms，hash 一致 |

导入不再“解压到系统临时目录再复制一次”，而是同盘 staging + rename，正常路径只有一次解压写入。

## 已知限制

- 导出复制仍是同步 I/O，超大工作区会占用扩展宿主；后续可改异步流式复制。
- ZIP 解压由 Python 子进程完成，依赖工作区/扩展解析到的 Python；解析失败会明确报错，不再静默回退 PATH 解释器。
- 清单未做数字签名；完整性依赖随包 hash，能发现损坏/篡改，但不能证明来源。
