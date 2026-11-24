# ICLR Template

- Verified edition: ICLR 2026
- Verified at: 2026-07-17
- Primary official source: https://iclr.cc/Conferences/2026/ReviewerGuide
- Scale origin: `public_venue_reviews`
- Scope: author-side internal mock review; not an official ICLR review

The official guide asks reviewers to summarize contributions, list strong and weak points, state an initial accept/reject recommendation with key reasons, provide supporting arguments, ask decision-relevant questions, and give improvement-oriented additional feedback. It emphasizes clarity, technical correctness, experimental rigor, reproducibility, novelty, claim support, and significance.

The 2026 numeric fields below reflect the form visible in public ICLR 2026 reviews. Because the reviewer guide does not itself enumerate those numeric choices, record `score_scale_origin: public_venue_reviews` rather than `official`.

## Required Fields

1. Summary
2. Soundness
3. Presentation
4. Contribution
5. Strengths
6. Weaknesses
7. Questions
8. Ethics concern assessment
9. Rating
10. Confidence
11. AI assistance disclosure note

## Dimension Scores

Score Soundness, Presentation, and Contribution independently:

| Score | Label |
|-------|-------|
| 4 | excellent |
| 3 | good |
| 2 | fair |
| 1 | poor |

The prose must justify each dimension. Contribution combines novelty, significance, and community value; it is not synonymous with state-of-the-art performance.

## Overall Rating

Use only the current form choices:

| Score | Label | Normalized recommendation |
|-------|-------|---------------------------|
| 10 | strong accept; should be highlighted at the conference | `strong_accept` |
| 8 | accept; good paper | `accept` |
| 6 | marginally above the acceptance threshold | `weak_accept` |
| 4 | marginally below the acceptance threshold | `weak_reject` |
| 2 | reject; not good enough | `reject` |

Do not invent intermediate values or acceptance probabilities.

## Confidence

Use 1–5:

- 5: absolutely certain; very familiar with related work and checked details carefully;
- 4: confident but not absolutely certain;
- 3: fairly confident; some parts, literature, or technical details may not have been fully checked;
- 2: willing to defend the assessment, but likely missed central details or related work;
- 1: educated guess because the paper is outside the reviewer's area or difficult to assess.

## ICLR-Specific Checks

- Can the exact problem and contribution be stated clearly?
- Is the approach motivated and correctly situated in the literature?
- Do theoretical or empirical results actually support every central claim?
- Is the work scientifically rigorous and reproducible?
- Does it contribute new, relevant, impactful knowledge even if it is not state of the art?
- Are missing comparisons to very recent or preprint-only work being treated consistently with the edition's contemporaneous-work policy?
- Is any significant LLM use in research ideation or writing disclosed as required by the target edition?

## Output Note

Add this sentence near the top:

> This author-side mock review was generated with AI assistance. It is not an official ICLR review; any use in a submission or formal review process remains subject to current ICLR disclosure and confidentiality rules.
