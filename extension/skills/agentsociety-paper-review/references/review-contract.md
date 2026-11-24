# Independent Review Artifact Contract

Each of the three reviewer subagents writes one complete, independent venue review. This contract makes the reviews comparable and parseable without forcing their scientific judgments to agree.

## File Location

The orchestrator assigns exactly one path to each reviewer:

```text
paper/reviews/<venue>-review-r<N>/reviewer-1.md
paper/reviews/<venue>-review-r<N>/reviewer-2.md
paper/reviews/<venue>-review-r<N>/reviewer-3.md
```

The reviewer writes only its assigned file. It never chooses the round, reads another review, writes the final MetaReview path, or changes an input artifact.

## YAML Frontmatter

```yaml
---
schema: agentsociety.paper-review.individual/v1
title: Internal Mock Review — Independent Reviewer R1
review_mode: author_side_internal_mock_individual
round_id: iclr-r1
reviewer_id: R1
independence: isolated
input_manifest: paper/reviews/iclr-review-r1/input-manifest.yaml
venue: iclr
venue_edition: "2026"
template_verified_at: "2026-07-17"
template_source: "https://iclr.cc/Conferences/2026/ReviewerGuide"
score_scale_origin: public_venue_reviews
reviewed_at: "2026-07-17T12:00:00+08:00"
reviewed_artifacts:
  - path: paper/main.pdf
    sha256: <64-lowercase-hex-digits-or-unavailable>
pdf_intake:
  status: pass
  report_path: paper/reviews/iclr-review-r1/pdf-intake/extraction-report.json
  report_sha256: <64-lowercase-hex-digits>
  warnings: []
overall_score:
  value: 6
  label: marginally above the acceptance threshold
confidence:
  value: 3
  label: fairly confident
recommendation: weak_accept
primary_reroute: analysis
secondary_reroutes:
  - generate_paper
blocking_issue_ids:
  - W1
---
```

Rules:

- `reviewer_id` is exactly the assigned `R1`, `R2`, or `R3`.
- `round_id`, `input_manifest`, venue, and artifact digests must match the frozen input manifest.
- Quote edition values such as `"2026"` so YAML does not reinterpret them.
- `template_source` must be the source named in the venue reference. If the scale is reconstructed from publicly visible venue reviews, use `score_scale_origin: public_venue_reviews`.
- Use `score_scale_origin: project_local` for the generic and AAAI author-side internal scales.
- `sha256` is either the digest from the frozen manifest or the literal `unavailable`; never invent one.
- For PDF input, copy `pdf_intake` identity, status, and warnings from the frozen manifest. This field is omitted for non-PDF input.
- `recommendation` is a normalized label such as `strong_reject`, `reject`, `weak_reject`, `borderline`, `weak_accept`, `accept`, `strong_accept`, `findings`, or `revise_and_resubmit`.
- Reroutes must come from the controlled vocabulary in `reroute-guide.md`.
- `blocking_issue_ids` contains only major or fatal decision-relevant issues. Use `[]` when there are none.

## Required Body Sections

Use this order, inserting venue-only sections where its reference requires them:

```markdown
# Internal Mock Review — <Venue> — <R1|R2|R3>

> This is one isolated author-side mock review. It is not an official venue review or acceptance prediction.

## Review target
## Artifact intake and limitations
## Paper summary
## Claimed contributions
## Venue scorecard
## Strengths
## Concerns
## Questions and score-change conditions
## Limitations, ethics, and reproducibility
## Overall recommendation
## Advisory reroute
## Machine-readable handoff
```

## Review Target

State:

- reviewer ID and round ID;
- frozen input manifest path;
- manuscript path and digest;
- supporting artifacts actually inspected;
- venue template and edition;
- unavailable material that limits the review;
- whether the main paper was self-contained.

## Artifact Intake and Limitations

For PDF input, state the intake status and warnings. Confirm that full text and rendered pages were both inspected. List every warned page that was visually checked and any material element that remained unreadable. A figure, table, equation, footnote, or layout-dependent concern must cite a rendered source page; extracted text alone is insufficient.

## Venue Scorecard

Use a table:

| Field | Score | Evidence and rationale |
|-------|-------|------------------------|
| ... | ... | concrete paper pointer and concise justification |

Use native field names and scales. Do not average dimension scores to manufacture an overall score when the venue defines overall judgment separately.

## Concern Contract

Each concern uses this exact shape:

```markdown
### W1 — Short decision-relevant title

- Severity: major
- Paper pointer: Section 4.2, Table 3, page 7
- Suggested reroute: analysis
- Why it matters: <relationship to a central claim or venue criterion>
- Evidence: <what the paper or supporting artifact actually shows>
- Suggested action: <bounded action, not an instruction to execute automatically>
- Resolution evidence: <artifact or observation that would demonstrate resolution>
- Score impact: <how resolution or confirmation would change the assessment>
```

Allowed severity values:

- `minor`: improves the paper but does not currently determine the overall recommendation;
- `major`: materially affects a central claim or overall score;
- `fatal`: the present manuscript cannot support its central research conclusion without foundational change.

Requirements:

- Use local IDs `W1`, `W2`, ... in descending severity and decision impact. MetaReview will qualify them as `R1-W1`, `R2-W1`, and so on.
- Cite a paper section, page, figure, table, equation, appendix, or explicit `not found in manuscript` observation.
- Separate evidence from interpretation.
- Do not request a large new experiment without stating the claim it would test and the minimum sufficient evidence.
- Minor comments and typos may be grouped; never inflate them into upstream reroutes.
- Do not mention, predict, or imitate another reviewer.

## Questions and Score-Change Conditions

Ask only questions whose answers could:

- resolve a concrete uncertainty;
- change a dimension or overall score; or
- identify the appropriate reroute.

For each material question, state what answer or evidence would raise, preserve, or lower the score. If no author response is in scope, phrase this as evidence a later agent should seek.

## Advisory Reroute

Include:

- one primary reroute and its decisive issue IDs;
- ordered secondary reroutes, if any;
- why later-stage edits alone are insufficient for each upstream route;
- `none` when no material revision is advised;
- `human_decision` for questions that should not be delegated to autonomous execution.

Reroutes never change `.agentsociety/progress.json` and never trigger work by themselves.

## Machine-readable Handoff

End with valid JSON:

```json
{
  "schema": "agentsociety.paper-review.individual-handoff/v1",
  "review_path": "paper/reviews/iclr-review-r1/reviewer-1.md",
  "round_id": "iclr-r1",
  "reviewer_id": "R1",
  "overall_score": {"value": 6, "label": "marginally above the acceptance threshold"},
  "confidence": {"value": 3, "label": "fairly confident"},
  "recommendation": "weak_accept",
  "primary_reroute": "analysis",
  "secondary_reroutes": ["generate_paper"],
  "blocking_issue_ids": ["W1"],
  "issues": [
    {
      "id": "W1",
      "severity": "major",
      "reroute": "analysis",
      "summary": "Primary effect lacks uncertainty reporting"
    }
  ]
}
```

The JSON must mirror the prose and frontmatter exactly. It is input to MetaReview, not an execution plan.

## Reviewer Consistency Check

Before writing the assigned file, verify:

- every score has supporting rationale;
- every major or fatal concern appears in `blocking_issue_ids`;
- every issue uses an allowed reroute;
- the primary reroute addresses the highest-impact concern at the earliest necessary stage;
- recommendation, score, confidence, and prose do not contradict one another;
- reviewer ID, round ID, manifest, and digests match the frozen input;
- output is clearly labeled as internal, independent, and advisory;
- no file other than the assigned reviewer output was changed.
- for PDF input, all warnings were acknowledged and every layout-dependent major/fatal concern was checked against the shared page render.
