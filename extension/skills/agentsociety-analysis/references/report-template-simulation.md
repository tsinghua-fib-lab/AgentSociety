# Simulation Analysis Report Template (ABM / AgentSociety)

Adapted from CompeteAI `competition-dynamics-analysis` and deep-research section contracts. Use with `report_zh.md` / `report_en.md` — headings may be `##` in Chinese or English.

## Recommended sections

### 1. 实验设置 / Experiment setup

- Hypothesis and research question (from `analysis_plan.yaml`)
- Agent/environment configuration, run length, seeds
- Data source: `hypothesis_{id}/experiment_{id}/run/replay/`

### 2. 数据与探索 / Data and exploration

**Integrate EDA here** (from `data/report_context.md`; see `report-embeddings.md`):

- Target tables and row counts (prefer a **small table**, not a screenshot)
- Missingness / time range / key variable distributions as bullets
- Pull numbers from `eda_quick_stats.md` or SQL — do not paste raw profiler HTML in the body
- Appendix: link `data/eda_profile.html` and list EDA files in artifact table

### 3. 核心发现 / Findings

One subsection per **confirmatory** claim (`claims.json`):

- Claim statement
- Evidence (table, SQL, or statistic)
- Figure: `![caption](assets/chart_nn_slug.png)` + one-line caption (after `collect-assets`)
- Optional: compact evidence table (condition A vs B) beside the figure
- Caveat if exploratory or single-run simulation

### 4. 结论 / Conclusions

- Direct answer to research question
- What would falsify the result
- **Simulation limitations** (external validity, single seed, etc.)

### 5. 附录 / Appendix

- Artifact table (`filename`, `type`, `description`, finding #)
- Optional links: `data/eda_profile.html`

## Metric table (when applicable)

| Metric | Condition A | Condition B | Notes |
|--------|-------------|-------------|-------|
| (from SQL) | | | |

## Quality checks

- Every number traceable to a replay dataset query or registered artifact
- EDA informs §2; charts defend §3 only
- Same narrative order in `report_en.md` as `report_zh.md`
