"""面向 Swagger / ReDoc 的说明元数据，不改变路由或请求校验。"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

API_DESCRIPTION = """
AgentSociety 2 研究工作区的 HTTP 接口，供 AI Social Scientist 扩展和集成客户端使用。

### 开始使用

1. 调用 `GET /health` 确认后端可用。
2. 在 **modules** 分组查询可用的智能体类和环境模块。
3. 访问实验或回放时，填写后端可访问的工作区**绝对路径** `workspace_path`，以及假设和实验编号。
4. 回放查询先列出 `datasets`，再使用返回的 `dataset_id` 获取字段与记录。

### 工作区和操作

`workspace_path` 受后端 `WORKSPACE_PATH` 配置约束。示例中的 `/path/to/workspace` 需替换为实际路径。
查询实验与回放使用 GET；技能导入、创建、上传及模块扫描、清理等 POST 操作会改变工作区文件或模块注册状态。
Swagger 中展开接口后使用 **Try it out → Execute** 发送真实请求。ReDoc 用于连续阅读接口和模型。

### 响应与错误

成功响应的字段、分页与默认值见各接口的 Responses 和 Schemas。
参数缺失或类型不符通常返回 `422`；不合法的路径或标识符、访问范围限制、资源不存在和服务异常分别查看实际响应中的 `detail` 或 `error`。
后端的模型 API Key 用于调用模型；远程部署的访问认证由部署环境提供。
""".strip()

OPENAPI_TAGS = [
    {
        "name": "service",
        "description": "服务信息与健康检查。首次连接时先调用 `/health`。",
    },
    {
        "name": "modules",
        "description": "智能体类与环境模块目录。返回可用于实验配置的类名、说明及构造参数；`include_custom` 控制是否包含已发现的自定义模块。",
    },
    {
        "name": "prefill-params",
        "description": "读取工作区预填充参数，支持查看全部配置或指定智能体／环境模块的参数。",
    },
    {
        "name": "custom",
        "description": "扫描、测试和管理 `custom/agents/`、`custom/envs/` 中的自定义类。扫描与重新扫描更新模块注册状态，测试可能执行自定义代码，清理会删除对应配置。",
    },
    {
        "name": "agent-skills",
        "description": "管理仿真参与者的行为技能：列出、扫描、导入、创建、上传和查看内容。技能被发现后，由智能体在运行时按需激活；研究助手使用的文献、假设等研究技能通过扩展同步。",
    },
    {
        "name": "experiments",
        "description": "读取假设下某次实验的状态、Markdown 产物与运行日志。`hypothesis_id` 和 `experiment_id` 填编号，例如 `1`，工作区根目录通过 `workspace_path` 指定。",
    },
    {
        "name": "replay",
        "description": "读取实验回放：概览 → 数据集目录 → 字段与分页记录。也可按仿真步查询位置、智能体状态及环境状态，用于构建回放与分析界面。",
    },
]

SWAGGER_UI_PARAMETERS = {
    "docExpansion": "none",
    "filter": True,
    "displayRequestDuration": True,
    "defaultModelsExpandDepth": 0,
}

# 按 HTTP 方法和完整路径维护，避免同名 Python 函数在不同路由中相互覆盖。
_OPERATION_DOCS = {
    ("get", "/"): ("查看服务信息", "返回服务名称、版本、状态和主要接口入口。"),
    ("get", "/health"): (
        "检查服务健康状态",
        "返回 `status: healthy` 表示 HTTP 服务可用；此检查不调用模型，也不验证模型凭据。",
    ),
    ("get", "/api/v1/modules/agent_classes"): (
        "列出智能体类",
        "返回已注册智能体类的名称、说明、参数信息与来源，供实验配置选择。",
    ),
    ("get", "/api/v1/modules/env_module_classes"): (
        "列出环境模块类",
        "返回已注册环境模块类的名称、说明、参数信息与来源，供环境配置选择。",
    ),
    ("get", "/api/v1/modules/all"): (
        "列出智能体与环境模块",
        "一次获取智能体类和环境模块类目录，以及各自的数量。",
    ),
    ("get", "/api/v1/prefill-params"): (
        "读取全部预填充参数",
        "读取工作区中智能体与环境模块的预填充参数。配置文件缺失时返回空配置结构。",
    ),
    ("get", "/api/v1/prefill-params/{class_kind}/{class_name}"): (
        "读取指定类的预填充参数",
        "按 `class_kind` 和 `class_name` 读取参数。先从 modules 分组取得类名；未配置的类返回空参数字典。",
    ),
    ("get", "/api/v1/experiments/{hypothesis_id}/{experiment_id}/info"): (
        "查看实验状态",
        "返回实验状态、起止时间、智能体数量与已执行步数。状态读取运行目录中的记录，统计信息在存在 replay 时从回放读取。",
    ),
    ("get", "/api/v1/experiments/{hypothesis_id}/{experiment_id}/artifacts"): (
        "列出实验 Markdown 产物",
        "列出运行产生的 Markdown 文件及其元信息，再使用产物读取接口获取内容。",
    ),
    (
        "get",
        "/api/v1/experiments/{hypothesis_id}/{experiment_id}/artifacts/{artifact_name}",
    ): (
        "读取 Markdown 产物",
        "按产物列表返回的文件名读取 UTF-8 内容。文件名应为当前实验允许访问的 Markdown 产物。",
    ),
    ("get", "/api/v1/experiments/{hypothesis_id}/{experiment_id}/log"): (
        "读取运行日志末尾",
        "返回 `text/plain` 日志。`tail` 限制返回行数；`source=auto` 自动选择日志，也可指定 `output.log` 或 `stderr.log`。",
    ),
    ("get", "/api/v1/replay/{hypothesis_id}/{experiment_id}/info"): (
        "查看回放概览",
        "返回回放中的步数、时间范围、智能体数量与数据集统计；运行状态可从实验记录补充。",
    ),
    ("get", "/api/v1/replay/{hypothesis_id}/{experiment_id}/datasets"): (
        "列出回放数据集",
        "返回数据集目录，包括 `dataset_id`、列定义与能力标记。后续查询使用这里返回的标识，不必猜测表名。",
    ),
    ("get", "/api/v1/replay/{hypothesis_id}/{experiment_id}/datasets/{dataset_id}"): (
        "查看数据集定义",
        "读取指定数据集的列、实体字段、时间字段及查询能力。",
    ),
    (
        "get",
        "/api/v1/replay/{hypothesis_id}/{experiment_id}/datasets/{dataset_id}/rows",
    ): (
        "分页查询数据集记录",
        "按页读取记录，可按步数、实体、时间步区间和列名过滤。`latest_per_entity=true` 用于保留各实体的最新记录；排序字段应来自数据集列定义。",
    ),
    ("get", "/api/v1/replay/{hypothesis_id}/{experiment_id}/panel-schema"): (
        "查看回放面板定义",
        "返回可用于智能体状态和环境状态面板的数据集定义与字段信息。",
    ),
    ("get", "/api/v1/replay/{hypothesis_id}/{experiment_id}/steps/{step}/bundle"): (
        "读取单步回放数据",
        "汇总指定步的位置、智能体状态和环境状态，供回放界面一起展示。`step` 使用回放中的实际步号。",
    ),
    ("get", "/api/v1/replay/{hypothesis_id}/{experiment_id}/timeline"): (
        "读取仿真时间线",
        "返回仿真步与时间的对应关系，用于定位和切换回放时刻。",
    ),
    ("get", "/api/v1/replay/{hypothesis_id}/{experiment_id}/agents/profiles"): (
        "读取智能体画像",
        "返回回放中记录的智能体标识、名称与画像信息，用于实体列表和详情展示。",
    ),
    ("post", "/api/v1/custom/scan"): (
        "扫描自定义模块",
        "扫描工作区 `custom/agents/` 与 `custom/envs/`，跳过 examples 子目录，并将可用类注册到内存。返回发现数量、注册数量和诊断信息。",
    ),
    ("post", "/api/v1/custom/clean"): (
        "清理自定义模块配置",
        "删除标记为 `is_custom=true` 的模块 JSON 配置。操作会修改工作区，执行前确认目标路径。",
    ),
    ("post", "/api/v1/custom/test"): (
        "测试自定义模块",
        "扫描并测试全部模块，或通过 `module_kind` 与 `module_class_name` 选择目标。返回各模块的检查结果、输出与错误信息。测试会加载或执行自定义模块。",
    ),
    ("get", "/api/v1/custom/list"): (
        "列出已注册自定义模块",
        "读取内存注册表中的自定义智能体与环境模块，以及各自的数量。",
    ),
    ("get", "/api/v1/custom/status"): (
        "查看自定义模块目录状态",
        "检查配置工作区中的自定义目录、Python 文件数量与已注册模块数量。工作区由后端配置提供。",
    ),
    ("get", "/api/v1/custom/classes"): (
        "查看可用类与预填充状态",
        "返回智能体与环境模块目录，并标记各类是否已有预填充参数。",
    ),
    ("post", "/api/v1/custom/rescan"): (
        "重新扫描并注册自定义模块",
        "清除内存中的旧自定义模块后重新扫描指定工作区，返回扫描详情与注册结果。",
    ),
    ("get", "/api/v1/agent-skills/list"): (
        "列出已发现的行为技能",
        "返回内置、自定义和环境技能的标识、来源、目录与脚本信息。目录可见表示技能已被发现，实际激活由智能体运行时决定。",
    ),
    ("post", "/api/v1/agent-skills/scan"): (
        "扫描工作区行为技能",
        "扫描工作区 `custom/skills/` 中的技能目录，返回新发现的技能标识和目录总数。",
    ),
    ("post", "/api/v1/agent-skills/import"): (
        "从目录导入行为技能",
        "将工作区范围内的技能目录复制到 `custom/skills/`。同名目标目录存在时会被替换。",
    ),
    ("post", "/api/v1/agent-skills/create"): (
        "创建自定义行为技能",
        "在 `custom/skills/{name}/` 创建 `SKILL.md`，并按需生成脚本文件。名称作为目录名；纯提示技能可将脚本路径留空。同名技能已存在时返回错误。",
    ),
    ("post", "/api/v1/agent-skills/upload"): (
        "上传 ZIP 行为技能",
        "使用 `multipart/form-data` 上传 ZIP 文件。压缩包应包含一个顶层技能目录及 `SKILL.md`；内容写入工作区的自定义技能目录。",
    ),
    ("get", "/api/v1/agent-skills/{skill_id}/info"): (
        "查看技能内容与元数据",
        "使用技能列表返回的 `skill_id`，例如 `built-in@daily-guidance`，读取元数据与 `SKILL.md` 正文。",
    ),
}

_PARAMETER_DOCS = {
    "workspace_path": (
        "后端可访问的研究工作区绝对路径，受 WORKSPACE_PATH 限制。",
        "/path/to/workspace",
    ),
    "hypothesis_id": ("假设编号，与工作区 hypothesis_<编号> 目录对应。", "1"),
    "experiment_id": ("该假设下的实验编号，与 experiment_<编号> 目录对应。", "1"),
    "include_custom": ("是否包含已发现的自定义智能体和环境模块。", False),
    "class_kind": ("类的类别：agent 为智能体，env_module 为环境模块。", "agent"),
    "class_name": ("modules 接口返回的类名。", "PersonAgent"),
    "artifact_name": ("产物列表接口返回的 Markdown 文件名。", "report.md"),
    "dataset_id": ("数据集目录接口返回的 dataset_id。", "core.agent_profile"),
    "skill_id": ("技能列表返回的完整标识，包含命名空间。", "built-in@daily-guidance"),
    "step": ("需要读取或筛选的实际仿真步号。", 1),
    "entity_id": ("需要筛选的实体编号，含义由数据集的 entity_key 决定。", 1),
    "page": ("页码，从 1 开始。", 1),
    "page_size": ("每页记录数；允许范围见下方约束。", 20),
    "order_by": ("排序列名，使用数据集定义中的字段。", "step"),
    "desc_order": ("是否按排序列降序排列。", False),
    "start_step": ("起始仿真步，包含该步。", 0),
    "end_step": ("结束仿真步，包含该步。", 10),
    "max_step": ("读取记录的最大仿真步，包含该步。", 10),
    "columns": ("需要返回的列名白名单，用英文逗号分隔。", "step,agent_id"),
    "latest_per_entity": ("是否只返回每个实体的最新记录。", False),
    "tail": ("最多返回的日志末尾行数。", 100),
    "source": ("日志来源：auto 自动选择，也可指定 output.log 或 stderr.log。", "auto"),
}

_FIELD_DOCS = {
    "workspace_path": "工作区绝对路径；留空时使用后端的工作区配置。",
    "source_path": "待导入技能目录的绝对路径，必须位于允许的工作区内。",
    "module_kind": "可选的模块类别：agent 或 env_module，与 module_class_name 配合使用。",
    "module_class_name": "指定测试的类名；与 module_kind 配合使用。",
    "name": "名称；创建技能时也作为目标目录名。",
    "description": "面向使用者或智能体的简短说明。",
    "script": "技能脚本相对路径，例如 scripts/main.py；留空表示不创建脚本。",
    "body": "SKILL.md 的 Markdown 正文，不含 YAML frontmatter。",
    "script_content": "脚本文件内容，指定 script 时使用。",
    "file": "技能 ZIP 文件，包含顶层技能目录与 SKILL.md。",
    "detail": "请求参数的校验错误列表，包含字段位置与原因。",
    "success": "操作是否成功。",
    "message": "操作结果说明。",
    "error": "错误信息；为空时以其他结果字段为准。",
    "errors": "扫描、注册或测试产生的错误列表。",
    "skill_id": "包含命名空间的技能标识，例如 built-in@daily-guidance。",
    "namespace": "技能命名空间，例如 built-in、custom 或 env:<模块名>。",
    "source": "技能或数据的来源类别。",
    "source_label": "来源的显示名称。",
    "path": "后端文件系统中的路径。",
    "has_skill_md": "目录内是否存在 SKILL.md。",
    "new_skills": "此次扫描新发现的技能标识。",
    "total": "结果总数。",
    "skills": "已发现的行为技能列表。",
    "hypothesis_id": "假设编号。",
    "experiment_id": "假设下的实验编号。",
    "agent_count": "回放或实验中记录的智能体数量。",
    "step_count": "已记录或执行的仿真步数。",
    "total_steps": "回放记录中的总步数。",
    "start_time": "记录中的开始时间；没有记录时可能为空。",
    "end_time": "记录中的结束时间；没有记录时可能为空。",
    "dataset_id": "数据集的稳定标识，用于后续查询。",
    "columns": "数据列信息；元素结构见字段类型定义。",
    "datasets": "回放数据集目录。",
    "rows": "当前查询返回的数据记录。",
    "page": "当前页码，从 1 开始。",
    "page_size": "每页记录数。",
    "total_pages": "可用的总页数。",
}


def _describe_schema(schema: dict[str, Any]) -> None:
    """仅补充显示说明，保留模型的字段、默认值和校验约束。"""
    for field, definition in schema.get("properties", {}).items():
        if field in _FIELD_DOCS:
            definition["description"] = _FIELD_DOCS[field]


def _describe_openapi(schema: dict[str, Any]) -> None:
    for path, operations in schema["paths"].items():
        for method, operation in operations.items():
            details = _OPERATION_DOCS.get((method, path))
            if not details:
                continue
            operation["summary"], operation["description"] = details
            if path in {"/", "/health"}:
                operation["tags"] = ["service"]
            for parameter in operation.get("parameters", []):
                if parameter["name"] in _PARAMETER_DOCS:
                    description, example = _PARAMETER_DOCS[parameter["name"]]
                    parameter.update(description=description, example=example)
            if path == "/health":
                operation["responses"]["200"]["content"]["application/json"][
                    "example"
                ] = {"status": "healthy"}
            for status, response in operation.get("responses", {}).items():
                if status == "200":
                    response["description"] = details[0] + "的结果。"
                elif status == "422":
                    response["description"] = (
                        "请求参数未通过校验；detail 中包含字段位置与原因。"
                    )
    for definition in schema.get("components", {}).get("schemas", {}).values():
        _describe_schema(definition)


def install_api_documentation(app: FastAPI) -> None:
    """在原生 OpenAPI 生成与缓存上附加文档，不修改路由和依赖解析。"""
    original_openapi = app.openapi

    def documented_openapi() -> dict[str, Any]:
        if app.openapi_schema is None:
            schema = original_openapi()
            _describe_openapi(schema)
        return app.openapi_schema

    app.openapi = documented_openapi
