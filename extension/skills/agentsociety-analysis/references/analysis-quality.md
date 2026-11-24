# Analysis Quality Standard

The harness proves **structure and traceability**. This document defines what **high-quality** analysis means. Do not treat `validate-*` PASS as sufficient if the science or narrative is weak.

## Quality bar (before any gate)

Ask yourself:

1. Would a skeptical colleague accept the claim **without** seeing the simulation code?
2. Can every number in the report be traced to a replay dataset query or registered artifact?
3. Are limitations of **simulation evidence** stated plainly (not buried)?
4. Is the main message visible in **10 seconds** on each chart?

If any answer is no, improve content before `record-attestation`.

## Per-phase quality (LLM-owned)

### Frame

- Research question is **falsifiable** on available data.
- Primary metrics match hypothesis wording (not vague “outcomes”).
- Confirmatory claims are listed **before** deep exploration.

### Explore

- Explain **why** each target table matters; note empty columns, time range, agent count.
- EDA informs doubt or confidence — do not copy EDA boilerplate into final claims.
- Record real artifact paths after `run-eda`.

### Claims

- Each claim has `mode`: confirmatory vs exploratory.
- Evidence field names table + column or SQL file path, not “the data shows”.
- User explicitly aligned before refine — reflect in attestation `claims_user_approved`.

### Refine

- One visual = one message; no decorative charts.
- Same condition → same color across charts.
- Composite figures only when one finding needs multiple views.

### Produce

- Run `build-report-context` first; **data** section synthesizes EDA from `report_context.md`, not orphan files.
- Chinese and English reports tell the **same story** (not machine-translated slop).
- `report_outline.json` captions match what a reader should take away.
- `limitations` in `analysis_summary.json` mentions external validity of simulation.

### Synthesis

- Integrates scoped hypotheses; surfaces **agreement and tension**.
- Does not over-claim from a single run.
- `synthesis_brief.json` lists every `source_artifacts` path you actually used.

## Anti-patterns (reject even if gates pass)

| Anti-pattern                                | Why it fails quality                 |
| ------------------------------------------- | ------------------------------------ |
| Chart-first exploration                     | HARKing — story follows pretty plots |
| Generic “results show interesting patterns” | No testable claim                    |
| Causal language for ABM output              | Misleading without caveats           |
| 5 weak charts                               | Quantity over argument               |
| Skipping synthesis as summary of one report | Misses workspace-level insight       |

## When to use DONE_WITH_CONCERNS

Use attestation status `DONE_WITH_CONCERNS` when structure is ready but:

- Sample size is tiny
- One confirmatory claim failed but exploratory follow-ups exist
- User accepted a deliberate scope cut

Document why in `key_findings` and `recommended_next_step`.

## References while writing

- Methods: `references/analysis-methods.md`
- Chart choice & QA: `references/charts.md`
- Payload shapes: `references/json-payloads.md`
- Produce checklist: `checklists/quality.md`
