# Frontend Design × AgentSociety Analysis Reports

Read `support/frontend-design/SKILL.md` (or `.claude/skills/agentsociety-analysis/support/frontend-design/SKILL.md` in the workspace) for craft. This file **scopes** it to simulation analysis HTML — not landing pages.

## When to combine skills

| Task                                | Skills                                                                                                     |
| ----------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| `report_zh.html` / `report_en.html` | **agentsociety-analysis** + **report-blocks** + **frontend-design** (this bridge)                          |
| IDE metric exploration              | Cursor **canvas** skill — see `references/reports.md` for the canvas-vs-disk boundary                      |
| `presentation/.../data/eda_*.html`  | Already interactive (ydata/Sweetviz); embed via iframe per agentsociety-analysis `references/eda.md` |
| Marketing site / dashboard          | frontend-design only                                                                                       |

## Non-negotiable analysis constraints (override frontend-design defaults)

1. **Evidence first** — numbers match `report_context.md` and Markdown reports; no decorative KPIs.
2. **Scientific tone** — follow `assets/report-shell.reference.html` (warm paper + Nature accent); official logo only; LLM may refine layout/typography, not redraw the mark; no purple-gradient-on-white unless user asks.
3. **Interactivity** — preserve Tab + iframe to `data/eda_profile.html` / `data/eda_sweetviz.html`; polish tab bar, iframe chrome, table hover only.
4. **No MD→HTML** — refine authored HTML; do not run pandoc on `report_zh.md`.
5. **Paths** — `assets/` for figures + **`assets/agentsociety_icon.svg`** (official logo, copied from repo `static/`), `data/` for EDA; run `sync-report-assets` before final HTML.
6. **Logo** — `agentsociety_icon.svg` is auto-tinted on copy (SVG filter, shape unchanged). Paths: `assets/...` in reports; same-folder in shell. No extra border/frame around the icon.

## What to steal from frontend-design

- Distinctive but readable font pairing (e.g. display for `h1`, refined body — avoid Inter if possible)
- CSS variables for spacing and colors aligned with shell
- Subtle motion: tab transition, table row hover, optional `prefers-reduced-motion` respect
- Refined figure cards and data-table typography

## Read order

1. `agentsociety-analysis` → `references/reports.md`, `references/eda.md`
2. `assets/report-shell.reference.html` (in agentsociety-analysis)
3. `support/frontend-design/SKILL.md` (general craft)
4. This file (scope guardrails)

## Source

Bundled from [anthropics/skills `frontend-design`](https://github.com/anthropics/skills/tree/main/skills/frontend-design) (Apache-2.0, see `LICENSE.txt`).
