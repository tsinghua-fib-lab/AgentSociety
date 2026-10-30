"""Resume checkpoints advance only through the contiguous completed prefix."""

from pathlib import Path

from agentsociety2.society.society import AgentSociety


def _bare_society(tmp_path: Path) -> AgentSociety:
    from datetime import datetime

    soc = object.__new__(AgentSociety)
    soc._run_dir = tmp_path
    soc._completed_step_count = 0
    soc._step_count = 0
    soc._t = datetime(2026, 10, 19, 0, 0)
    soc._should_terminate = False
    return soc


def test_cursor_advances_only_on_prefix(tmp_path):
    soc = _bare_society(tmp_path)
    soc.mark_step_completed(0)
    soc.mark_step_completed(1)
    assert soc._completed_step_count == 2
    # 前缀正常推进。
    soc.mark_step_completed(2)
    assert soc._completed_step_count == 3


def test_gap_does_not_advance_cursor(tmp_path):
    """核心回归:step 3 失败,step 4 成功——游标不得越过 3。"""
    soc = _bare_society(tmp_path)
    for i in (0, 1, 2):
        soc.mark_step_completed(i)
    # step 3 失败(无 mark);step 4 成功:
    soc.mark_step_completed(4)
    assert soc._completed_step_count == 3, "缺口后的成功步不得顶翻游标"
    # step 5、6 成功也不行:
    soc.mark_step_completed(5)
    soc.mark_step_completed(6)
    assert soc._completed_step_count == 3


def test_cursor_recovers_when_gap_filled(tmp_path):
    """缺口修复(resume 重跑 step 3 成功)后游标自然前进到 7。"""
    soc = _bare_society(tmp_path)
    for i in (0, 1, 2, 4, 5, 6):
        soc.mark_step_completed(i)
    assert soc._completed_step_count == 3
    soc.mark_step_completed(3)  # resume 重跑补上失败步
    assert soc._completed_step_count == 4
    # 游标不会记住缺口后的完成状态；恢复可能重放这些步骤。
    # 此处只验证游标可继续推进，不声称任意业务副作用具有幂等性。
    soc.mark_step_completed(4)
    assert soc._completed_step_count == 5
    soc.mark_step_completed(5)
    soc.mark_step_completed(6)
    assert soc._completed_step_count == 7


def test_persistence_writes_checkpoint(tmp_path):
    soc = _bare_society(tmp_path)
    soc.mark_step_completed(0)
    data = (tmp_path / "SOCIETY_STEP.json").read_text(encoding="utf-8")
    assert '"completed_step_count": 1' in data


def test_repeated_marks_are_idempotent(tmp_path):
    soc = _bare_society(tmp_path)
    soc.mark_step_completed(0)
    soc.mark_step_completed(0)
    soc.mark_step_completed(1)
    assert soc._completed_step_count == 2
    soc.mark_step_completed(0)
    assert soc._completed_step_count == 2


def test_no_run_dir_is_noop(tmp_path):
    soc = _bare_society(tmp_path)
    soc._run_dir = None
    soc.mark_step_completed(0)  # 不应抛错
