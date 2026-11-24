# Analysis Methods

Pick the lightest method that can support the claim.

## Method Hints

- Descriptive statistics first: counts, shares, averages, medians, ranges, and simple group splits should come before inferential claims.
- Correlation: use only when both variables have enough non-null support and the relationship matters to the question.
- Group comparison: compare effect size and practical difference, not only p-values.
- Time trend: verify ordering, missing intervals, and whether smoothing hides meaningful variance.
- Categorical patterns: use frequency tables before jumping to more complex modeling.
- Inequality or concentration: use distribution summaries or inequality metrics only when the hypothesis is actually about spread or concentration.
- Cross-experiment comparison: align metrics, sample scope, and run conditions before drawing comparison charts; identical filenames do not imply identical semantics.
- Multi-seed or replicated runs: prefer seed-aware summaries or interval plots over reporting one lucky run.

## Interpretation Constraints

- Simulation outputs are synthetic evidence, not direct real-world proof.
- Distinguish observation, association, and causal claims explicitly.
- If data quality is weak, downgrade the strength of the conclusion rather than forcing a stronger method.
- Separate environment mechanics, agent behavior, and aggregate outcomes; avoid collapsing all three into one causal sentence.
- When a claim depends on derived metrics, keep the formula or aggregation rule beside the finding or in the appendix artifact table.
