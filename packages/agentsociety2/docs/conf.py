# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import os
import tomllib
from datetime import datetime
from pathlib import Path

# Autodoc renders Config class attributes, so always use placeholder credentials
# in this build process, including when the caller has real keys configured.
for _credential in (
    "AGENTSOCIETY_LLM_API_KEY",
    "AGENTSOCIETY_CODER_LLM_API_KEY",
    "AGENTSOCIETY_EMBEDDING_API_KEY",
    "LITERATURE_SEARCH_API_KEY",
):
    os.environ[_credential] = "docs-build-placeholder"
os.environ.setdefault("AGENTSOCIETY_LLM_API_BASE", "https://api.openai.com/v1")
os.environ.setdefault("AGENTSOCIETY_LLM_MODEL", "gpt-5.5")

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information

# Read version from pyproject.toml
_pyproject = Path(__file__).parent.parent / "pyproject.toml"
with open(_pyproject, "rb") as f:
    _version = tomllib.load(f)["project"]["version"]

project = "AgentSociety 2"
copyright = f"{datetime.now().year}, FIBLAB"
author = "AgentSociety Team"
release = _version
version = _version

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.duration",
    "sphinx.ext.graphviz",
    "sphinx.ext.napoleon",
    "sphinx.ext.intersphinx",
    "sphinx.ext.autodoc",  # 自动从代码生成 API 文档
    "sphinx.ext.autosummary",  # 自动生成 API 摘要
    "sphinx.ext.viewcode",  # 添加 [source] 链接
    "myst_parser",
    "sphinx_design",
    "sphinx_copybutton",
    "sphinx.ext.doctest",
    "sphinx.ext.coverage",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "_static/**", "Thumbs.db", ".DS_Store"]

gettext_allow_fuzzy_translations = False
gettext_additional_targets = ["literal-block"]

# -- Autodoc configuration ---------------------------------------------------
autodoc_default_options = {
    "members": "",  # Preserve explicit member lists on individual API directives.
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": True,
    "exclude-members": "__weakref__",
}
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"

# -- Autosummary configuration -----------------------------------------------
autosummary_generate = True
autosummary_imported_members = True

# The suffix(es) of source filenames.
source_suffix = {
    ".rst": "restructuredtext",
    ".md": "markdown",
}

# The master toctree document.
master_doc = "index"

# -- Internationalization options --------------------------------------------
# 设置国际化支持
locale_dirs = ["locale/"]  # 翻译文件所在的路径

# 默认语言设置为中文
language = "zh_CN"

# 多语言配置
html_context = {
    "current_language": language,
    "languages": {
        "zh": "中文",
        "en": "English",
    },
    "display_github": True,
    "github_user": "tsinghua-fib-lab",
    "github_repo": "agentsociety",
    "github_version": "main",
    "conf_py_path": "packages/agentsociety2/docs/",
}

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_js_files = ["docs-ui.js"]

# Copy commands without console prompts or printed output.
copybutton_exclude = ".linenos, .gp, .go"
copybutton_prompt_text = r">>> |\.\.\. |\$ "
copybutton_prompt_is_regexp = True
copybutton_selector = "div.highlight-python pre, div.highlight-bash pre, div.highlight-console pre, div.highlight-pycon pre, div.highlight-default pre"

# Live external services are checked separately from deterministic PR checks.
linkcheck_anchors = False
linkcheck_timeout = 20
linkcheck_retries = 2
linkcheck_workers = 5
linkcheck_rate_limit_timeout = 60
# The local asset checker validates mirror files against this checkout, including
# documentation that has not been published to main yet.
linkcheck_ignore = [
    r"https://github\.com/tsinghua-fib-lab/[Aa]gent[Ss]ociety/blob/main/.*",
    r"https://raw\.githubusercontent\.com/tsinghua-fib-lab/[Aa]gent[Ss]ociety/main/.*",
]
coverage_show_missing_items = True
# Run only explicitly maintained test directives, not illustrative docstring sessions.
doctest_test_doctest_blocks = ""

# 品牌主色：rgb(0, 0, 136)
_BRAND = "rgb(0, 0, 136)"
_BRAND_CONTENT = "rgb(0, 0, 136)"
_BRAND_VISITED = "rgb(72, 38, 131)"
_BRAND_DARK_PRIMARY = "#b0b0e8"
_BRAND_DARK_CONTENT = "#c4c4f0"
_BRAND_DARK_VISITED = "#d4a8ff"

html_theme_options = {
    "sidebar_hide_name": False,
    "navigation_with_keys": True,
    "top_of_page_buttons": ["view", "edit"],
    "source_repository": "https://github.com/tsinghua-fib-lab/agentsociety/",
    "source_branch": "main",
    "source_directory": "packages/agentsociety2/docs/",
    "footer_icons": [
        {
            "name": "GitHub",
            "url": "https://github.com/tsinghua-fib-lab/agentsociety/",
            "html": """
                <svg stroke="currentColor" fill="currentColor" stroke-width="0" viewBox="0 0 16 16">
                    <path fill-rule="evenodd" d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"></path>
                </svg>
            """,
            "class": "",
        },
    ],
    "light_css_variables": {
        "font-stack": 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", Roboto, "Helvetica Neue", Arial, sans-serif',
        "color-brand-primary": _BRAND,
        "color-brand-content": _BRAND_CONTENT,
        "color-brand-visited": _BRAND_VISITED,
    },
    "dark_css_variables": {
        "color-brand-primary": _BRAND_DARK_PRIMARY,
        "color-brand-content": _BRAND_DARK_CONTENT,
        "color-brand-visited": _BRAND_DARK_VISITED,
    },
}

# 浏览器标签：首页为站点名；内页为「页面标题 - 站点名」（见 Furo base.html htmltitle）
html_title = "AgentSociety 2 文档"
html_short_title = "AgentSociety 2"


def _configure_language(app, config):
    """在命令行语言覆盖生效后，同步浏览器标题与模板语言。"""
    # Keep the short CLI alias while using Sphinx's complete Chinese UI catalog.
    if config.language == "zh":
        config.language = "zh_CN"
    config.html_title = (
        "AgentSociety 2 Documentation"
        if config.language == "en"
        else "AgentSociety 2 文档"
    )
    if config.language.startswith("zh"):
        config.html_search_options = {
            "dict": str(Path(__file__).with_name("search-terms.dict")),
            **config.html_search_options,
        }
    config.html_context = {
        **config.html_context,
        "current_language": config.language,
    }


# Docstrings use these short names across module boundaries. Resolve them to
# actual documented objects, leaving other missing references visible to Sphinx.
_REFERENCE_ALIASES = {
    "Path": "pathlib.Path",
    "AgentBase": "agentsociety2.agent.base.AgentBase",
    "AgentSociety": "agentsociety2.society.AgentSociety",
    "ServiceProxy": "agentsociety2.agent.service_proxy.ServiceProxy",
    "LLMClient": "agentsociety2.config.llm_dispatcher.LLMClient",
    "ThinkingSettings": "agentsociety2.config.llm_dispatcher.ThinkingSettings",
    "QuestionItem": "agentsociety2.society.models.QuestionItem",
    "AgentQuestionnaireResult": "agentsociety2.society.questionnaire.AgentQuestionnaireResult",
    "ReplaySink": "agentsociety2.storage.ReplaySink",
    "ReplayProxy": "agentsociety2.storage.replay_proxy.ReplayProxy",
    "SkillRegistry.list_all": "agentsociety2.agent.base.skill_registry.SkillRegistry.list_all",
    "RouterBase.set_current_time": "agentsociety2.env.router_base.RouterBase.set_current_time",
    "RouterBase.get_token_usages": "agentsociety2.env.router_base.RouterBase.get_token_usages",
    "dispatch_todo_tool": "agentsociety2.agent.base.AgentBase.dispatch_todo_tool",
}
# A source module must use one namespace in autodoc for viewcode's backlinks.
# Keep public re-export references working while indexing their definitions.
for _name in ("Config", "get_llm_router", "get_llm_router_and_model", "extract_json"):
    _REFERENCE_ALIASES[f"agentsociety2.config.{_name}"] = (
        f"agentsociety2.config.config.{_name}"
    )
for _name in ("ShardedAppendSink", "TraceProxy", "build_local_sink"):
    _REFERENCE_ALIASES[f"agentsociety2.trace.{_name}"] = (
        f"agentsociety2.trace.sharded_writer.{_name}"
    )


def _resolve_reference_alias(app, env, node, contnode):
    if node.get("refdomain") != "py":
        return None
    target = _REFERENCE_ALIASES.get(node.get("reftarget"))
    if target is None:
        return None
    node["reftarget"] = target
    # If the target belongs to Python's inventory, intersphinx handles it next.
    return env.get_domain("py").resolve_xref(
        env, node["refdoc"], app.builder, node["reftype"], target, node, contnode
    )


def _preserve_public_alias_anchors(app, doctree):
    """Keep published re-export fragment URLs after indexing canonical objects."""
    from sphinx.addnodes import desc_signature

    aliases = {
        alias: target
        for alias, target in _REFERENCE_ALIASES.items()
        if alias.startswith("agentsociety2.")
    }
    for signature in doctree.findall(desc_signature):
        for identifier in list(signature.get("ids", [])):
            for alias, target in aliases.items():
                if identifier == target or identifier.startswith(target + "."):
                    anchor = alias + identifier[len(target) :]
                    if anchor not in doctree.ids:
                        signature["ids"].append(anchor)
                        doctree.ids[anchor] = signature


def _skip_model_boilerplate(app, what, name, obj, skip, options):
    """Keep SDK API pages focused on project fields and methods."""
    if name == "model_config":
        return True
    if name == "__init__" and getattr(obj, "__module__", "").split(".")[0] in {
        "pydantic", "sqlmodel", "sqlalchemy"
    }:
        return True
    return None


def _translate_graph_alt(app, doctree, docname):
    """Graphviz keeps alt text outside the image nodes translated by Sphinx."""
    from sphinx.ext.graphviz import graphviz
    from sphinx.locale import get_translation
    from sphinx.util.i18n import docname_to_domain

    translate = get_translation(docname_to_domain(docname, app.config.gettext_compact))
    for node in doctree.findall(graphviz):
        if node.get("alt"):
            node["alt"] = translate(node["alt"])


def setup(app):
    app.connect("config-inited", _configure_language)
    app.connect("missing-reference", _resolve_reference_alias, priority=400)
    app.connect("doctree-read", _preserve_public_alias_anchors)
    app.connect("autodoc-skip-member", _skip_model_boilerplate)
    app.connect("doctree-resolved", _translate_graph_alt)

# Add logo and favicon（favicon.svg → static/agentsociety_icon.svg）
html_logo = "_static/logo/1.png"
html_favicon = "_static/logo/favicon.svg"

# -- Options for intersphinx -------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://pydantic.dev/docs/validation/latest/", None),
}

# nitpicky 模式下优先修正文档内的确定性错误；以下保留项主要来自
# 第三方类型提示、TypeVar 和当前 Sphinx/autodoc 对导入重导出模型的解析限制。
nitpick_ignore_regex = [
    (
        r"py:class",
        r"litellm\.types\.llms\.openai\.ChatCompletion(?:User|Assistant|Tool|System|Function|Developer)Message",
    ),
    (r"py:class", r"litellm\.types\.utils\.ModelResponse"),
    (
        r"py:class",
        r"litellm\.litellm_core_utils\.streaming_handler\.CustomStreamWrapper",
    ),
    (r"py:class", r"litellm\.router\.Router"),
    (r"py:class", r"starlette\.requests\.Request"),
    (r"py:class", r"starlette\.responses\.PlainTextResponse"),
    (r"py:exc", r"HTTPException"),
    (r"py:class", r"agentsociety2\.(?:agent\.base|env\.router_base)\.T"),
    (r"py:class", r"agentsociety2\.env\.base\.F"),
    (r"py:class", r"datetime"),
    (
        r"py:class",
        r"(?:WordingStrength|DispatchStatus|EnvelopeStatus|Severity|EvidenceCategory|Priority|EvidenceGapType|EvidenceTool|FigureStatus|HumanGateSeverity|HumanDecision|RoundConstraint|Confidence|Verdict|TargetLayer|ResolvedState)",
    ),
]

# -- Options for Napoleon -----------------------------------------------------

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = False
napoleon_use_admonition_for_notes = False
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_preprocess_types = False
napoleon_type_aliases = None
napoleon_attr_annotations = True

# -- MyST Parser Options -----------------------------------------------------

myst_enable_extensions = [
    "colon_fence",
    "deflist",
    "dollarmath",
    "fieldlist",
    "html_admonition",
    "html_image",
    "linkify",
    "replacements",
    "smartquotes",
    "strikethrough",
    "substitution",
    "tasklist",
]

myst_heading_anchors = 3
myst_fence_as_directive = ["math", "graphviz"]
