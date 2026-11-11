# 模块与参数管理

先查询当前环境中的真实模块，再配置参数；这页不列固定模块数量，避免安装版本不同导致照抄失败。

本页说明注册表、工作区自定义模块与预填充参数的关系。模块实现教程见 {doc}`custom_modules`，方法签名和返回结构以 {doc}`api/registry` 为准。

## 查询已注册模块

注册表延迟发现内置模块。先查询实际安装环境中的标识符，再用于配置；不依赖文档中固定的模块数量或示例清单。

```python
from agentsociety2.registry import get_registry

registry = get_registry()
for module_type, module_class in registry.list_env_modules():
    print(module_type, module_class.__name__)

for agent_type, agent_class in registry.list_agent_modules():
    print(agent_type, agent_class.__name__)
```

`get_module_info(module_type, kind)` 返回描述和构造参数；`kind` 为 `env_module` 或 `agent`。查询时使用上一步返回的标识符。

## 发现工作区自定义模块

```text
workspace-root/
├── custom/
│   ├── agents/
│   ├── envs/
│   └── skills/
└── .agentsociety/
    └── prefill_params.json
```

`custom/agents/` 和 `custom/envs/` 放置 Python 模块；`custom/skills/` 放置智能体技能，两者使用不同的注册表。

```python
from pathlib import Path
from agentsociety2.registry import get_registry, scan_and_register_custom_modules

workspace = Path("/path/to/research-workspace")
result = scan_and_register_custom_modules(workspace_path=workspace, registry=get_registry())
print(result)
```

检查返回的 `errors` 后再引用自定义类。类定义与最小实现见 {doc}`custom_modules`；技能目录见 {doc}`agent_skills`。

## 预填充参数

`.agentsociety/prefill_params.json` 保存工作区的可复用默认参数，基础结构如下：

```json
{
  "version": "1.0",
  "env_modules": {},
  "agents": {}
}
```

以注册表中的模块标识符为键添加默认参数。最终实验配置仍需符合实际构造函数和配置模型；预填充文件不会替代参数校验或自动改变已经生成的实验配置。

- 在工作台的参数查看器中检查和编辑预填充信息。
- 运行前核对 `init_config.json` 与 `steps.yaml`，配置模型见 {doc}`api/config`。
- 后端的类查询与预填充接口见 {doc}`api/backend`，运行中的请求字段以 `/docs` 为准。
