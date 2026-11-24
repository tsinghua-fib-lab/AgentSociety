# AAAI Template

- Verified edition: AAAI-26 main technical track
- Verified at: 2026-07-17
- Official reviewer instructions: https://docs.google.com/document/d/1tqQGwtNUlALPSTqoTo5uTFx8vKuqpILNTne9jeBCOVI/mobilebasic
- Official criteria: https://aaai.org/conference/aaai/aaai-26/main-technical-track-call/
- Scale origin: `project_local`
- Scope: author-side internal mock review; not an official AAAI review or AAAI AI-pilot output

AAAI-26 recommends a review structure but does not require a fixed one. Its public instructions call for a paper summary, review summary, and specific feedback. The public criteria assess significance and novelty, theoretical or empirical soundness, AAAI relevance, clarity, responsible research, and reproducibility.

AAAI-26's official AI-generated supplementary reviews explicitly contain **no ratings or recommendations**. Because this AgentSociety skill is an author-side diagnostic and the user requested a score, it adds a clearly labeled project-local scale. Never represent this score as the AAAI AI-review form or an official AAAI recommendation.

## Required Fields

1. Paper Summary, normally 4–10 sentences
2. Review Summary, normally 4–10 sentences
3. Specific Points of Feedback
4. Project-local Scorecard
5. Project-local Overall Score and Confidence
6. Advisory Reroute

The Paper Summary should identify the main contribution, core problem, key idea, implementation, and claimed conclusion. The Review Summary should state the overall assessment and cover clarity, technical and experimental soundness, novelty, relevance, and highest-order improvements.

Specific feedback must include strengths as well as shortcomings, remain depersonalized and respectful, and distinguish essential changes from optional improvements.

## Project-local Dimension Scores

Score each dimension 1–5 using the anchors in `generic.md`:

- significance;
- novelty;
- theoretical and/or empirical soundness;
- relevance to the AAAI community;
- clarity;
- reproducibility;
- responsible research practices.

## Project-local Overall Score

| Score | Label | Normalized recommendation |
|-------|-------|---------------------------|
| 5 | Strong internal accept | `strong_accept` |
| 4 | Internal accept | `accept` |
| 3 | Internal borderline / major revision | `borderline` |
| 2 | Internal reject / substantial revision | `reject` |
| 1 | Strong internal reject / foundational rework | `strong_reject` |

Prefix the displayed value with `Project-local`, for example `Project-local overall: 3/5`. Use the generic 1–5 confidence scale.

## AAAI-Specific Checks

- Is the problem and limitation of the state of the art clear?
- Is the key novel technical or scientific contribution identifiable?
- Are technical assumptions, details, and possible errors exposed sufficiently for reproduction?
- Do empirical results support the claims using appropriate baselines, metrics, benchmarks, datasets, and error analysis?
- Is the paper situated fairly in related work?
- Are scope and generalizability limitations explicit?
- Are responsible research, sensitive data, human-subject, bias, and reproducibility concerns addressed?
- Are suggested revisions reasonable in time and resources, and clearly separated into essential versus optional?

## Mandatory Output Note

Add this note immediately below the review title:

> This is an author-side internal mock review. Its project-local scores are not part of AAAI-26's official AI-assisted review pilot, whose AI-generated supplementary reviews contain no ratings or recommendations.
