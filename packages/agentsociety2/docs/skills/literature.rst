文献检索与假设
==============

.. _skills-literature-3:

学术文献检索
~~~~~~~~~~~~

``agentsociety-literature-search`` 通过统一的远程检索服务收集学术文献，并把结果保存到工作区 ``papers/`` 目录。默认检索所有已配置数据源：``local``、``arxiv``、``crossref``、``openalex``。

配置项：

.. code-block:: bash

   LITERATURE_SEARCH_MCP_URL=https://llmapi.fiblab.net/mcp/
   LITERATURE_SEARCH_API_KEY=your-literature-search-key

搜索命令示例：

.. code-block:: bash

   python .agentsociety/bin/ags.py literature-search "agent-based modeling social networks"
   python .agentsociety/bin/ags.py literature-search "urban mobility simulation LLM agents" --year-from 2020 --year-to 2026 --multi-query

输出约定：

- ``papers/literature_index.json`` 是稳定索引，记录标题、作者、年份、来源、query、分数和本地 ``file_path``。
- 每篇文献保存为 ``papers/<title>_<timestamp>.md``，这是后续 hypothesis、analysis 与外部 ``paper-toolkit`` 写作流程引用的主要本地笔记。
- 检索完成后会自动尝试下载开放获取 PDF 到 ``papers/full_texts/``，路径写入 ``extra_fields.full_text.file_path``；不要把索引中的 ``file_path`` 从 Markdown 笔记替换成 PDF。
- 文献检索不会自动绕过出版商权限。PDF 下载只处理开放获取或用户授权的文件；没有开放 PDF 时，可以补充本地 Markdown 笔记并记录来源。

.. _skills-literature-5:

文献技能 (literature)
~~~~~~~~~~~~~~~~~~~~~

文献技能通过 **MCP 协议** 连接学术文献检索网关，使用工作区 ``.env`` 中的
``LITERATURE_SEARCH_MCP_URL`` 和 ``LITERATURE_SEARCH_API_KEY``（无需单独配置
Claude ``mcp.json``）。网关上的其他 MCP 工具不会被文献技能调用。推荐优先使用
``search_literature_and_save``，而不是直接调用底层 ``search_literature``：前者会把检索结果落到工作区中，确保后续 Agent、Claude Code 和论文写作技能都能通过本地文件继续引用这些文献。

.. code-block:: python

   from pathlib import Path
   from agentsociety2.skills.literature import search_literature_and_save, load_literature_index

   # 搜索并保存文献（默认 10 篇、已配置数据源，并更新 papers/literature_index.json）
   result = await search_literature_and_save(
       workspace_path=Path("./workspace"),
       query="agent-based modeling social networks",
       year_from=2020,      # 可选：年份筛选
       year_to=2024,
       enable_multi_query=True,  # 可选：启用多查询模式
   )

   # 指定数据源搜索
   await search_literature_and_save(
       workspace_path=Path("./workspace"),
       query="machine learning",
       sources=["local", "arxiv"],  # 可选：指定数据源
   )

   # 加载文献索引
   index = load_literature_index(workspace_path=Path("./workspace"))

**保存结果**:

- 每篇检索结果都会保存为 ``papers/<title>_<timestamp>.md``。这个 Markdown 文件是稳定的本地文献笔记，包含标题、检索词、年份、期刊、
  DOI/URL、摘要、作者和相关内容片段。
- ``papers/literature_index.json`` 会同步更新。索引中的 ``file_path``
  指向本地 Markdown 文献笔记，因此插件中的 ``@引用`` 可以复制为
  ``@papers/<title>_<timestamp>.md``，供 Claude Code 或 Agent 读取。
- 重复运行检索时会生成新的本地文献笔记，并追加到索引中，便于保留不同检索轮次的上下文。

**原文下载（由 Claude/Agent 按需执行）**:

``search_literature_and_save`` 默认会尝试下载开放获取的原文，可用 ``download_full_text=False`` 关闭；下载失败不会把元数据笔记替换成错误文件。检索结果会尽量保留
``doi``、``url``、``pdf_url``、``full_text_url``、``download_url``、
``open_access``、``best_oa_location`` 等元信息；Claude Code 或 Agent
可以基于这些线索按需下载开放获取原文。

建议的下载约定：

- 原文 PDF 放在 ``papers/full_texts/*.pdf``。
- 优先使用 API 返回的 PDF 直链；arXiv 论文可从 ``/abs/<id>`` 转为
  ``https://arxiv.org/pdf/<id>.pdf``。
- DOI 仅作为落地页线索，不保证能直接得到 PDF；如果需要下载，应确认最终响应确实是 PDF。
- 下载完成后，可在对应索引条目的 ``extra_fields["full_text"]`` 中记录:

  .. code-block:: json

     {
       "status": "downloaded",
       "file_path": "papers/full_texts/example.pdf",
       "source_url": "https://arxiv.org/pdf/2401.01234.pdf"
     }

  如果没有找到开放原文，也可以记录 ``{"status": "no_candidate"}`` 或
  ``{"status": "failed", "reason": "..."}``，便于插件页面显示状态。

.. note::

   许多 CrossRef/OpenAlex 结果只提供 DOI 或落地页，不一定有开放 PDF。
   Claude/Agent 不应绕过出版商权限，也不应把 HTML 落地页当作 PDF 保存。

**数据源**:
- ``local``: RAGFlow 本地知识库
- ``arxiv``: arXiv 预印本平台
- ``crossref``: CrossRef DOI 元数据库
- ``openalex``: OpenAlex 学术图谱

**配置**:
在 workspace ``.env`` 中配置 MCP（无需 Claude ``mcp.json``，除非要让 Claude 独立连接同一网关）:

.. code-block:: bash

   LITERATURE_SEARCH_MCP_URL=https://llmapi.fiblab.net/mcp/
   LITERATURE_SEARCH_API_KEY=your-literature-search-key

.. _skills-literature-4:

假设技能 (hypothesis)
~~~~~~~~~~~~~~~~~~~~~

.. figure:: /_static/images/hypothesis_workflow.svg
   :alt: 从文献证据到可检验假设
   :width: 90%
   :align: center
   :class: doc-figure

   从文献证据到可检验假设

检索文献后整理依据，生成假设并写入 ``HYPOTHESIS.md``，再进入实验设计。

.. code-block:: python

   from pathlib import Path
   from agentsociety2.skills.hypothesis import add_hypothesis, get_hypothesis, list_hypotheses

   # 添加假设
   add_hypothesis(
       workspace_path=Path("./workspace"),
       hypothesis="网络密度越高，信息传播速度越快"
   )

   # 列出假设
   hypotheses = list_hypotheses(workspace_path=Path("./workspace"))
