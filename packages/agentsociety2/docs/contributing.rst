为 AgentSociety 2 贡献
===============================

问题报告应尽量让维护者能复现；改文档时，请同时说明适用版本、实际操作入口与验证方式。

本页提供贡献入口；安装、检查与构建命令统一维护在 :doc:`development`，完整 PR 与发布约定见仓库的 `CONTRIBUTING.md <https://github.com/tsinghua-fib-lab/agentsociety/blob/main/CONTRIBUTING.md>`_。

报告错误
--------------

报告错误时，请包括：

* Python 版本
* AgentSociety 2 版本
* 最小的可重现示例
* 预期行为与实际行为
* 任何错误消息或回溯

提交更改
--------------

修改应说明具体问题、预期行为与验证结果。行为变更补充相应测试，文档和界面变更同步检查示例、翻译与图片引用。

* 新增环境或智能体：参阅 :doc:`custom_modules`。
* 新增智能体技能：参阅 :doc:`skill_guide`。
* 运行测试、检查与构建文档：参阅 :doc:`development`。
* 公开 Python 接口应提供文档字符串，说明参数、返回值、异常与必要的使用条件。同一模块保持一种格式；现有 reST 字段与 NumPy 风格都可由文档构建解析。

格式参考 `PEP 257 <https://peps.python.org/pep-0257/>`_ 与 `NumPy 文档字符串指南 <https://numpydoc.readthedocs.io/en/latest/format.html>`_。函数名、参数名与示例必须与代码一致，说明文字随文档语言提供翻译。

许可证
-------

通过贡献 AgentSociety 2，您同意您的贡献将根据 Apache License 2.0 获得许可。
