# ICML Template

- Verified edition: ICML 2026 main track
- Verified at: 2026-07-17
- Official source: https://icml.cc/Conferences/2026/ReviewerInstructions
- Scale origin: `official`
- Scope: author-side internal mock review; not an official ICML review

## Required Fields

1. Summary
2. Strengths and Weaknesses
3. Soundness score
4. Presentation score
5. Significance score
6. Originality score
7. Key Questions for Authors, ideally 3–5
8. Limitations and potential negative societal impact
9. Overall Recommendation
10. Confidence
11. Ethical Concerns

## Dimension Scores

Soundness, Presentation, Significance, and Originality each use:

| Score | Label |
|-------|-------|
| 4 | excellent |
| 3 | good |
| 2 | fair |
| 1 | poor |

Every `fair` or `poor` score requires a specific justification in Strengths and Weaknesses.

## Overall Recommendation

| Score | Label | Normalized recommendation |
|-------|-------|---------------------------|
| 6 | Strong Accept | `strong_accept` |
| 5 | Accept | `accept` |
| 4 | Weak Accept | `weak_accept` |
| 3 | Weak Reject | `weak_reject` |
| 2 | Reject | `reject` |
| 1 | Strong Reject | `strong_reject` |

Use 4 and 3 sparingly. The overall score is holistic and must not be derived mechanically from dimension scores.

## Confidence

| Score | Meaning |
|-------|---------|
| 5 | absolutely certain; very familiar with related work and checked math or other details carefully |
| 4 | confident but not absolutely certain |
| 3 | fairly confident; may have missed parts or related work, and details were not all checked |
| 2 | willing to defend the assessment, but likely misunderstood central parts or missed related work |
| 1 | educated guess; outside the area or paper was difficult to understand |

## ICML-Specific Checks

- Summary must reflect the reviewer's understanding, not copy the abstract.
- Strengths and Weaknesses must touch soundness, presentation, significance, and originality.
- Verify that proofs, assumptions, experiments, and empirical conclusions substantiate the claimed contributions.
- Treat missing related work according to whether its inclusion would change the paper's conclusions; not every omission is major.
- Key questions should be reserved for answers likely to change the score, resolve confusion, or address a critical limitation.
- Assess whether limitations and potential negative societal impact are adequately discussed.
- Record concrete ethical concerns separately from ordinary technical limitations.

## Policy Boundary

ICML reviewer LLM policies can differ by track and edition, including tracks where LLM use in reviewing is prohibited. This skill is only for authorized author-side internal review. Never use this template to imply that an assigned official reviewer may upload a confidential submission to an AI system.
