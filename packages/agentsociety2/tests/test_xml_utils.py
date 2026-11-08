"""xml_utils 行为锁测试。

用例从 prisoners_dilemma / commons_tragedy 原**手写正则**的观测行为推导
(重构前先锁行为,保证替换为共享 helper 后语义不变)。
"""

from agentsociety2.agent.xml_utils import extract_xml_tag_value


def test_extracts_simple_value_tag():
    assert extract_xml_tag_value("<action>Yes</action>", "action", "Yes|No") == "Yes"


def test_value_tag_is_case_insensitive():
    # 原正则 re.IGNORECASE:小写输入也能命中,值保留原大小写由调用方处理。
    assert extract_xml_tag_value("<action>no</action>", "action", "Yes|No") == "no"


def test_value_tag_tolerates_inner_whitespace():
    assert (
        extract_xml_tag_value("<action>  Yes  </action>", "action", "Yes|No") == "Yes"
    )


def test_multidigit_value_pattern_prefers_longer_alternative():
    # (10|[1-9]) 与原 commons_tragedy 手写正则一致:10 必须整体命中。
    assert (
        extract_xml_tag_value("<extraction>10</extraction>", "extraction", "10|[1-9]")
        == "10"
    )
    assert (
        extract_xml_tag_value("<extraction>7</extraction>", "extraction", "10|[1-9]")
        == "7"
    )


def test_explanation_multiline_requires_dotall():
    text = "<explanation>第一行\n第二行</explanation>"
    # 不开 dotall 时 "." 不匹配换行,无法命中跨行内容。
    assert extract_xml_tag_value(text, "explanation") is None
    assert extract_xml_tag_value(text, "explanation", dotall=True) == "第一行\n第二行"


def test_explanation_whitespace_only_value_returns_empty_string_not_none():
    # 原实现:match 命中但值为空白 → strip 后为空串;helper 同样返回 ""
    # 而非 None,调用方用 ``is not None`` 判定。
    assert extract_xml_tag_value("<explanation>   </explanation>", "explanation") == ""


def test_returns_none_when_tag_absent_or_unclosed():
    assert extract_xml_tag_value("no tags here", "action", "Yes|No") is None
    assert extract_xml_tag_value("<action>Yes", "action", "Yes|No") is None


def test_extracts_first_occurrence_among_surrounding_prose():
    text = (
        "I will decide now.\n<output>\n  <action>No</action>\n"
        "  <explanation>理由</explanation>\n</output>"
    )
    assert extract_xml_tag_value(text, "action", "Yes|No") == "No"
    assert extract_xml_tag_value(text, "explanation", dotall=True) == "理由"
