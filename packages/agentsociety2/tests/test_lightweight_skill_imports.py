"""轻量技能上下文不能触发 SDK 初始化，公开导出仍保持对象身份。"""

import importlib
import os
import subprocess
import sys
from pathlib import Path

import pytest


def test_context_imports_without_model_credentials_or_heavy_dependencies(tmp_path):
    package_root = Path(__file__).resolve().parents[1]
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(tmp_path),
        "PYTHONPATH": str(package_root),
        "MEM0_TELEMETRY": "False",
        "ANONYMIZED_TELEMETRY": "False",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import sys
from agentsociety2.agent.base.skill_hook_context import HookContext, get_hook_context
from agentsociety2.agent.base.skill_script_context import SkillScriptContext
assert all(name not in sys.modules for name in (
    "litellm", "ray", "agentsociety2.config", "agentsociety2.agent.person",
    "agentsociety2.agent.base.skill_runtime",
))
assert HookContext.__name__ == "HookContext"
assert SkillScriptContext.__name__ == "SkillScriptContext"
""",
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    "module_name", ["agentsociety2", "agentsociety2.agent", "agentsociety2.agent.base"]
)
def test_lazy_public_exports_keep_identity_and_discoverability(module_name):
    module = importlib.import_module(module_name)
    assert set(module.__all__) <= set(dir(module))
    for name in module.__all__:
        value = getattr(module, name)
        source = importlib.import_module(module._EXPORT_MODULES[name])
        assert value is getattr(source, name)
        assert getattr(module, name) is value
    with pytest.raises(AttributeError):
        _ = module.not_an_export


@pytest.mark.parametrize(
    "module_name,name",
    [
        ("agentsociety2.agent", "MemoryConsolidationResult"),
        ("agentsociety2.agent.base", "ReactTurn"),
        ("agentsociety2.agent.base", "TodoStateStore"),
    ],
)
def test_main_branch_public_exports_remain_available(module_name, name):
    module = importlib.import_module(module_name)
    assert name in module.__all__
    assert getattr(module, name).__name__ == name


def test_script_context_legacy_import_keeps_identity():
    from agentsociety2.agent.base.skill_runtime import SkillScriptContext as legacy
    from agentsociety2.agent.base.skill_script_context import SkillScriptContext

    assert legacy is SkillScriptContext
