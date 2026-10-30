"""env 模块 workspace 持久化契约测试（单元级，无 Ray / 无 LLM）。"""

from __future__ import annotations

from collections import defaultdict, deque
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agentsociety2.config import Config
from agentsociety2.contrib.env.economy_space import EconomyPerson, EconomySpace
from agentsociety2.contrib.env.prisoners_dilemma import PrisonersDilemmaEnv
from agentsociety2.contrib.env.simple_social_space import (
    SimpleSocialSpace,
)
from agentsociety2.env.base import EnvBase
from agentsociety2.env.router_base import RouterBase

# 迁移模块自选的 workspace 布局：<root>/state/ENV_STATE.json。
_STATE_REL = "state/ENV_STATE.json"
_STATE_FILE = Path(_STATE_REL)


# ---------------------------------------------------------------------------
# 单模块 round-trip：to_workspace -> restore
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prisoners_dilemma_roundtrip(tmp_path: Path) -> None:
    ws = tmp_path / "env" / "prisoners_dilemma"

    m1 = PrisonersDilemmaEnv(payoff_cc=3)
    m1._bind_workspace(ws)
    await m1.submit_action("Agent A", "Yes")
    m1.round_number = 5
    m1._step_counter = 7
    await m1.to_workspace()

    m2 = await PrisonersDilemmaEnv.from_workspace(ws, payoff_cc=3)
    assert m2._pending_actions == {"Agent A": "Yes"}
    assert m2.round_number == 5
    assert m2._step_counter == 7
    assert m2.payoff_cc == 3  # 构造 kwargs 不在动态状态里，保持不变
    assert m2._lock is not None  # _lock 由 __init__ 重建，从不从盘读


@pytest.mark.asyncio
async def test_simple_social_space_roundtrip(tmp_path: Path) -> None:
    ws = tmp_path / "env" / "simple_social_space"
    pairs = [(1, "Alice"), (2, "Bob"), (3, "Carol")]

    m1 = SimpleSocialSpace(agent_id_name_pairs=pairs)
    m1._bind_workspace(ws)
    await m1.send_message(1, 2, "hello")
    await m1.create_group(1, "team", [2, 3])
    m1._step_counter = 4
    m1._total_messages_sent = 10
    await m1.to_workspace()

    m2 = await SimpleSocialSpace.from_workspace(ws, agent_id_name_pairs=pairs)
    assert m2._next_message_id == m1._next_message_id
    assert m2._next_group_id == m1._next_group_id
    assert m2._total_messages_sent == 10
    assert m2._step_counter == 4
    assert 2 in m2._mailboxes and len(m2._mailboxes[2]) == 1
    assert m2._groups  # group 已恢复
    m2._mailboxes[999]  # defaultdict(list) 自动建键得以保留
    assert m2._agent_names == {1: "Alice", 2: "Bob", 3: "Carol"}


@pytest.mark.asyncio
async def test_economy_space_roundtrip(tmp_path: Path) -> None:
    ws = tmp_path / "env" / "economy_space"
    persons = [
        EconomyPerson(id=1, currency=100.0, skill="eng", consumption=5.0, income=10.0)
    ]

    m1 = EconomySpace(persons=persons)
    m1._bind_workspace(ws)
    await m1.add_person_currency(1, 50.0)
    m1._step_counter = 3
    await m1.to_workspace()

    m2 = await EconomySpace.from_workspace(ws, persons=persons)
    cur = await m2.get_person_currency(1)
    assert cur.currency == 150.0
    assert m2._step_counter == 3
    assert len(m2._persons) == 1


# ---------------------------------------------------------------------------
# 基类默认行为（未迁移模块不崩）
# ---------------------------------------------------------------------------


class _BareEnv(EnvBase):
    """未覆盖 to_workspace/restore 的 EnvBase（opt-in 契约）。"""

    def __init__(self, value: int = 0) -> None:
        super().__init__()
        self.value = value

    async def step(self, tick: int, t: datetime) -> None:
        self.value += 1


@pytest.mark.asyncio
async def test_unmigrated_module_persists_nothing_without_crashing(
    tmp_path: Path,
) -> None:
    """未覆盖 to_workspace 的模块：no-op，不写文件、不崩；restore 返回 False。"""
    ws = tmp_path / "env" / "bare"
    m1 = _BareEnv(value=42)
    m1._bind_workspace(ws)
    await m1.to_workspace()  # 默认 no-op
    assert not any(ws.rglob("*"))  # 什么都没写

    m2 = await _BareEnv.from_workspace(ws, value=0)
    assert m2.value == 0  # 未覆盖 -> 状态不恢复（opt-in）
    restored = await m2.restore(ws)
    assert restored is False


@pytest.mark.asyncio
async def test_restore_returns_false_on_fresh_workspace(tmp_path: Path) -> None:
    ws = tmp_path / "env" / "fresh"
    m = PrisonersDilemmaEnv()
    restored = await m.restore(ws)  # 无快照文件 -> 返回 False（fresh）
    assert restored is False
    assert ws.is_dir()  # 绑定已建目录


# ---------------------------------------------------------------------------
# RouterBase：restore 在 init() 之后执行，覆盖破坏性 init 的重置
# ---------------------------------------------------------------------------


class _StubRouter(RouterBase):
    """用于测试持久化接线的最小 RouterBase。"""

    async def ask(
        self,
        ctx: dict,
        instruction: str,
        readonly: bool = False,
        template_mode: bool = False,
        trace_id: str | None = None,
        parent_span_id: str | None = None,
    ):
        return ctx, ""


def _stub_router(env_modules):
    # 注入轻量 dispatcher stub，避免构造真实 LLM client。
    return _StubRouter(
        env_modules=env_modules,
        llm_clients_spec={"coder": object(), "default": object()},
    )


@pytest.mark.asyncio
async def test_router_restores_env_state_after_init(tmp_path: Path) -> None:
    """破坏性 ``init()`` 不得覆盖 checkpoint。

    PrisonersDilemmaEnv.init() 会清空 round_history/pending_actions/step_counter，
    故 RouterBase.init 末尾的 restore 必须覆盖回持久化的值。
    """
    root = tmp_path / "env"
    module_type = "prisoners_dilemma"

    # 阶段 1：经 router 写一份 checkpoint。
    m1 = PrisonersDilemmaEnv()
    router1 = _stub_router([m1])
    router1.run_dir = tmp_path
    router1.bind_env_workspaces(root, [module_type])
    await router1.init(datetime(2025, 1, 1))
    await m1.submit_action("Agent A", "Yes")
    m1.round_number = 5
    m1._step_counter = 9
    await router1.to_workspaces()
    assert (root / module_type / _STATE_FILE).is_file()

    # 阶段 2：全新 router+模块恢复。RouterBase 重新 init（会重置）再 restore，
    # 恢复的值必须保留。
    m2 = PrisonersDilemmaEnv()
    router2 = _stub_router([m2])
    router2.run_dir = tmp_path
    router2.bind_env_workspaces(root, [module_type])
    restored = await router2.init(datetime(2025, 1, 1))
    assert restored is True  # 标记为 resume
    assert m2._pending_actions == {"Agent A": "Yes"}
    assert m2.round_number == 5
    assert m2._step_counter == 9


@pytest.mark.asyncio
async def test_router_to_workspaces_persists_all_modules(tmp_path: Path) -> None:
    root = tmp_path / "env"
    m1 = PrisonersDilemmaEnv()
    m2 = SimpleSocialSpace(agent_id_name_pairs=[(1, "A")])
    router = _stub_router([m1, m2])
    router.run_dir = tmp_path
    router.bind_env_workspaces(root, ["prisoners_dilemma", "simple_social_space"])
    await router.init(datetime(2025, 1, 1))
    await m1.submit_action("X", "Yes")
    await m2.send_message(1, 1, "note")
    await router.to_workspaces()

    assert (root / "prisoners_dilemma" / _STATE_FILE).is_file()
    assert (root / "simple_social_space" / _STATE_FILE).is_file()


# ---------------------------------------------------------------------------
# 容错：单模块失败不拖垮整体 restore / to_workspace
# ---------------------------------------------------------------------------


class _FailingRestoreEnv(PrisonersDilemmaEnv):
    """restore 时抛错（模拟 schema 漂移）。"""

    async def restore(self, workspace_path) -> bool:
        raise RuntimeError("schema drift")


class _FailingDumpEnv(PrisonersDilemmaEnv):
    """to_workspace 时抛错。"""

    async def to_workspace(self, workspace_path=None) -> None:
        raise RuntimeError("serialize failed")


@pytest.mark.asyncio
async def test_partial_restore_aborts_by_default(tmp_path: Path) -> None:
    """严格模式（默认）：任一模块 restore 失败 → 中止整个 resume 并抛错。

    静默降级（失败模块 fresh 启动）曾让坏 key 覆盖整个模块状态，而
    SOCIETY_STEP.json 仍记录原步数——损坏直到下游指标才暴露。抛错前仍会
    尝试恢复所有模块，便于一次汇总全部失败点。
    """
    root = tmp_path / "env"
    good = PrisonersDilemmaEnv()
    bad = _FailingRestoreEnv()
    # 先各自写一份 checkpoint。
    good._bind_workspace(root / "good")
    await good.submit_action("A", "Yes")
    await good.to_workspace()
    bad._bind_workspace(root / "bad")
    await bad.to_workspace()

    router = _stub_router([_FailingRestoreEnv(), PrisonersDilemmaEnv()])
    router.run_dir = tmp_path
    router.bind_env_workspaces(root, ["bad", "good"])
    with pytest.raises(RuntimeError, match="AGENTSOCIETY_ENV_RESTORE_ALLOW_FRESH"):
        await router.from_workspaces()
    # 收集全部失败点后统一抛错：good 在抛错前仍完成了恢复。
    assert router.env_modules[1]._pending_actions == {"A": "Yes"}


@pytest.mark.asyncio
async def test_partial_restore_degrades_only_with_allow_fresh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """显式 opt-in（ENV_RESTORE_ALLOW_FRESH=1）才降级：bad fresh、good 照常恢复。"""
    monkeypatch.setattr(Config, "ENV_RESTORE_ALLOW_FRESH", True)
    root = tmp_path / "env"
    good = PrisonersDilemmaEnv()
    bad = _FailingRestoreEnv()
    # 先各自写一份 checkpoint。
    good._bind_workspace(root / "good")
    await good.submit_action("A", "Yes")
    await good.to_workspace()
    bad._bind_workspace(root / "bad")
    await bad.to_workspace()

    router = _stub_router([_FailingRestoreEnv(), PrisonersDilemmaEnv()])
    router.run_dir = tmp_path
    router.bind_env_workspaces(root, ["bad", "good"])
    # 降级模式下即使 bad 抛错，good 仍恢复；整体返回 True（发生过恢复）。
    restored = await router.from_workspaces()
    assert restored is True
    assert router.env_modules[1]._pending_actions == {"A": "Yes"}


@pytest.mark.asyncio
async def test_to_workspaces_one_module_failure_does_not_abort_others(
    tmp_path: Path,
) -> None:
    """一个模块 to_workspace 抛错不应让本步其它模块的落盘全部丢失。"""
    root = tmp_path / "env"
    router = _stub_router([_FailingDumpEnv(), PrisonersDilemmaEnv()])
    router.run_dir = tmp_path
    router.bind_env_workspaces(root, ["bad", "good"])
    await router.init(datetime(2025, 1, 1))
    # bad 会抛错，但 good 的快照仍应写入。
    await router.to_workspaces()
    assert (root / "good" / _STATE_FILE).is_file()


# ---------------------------------------------------------------------------
# 12 个已迁移模块的 round-trip（纯单元，无 LLM/Ray，ms 级）
# ---------------------------------------------------------------------------

# ── 游戏型模块（round_number / round_history / _pending_* / _step_counter）──

GAME_MODULES = [
    (
        "public_goods",
        "PublicGoodsEnv",
        {"num_agents": 2},
        lambda m: (
            m._pending_contributions.update({"a": 5, "b": 3}),
            m._agents_submitted_in_current_round.update({"a", "b"}),
            m.__setattr__("round_number", 2),
            m.__setattr__("_step_counter", 4),
        ),
        lambda b: (
            b._pending_contributions == {"a": 5, "b": 3}
            and b._agents_submitted_in_current_round == {"a", "b"}
            and b.round_number == 2
            and b._step_counter == 4
        ),
    ),
    (
        "trust_game",
        "TrustGameEnv",
        {},
        lambda m: (
            m.__setattr__("round_number", 3),
            m.__setattr__("partner_mapping", {"Alice": "Bob"}),
            m._pending_investments.update({"Alice": 10}),
            m._pending_returns.update({"Bob": 5}),
            m.__setattr__("_step_counter", 5),
        ),
        lambda b: (
            b.round_number == 3
            and b.partner_mapping == {"Alice": "Bob"}
            and b._pending_investments == {"Alice": 10}
            and b._pending_returns == {"Bob": 5}
            and b._step_counter == 5
        ),
    ),
    (
        "volunteer_dilemma",
        "VolunteerDilemmaEnv",
        {},
        lambda m: (
            m._pending_choices.update({"a": "yes", "b": "no"}),
            m.__setattr__("round_number", 1),
            m.__setattr__("_step_counter", 2),
        ),
        lambda b: (
            b._pending_choices == {"a": "yes", "b": "no"}
            and b.round_number == 1
            and b._step_counter == 2
        ),
    ),
    (
        "commons_tragedy",
        "CommonsTragedyEnv",
        {},
        lambda m: (
            m._pending_extractions.update({"X": 5}),
            m._agents_submitted_in_current_round.add("X"),
            m.__setattr__("current_pool_resources", 80),
            m.__setattr__("_last_round_executed", 3),
            m.__setattr__("_step_counter", 7),
        ),
        lambda b: (
            b._pending_extractions == {"X": 5}
            and b._agents_submitted_in_current_round == {"X"}
            and b.current_pool_resources == 80
            and b._last_round_executed == 3
            and b._step_counter == 7
        ),
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("module_key,class_name,kwargs,mutate,check", GAME_MODULES)
async def test_game_modules_roundtrip(
    tmp_path, module_key, class_name, kwargs, mutate, check
):
    """游戏型模块 round-trip：公共 goods / 信任博弈 / volunteer / 公地悲剧。"""
    import importlib

    pkg = importlib.import_module(f"agentsociety2.contrib.env.{module_key}")
    cls = getattr(pkg, class_name)
    ws = tmp_path / "env" / module_key
    m1 = cls(**kwargs)
    m1._bind_workspace(ws)
    mutate(m1)
    await m1.to_workspace()
    m2 = await cls.from_workspace(ws, **kwargs)
    assert check(m2), f"{module_key}: round-trip mismatch"


# ── 心理/全局模块（int 键 dict / str）──

PSYCH_MODULES = [
    (
        "endowment_effect",
        "EndowmentEffectEnv",
        {"agent_ids": [1, 2]},
        lambda m: (
            m._evaluations[1].update({"item1": {"wta": 10, "wtp": 5}}),
            m.__setattr__("_step_counter", 3),
        ),
        lambda b: (
            b._evaluations.get(1, {}).get("item1") == {"wta": 10, "wtp": 5}
            and b._step_counter == 3
        ),
    ),
    (
        "self_enhancement",
        "SelfEnhancementEnv",
        {"agent_ids": [1, 2]},
        lambda m: (
            m._rankings[1].update({"intelligence": 95}),
            m.__setattr__("_step_counter", 6),
        ),
        lambda b: (
            b._rankings.get(1, {}).get("intelligence") == 95 and b._step_counter == 6
        ),
    ),
    (
        "self_reference_effect",
        "SelfReferenceEffectEnv",
        {"agent_ids": [1]},
        lambda m: (
            m._encoding_ratings[1].append(
                {"trait": "kind", "identity": "self", "rating": 5}
            ),
            m._recognition_judgments[1].append(
                {"trait": "kind", "judge_type": "old", "is_correct": True}
            ),
            m.__setattr__("_step_counter", 3),
        ),
        lambda b: (
            len(b._encoding_ratings.get(1, [])) == 1
            and len(b._recognition_judgments.get(1, [])) == 1
            and b._step_counter == 3
        ),
    ),
    (
        "global_information",
        "GlobalInformationEnv",
        {},
        lambda m: m.__setattr__("_global_information", "storm warning"),
        lambda b: b._global_information == "storm warning",
    ),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("module_key,class_name,kwargs,mutate,check", PSYCH_MODULES)
async def test_psych_global_modules_roundtrip(
    tmp_path, module_key, class_name, kwargs, mutate, check
):
    """心理实验/全局信息模块 round-trip。"""
    import importlib

    pkg = importlib.import_module(f"agentsociety2.contrib.env.{module_key}")
    cls = getattr(pkg, class_name)
    ws = tmp_path / "env" / module_key
    m1 = cls(**kwargs)
    m1._bind_workspace(ws)
    mutate(m1)
    await m1.to_workspace()
    m2 = await cls.from_workspace(ws, **kwargs)
    assert check(m2), f"{module_key}: round-trip mismatch"


# ── EventSpace: pydantic CurrentEvent（含 datetime）──


@pytest.mark.asyncio
async def test_event_space_roundtrip(tmp_path):
    from agentsociety2.contrib.env.event_space.environment import (
        CurrentEvent,
        EventSpace,
    )

    ws = tmp_path / "env" / "event_space"
    m1 = EventSpace()
    m1._bind_workspace(ws)
    ev = CurrentEvent(
        person_id=1,
        event_type="work",
        event_name="coding",
        status="in_progress",
        start_time=datetime(2025, 1, 1, 9, 0),
        expected_end_time=datetime(2025, 1, 1, 17, 0),
    )
    m1._agent_events[1] = ev
    m1._recent_stopped_events[2] = ev
    m1._step_counter = 4
    await m1.to_workspace()
    m2 = await EventSpace.from_workspace(ws)
    assert m2._step_counter == 4
    assert 1 in m2._agent_events
    assert m2._agent_events[1].event_name == "coding"
    assert m2._agent_events[1].status == "in_progress"
    assert 2 in m2._recent_stopped_events


# ── ReputationGame: enum Reputation + pydantic ActionLogEntry ──


@pytest.mark.asyncio
async def test_reputation_game_roundtrip(tmp_path):
    from agentsociety2.contrib.env.reputation_game import (
        ActionLogEntry,
        Reputation,
        ReputationGameEnv,
    )

    ws = tmp_path / "env" / "reputation_game"
    m1 = ReputationGameEnv()
    m1._bind_workspace(ws)
    m1._reputations[1] = Reputation.GOOD
    m1._reputations[2] = Reputation.BAD
    m1._payoffs[1] = 12.5
    m1._action_log.append(
        ActionLogEntry(
            donor_id=1,
            recipient_id=2,
            action="cooperate",
            donor_old_rep="good",
            donor_new_rep="good",
            recipient_rep="bad",
            cost=1,
            benefit=5,
            timestamp="2025-01-01T00:00:00",
        )
    )
    m1._step_counter = 9
    await m1.to_workspace()
    m2 = await ReputationGameEnv.from_workspace(ws)
    assert m2._reputations[1] == Reputation.GOOD
    assert m2._reputations[2] == Reputation.BAD
    assert m2._payoffs[1] == 12.5
    assert len(m2._action_log) == 1
    assert m2._action_log[0].action == "cooperate"
    assert m2._step_counter == 9


# ── ImplicitAssociationTest: int-keyed dict ──


@pytest.mark.asyncio
async def test_implicit_association_test_roundtrip(tmp_path):
    from agentsociety2.contrib.env.implicit_association_test import (
        ImplicitAssociationTestEnv,
    )

    ws = tmp_path / "env" / "iat"
    m1 = ImplicitAssociationTestEnv(agent_ids=[1])
    m1._bind_workspace(ws)
    m1._trial_progress[1] = 5
    m1._responses[1].append({"trial_id": 3, "key_press": "left", "rt": 450})
    m1._step_counter = 2
    await m1.to_workspace()
    m2 = await ImplicitAssociationTestEnv.from_workspace(ws, agent_ids=[1])
    assert m2._trial_progress[1] == 5
    assert len(m2._responses[1]) == 1
    assert m2._responses[1][0] == {"trial_id": 3, "key_press": "left", "rt": 450}
    assert m2._step_counter == 2


# ── SocialMediaSpace: 社交图 + deque/defaultdict + 推荐器重建 ──


@pytest.mark.asyncio
async def test_social_media_roundtrip(tmp_path):

    from agentsociety2.contrib.env.social_media.models import (
        Post,
        SocialMediaPerson,
    )
    from agentsociety2.contrib.env.social_media.social_media_space import (
        SocialMediaSpace,
    )

    ws = tmp_path / "env" / "social_media"
    kwargs = {"agent_id_name_pairs": [(1, "A"), (2, "B")]}
    m1 = SocialMediaSpace(**kwargs)
    m1._bind_workspace(ws)
    now = datetime.now(UTC)
    m1._persons[1] = SocialMediaPerson(id=1, username="A", created_at=now)
    m1._posts[1] = Post(post_id=1, author_id=1, content="hello", created_at=now)
    m1._comments = {1: []}  # restore 会还原为 defaultdict(list)
    m1._next_post_id = 5
    m1._next_comment_id = 3
    m1._event_id = 10
    m1._pending_events = [{"type": "post", "id": 1}]
    m1._recent_events.append({"type": "post"})
    m1._step_counter = 7
    await m1.to_workspace()

    m2 = await SocialMediaSpace.from_workspace(ws, **kwargs)
    assert m2._next_post_id == 5
    assert m2._next_comment_id == 3
    assert m2._event_id == 10
    assert m2._step_counter == 7
    assert 1 in m2._persons
    assert 1 in m2._posts
    assert m2._posts[1].content == "hello"
    assert len(m2._pending_events) == 1
    assert len(m2._recent_events) == 1
    assert isinstance(m2._recent_events, deque)
    assert isinstance(m2._comments, defaultdict)
    # 推荐器在无 model_path 时也正常构造（轻量 fallback）
    assert m2._rec_engine is not None
