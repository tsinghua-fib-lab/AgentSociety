"""Static rejection of private attribute access in generated programs."""

from __future__ import annotations

from agentsociety2.env.router_codegen import CodeGenRouter, CodeStage

_ESCAPES = [
    (
        "results['pwn'] = print.__globals__['os'].getcwd()\n"
        "results['status'] = 'success'"
    ),
    (
        "g = getattr(print, '__globals__')\n"
        "results['pwn'] = g['os'].getcwd()\n"
        "results['status'] = 'success'"
    ),
    (
        "m = modules['x']\n"
        "results['pwn'] = m.__init__.__globals__\n"
        "results['status'] = 'success'"
    ),
    ("results['pwn'] = type(print).__mro__\nresults['status'] = 'success'"),
    (
        "results['pwn'] = print.__globals__['__builtins__']\n"
        "results['status'] = 'success'"
    ),
]

_LEGIT = [
    # 正常合法代码不受影响(含普通属性访问)
    (
        "response = await modules['MobilitySpace'].get_status(ctx['id'])\n"
        "status = response.get('status', 'success') if isinstance(response, dict) else 'success'\n"
        "if status == 'success':\n"
        "    loc = response.get('aoi_id')\n"
        "    print(f'Checked the agent status: at AOI {loc} and idle.')\n"
        "    outcome = 'success'\n"
        "else:\n"
        "    print('Could not read the agent status.')\n"
        "    outcome = 'fail'\n"
        "    results['reason'] = response.get('reason', 'The tool reported a failure.')\n"
        "results['status'] = outcome"
    ),
]


def test_dunder_escape_payloads_are_rejected():
    for code in _ESCAPES:
        ok, reason = CodeStage._validate_code_safety(CodeGenRouter, code)
        assert not ok, f"逃逸载荷未被拦截: {code[:60]!r} -> {reason}"
        assert "Dunder" in reason or "dunder" in reason.lower()


def test_legit_code_with_normal_attributes_still_passes():
    for code in _LEGIT:
        ok, reason = CodeStage._validate_code_safety(CodeGenRouter, code)
        assert ok, f"合法代码被误拦: {reason}"


def test_mixed_escape_in_benign_wrapper_rejected():
    """逃逸载荷藏在正常代码中间也要拦。"""
    code = (
        "response = await modules['MobilitySpace'].get_status(ctx['id'])\n"
        "results['pwn'] = print.__globals__['os'].getcwd()\n"
        "results['status'] = 'success'"
    )
    ok, reason = CodeStage._validate_code_safety(CodeGenRouter, code)
    assert not ok
    assert "Dunder" in reason or "dunder" in reason.lower()
