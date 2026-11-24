# Analysis Harness Contract

The harness splits work into two layers. Do not duplicate LLM judgment in Python validators.

## Layer 1 — Structural (Python, deterministic)

Checks artifacts, schemas, paths, and cross-references:

| Phase     | Structural checks                                                                                                |
| --------- | ---------------------------------------------------------------------------------------------------------------- |
| frame     | `analysis_plan.yaml` fields via Pydantic                                                                         |
| explore   | replay catalog, target datasets/tables, `phase_artifacts.explore` paths exist                                    |
| claims    | `claims.json` shape, confirmatory claim present, at least one confirmatory claim approved                        |
| refine    | `validate-refine` (contracts + validated files on disk); per-chart `validate-chart`                              |
| produce   | Reports exist, `report_outline.json`, `artifact_manifest.json`, `analysis_summary.json`, asset graph consistency |
| synthesis | Reports exist, `synthesis_brief.json`, source paths, per-hypothesis summaries/evidence/reviews                   |

Commands: `validate-<phase>` returns `structural_pass` plus issues with `code` (machine-readable).

## Layer 2 — Attestation (LLM, schema-validated)

After you finish the narrative work for a phase, record judgment:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis record-attestation \
  --workspace . --hypothesis-id ID --payload '{
  "phase": "explore",
  "status": "DONE",
  "key_findings": ["..."],
  "artifacts_written": ["presentation/hypothesis_ID/data/eda_quick_stats.md"],
  "rubric": {
    "tables_inspected": ["metrics"],
    "data_limitations": "...",
    "eda_takeaway": "..."
  }
}'
```

Harness state files live under `.agentsociety/analysis/hypothesis_{id}/`, not under `presentation/`.

Rubric keys per phase: see `references/phase-attestation.md`.

`record-attestation` automatically stores an `artifact_fingerprint` for the current phase.
If relevant files change afterwards, `validate-<phase>` returns `attestation_stale`; re-read
the changed artifacts and record the attestation again. `advance` requires the **prior**
phase `gate_pass=true` (`structural_pass` AND `attestation_pass`).

## Monitoring

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis gate-status --workspace . --hypothesis-id ID
```

Returns per-phase `structural_pass`, `attestation_pass`, `gate_pass`, and `rubric_keys`, plus capability states (`available`, `missing_dependency`, `unhealthy`, `disabled`) used by intake and run-loop orchestration.

Every analysis command also accepts `--dry-run`. It parses the same operation contract
without calling the handler or writing workspace files, and returns one machine-readable
availability state: `AVAILABLE`, `BLOCKED_BY_PHASE`, `BLOCKED_BY_GATE`,
`MISSING_DEPENDENCY`, `UNHEALTHY`, `DISABLED`, or `INVALID_INPUT`. Malformed
`payload`/`artifacts` JSON and unreadable or malformed `spec` files are reported as
`INVALID_INPUT` before phase or gate evaluation. `run-loop` uses the
same preflight evaluator for `available_operations` and `blocked_operations`, so agent
guidance and direct CLI execution share one eligibility decision.
Operations with an idempotent planner, currently `prepare-produce`, also return an
`execution_plan` in dry-run output. Plan actions are `RUN` or `SKIP`; a failed phase/gate
preflight remains represented by the top-level preflight status and no handler is called.

## Operation outcomes and run receipts

Mutating analysis operations return a normalized `outcome` while preserving their
existing result fields. Outcome status is one of `SUCCEEDED`, `BLOCKED`, `FAILED`,
`SKIPPED`, or `UNCHANGED`. Exit codes are stable: `0` for successful/skipped/unchanged
work, `2` for a business or preflight block, and `1` for execution failure.

Each non-dry-run mutating analysis invocation writes an atomic receipt under
`.agentsociety/analysis/runs/{run_id}.json`. Receipts contain the operation contract
version, safe scope fields, an input fingerprint, preflight state, timings, a redacted
result summary, and output fingerprints. Raw payload, SQL, and code are never persisted.
An orphaned `RUNNING` receipt from a dead local process becomes `INTERRUPTED` when status
is inspected; repeatable operations are marked retryable, but payload replay remains
disabled.

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis status \
  --workspace . --hypothesis-id ID --run-id RUN_ID
```

`status`, `gate-status`, and `run-loop` expose recent and retryable runs. Read-only
inspection/query/status commands do not create receipts.

Equivalent mutating analysis operations use a cross-process, non-waiting single-flight lock
derived from operation id, contract version, and the full input fingerprint. A concurrent
duplicate is not executed and returns `BLOCKED` with
`reason=operation_already_running`; no second receipt is created for that rejected call.
Path inputs are resolved before fingerprinting, inline JSON is canonicalized, and
file-backed payload/code inputs include a content digest, so superficial spelling or JSON
formatting differences do not bypass the identity policy.
After a non-repeatable operation succeeds, the same execution identity returns
`UNCHANGED` and writes a receipt linked through `deduplicated_from_run_id`. Changing an
input or the operation contract version creates a different identity. The harness never
reconstructs or automatically replays redacted inputs.

`run-loop` is receipt-aware: it suppresses completed non-repeatable operations, marks
active equivalents `ALREADY_RUNNING`, annotates retryable operations with their prior run
id, and returns `recommended_operations`, `completed_operations`, `in_flight_runs`, and
`suggested_next_operation` as machine-readable orchestration state. Retry lists retain
only the latest receipt for each execution identity, so a later success resolves an older
failure without rewriting historical receipts.

## LLM responsibilities (not harness)

- Choosing analysis angle and interpreting ambiguous patterns
- Deciding which claims are confirmatory vs exploratory
- Chart design and report prose
- Synthesis narrative and scientific caveats for simulation evidence
- Reviewing reflection drafts before promotion; user preferences require explicit confirmation
- Asking for post-analysis user feedback and recording it before durable preference promotion

## Downstream gates

- **Pipeline:** `research-pipeline update-stage analysis completed` only after `validate-synthesis` PASS.
- **Paper:** `paper-toolkit` should consume outputs only after `validate-synthesis` passes when `presentation/hypothesis_*` exists.

## JSON payloads

CLI `--payload` and on-disk `*.json` metadata use `json-repair` before Pydantic validation. Templates: `references/json-payloads.md`.

## Anti-patterns

- Do not rely on harness keyword search in report body (removed).
- Do not skip `record-attestation` after validate passes.
- Do not edit phase artifacts after attestation without re-attesting; stale attestations block gates.
- Do not write `approved: true` in claims without user alignment — use attestation `rubric.claims_user_approved`.
- Do not treat structural PASS as sufficient quality — see `references/analysis-quality.md`.
- Do not treat `draft-reflection` as long-term memory; promote reviewed lessons explicitly and keep project lessons separate from user preferences.
- Do not use `--include-preferences` without `record-feedback` or explicit `user-confirmed` evidence.
