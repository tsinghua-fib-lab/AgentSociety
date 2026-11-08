"""run 级提示词 override 测试(Phase 2.2 脚手架)。

核心契约:
- 文件缺失/畸形 → 提示词与编译期默认**逐字节一致**(默认关闭即零影响)
- override 生效 → 全 agent 一致地替换(run 级,前缀缓存共享不破)
- 合并 prompt override → 实际进入 LLM dispatch 的 system 内容
- 加载器 fail-safe:非对象 JSON/文件不可读 → 空 dict
"""

import json

import pytest

from agentsociety2.agent.memory import MemoryConsolidationConfig
from agentsociety2.agent.memory_runtime import (
    MEMORY_CONSOLIDATION_SYSTEM_PROMPT,
    MemoryRuntimeConfig,
    PersonMemoryRuntime,
)
from agentsociety2.agent.person_prompt import (
    PROMPT_OVERRIDES_FILENAME,
    build_base_rules,
    build_react_messages,
    load_prompt_overrides,
)

# ------------------------------ 加载器 ------------------------------


def test_loader_absent_file_returns_empty(tmp_path):
    assert load_prompt_overrides(tmp_path) == {}


def test_loader_valid_file(tmp_path):
    (tmp_path / PROMPT_OVERRIDES_FILENAME).write_text(
        json.dumps({"base_rules": "X"}), encoding="utf-8"
    )
    assert load_prompt_overrides(tmp_path) == {"base_rules": "X"}


def test_loader_malformed_json_returns_empty(tmp_path):
    (tmp_path / PROMPT_OVERRIDES_FILENAME).write_text("{ not json", encoding="utf-8")
    assert load_prompt_overrides(tmp_path) == {}


def test_loader_non_object_json_returns_empty(tmp_path):
    (tmp_path / PROMPT_OVERRIDES_FILENAME).write_text("[1, 2]", encoding="utf-8")
    assert load_prompt_overrides(tmp_path) == {}


def test_loader_mutation_visible_next_read(tmp_path):
    # RSI 循环语义:改文件后下一次读取(下一 tick restore)即生效。
    f = tmp_path / PROMPT_OVERRIDES_FILENAME
    f.write_text(json.dumps({"base_rules": "v1"}), encoding="utf-8")
    assert load_prompt_overrides(tmp_path)["base_rules"] == "v1"
    f.write_text(json.dumps({"base_rules": "v2"}), encoding="utf-8")
    assert load_prompt_overrides(tmp_path)["base_rules"] == "v2"


# -------------------------- 消息装配 --------------------------


def _react_messages(**over):
    kwargs = {
        "world_description": "W",
        "skill_catalog": [],
        "activated_skill_content": "",
        "observations": [],
        "agent_json": {"id": 1},
    }
    kwargs.update(over)
    return build_react_messages(**kwargs)


def test_no_override_byte_identical_to_default():
    default_msgs = _react_messages()
    ov_msgs = _react_messages(base_rules_override=None)
    assert default_msgs[0]["content"] == ov_msgs[0]["content"]
    assert default_msgs[0]["content"].startswith(build_base_rules())


def test_override_replaces_leading_system_block():
    msgs = _react_messages(base_rules_override="RULES-V2")
    assert msgs[0]["content"].startswith("RULES-V2")
    assert build_base_rules() not in msgs[0]["content"]


def test_override_is_shared_across_agent_views():
    # run 级一致性:不同 agent 身份/状态,system 前导块完全相同。
    a = _react_messages(agent_json={"id": 1}, base_rules_override="SHARED")
    b = _react_messages(agent_json={"id": 2}, base_rules_override="SHARED")
    assert a[0]["content"] == b[0]["content"]


# --------------------- 合并 prompt override ---------------------


def _runtime_with_prompt(prompt, tmp_path):
    calls = {}

    async def dispatch_llm(**kwargs):
        calls["messages"] = kwargs.get("messages")
        content = "# Memory\n\n## Identity And Profile\n- x"
        resp = type(
            "R",
            (),
            {
                "choices": [
                    type("C", (), {"message": type("M", (), {"content": content})()})
                ]
            },
        )()
        return resp

    rt = PersonMemoryRuntime(
        agent_id=1,
        config=MemoryRuntimeConfig(
            consolidation=MemoryConsolidationConfig(
                pending_threshold=1,
                interval_steps=99,
                high_importance_threshold=0.75,
            )
        ),
        get_model_name=lambda: "m",
        dispatch_llm=dispatch_llm,
        logger=__import__("logging").getLogger("test"),
        consolidation_system_prompt=prompt,
    )
    rt.ensure_store(tmp_path)
    return rt, calls


@pytest.mark.asyncio
async def test_consolidation_override_reaches_llm_dispatch(tmp_path):
    from datetime import datetime

    rt, calls = _runtime_with_prompt("CONSOLIDATE-V2", tmp_path)
    await rt.after_step(
        tick=1,
        t=datetime(2026, 1, 2, 9, 0),
        step_count=1,
        finish_memories=[
            {"type": "goal", "importance": 0.6, "keywords": ["k"], "text": "t"}
        ],
    )
    system_msg = calls["messages"][0]
    assert system_msg["role"] == "system"
    assert system_msg["content"] == "CONSOLIDATE-V2"


@pytest.mark.asyncio
async def test_consolidation_default_when_no_override(tmp_path):
    from datetime import datetime

    rt, calls = _runtime_with_prompt(None, tmp_path)
    await rt.after_step(
        tick=1,
        t=datetime(2026, 1, 2, 9, 0),
        step_count=1,
        finish_memories=[
            {"type": "goal", "importance": 0.6, "keywords": ["k"], "text": "t"}
        ],
    )
    assert calls["messages"][0]["content"] == MEMORY_CONSOLIDATION_SYSTEM_PROMPT
