from __future__ import annotations

import html
import re
from pathlib import Path

from agentsociety2.skills.analysis.chart_export import (
    EDA_HUB_ENTRIES,
    ensure_brand_icon,
    html_font_links,
    html_tab_switcher_script,
    report_eda_section_css,
)

_REPORT_TOOL_LINKS: tuple[dict[str, str], ...] = tuple(
    entry for entry in EDA_HUB_ENTRIES if entry["key"] != "quick-stats"
)

EDA_INTERACTIVE_BEGIN = "<!-- EDA_INTERACTIVE_BEGIN -->"
EDA_INTERACTIVE_END = "<!-- EDA_INTERACTIVE_END -->"

_SECTION_TAG_RE = re.compile(r"<(/?)section\b[^>]*>", re.IGNORECASE)
_DATA_ID_RE = re.compile(r"\bid\s*=\s*(['\"])data\1", re.IGNORECASE)

_REPORT_TAB_META: dict[str, tuple[str, str, str, str]] = {
    "summary": ("数据摘要", "Summary", "static", ""),
    "hub": ("探索中心", "Exploration hub", "eda_hub.html", "featured"),
    "pygwalker": ("拖拽探索", "PyGWalker", "eda_pygwalker.html", ""),
    "datatable": ("数据表", "Tables", "eda_datatable.html", ""),
    "ydata": ("自动画像", "ydata profile", "eda_profile.html", ""),
    "sweetviz": ("对比画像", "Sweetviz", "eda_sweetviz.html", ""),
    "plotly": ("数值分布", "Distributions", "eda_plotly.html", ""),
    "missingno": ("缺失结构", "Missingness", "eda_missingno.html", ""),
}

_TOOL_ICONS: dict[str, str] = {e["key"]: e["icon"] for e in _REPORT_TOOL_LINKS}
_TOOL_DESC: dict[str, tuple[str, str]] = {
    e["key"]: (e["desc_zh"], e["desc_en"]) for e in _REPORT_TOOL_LINKS
}


def _quick_stats_excerpt(data_dir: Path) -> str:
    path = data_dir / "eda_quick_stats.md"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    if not text:
        return ""
    if len(text) > 4000:
        text = text[:4000] + "\n…(truncated)"
    return f'<pre class="eda-quick-stats">{html.escape(text)}</pre>'


def _tool_cards_html(data_dir: Path, *, lang: str) -> str:
    zh = lang.startswith("zh")
    cards: list[str] = []
    for spec in _REPORT_TOOL_LINKS:
        path = data_dir / spec["file"]
        if not path.is_file():
            continue
        label = spec["zh"] if zh else spec["en"]
        desc = spec["desc_zh"] if zh else spec["desc_en"]
        icon = spec["icon"]
        cards.append(
            f'<a class="tool-card" href="data/{spec["file"]}" target="_blank" rel="noopener">'
            f'<span class="tool-card-icon" aria-hidden="true">{icon}</span>'
            f'<span class="tool-card-title">{html.escape(label)}</span>'
            f'<span class="tool-card-desc">{html.escape(desc)}</span></a>'
        )
    if not cards:
        return ""
    heading = "更多探索工具" if zh else "More exploration tools"
    hint = (
        "下列工具已生成，可在新标签页打开；推荐优先使用「探索中心」标签。"
        if zh
        else "Open tools in a new tab; prefer the Exploration hub tab when available."
    )
    return (
        f'<div class="eda-tool-deck"><h3 class="tool-deck-title">{heading}</h3>'
        f'<p class="panel-intro">{hint}</p>'
        f'<div class="tool-grid">{"".join(cards)}</div></div>'
    )


def discover_eda_tabs(data_dir: Path) -> list[tuple[str, str, str]]:
    data_dir = data_dir.resolve()
    has_any = False
    for _tid, _zh, _en, filename, _feat in (
        (k, v[0], v[1], v[2], v[3]) for k, v in _REPORT_TAB_META.items()
    ):
        if filename and (data_dir / filename).is_file():
            has_any = True
            break
    if (data_dir / "eda_quick_stats.md").is_file():
        has_any = True

    if not has_any:
        return []

    tabs: list[tuple[str, str, str]] = []
    has_hub = (data_dir / "eda_hub.html").is_file()

    if (data_dir / "eda_quick_stats.md").is_file() or has_any:
        tabs.append(("summary", "static", ""))

    if has_hub:
        tabs.append(("hub", "iframe", "eda_hub.html"))
        return tabs

    for tab_id, _zh, _en, filename, _feat in (
        (k, v[0], v[1], v[2], v[3]) for k, v in _REPORT_TAB_META.items()
    ):
        if tab_id in ("summary", "hub") or not filename:
            continue
        if (data_dir / filename).is_file():
            tabs.append((tab_id, "iframe", filename))

    if not tabs and (data_dir / "eda_hub.html").is_file():
        tabs.append(("hub", "iframe", "eda_hub.html"))
    return tabs


def build_interactive_eda_section(
    data_dir: Path,
    *,
    lang: str = "zh",
) -> str:
    data_dir = data_dir.resolve()
    tabs = discover_eda_tabs(data_dir)
    zh = lang.startswith("zh")

    if not tabs:
        msg = (
            "暂无交互式 EDA。请运行 run-eda --type bundle。"
            if zh
            else "No interactive EDA yet. Run run-eda --type bundle."
        )
        return (
            '<div class="eda-interactive eda-interactive--empty" '
            'data-eda-interactive="empty">'
            f'<p class="iframe-hint">{html.escape(msg)}</p></div>'
        )

    title = "交互式探索" if zh else "Interactive exploration"
    tab_buttons: list[str] = []
    tab_panels: list[str] = []
    any(t[0] == "hub" for t in tabs)

    for idx, (tab_id, mode, filename) in enumerate(tabs):
        active = " active" if idx == 0 else ""
        aria = "true" if idx == 0 else "false"
        meta = _REPORT_TAB_META.get(tab_id, (tab_id, tab_id, "", ""))
        zh_label, en_label, _fn, feat = meta
        label = zh_label if zh else en_label
        icon = _TOOL_ICONS.get(tab_id, "•")
        tab_cls = "tab"
        if feat == "featured":
            tab_cls += " tab--featured"
        badge = ""
        if tab_id == "hub":
            badge = f'<span class="tab-badge">{"推荐" if zh else "Hub"}</span>'
        tab_buttons.append(
            f'<button type="button" class="{tab_cls}{active}" data-tab="{tab_id}" '
            f'role="tab" aria-selected="{aria}">'
            f'<span class="tab-icon" aria-hidden="true">{icon}</span>'
            f"<span>{html.escape(label)}</span>{badge}</button>"
        )

        panel_cls = f"tab-panel{active}"
        if tab_id == "summary":
            panel_cls += " panel-summary"
        elif tab_id == "hub":
            panel_cls += " panel-hub"

        if tab_id == "summary":
            excerpt = _quick_stats_excerpt(data_dir)
            spec_desc = (
                "实验库表的统计摘要；下方卡片可直达各探索工具。"
                if zh
                else "Table-level statistics; cards below link to each tool."
            )
            body = f'<p class="panel-intro">{spec_desc}</p>'
            body += excerpt or (
                f'<p class="iframe-hint">{"见「探索中心」或下方工具卡片。" if zh else "See Exploration hub or tool cards below."}</p>'
            )
            body += _tool_cards_html(data_dir, lang=lang)
        elif mode == "iframe":
            desc_zh, desc_en = (
                _TOOL_DESC.get(tab_id, ("", "")) if tab_id in _TOOL_DESC else ("", "")
            )
            desc = desc_zh if zh else desc_en
            hint_open = (
                f'若嵌入空白，请 <a href="data/{filename}" target="_blank" rel="noopener">'
                f"在新标签页打开</a>。"
                if zh
                else f'If the frame is blank, <a href="data/{filename}" target="_blank" rel="noopener">open in a new tab</a>.'
            )
            if tab_id == "hub":
                intro = (
                    "统一入口：统计摘要、拖拽探索、数据表、画像与分布图在同一页切换。"
                    if zh
                    else "Single entry: stats, drag-and-drop, tables, profiles, and charts in one place."
                )
            else:
                intro = desc
            body = (
                f'<p class="panel-intro"><strong>{html.escape(label)}</strong> — {html.escape(intro)}</p>'
                f'<p class="iframe-hint">{hint_open}</p>'
                f'<iframe class="eda-frame" src="data/{filename}" '
                f'title="{html.escape(label)}" loading="lazy"></iframe>'
            )
        else:
            body = ""

        tab_panels.append(
            f'<div class="{panel_cls}" data-panel="{tab_id}" role="tabpanel">{body}</div>'
        )

    styles = f"{html_font_links()}\n<style>{report_eda_section_css()}</style>"
    return (
        f'{styles}\n<div class="eda-interactive" data-eda-interactive="tabs">\n'
        f'  <h3 class="eda-section-title">{title}</h3>\n'
        f'  <div class="tab-root">\n'
        f'  <div class="tab-bar" role="tablist">{"".join(tab_buttons)}</div>\n'
        f"{''.join(tab_panels)}\n"
        f"  </div>\n"
        f"</div>\n"
        f"{html_tab_switcher_script()}"
    )


def _section_bounds_with_id(
    report_html: str,
    section_id_pattern: re.Pattern[str],
) -> tuple[int, int, int, int] | None:
    """Return opening start/end and closing start/end for one balanced section."""

    tags = list(_SECTION_TAG_RE.finditer(report_html))
    for index, tag in enumerate(tags):
        if tag.group(1) or not section_id_pattern.search(tag.group(0)):
            continue
        depth = 1
        for nested in tags[index + 1 :]:
            depth += -1 if nested.group(1) else 1
            if depth == 0:
                return tag.start(), tag.end(), nested.start(), nested.end()
        return None
    return None


def _generated_data_wrapper(section_html: str) -> str:
    zh = "暂无交互式" in section_html or "交互式探索" in section_html
    title = "数据与探索" if zh else "Data exploration"
    return (
        '<section id="data" data-eda-generated-section="true">\n'
        f"  <h2>{title}</h2>\n"
        f"  {EDA_INTERACTIVE_BEGIN}\n{section_html}\n{EDA_INTERACTIVE_END}\n"
        "</section>"
    )


def embed_interactive_eda_in_html(report_html: str, section_html: str) -> str:
    if EDA_INTERACTIVE_BEGIN in report_html and EDA_INTERACTIVE_END in report_html:
        pattern = re.compile(
            re.escape(EDA_INTERACTIVE_BEGIN) + r".*?" + re.escape(EDA_INTERACTIVE_END),
            re.DOTALL,
        )
        data_section = _section_bounds_with_id(report_html, _DATA_ID_RE)
        marker_start = report_html.index(EDA_INTERACTIVE_BEGIN)
        marker_end = report_html.index(EDA_INTERACTIVE_END) + len(EDA_INTERACTIVE_END)
        replacement = f"{EDA_INTERACTIVE_BEGIN}\n{section_html}\n{EDA_INTERACTIVE_END}"
        marker_contains_data_section = bool(
            data_section
            and marker_start <= data_section[0]
            and data_section[3] <= marker_end
        )
        if data_section is None or marker_contains_data_section:
            replacement = _generated_data_wrapper(section_html)
            return pattern.sub(replacement, report_html, count=1)
        marker_is_inside_data = data_section[1] <= marker_start < data_section[2]
        if marker_is_inside_data:
            return pattern.sub(replacement, report_html, count=1)

        without_top_level_marker = pattern.sub("", report_html, count=1)
        relocated_data_section = _section_bounds_with_id(
            without_top_level_marker,
            _DATA_ID_RE,
        )
        if relocated_data_section is None:  # pragma: no cover - defensive
            return without_top_level_marker
        closing_start = relocated_data_section[2]
        return (
            without_top_level_marker[:closing_start]
            + f"\n{replacement}\n"
            + without_top_level_marker[closing_start:]
        )

    data_section = _section_bounds_with_id(report_html, _DATA_ID_RE)
    if data_section:
        closing_start = data_section[2]
        marker_block = (
            f"\n{EDA_INTERACTIVE_BEGIN}\n{section_html}\n{EDA_INTERACTIVE_END}\n"
        )
        return report_html[:closing_start] + marker_block + report_html[closing_start:]

    findings = re.search(
        r'<h2\s+id="findings"[^>]*>',
        report_html,
        re.IGNORECASE,
    )
    if findings:
        return (
            report_html[: findings.start()]
            + _generated_data_wrapper(section_html)
            + "\n\n        "
            + report_html[findings.start() :]
        )
    return report_html


def embed_interactive_eda_in_reports(presentation_dir: Path) -> dict[str, object]:
    presentation_dir = presentation_dir.resolve()
    data_dir = presentation_dir / "data"
    if not data_dir.is_dir():
        return {"updated": [], "snippet": None, "reason": "no_data_dir"}

    ensure_brand_icon(presentation_dir / "assets")

    snippet_path = data_dir / "interactive_eda_section.html"
    section_zh = build_interactive_eda_section(data_dir, lang="zh")
    section_en = build_interactive_eda_section(data_dir, lang="en")
    snippet_path.write_text(section_zh, encoding="utf-8")

    updated: list[str] = []
    targets = {
        "report_zh.html": section_zh,
        "report_en.html": section_en,
    }
    for fname, section in targets.items():
        path = presentation_dir / fname
        if not path.is_file():
            continue
        original = path.read_text(encoding="utf-8")
        merged = embed_interactive_eda_in_html(original, section)
        if merged != original:
            path.write_text(merged, encoding="utf-8")
            updated.append(fname)

    return {
        "updated": updated,
        "snippet": str(snippet_path),
        "tabs": [t[0] for t in discover_eda_tabs(data_dir)],
    }
