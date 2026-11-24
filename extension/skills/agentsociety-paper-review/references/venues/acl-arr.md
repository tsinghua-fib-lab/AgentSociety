# ACL Rolling Review Template

- Verified form: ACL Rolling Review form in effect after the February 2025 scoring change
- Verified at: 2026-07-17
- Official form: https://aclrollingreview.org/reviewform
- Official guidance: https://aclrollingreview.org/reviewerguidelines
- Scale origin: `official`
- Scope: author-side internal mock review; not an official ARR review

## Required Fields

1. Paper Summary
2. Summary of Strengths
3. Summary of Concerns, numbered where possible
4. Comments, Suggestions, and Typos
5. Reviewer Confidence
6. Soundness
7. Excitement
8. Overall Assessment
9. Best Paper Justification when overall assessment is 4.5 or 5
10. Limitations and Societal Impact
11. Ethical Concerns and whether an ethics review would be needed
12. Reproducibility
13. Dataset and Software value when applicable

## Reviewer Confidence

Use the official 1–5 scale:

- 5: positive the evaluation is correct; read very carefully and familiar with related work;
- 4: quite sure; important points checked carefully;
- 3: pretty sure, but details such as math or experimental design were not checked fully;
- 2: willing to defend, but likely missed details, central points, or novelty context;
- 1: outside the area or an educated guess.

## Soundness

Use half-point increments:

| Score | Anchor |
|-------|--------|
| 5 | Excellent; exceptionally thorough for its paper type |
| 4 | Strong; sufficient support for all claims, with only nonessential additions possible |
| 3 | Acceptable; main claims supported, with minor support or detail gaps |
| 2 | Poor; some main claims unsupported or major technical/methodological problems |
| 1 | Major Issues; not sufficiently thorough for publication or not relevant to ACL |

Scores 1.5, 2.5, 3.5, and 4.5 interpolate between anchors. Low soundness must be justified by concrete faults in the review text.

## Excitement

Use half-point increments:

| Score | Anchor |
|-------|--------|
| 5 | Highly Exciting; recommend to others or attend its presentation |
| 4 | Exciting; mention to others or make an effort to attend |
| 3 | Interesting; might mention or attend if time permits |
| 2 | Potentially Interesting; may resonate with others in the ACL community |
| 1 | Not Exciting; unlikely to resonate with the ACL community |

Excitement is subjective and orthogonal to soundness. Do not manufacture technical weaknesses to justify a low excitement score.

## Overall Assessment

Use half-point increments:

| Score | Label | Normalized recommendation |
|-------|-------|---------------------------|
| 5 | Consider for Award | `strong_accept` |
| 4.5 | Borderline Award | `strong_accept` |
| 4 | Conference | `accept` |
| 3.5 | Borderline Conference | `weak_accept` |
| 3 | Findings | `findings` |
| 2.5 | Borderline Findings | `borderline` |
| 2 | Resubmit next cycle | `revise_and_resubmit` |
| 1.5 | Resubmit after next cycle | `revise_and_resubmit` |
| 1 | Do not resubmit | `strong_reject` |

This is a composite recommendation reflecting soundness, excitement, novelty, impact, and reproducibility. Main-conference recommendations can be justified even when personal excitement is modest.

## Reproducibility

Use 1–5:

- 5: main results could be reproduced easily;
- 4: mostly reproducible, with minor variation likely;
- 3: reproducible with difficulty because settings or data are underspecified;
- 2: very difficult because material data or details are unavailable;
- 1: impossible to reproduce from the available information.

Score Dataset and Software value from 1–5 only when the paper makes an applicable release claim. Otherwise mark them `N/A` with rationale.
