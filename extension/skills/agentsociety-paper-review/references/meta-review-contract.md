# MetaReview Artifact Contract

The MetaReview is an evidence-verifying adjudication of three independent reviews. It is not a fourth unconstrained vote and not a prose concatenation.

## Final File Location

Write exactly one final artifact:

```text
paper/reviews/<venue>-review-r<N>.md
```

The supporting round directory with the input manifest and three individual reviews must already exist. Never create a normal final MetaReview from fewer than three valid reviews.

## YAML Frontmatter

```yaml
---
schema: agentsociety.paper-review.meta/v1
title: Internal Mock MetaReview
review_mode: author_side_internal_mock_ensemble
round_id: iclr-r1
venue: iclr
venue_edition: "2026"
input_manifest: paper/reviews/iclr-review-r1/input-manifest.yaml
pdf_intake:
  status: pass
  report_path: paper/reviews/iclr-review-r1/pdf-intake/extraction-report.json
  report_sha256: <64-lowercase-hex-digits>
  warnings: []
individual_reviews:
  - paper/reviews/iclr-review-r1/reviewer-1.md
  - paper/reviews/iclr-review-r1/reviewer-2.md
  - paper/reviews/iclr-review-r1/reviewer-3.md
ensemble_size_requested: 3
ensemble_size_completed: 3
execution_mode: parallel
score_observations: [6, 6, 4]
score_median: 6
score_spread_steps: 1
recommendation_votes: [weak_accept, weak_accept, weak_reject]
decision_band_votes: [positive, positive, negative]
concern_agreement:
  unanimous_confirmed: 1
  majority_confirmed: 2
  minority_confirmed: 0
  rejected_after_verification: 1
  unresolved: 0
robustness_status: medium
adjudication_required: false
meta_score:
  value: 6
  label: marginally above the acceptance threshold
meta_score_override:
  applied: false
  median_value: 6
  final_value: 6
  reason: null
confidence:
  value: 3
  label: fairly confident
primary_reroute: analysis
secondary_reroutes:
  - generate_paper
blocking_issue_ids:
  - M1
---
```

Rules:

- Preserve score observations in `R1`, `R2`, `R3` order.
- `score_spread_steps` uses ordinal positions in the venue's allowed scale, not raw numeric subtraction.
- `concern_agreement` counts MetaReview-verified clusters, not raw wording overlap.
- `robustness_status` follows `ensemble-protocol.md` exactly.
- Set `adjudication_required: true` for low robustness or unresolved decision-relevant disagreement.
- `meta_score` equals the native-score median by default.
- `confidence` must not exceed the median individual confidence unless the MetaReview independently checked every uncertainty used to justify a lower reviewer confidence.
- For PDF input, copy the frozen intake identity, status, and warnings. Omit `pdf_intake` for non-PDF input.

## Median Anchor and Override Rule

MetaReview may move the final score by at most one adjacent native scale step, and only when source verification shows that a score-driving factual premise is wrong or a verified major/fatal issue was omitted.

When overriding:

- set `meta_score_override.applied: true`;
- record median, final value, exact source evidence, and affected reviewer premises;
- cap `robustness_status` at `medium`;
- explain why the venue rubric requires the adjacent score.

If MetaReview believes a shift larger than one native step is warranted, do not force a decisive score. Keep the median as a provisional anchor, set `robustness_status: low` and `adjudication_required: true`, and explain the unresolved conflict.

## Evidence Adjudication

Cluster semantically equivalent concerns even when reviewers use different wording. Use source IDs such as `R1-W2`, `R2-W1`, and `R3-W3`.

For each candidate concern:

1. identify supporting reviewers;
2. inspect the cited paper location and relevant evidence artifact;
   for PDF input, visually inspect the rendered source page for every layout-dependent or major/fatal claim;
3. classify the source claim as `verified`, `partially_verified`, `not_verified`, or `contradicted`;
4. decide whether it belongs in the final review;
5. assign the smallest sufficient reroute.

Reviewer IDs carry no priority. Extract all three scorecards and concern lists before adjudicating, and never use `R1` as the default anchor; the native median and source evidence are the anchors.

Inclusion rules:

- A 2/3 or 3/3 concern may be included only after MetaReview verifies its material evidence.
- A 1/3 minority concern may be promoted only when MetaReview independently verifies exact source evidence. Label it `meta_confirmed_minority`.
- Do not include an unverified concern as a blocking issue, regardless of vote count.
- Preserve rejected decision-relevant concerns in an adjudication table with the rejection reason, so aggregation remains auditable.

## Required Body Sections

```markdown
# Internal Mock MetaReview — <Venue>

> This is an author-side internal ensemble review, not an official venue review or acceptance prediction.

## Review target and ensemble
## Artifact intake and limitations
## Paper summary
## Claimed contributions
## Reviewer score observations
## Agreement and robustness
## MetaReview venue scorecard
## Confirmed strengths
## Confirmed concerns
## Minority and rejected concerns
## Questions and score-change conditions
## Limitations, ethics, and reproducibility
## Final recommendation
## Advisory reroute
## Machine-readable handoff
```

## Reviewer Score Observations

Include a table:

| Reviewer | Overall | Confidence | Recommendation | Primary reroute |
|----------|---------|------------|----------------|-----------------|
| R1 | ... | ... | ... | ... |
| R2 | ... | ... | ... | ... |
| R3 | ... | ... | ... | ... |

Report the native median, spread in native scale steps, decision-band votes, and whether a retry occurred.

Also include a per-dimension agreement table for every numeric venue field:

| Venue dimension | R1 | R2 | R3 | Median | Spread in native steps |
|-----------------|----|----|----|--------|------------------------|
| Soundness | ... | ... | ... | ... | ... |

When a venue field is categorical rather than numeric, report the three observations and modal value without inventing arithmetic.

## Agreement and Robustness

Explain:

- what the reviewers agreed on;
- where scores or concern severity diverged;
- whether divergence came from factual interpretation, venue-value judgment, missing evidence, or reviewer error;
- why the ensemble is `high`, `medium`, or `low` robustness;
- what evidence would reduce the remaining uncertainty.

Never say “the reviews are consistent” without reporting the observations and spread.

## Artifact Intake and Limitations

For PDF input, report the shared intake status and warnings, confirm that its hash chain passed the pre-MetaReview integrity gate, and state which source page renders were re-checked. Every candidate major or fatal concern must be visually verified when the cited evidence depends on a figure, table, equation, footnote, absence claim, or page layout. If the render is unreadable, leave the concern unresolved and require human adjudication instead of inferring the content.

## Confirmed Concern Contract

```markdown
### M1 — Short decision-relevant title

- Severity: major
- Support: 2/3 (`R1-W1`, `R3-W2`)
- Meta verification: verified
- Paper pointer: Section 4.2, Table 3, page 7
- Suggested reroute: analysis
- Why it matters: <effect on central claim or venue criterion>
- Verified evidence: <what the source artifact shows>
- Suggested action: <bounded advisory action>
- Resolution evidence: <what would close the issue>
- Score impact: <how resolution could change the native score>
```

Use stable MetaReview IDs `M1`, `M2`, ... in descending decision impact.

## Minority and Rejected Concerns

Include an auditable table:

| Source concern(s) | Support | Verification | Disposition | Reason |
|-------------------|---------|--------------|-------------|--------|
| R2-W3 | 1/3 | verified | promoted as M2 | exact evidence confirms a material issue |
| R1-W4, R3-W2 | 2/3 | contradicted | rejected | table contains the allegedly missing result |

Do not silently discard conflicting reviews.

## Advisory Reroute

Derive the primary reroute from the highest-impact **verified** blocking concern. Majority vote alone does not determine the route. If low agreement leaves no stable evidence-based route, use `human_decision`; otherwise keep the scientifically appropriate route and set `adjudication_required: true` separately.

## Machine-readable Handoff

End with valid JSON:

```json
{
  "schema": "agentsociety.paper-review.meta-handoff/v1",
  "review_path": "paper/reviews/iclr-review-r1.md",
  "round_id": "iclr-r1",
  "ensemble": {
    "requested": 3,
    "completed": 3,
    "execution_mode": "parallel",
    "score_observations": [6, 6, 4],
    "score_median": 6,
    "score_spread_steps": 1,
    "concern_agreement": {
      "unanimous_confirmed": 1,
      "majority_confirmed": 2,
      "minority_confirmed": 0,
      "rejected_after_verification": 1,
      "unresolved": 0
    },
    "robustness_status": "medium",
    "adjudication_required": false
  },
  "meta_score": {"value": 6, "label": "marginally above the acceptance threshold"},
  "confidence": {"value": 3, "label": "fairly confident"},
  "primary_reroute": "analysis",
  "secondary_reroutes": ["generate_paper"],
  "blocking_issue_ids": ["M1"],
  "issues": [
    {
      "id": "M1",
      "severity": "major",
      "support": 2,
      "verification": "verified",
      "reroute": "analysis",
      "summary": "Primary effect lacks uncertainty reporting"
    }
  ]
}
```

The JSON must mirror frontmatter and prose exactly. It remains advisory and contains no execution commands.

## Final Consistency Gate

Before writing the final path, verify:

- exactly three valid individual review paths are listed;
- all reviews refer to the same frozen input manifest and artifact digests;
- score observations, median, native-step spread, decision bands, and robustness status are correct;
- every blocking concern is source-verified;
- minority promotions and rejected concerns are explicit;
- any score override obeys the one-step limit and is fully justified;
- low robustness sets `adjudication_required: true`;
- frontmatter, tables, prose, and JSON handoff agree;
- no research artifact or progress state was changed.
