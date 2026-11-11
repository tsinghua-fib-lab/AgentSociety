## 初始化研究项目

**请先在配置页保存仿真 LLM 设置**（API Key 会写入 `.env`）。侧栏在检测到密钥后才会显示「初始化工作区」。

开始前需要一个研究工作区文件夹。

### 新建工作目录

若还没有项目目录，先新建空文件夹再用 VS Code / code-server 打开：

![新建工作目录](../images/gif/create-project-folder.gif)

### 初始化项目结构

1. 在配置页保存仿真 LLM 的 API 地址、密钥与模型。
2. 点击侧边栏“初始化工作区”，或运行命令 **AI Social Scientist: Initialize Research Project**。
3. 输入研究话题，等待初始化完成；已有研究文件会保留。
4. 在 `TOPIC.md` 补充研究背景，再按需启动后端。配置细节见[配置 LLM 与后端](05-configure.md)。

想看连续操作，可查看[工作区初始化动图](https://github.com/tsinghua-fib-lab/agentsociety/blob/main/extension/resources/readme/research-workspace.gif)；客户端标签变化时以上方步骤为准。

插件会创建基础目录结构，并写入 `TOPIC.md`、`.env` 模板等相关文件：

```text
workspace-root/
├── TOPIC.md
├── .env
├── papers/
├── datasets/
├── user_data/
├── custom/
├── .claude/skills/
├── .agentsociety/       # 项目设置与工作流状态
├── hypothesis_<id>/     # 后续由工作流创建
├── presentation/        # 分析报告与资源，由后续分析流程生成
├── synthesis/           # 跨假设综合结果，由后续综合流程生成
└── paper/               # 使用 paper-toolkit 时创建
```

也可直接打开已有研究工作区，插件会识别目录结构。

### 命令面板

命令面板搜索 **AI Social Scientist: Initialize Research Project** 也可触发初始化。

- `Ctrl+Shift+P`（Mac: `Cmd+Shift+P`）
- 输入 `AI Social Scientist` 查看插件命令

[初始化项目](command:aiSocialScientist.initProject)
