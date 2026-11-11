## 用 AI Social Scientist 启动研究

AI Chat 是协作入口，真正的研究过程发生在工作区产物和可执行实验中。AgentSociety² 将流程组织为七个可以检查和回退的阶段：

![AI Social Scientist 研究工作流](../images/ai-social-scientist-workflow.png)

*图：从研究范围界定、假设生成、实验设计和仿真配置，到运行、结果分析与论文草拟。原图来自 [AgentSociety 2 论文](https://arxiv.org/abs/2607.11895)。*

### 第一次任务

> 阅读 `TOPIC.md`，检查工作区目录和当前配置，列出还需要填写的项目，并告诉我从哪个入口操作。

### 打开 AI Chat

打开右侧 **Chat** 面板，选择 Agent / 模型并描述任务：

![开始对话](../images/gif/start-chat.gif)

也可以从侧边栏 **AI 对话**、标题栏聊天控件或命令面板进入：

[打开 AI Chat](command:aiSocialScientist.openChat)

### 分享给同事

研究告一段落后，可在侧边栏用 **导出工作区** 打包项目。研究问题、假设与实验、文献、数据、报告、项目设置和技能都会出现在选择列表中，已有的关键内容默认勾选；密钥、`.env`、虚拟环境、Git 历史以及本地 IDE 状态（`.cursor` / `.vscode`）不会导出。对方用 **导入工作区** 选择保存位置和新项目名，扩展会新建目录且不会覆盖已有项目。导入后需要自己填写模型密钥。

### 文献库小提示

侧边栏 **文献库** 可上传 PDF，或粘贴 DOI / arXiv ID 入库；扩展会尽量补全元数据。按主题批量检索仍通过文献技能 / MCP 完成。
