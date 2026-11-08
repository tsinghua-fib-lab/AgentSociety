"""Contrib agent 与 AgentBase 的槽位契约。

清理 AgentBase.__init__ 时曾删掉 _logger 槽位——审计只 grep 了 agent/ 内部,
漏掉 contrib 博弈 agent 全部通过 ``self._logger`` 打日志,单测全绿而所有
game example 当场崩溃。此测试把"基类槽位被子类消费"的契约钉住:基类
初始化后的每一个被 contrib 依赖的属性都必须存在,删一个当场红。
"""

import pytest

from agentsociety2.agent.base.agent import AgentBase
from agentsociety2.contrib.agent import (
    CommonsTragedyAgent,
    PrisonersDilemmaAgent,
    PublicGoodsAgent,
    SpecialistAgent,
    TrustGameAgent,
    VolunteerDilemmaAgent,
)

# contrib agent 依赖的基类槽位。新增依赖时在此登记。
SLOTS_CONTRIB_DEPENDS_ON = (
    "_logger",
    "_step_count",
    "_profile",
    "_name",
    "_config",
    "_env",
)

CONTRIB_AGENT_CLASSES = (
    CommonsTragedyAgent,
    PrisonersDilemmaAgent,
    PublicGoodsAgent,
    SpecialistAgent,
    TrustGameAgent,
    VolunteerDilemmaAgent,
)


@pytest.mark.parametrize("cls", CONTRIB_AGENT_CLASSES, ids=lambda c: c.__name__)
def test_contrib_agents_get_required_base_slots_after_init(cls):
    """无参 __init__(构造契约)后,contrib 依赖的槽位必须全部就位。

    只断言存在性:契约规定空槽位为 None,由 restore() 填充。
    """
    agent = cls()
    for slot in SLOTS_CONTRIB_DEPENDS_ON:
        assert hasattr(agent, slot), (
            f"{cls.__name__} 依赖基类槽位 {slot},但 {AgentBase.__name__} "
            f"的 __init__ 未提供——清理基类前先更新此契约测试"
        )


# ---------------- acompletion empty-content fallback --------------------------


class _StubMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _StubChoice:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.message = _StubMessage(content)
        self.finish_reason = finish_reason


class _StubResponse:
    def __init__(self, content: str, finish_reason: str = "stop") -> None:
        self.choices = [_StubChoice(content, finish_reason)]


class _RecordingDispatcher:
    """记录每次 call 的 kwargs,按预设序列返回 (content, finish_reason)。"""

    def __init__(self, responses: list[tuple[str, str]]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    async def call(self, **kwargs):
        self.calls.append(kwargs)
        content, finish = self._responses.pop(0)
        return _StubResponse(content, finish)


def _agent_with_dispatcher(dispatcher):
    agent = object.__new__(PrisonersDilemmaAgent)
    agent._dispatcher = dispatcher
    agent._model_name = "test-model"
    agent._name = "T"
    agent._id = 1
    return agent


@pytest.mark.asyncio
async def test_acompletion_retries_once_with_higher_cap_on_length_truncation():
    """空内容 + finish_reason=length(思考链烧满输出上限)→ 一次 max_tokens=16384 重试。"""
    disp = _RecordingDispatcher(
        [("", "length"), ("<output><action>Yes</action></output>", "stop")]
    )
    agent = _agent_with_dispatcher(disp)
    resp = await agent.acompletion([{"role": "user", "content": "decide"}])
    assert resp.choices[0].message.content == "<output><action>Yes</action></output>"
    assert len(disp.calls) == 2
    assert "max_tokens" not in disp.calls[0]  # 首调不设上限(保持调用方原语义)
    assert disp.calls[1].get("max_tokens") == 16384


@pytest.mark.asyncio
async def test_acompletion_retry_respects_larger_caller_cap():
    """调用方已设更大的 max_tokens 时,重试保留调用方的上限而非降档。"""
    disp = _RecordingDispatcher([("", "length"), ("ok", "stop")])
    agent = _agent_with_dispatcher(disp)
    await agent.acompletion([{"role": "user", "content": "q"}], max_tokens=32768)
    assert disp.calls[1].get("max_tokens") == 32768


@pytest.mark.asyncio
async def test_acompletion_no_retry_when_content_present():
    disp = _RecordingDispatcher([("plain answer", "stop")])
    agent = _agent_with_dispatcher(disp)
    resp = await agent.acompletion([{"role": "user", "content": "q"}])
    assert resp.choices[0].message.content == "plain answer"
    assert len(disp.calls) == 1


@pytest.mark.asyncio
async def test_acompletion_no_retry_when_empty_but_not_truncated():
    """空内容但 finish_reason 不是 length(非截断形态)→ 不重试,留给调用方报错。

    这条纪律防止 fallback 掩盖真正的模型异常(如网关返回空 content +
    finish=stop 的病态响应)。
    """
    disp = _RecordingDispatcher([("", "stop")])
    agent = _agent_with_dispatcher(disp)
    resp = await agent.acompletion([{"role": "user", "content": "q"}])
    assert resp.choices[0].message.content == ""
    assert len(disp.calls) == 1
