"""Chart export + Nature-aligned visual tokens (Wong palette, report chrome)."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Literal

SurfaceKind = Literal["report", "data"]

try:
    import pandas as pd
except ModuleNotFoundError:  # pragma: no cover
    pd = None

OKABE_ITO: tuple[str, ...] = (
    "#E69F00",
    "#56B4E9",
    "#009E73",
    "#F0E442",
    "#0072B2",
    "#D55E00",
    "#CC79A7",
    "#000000",
)

REPORT_UI: dict[str, str] = {
    "text": "#1a1a1a",
    "text_muted": "#5e5e5e",
    "bg": "#ffffff",
    "bg_subtle": "#f6f4f0",
    "bg_warm": "#ebe8e2",
    "bg_panel": "#faf8f5",
    "border": "#d4cfc6",
    "border_light": "#e6e2da",
    "accent": "#c41e3a",
    "link": "#0066cc",
    "node_blue": "#0072b2",
    "node_green": "#009e73",
    "node_amber": "#e69f00",
}

FIGURE_MM: dict[str, float] = {
    "single": 89.0,
    "wide": 120.0,
    "double": 183.0,
}


def mm_to_inches(mm: float) -> float:
    return mm / 25.4


def report_figsize(
    width_mm: float = 120.0, aspect: float = 0.62
) -> tuple[float, float]:
    w = mm_to_inches(width_mm)
    return (w, w * aspect)


def apply_report_style(*, font_size: float = 7.0, display_scale: float = 1.45) -> None:
    import matplotlib.pyplot as plt

    size = font_size * display_scale
    u = REPORT_UI
    plt.rcParams.update(
        {
            "font.family": "sans-serif",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans", "Liberation Sans"],
            "svg.fonttype": "none",
            "pdf.fonttype": 42,
            "font.size": size,
            "axes.labelsize": size,
            "axes.titlesize": size + 1,
            "xtick.labelsize": size - 0.5,
            "ytick.labelsize": size - 0.5,
            "legend.fontsize": size - 0.5,
            "axes.labelcolor": u["text"],
            "axes.edgecolor": u["text"],
            "xtick.color": u["text_muted"],
            "ytick.color": u["text_muted"],
            "text.color": u["text"],
            "axes.spines.right": False,
            "axes.spines.top": False,
            "axes.linewidth": 0.8,
            "axes.grid": False,
            "legend.frameon": False,
            "axes.prop_cycle": plt.cycler(color=OKABE_ITO),
            "lines.linewidth": 1.2,
            "lines.markersize": 4.5,
            "figure.facecolor": u["bg"],
            "axes.facecolor": u["bg"],
            "savefig.facecolor": u["bg"],
        }
    )


def apply_seaborn_report_style(
    *, palette: str = "colorblind", context: str = "paper"
) -> None:
    import seaborn as sns

    sns.set_theme(style="ticks", context=context, palette=palette, font_scale=1.0)
    apply_report_style()


BRAND_NAME = "AgentSociety"
BRAND_ICON_NAME = "agentsociety_icon.svg"
BRAND_TAGLINE_ZH = "多智能体社会仿真 · 分析报告"
BRAND_TAGLINE_EN = "Multi-agent social simulation · Analysis report"


def _brand_icon_candidates() -> tuple[Path, ...]:
    """Return supported source, installed-skill, and explicit icon locations."""

    here = Path(__file__).resolve()
    roots: list[Path] = []

    configured_skill_root = os.environ.get("AGENTSOCIETY_ANALYSIS_SKILL_ROOT")
    if configured_skill_root:
        roots.append(Path(configured_skill_root).expanduser())

    roots.extend(
        (
            here.parent,
            Path.cwd() / ".codex" / "skills" / "agentsociety-analysis",
            Path.cwd() / ".claude" / "skills" / "agentsociety-analysis",
        )
    )

    launcher = Path(sys.argv[0]).expanduser().resolve()
    if launcher.parent.name == "bin" and launcher.parent.parent.name == ".agentsociety":
        workspace = launcher.parents[2]
        roots.extend(
            (
                workspace / ".codex" / "skills" / "agentsociety-analysis",
                workspace / ".claude" / "skills" / "agentsociety-analysis",
            )
        )

    candidates = [root / "assets" / BRAND_ICON_NAME for root in roots]
    candidates.extend(
        base / "static" / BRAND_ICON_NAME
        for base in (here.parents[5], here.parents[4], here.parents[3])
    )

    deduplicated: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        deduplicated.append(resolved)
    return tuple(deduplicated)


def brand_icon_source_path() -> Path:
    candidates = _brand_icon_candidates()
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    attempted = ", ".join(str(path) for path in candidates)
    raise FileNotFoundError(f"Official brand icon not found. Checked: {attempted}")


_PAGE_TINT_SVG_FILTER = """<defs>
  <filter id="as-page-tint" color-interpolation-filters="sRGB">
    <feColorMatrix type="saturate" values="1.1"/>
    <feColorMatrix type="matrix" values="
      1.04 0.06 0.02 0 0.01
      0.03 0.98 0.04 0 0.008
      0.02 0.07 1.03 0 0.008
      0 0 0 1 0"/>
  </filter>
</defs>"""


def _apply_page_tint_to_svg(svg_text: str) -> str:
    if 'id="as-page-tint"' in svg_text or "<image" not in svg_text:
        return svg_text
    open_tag = svg_text.find("<svg")
    if open_tag == -1:
        return svg_text
    close_open = svg_text.find(">", open_tag)
    if close_open == -1:
        return svg_text
    svg_text = (
        svg_text[: close_open + 1] + _PAGE_TINT_SVG_FILTER + svg_text[close_open + 1 :]
    )
    if 'filter="url(#as-page-tint)"' not in svg_text:
        svg_text = svg_text.replace("<image ", '<image filter="url(#as-page-tint)" ', 1)
    return svg_text


def write_page_tinted_brand_icon(dest: Path) -> Path:
    src = brand_icon_source_path()
    tinted = _apply_page_tint_to_svg(src.read_text(encoding="utf-8"))
    dest = dest.resolve()
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(tinted, encoding="utf-8")
    return dest


def ensure_brand_icon(assets_dir: Path) -> Path:
    assets_dir = assets_dir.resolve()
    assets_dir.mkdir(parents=True, exist_ok=True)
    dest = assets_dir / BRAND_ICON_NAME
    src = brand_icon_source_path()
    needs_write = not dest.is_file() or dest.stat().st_mtime < src.stat().st_mtime
    if not needs_write and dest.is_file():
        needs_write = 'id="as-page-tint"' not in dest.read_text(
            encoding="utf-8", errors="replace"
        )
    if needs_write:
        write_page_tinted_brand_icon(dest)
    return dest


def logo_href(*, surface: SurfaceKind = "report") -> str:
    """Relative logo URL from the HTML file location.

      - presentation/hypothesis_*/report_*.html → assets/agentsociety_icon.svg
      - presentation/.../data/*.html → ../assets/agentsociety_icon.svg
    - skill assets/report-shell.reference.html (same dir as icon) → agentsociety_icon.svg
    """
    if surface == "data":
        return f"../assets/{BRAND_ICON_NAME}"
    return f"assets/{BRAND_ICON_NAME}"


def logo_href_for_skill_shell() -> str:
    return BRAND_ICON_NAME


def html_font_links() -> str:
    return (
        '<link rel="preconnect" href="https://fonts.googleapis.com" />\n'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />\n'
        '<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;0,700&family=Source+Serif+4:opsz,wght@8..60,500;8..60,600;8..60,700&display=swap" rel="stylesheet" />'
    )


def brand_logo_img(*, href: str, size: int = 44, alt: str = BRAND_NAME) -> str:
    return (
        f'<img class="brand-logo" style="--logo-size: {size}px" src="{href}" '
        f'width="{size}" height="{size}" alt="{alt}" decoding="async" loading="eager" />'
    )


def brand_lockup_html(
    *,
    lang: str = "zh",
    logo_href_path: str | None = None,
    size: int = 52,
    surface: SurfaceKind = "report",
) -> str:
    tag = BRAND_TAGLINE_ZH if lang.startswith("zh") else BRAND_TAGLINE_EN
    if logo_href_path is None:
        logo_href_path = logo_href(surface=surface)
    return f"""<div class="brand-lockup" role="banner">
  {brand_logo_img(href=logo_href_path, size=size)}
  <div class="brand-text">
    <span class="brand-wordmark">{BRAND_NAME.upper()}</span>
    <span class="brand-tagline">{tag}</span>
  </div>
</div>"""


EDA_HUB_ENTRIES: tuple[dict[str, str], ...] = (
    {
        "key": "quick-stats",
        "file": "eda_quick_stats.md",
        "zh": "统计摘要",
        "en": "Quick stats",
        "icon": "Σ",
        "mode": "markdown",
        "desc_zh": "行数、缺失率与列类型速览",
        "desc_en": "Row counts, missingness, column types",
        "panel": "panel-muted",
    },
    {
        "key": "datatable",
        "file": "eda_datatable.html",
        "zh": "数据表",
        "en": "Tables",
        "icon": "▦",
        "mode": "iframe",
        "desc_zh": "可排序、可筛选的表格预览",
        "desc_en": "Sortable, filterable table preview",
        "panel": "panel-table",
    },
    {
        "key": "pygwalker",
        "file": "eda_pygwalker.html",
        "zh": "拖拽探索",
        "en": "PyGWalker",
        "icon": "◇",
        "mode": "iframe",
        "desc_zh": "Tableau 式交互制图",
        "desc_en": "Drag-and-drop visual exploration",
        "panel": "panel-explore",
    },
    {
        "key": "plotly",
        "file": "eda_plotly.html",
        "zh": "数值分布",
        "en": "Distributions",
        "icon": "◫",
        "mode": "iframe",
        "desc_zh": "数值列散点矩阵与直方图",
        "desc_en": "Scatter matrix and histograms",
        "panel": "panel-chart",
    },
    {
        "key": "ydata",
        "file": "eda_profile.html",
        "zh": "自动画像",
        "en": "ydata profile",
        "icon": "◎",
        "mode": "iframe",
        "desc_zh": "ydata-profiling 全量报告",
        "desc_en": "Full ydata-profiling report",
        "panel": "panel-profile",
    },
    {
        "key": "sweetviz",
        "file": "eda_sweetviz.html",
        "zh": "对比画像",
        "en": "Sweetviz",
        "icon": "⇄",
        "mode": "iframe",
        "desc_zh": "Sweetviz 特征对比",
        "desc_en": "Sweetviz feature comparison",
        "panel": "panel-profile",
    },
    {
        "key": "missingno",
        "file": "eda_missingno.html",
        "zh": "缺失结构",
        "en": "Missingness",
        "icon": "▤",
        "mode": "iframe",
        "desc_zh": "缺失值矩阵与条形图",
        "desc_en": "Missing-value matrix and bars",
        "panel": "panel-muted",
    },
    {
        "key": "correlation",
        "file": "correlation_index.html",
        "zh": "相关性",
        "en": "Correlation",
        "icon": "⊞",
        "mode": "iframe",
        "desc_zh": "变量相关热力图",
        "desc_en": "Correlation heatmaps",
        "panel": "panel-chart",
    },
)


def brand_header_html(
    title: str,
    subtitle: str,
    *,
    variant: str = "hub",
    lang: str = "zh",
    logo_href_path: str | None = None,
) -> str:
    surface: SurfaceKind = "data" if variant in ("hub", "standalone") else "report"
    logo_size = 48 if variant in ("hub", "standalone") else 52
    lockup = brand_lockup_html(
        lang=lang,
        logo_href_path=logo_href_path,
        size=logo_size,
        surface=surface,
    )
    variant_class = f"brand-header brand-header--{variant}"
    return f"""<header class="{variant_class}">
  {lockup}
  <div class="brand-title-block">
    <h1>{title}</h1>
    <p class="brand-subtitle">{subtitle}</p>
  </div>
</header>"""


def html_tab_switcher_script() -> str:
    return """
<script>
(function () {
  function activateTab(bar, tabId) {
    bar.querySelectorAll(".tab").forEach(function (t) {
      var on = t.getAttribute("data-tab") === tabId;
      t.classList.toggle("active", on);
      t.setAttribute("aria-selected", on ? "true" : "false");
    });
    var root = bar.closest(".tab-root") || bar.parentElement;
    (root.querySelectorAll(".tab-panel") || []).forEach(function (p) {
      p.classList.toggle("active", p.getAttribute("data-panel") === tabId);
    });
  }
  document.querySelectorAll(".tab-bar").forEach(function (bar) {
    bar.addEventListener("click", function (e) {
      var btn = e.target.closest(".tab");
      if (!btn) return;
      activateTab(bar, btn.getAttribute("data-tab"));
    });
  });
})();
</script>"""


def report_design_tokens_css() -> str:
    u = REPORT_UI
    return f"""
    :root {{
      --as-text: {u["text"]};
      --as-muted: {u["text_muted"]};
      --as-bg: {u["bg"]};
      --as-bg-subtle: {u["bg_subtle"]};
      --as-bg-warm: {u["bg_warm"]};
      --as-panel: {u["bg_panel"]};
      --as-border: {u["border"]};
      --as-border-light: {u["border_light"]};
      --as-accent: {u["accent"]};
      --as-link: {u["link"]};
      --as-blue: {u["node_blue"]};
      --as-green: {u["node_green"]};
      --as-amber: {u["node_amber"]};
      --as-font-serif: "Source Serif 4", "Noto Serif SC", "Songti SC", serif;
      --as-font-sans: "IBM Plex Sans", "PingFang SC", "Microsoft YaHei", sans-serif;
      --as-font-mono: "IBM Plex Mono", "SF Mono", ui-monospace, monospace;
      --as-radius: 8px;
      --as-radius-sm: 5px;
      --as-shadow: 0 1px 2px rgba(26, 24, 20, 0.05), 0 10px 28px rgba(26, 24, 20, 0.07);
      --as-shadow-sm: 0 1px 3px rgba(26, 24, 20, 0.06);
    }}
    """


def _chrome_base_css() -> str:
    return (
        report_design_tokens_css()
        + """
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: var(--as-font-sans);
      font-size: 15px;
      line-height: 1.6;
      color: var(--as-text);
      background: var(--as-bg-subtle);
      background-image:
        radial-gradient(ellipse 120% 80% at 100% -20%, rgba(196, 30, 58, 0.04), transparent 50%),
        radial-gradient(ellipse 80% 60% at 0% 100%, rgba(0, 114, 178, 0.04), transparent 45%);
    }}
    a {{ color: var(--as-link); text-decoration-thickness: 1px; text-underline-offset: 2px; }}
    a:hover {{ color: #004d99; }}
    .brand-header {{
      display: flex;
      flex-direction: column;
      gap: 18px;
      padding: 22px 28px;
      background: var(--as-bg);
      border-bottom: 1px solid var(--as-border);
      box-shadow: var(--as-shadow);
    }}
    .brand-header--hub {{
      border-bottom: 3px solid transparent;
      border-image: linear-gradient(90deg, var(--as-accent), var(--as-blue), var(--as-green)) 1;
      background: linear-gradient(165deg, var(--as-bg) 0%, var(--as-panel) 100%);
    }}
    .brand-header--standalone {{
      border-bottom: 1px solid var(--as-border-light);
      box-shadow: none;
      padding: 18px 24px;
    }}
    .brand-header--report {{
      padding: 0 0 16px;
      border: none;
      box-shadow: none;
      background: transparent;
      margin-bottom: 4px;
    }}
    .brand-lockup {{ display: flex; align-items: center; gap: 14px; min-width: 0; }}
    .brand-text {{ min-width: 0; }}
    .brand-logo {{
      --logo-size: 52px;
      display: block;
      flex-shrink: 0;
      width: var(--logo-size);
      height: var(--logo-size);
      border-radius: calc(var(--logo-size) * 0.26);
      object-fit: contain;
    }}
    .brand-wordmark {{
      display: block;
      font-family: var(--as-font-sans);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.16em;
      color: var(--as-text);
    }}
    .brand-tagline {{ display: block; font-size: 0.8rem; color: var(--as-muted); margin-top: 4px; line-height: 1.35; }}
    .brand-name, .brand-tag {{ display: none; }}
    .brand-title-block h1 {{
      font-family: var(--as-font-serif);
      font-size: clamp(1.2rem, 2.5vw, 1.55rem);
      font-weight: 600;
      margin: 0 0 6px;
      line-height: 1.25;
      letter-spacing: -0.02em;
    }}
    .brand-subtitle {{ margin: 0; font-size: 0.9rem; color: var(--as-muted); max-width: 42em; }}
    .tab-root {{ margin-top: 8px; }}
    .tab-bar {{
      display: flex;
      flex-wrap: wrap;
      gap: 4px;
      align-items: stretch;
      padding: 4px;
      background: var(--as-bg-warm);
      border-radius: var(--as-radius);
      border: 1px solid var(--as-border-light);
    }}
    .tab {{
      display: inline-flex;
      align-items: center;
      gap: 7px;
      padding: 10px 16px;
      border: none;
      background: transparent;
      color: var(--as-muted);
      font-weight: 600;
      font-size: 0.84rem;
      cursor: pointer;
      border-radius: 4px;
      transition: background 0.18s, color 0.18s, box-shadow 0.18s;
    }}
    .tab:hover {{ color: var(--as-text); background: rgba(255,255,255,0.7); }}
    .tab.active {{
      color: var(--as-text);
      background: var(--as-bg);
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }}
    .tab.tab--featured {{ font-weight: 700; }}
    .tab-icon {{ font-size: 0.9rem; opacity: 0.9; line-height: 1; }}
    .tab-badge {{
      font-size: 0.6rem;
      padding: 2px 7px;
      border-radius: 999px;
      background: var(--as-accent);
      color: #fff;
      font-weight: 700;
      letter-spacing: 0.04em;
    }}
    .tab-panel {{ display: none; padding: 20px 4px 12px; animation: as-fade 0.25s ease; }}
    .tab-panel.active {{ display: block; }}
    @keyframes as-fade {{ from {{ opacity: 0; transform: translateY(4px); }} to {{ opacity: 1; transform: none; }} }}
    @media (prefers-reduced-motion: reduce) {{
      .tab-panel {{ animation: none; }}
      .tab {{ transition: none; }}
    }}
    .panel-intro {{ font-size: 0.9rem; color: var(--as-muted); margin: 0 0 14px; max-width: 54em; line-height: 1.55; }}
    .panel-intro strong {{ color: var(--as-text); font-weight: 600; }}
    .eda-frame {{
      width: 100%;
      min-height: 72vh;
      border: 1px solid var(--as-border);
      background: var(--as-bg);
      border-radius: var(--as-radius);
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.8);
    }}
    .iframe-hint {{ font-size: 0.84rem; margin-bottom: 12px; color: var(--as-muted); }}
    .tool-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(210px, 1fr));
      gap: 12px;
      margin: 16px 0 4px;
    }}
    .tool-card {{
      display: flex;
      flex-direction: column;
      gap: 4px;
      padding: 14px 16px;
      background: var(--as-bg);
      border: 1px solid var(--as-border-light);
      border-radius: var(--as-radius);
      text-decoration: none;
      color: inherit;
      transition: transform 0.15s, border-color 0.15s, box-shadow 0.15s;
    }}
    .tool-card:hover {{
      border-color: var(--as-blue);
      box-shadow: var(--as-shadow);
      transform: translateY(-2px);
    }}
    .tool-card-icon {{ font-size: 1.15rem; color: var(--as-blue); line-height: 1; }}
    .tool-card-title {{ font-weight: 600; font-size: 0.92rem; }}
    .tool-card-desc {{ font-size: 0.78rem; color: var(--as-muted); line-height: 1.4; }}
    .eda-tool-deck {{ margin-top: 20px; padding-top: 16px; border-top: 1px dashed var(--as-border); }}
    .tool-deck-title {{
      font-family: var(--as-font-serif);
      font-size: 1rem;
      font-weight: 600;
      margin: 0 0 8px;
    }}
    .tab-panel.panel-explore .eda-frame {{ min-height: 80vh; border-color: #a8c5da; }}
    .tab-panel.panel-chart .eda-frame {{ min-height: 68vh; }}
    .tab-panel.panel-table .eda-frame {{ min-height: 74vh; }}
    .tab-panel.panel-profile .eda-frame {{ min-height: 82vh; }}
    .eda-quick-stats {{
      font-family: var(--as-font-mono);
      font-size: 0.8rem;
      line-height: 1.5;
      background: var(--as-bg);
      border: 1px solid var(--as-border-light);
      padding: 16px 18px;
      overflow-x: auto;
      white-space: pre-wrap;
      margin: 0;
      border-radius: var(--as-radius);
    }}
    """
        + report_responsive_css()
    )


def report_responsive_css() -> str:
    return """
    img, iframe, video { max-width: 100%; height: auto; }
    .page { width: min(100%, 1000px); }
    .tab-bar {
      overflow-x: auto;
      overflow-y: hidden;
      -webkit-overflow-scrolling: touch;
      scrollbar-width: thin;
    }
    .tab-bar .tab { flex-shrink: 0; white-space: nowrap; }
    @media (max-width: 960px) {
      .content-grid.has-toc { grid-template-columns: 1fr; }
      .report-toc {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        position: static;
        max-height: none;
        padding: 14px 18px;
        border-right: none;
        border-bottom: 1px solid var(--as-border-light);
      }
      .report-toc strong { width: 100%; margin-bottom: 4px; }
      .report-toc a {
        border-left: none;
        border-radius: 999px;
        padding: 6px 12px;
        background: var(--as-bg);
        border: 1px solid var(--as-border-light);
      }
    }
    @media (max-width: 720px) {
      body { font-size: clamp(14px, 3.6vw, 15px); }
      .page { margin: 12px auto 32px; border-radius: var(--as-radius-sm); }
      .brand-header, .header { padding: 20px 18px 18px; }
      .hub-body, .standalone-body, .index-body { padding: 14px 18px 22px; }
      .metrics { padding: 16px 18px; gap: 10px; grid-template-columns: repeat(2, minmax(0, 1fr)); }
      main, .hub-body { padding-left: 18px; padding-right: 18px; }
      .limitations { margin-left: 18px; margin-right: 18px; }
      .eda-interactive { padding: 16px; margin: 24px 0 28px; }
      .eda-frame { min-height: min(520px, 62vh); }
      .figure-block { padding: 14px; }
      .brand-wordmark { letter-spacing: 0.12em; font-size: 0.72rem; }
      .brand-tagline { font-size: 0.78rem; }
    }
    @media (max-width: 520px) {
      .metrics { grid-template-columns: 1fr; }
      .brand-lockup {
        flex-direction: row;
        align-items: center;
        gap: 12px;
      }
      .brand-logo { --logo-size: 48px; }
      .header-report h1, .brand-title-block h1 {
        font-size: clamp(1.15rem, 5vw, 1.35rem);
      }
      .tab {{ padding: 8px 12px; font-size: 0.8rem; }}
      .tool-grid { grid-template-columns: 1fr; }
      table.data-table th, table.data-table td { padding: 8px 10px; font-size: 0.82rem; }
      .chart-frame { min-height: 280px; }
    }
    @media (max-width: 380px) {
      .brand-lockup { flex-wrap: wrap; }
      .brand-text { flex: 1 1 140px; }
    }
    """


def eda_hub_page_css() -> str:
    return (
        _chrome_base_css()
        + """
    .hub-shell { max-width: 1280px; margin: 0 auto; padding: 0 0 48px; }
    .hub-body { padding: 20px 28px 32px; }
    .hub-empty {
      padding: 28px;
      color: var(--as-muted);
      background: var(--as-bg);
      border: 1px dashed var(--as-border);
      border-radius: var(--as-radius);
    }
    """
    )


def report_eda_section_css() -> str:
    return (
        _chrome_base_css()
        + """
    .eda-interactive {
      margin: 32px 0 40px;
      padding: 24px 24px 20px;
      background: var(--as-bg);
      border: 1px solid var(--as-border-light);
      border-radius: var(--as-radius);
      box-shadow: var(--as-shadow);
      border-left: 4px solid var(--as-blue);
    }
    .eda-section-title {
      font-family: var(--as-font-serif);
      font-size: 1.12rem;
      font-weight: 600;
      margin: 0 0 16px;
      display: flex;
      align-items: center;
      gap: 10px;
    }
    .eda-section-title::before {
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background: linear-gradient(135deg, var(--as-accent), var(--as-blue));
      flex-shrink: 0;
    }
    .eda-interactive .tab-panel.panel-summary {
      background: var(--as-panel);
      padding: 20px 22px;
      border: 1px solid var(--as-border-light);
      border-radius: var(--as-radius-sm);
    }
    .eda-interactive .tab-panel.panel-hub .eda-frame {
      min-height: min(720px, 75vh);
      border: 1px solid var(--as-border);
      border-radius: var(--as-radius-sm);
      box-shadow: var(--as-shadow-sm);
    }
    """
    )


def eda_hub_css() -> str:
    return eda_hub_page_css()


def eda_datatable_css() -> str:
    u = REPORT_UI
    base = _chrome_base_css()
    return (
        base
        + f"""
    .standalone-wrap {{ max-width: 100%; margin: 0; padding: 0 0 24px; }}
    .standalone-body {{ padding: 12px 24px 24px; }}
    .standalone-body h1 {{ font-size: 1.1rem; font-weight: 600; margin: 0 0 8px; }}
    input {{ padding: 6px 10px; border: 1px solid {u["border"]}; min-width: 220px; font-size: 0.88rem; border-radius: 2px; }}
    .meta {{ font-size: 0.85rem; color: {u["text_muted"]}; }}
    .wrap {{ overflow: auto; border: 1px solid {u["border_light"]}; background: {u["bg"]}; border-radius: 2px; }}
    table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
    th, td {{ border-bottom: 1px solid {u["border_light"]}; padding: 8px 10px; text-align: left; white-space: nowrap; }}
    th {{ background: {u["bg_panel"]}; cursor: pointer; position: sticky; top: 0; font-weight: 600; }}
    tr:hover td {{ background: {u["bg_subtle"]}; }}
    .toolbar {{ margin: 12px 0; display: flex; gap: 12px; flex-wrap: wrap; align-items: center; }}
    """
    )


def eda_index_page_css() -> str:
    u = REPORT_UI
    return (
        _chrome_base_css()
        + f"""
    .index-shell {{ max-width: 720px; margin: 0 auto; padding: 0 0 32px; }}
    .index-body {{ padding: 16px 24px 28px; }}
    .index-body table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
    .index-body th, .index-body td {{ border: 1px solid {u["border_light"]}; padding: 12px 14px; text-align: left; }}
    .index-body th {{ background: {u["bg_panel"]}; font-weight: 600; }}
    .index-body tr:hover {{ background: {u["bg_subtle"]}; }}
    td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
    """
    )


def plotly_report_layout(**overrides: Any) -> dict[str, Any]:
    layout: dict[str, Any] = {
        "template": "plotly_white",
        "font": {
            "family": "Arial, Helvetica, sans-serif",
            "size": 11,
            "color": REPORT_UI["text"],
        },
        "paper_bgcolor": REPORT_UI["bg"],
        "plot_bgcolor": REPORT_UI["bg"],
        "colorway": list(OKABE_ITO),
        "margin": {"l": 56, "r": 24, "t": 48, "b": 48},
    }
    layout.update(overrides)
    return layout


def export_plotly_html(
    fig: Any,
    path: str | Path,
    *,
    include_plotlyjs: bool = True,
) -> Path:
    fig.update_layout(**plotly_report_layout())
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.write_html(str(out), include_plotlyjs=include_plotlyjs)
    return out


def export_altair_html(
    chart: Any,
    path: str | Path,
    *,
    inline: bool = True,
) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    chart.save(str(out), inline=inline)
    return out


def export_pygwalker_html(
    df: pd.DataFrame,
    path: str | Path,
    *,
    embed_lib: bool = True,
) -> Path:
    import pygwalker as pyg

    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    html = pyg.to_html(df, embed_lib=embed_lib)
    out.write_text(html, encoding="utf-8")
    return out
