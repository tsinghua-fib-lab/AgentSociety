# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

import tomllib
import os
from datetime import datetime
from pathlib import Path

# Autodoc imports modules at documentation build time. The runtime validates
# LLM credentials on import, so provide harmless OpenAI-compatible placeholders
# for ReadTheDocs/local docs builds when the user has not configured real keys.
os.environ.setdefault("AGENTSOCIETY_LLM_API_KEY", "docs-build-placeholder")
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
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

# -- Autodoc configuration ---------------------------------------------------
autodoc_default_options = {
    "members": True,
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
language = "zh"

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
        "font-stack": 'system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
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

# Add logo and favicon（favicon.svg → static/agentsociety_icon.svg）
html_logo = "_static/logo/1.png"
html_favicon = "_static/logo/favicon.svg"

# -- Options for intersphinx -------------------------------------------------

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
    "pydantic": ("https://pydantic.dev/docs/validation/latest/", None),
}

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
