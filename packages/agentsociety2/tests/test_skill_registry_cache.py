"""Skill metadata cache invalidates when file contents change."""

from agentsociety2.agent.base.skill_registry import SkillRegistry


def test_skill_memo_does_not_drop_second_namespace(tmp_path):
    child = tmp_path / "skill"
    child.mkdir()
    (child / "SKILL.md").write_text("---\nname: same\ndescription: sample\n---\n")
    registry = SkillRegistry()
    registry.scan_custom(tmp_path, namespace="one")
    registry.scan_custom(tmp_path, namespace="two")
    assert registry.get("one@same") is not None
    assert registry.get("two@same") is not None


def test_skill_frontmatter_cache_invalidates_after_edit(tmp_path):
    child = tmp_path / "skill"
    child.mkdir()
    md = child / "SKILL.md"
    md.write_text("---\nname: before\ndescription: first\n---\n")
    first = SkillRegistry()
    first.scan_custom(tmp_path)
    md.write_text("---\nname: after\ndescription: second\n---\n")
    second = SkillRegistry()
    second.scan_custom(tmp_path)
    assert second.get("custom@after").description == "second"
    assert second.get("custom@before") is None


def test_same_size_edit_with_identical_stat_cannot_reuse_stale_metadata(
    tmp_path, monkeypatch
):
    from pathlib import Path

    child = tmp_path / "skill"
    child.mkdir()
    md = child / "SKILL.md"
    before = "---\nname: before\ndescription: first\n---\n"
    after = "---\nname: after\ndescription: second\n---\n"
    assert len(before) == len(after)
    md.write_text(before)
    frozen = md.stat()
    original_stat = Path.stat

    def same_stat(path, *args, **kwargs):
        return frozen if path == md else original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", same_stat)
    first = SkillRegistry()
    first.scan_custom(tmp_path)
    md.write_text(after)
    second = SkillRegistry()
    second.scan_custom(tmp_path)
    assert first.get("custom@before").description == "first"
    assert second.get("custom@after").description == "second"
    assert second.get("custom@before") is None
