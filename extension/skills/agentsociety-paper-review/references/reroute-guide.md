# Advisory Reroute Guide

Rerouting identifies where the evidence gap originated. It does not authorize the reviewer to change files or run work.

## Controlled Vocabulary

| Reroute | Use when the decisive gap is... | Typical resolution evidence |
|---------|---------------------------------|-----------------------------|
| `literature_search` | missing, stale, or misrepresented prior work; novelty cannot be established | updated literature index and corrected comparison/evidence map |
| `hypothesis` | unfalsifiable, ambiguous, unsupported, or materially changed research question/claim | revised hypothesis with explicit constructs, mechanism, predictions, and falsifiers |
| `experiment_config` | design cannot test the claim; missing controls, measures, baselines, power, robustness plan, or simulation setup | checked config and design rationale that can test the stated claim |
| `run_experiment` | sound checked design exists but required runs are missing, incomplete, stale, or failed | complete run artifacts and logs for the approved configuration |
| `analysis` | data exist but statistical inference, robustness, evidence traceability, interpretation, or figures do not support the claim | revised analysis report, claims, tables, figures, and limitations grounded in run data |
| `generate_paper` | underlying evidence is adequate but exposition, organization, citations already found, claim wording, formatting, or disclosure is deficient | revised manuscript that accurately presents existing evidence |
| `human_decision` | ethics, research integrity, legal/privacy risk, irreducible scope trade-off, or foundational pivot requires accountable judgment | explicit user/PI decision and documented constraints |
| `none` | no material issue warrants a research-stage revisit | no follow-up required beyond optional minor polish |

## Selection Algorithm

For each concern:

1. Identify the claim or venue criterion affected.
2. Identify the earliest point at which the missing or invalid evidence could have been prevented.
3. Choose the smallest sufficient reroute at that point.
4. State the exact evidence that would close the concern.
5. Do not chain execution. Later agents choose the next action.

Choose the review's `primary_reroute` from the highest-severity, highest-decision-impact concern. If several issues tie, prefer the earliest upstream stage because downstream repair depends on it.

## Distinguishing Adjacent Stages

### Literature Search vs Hypothesis

- Use `literature_search` when the core claim might be novel or well-motivated, but the paper has not established that against prior work.
- Use `hypothesis` when the claimed mechanism, constructs, or falsifiable prediction is itself unclear or unsupported, even with adequate literature coverage.

### Hypothesis vs Experiment Config

- Use `hypothesis` when it is unclear what result would support or refute the claim.
- Use `experiment_config` when the claim is testable but the proposed design, population, variables, controls, or metrics cannot test it.

### Experiment Config vs Run Experiment

- Use `experiment_config` when a new control, baseline, metric, population, seed plan, or intervention definition is needed.
- Use `run_experiment` only when the required checked configuration already exists and merely needs to be executed or completed.
- Never route directly to `run_experiment` to bypass a design change.

### Run Experiment vs Analysis

- Use `run_experiment` when required raw outcomes are absent or invalid.
- Use `analysis` when the required raw outcomes exist but are aggregated, tested, visualized, or interpreted incorrectly or incompletely.

### Analysis vs Generate Paper

- Use `analysis` when a claim needs different inference, uncertainty, robustness, evidence linkage, or limitation treatment.
- Use `generate_paper` when existing analysis already supports the claim and only the manuscript's communication is deficient.
- Weak prose is not evidence that new experiments are needed.

### Human Decision

Use `human_decision` when autonomous continuation would require a value judgment or new authority, including:

- participant risk, consent, privacy, or dual-use decisions;
- suspected fabrication, plagiarism, or irreconcilable provenance gaps;
- whether to abandon or substantially change the project's central objective;
- whether the cost or scope of a requested experiment is acceptable;
- conflicts between venue policy and intended AI use.

## Examples

| Review finding | Reroute | Why |
|----------------|---------|-----|
| A central baseline is missing and the current config never defined it | `experiment_config` | the comparison must be designed before it can be run |
| Baseline config exists and passed validation, but its run directory is absent | `run_experiment` | design exists; evidence generation is incomplete |
| Results report means only, despite available repeated-run data | `analysis` | raw evidence exists; inference and uncertainty are missing |
| Causal language overstates a correlational simulation result | `analysis` if interpretation originates in claims; `generate_paper` if the analysis is already correctly qualified | route to the actual source of the overclaim |
| The main idea appears identical to uncited prior work | `literature_search` | novelty and attribution require renewed literature evidence |
| Abstract omits an already documented limitation | `generate_paper` | no upstream scientific work is required |
| Human-subject data provenance is unclear | `human_decision` | accountable ethics/privacy review is required |

## Anti-patterns

- Do not use `generate_paper` as a catch-all when evidence is scientifically insufficient.
- Do not use `run_experiment` for every request for “more experiments.”
- Do not recommend all stages. Prefer one primary route and only necessary ordered secondary routes.
- Do not route minor typos, style preferences, or optional citations upstream.
- Do not emit shell commands or mutate pipeline state in the review.
