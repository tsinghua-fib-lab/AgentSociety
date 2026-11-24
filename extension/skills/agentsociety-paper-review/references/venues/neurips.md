# NeurIPS Template

- Verified edition: NeurIPS 2025 main track
- Verified at: 2026-07-17
- Official source: https://neurips.cc/Conferences/2025/ReviewerGuidelines
- Scale origin: `official`
- Scope: author-side internal mock review; not an official NeurIPS review

Use this template for NeurIPS only when the user accepts calibration to the 2025 main-track form or the target edition uses the same fields. Verify a newer edition before claiming exact fidelity.

## Required Fields

1. Summary
2. Strengths and Weaknesses covering Quality, Clarity, Significance, and Originality
3. Quality score
4. Clarity score
5. Significance score
6. Originality score
7. Questions, ideally 3–5 actionable decision-relevant items
8. Limitations and potential negative societal impact
9. Overall score
10. Confidence
11. Ethical concerns

## Dimension Scores

Quality, Clarity, Significance, and Originality each use:

| Score | Label |
|-------|-------|
| 4 | excellent |
| 3 | good |
| 2 | fair |
| 1 | poor |

If a dimension is `fair` or `poor`, the Strengths and Weaknesses section must contain a clear reason.

## Overall Score

| Score | Label | Normalized recommendation |
|-------|-------|---------------------------|
| 6 | Strong Accept | `strong_accept` |
| 5 | Accept | `accept` |
| 4 | Borderline Accept | `weak_accept` |
| 3 | Borderline Reject | `weak_reject` |
| 2 | Reject | `reject` |
| 1 | Strong Reject | `strong_reject` |

Use borderline scores sparingly. Judge the paper holistically; do not average the four dimension scores.

## Confidence

| Score | Meaning |
|-------|---------|
| 5 | absolutely certain; very familiar with related work and checked technical details carefully |
| 4 | confident but not absolutely certain |
| 3 | fairly confident; may have missed some content or related work, and details were not all checked |
| 2 | willing to defend the assessment, but likely misunderstood central parts or missed related work |
| 1 | educated guess; outside the area or paper was difficult to understand |

## NeurIPS-Specific Checks

- Quality: technical soundness, claim support, appropriate methods, completeness, and honest evaluation.
- Clarity: organization, readability, and enough information for an expert to reproduce results.
- Significance: demonstrable value or impact for researchers or practitioners, including data, findings, efficiency, or understanding.
- Originality: new insights, tasks, methods, combinations, or properties—not only entirely new algorithms.
- Questions: state the evidence or answer under which the evaluation would increase or decrease.
- Limitations: reward candid disclosure; identify missing limitations or societal impacts constructively.
- Ethics: flag a concern only with concrete rationale; an internal mock review cannot initiate an official ethics review.
