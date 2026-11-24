# Experience Memory

The experience loop turns finished analysis work into reviewable long-term assets.
It is deliberately conservative: the harness may draft lessons, but promotion is an
explicit action and user preferences require user confirmation.

## Flow

```text
analysis artifacts
  -> draft-reflection
  -> user / orchestrator review
  -> record-reflection
  -> promote-reflection
  -> .agentsociety/memory/
```

## Commands

Show what memory will be injected into orchestration:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis memory-context \
  --workspace . \
  --hypothesis-id 1
```

Draft from harness state:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis draft-reflection \
  --workspace . \
  --hypothesis-id 1 \
  --experiment-id 1
```

Store a reviewed payload:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis record-reflection \
  --workspace . \
  --hypothesis-id 1 \
  --payload reflection.json
```

Record post-analysis user feedback:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis record-feedback \
  --workspace . \
  --hypothesis-id 1 \
  --payload feedback.json
```

Run pre-promotion review:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis review-reflection \
  --workspace . \
  --hypothesis-id 1
```

Promote lessons and recipes:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis promote-reflection \
  --workspace . \
  --hypothesis-id 1
```

Promote preferences only after the user explicitly confirms them:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py analysis promote-reflection \
  --workspace . \
  --hypothesis-id 1 \
  --include-preferences
```

## Memory Layout

```text
.agentsociety/memory/
  memory_index.yaml          # confirmed user/project preferences
  project_lessons.jsonl      # append-only worked/failed lessons
  method_recipes/            # reusable protocols as markdown
  reflections/               # reviewable source reflection reports
```

## Governance

- Treat reflection output as a proposal, not truth.
- Do not promote inferred preferences without user confirmation.
- Ask for user feedback after important analyses; store it with `record-feedback`.
- `promote-reflection` runs `review-reflection` automatically and blocks unsafe promotion.
- Promote each reflection source once; reruns return `SKIPPED` unless you use `--include-preferences` after `record-feedback`.
- Preference promotion requires `record-feedback` (rating, satisfaction, or user-confirmed preference candidates), not reflection-only evidence.
- Store specific evidence paths, not vague claims like "the user likes this".
- Keep project lessons distinct from user preferences.
- Prefer recipes for reusable methods; prefer JSONL lessons for one-off observations.
- Never let memory override current user instructions or harness gates.

## Activation

Experience memory is on by default after promotion. `intake`, `status`, and
`run-loop` include `memory_context`; `run-loop` prepends a Memory step whenever
confirmed preferences, recent lessons, or method recipes exist. This makes memory
visible to orchestration without letting it silently override current user intent.

`status` and `run-loop` also include `feedback_prompt` so the orchestrator can ask
for post-analysis feedback before durable promotion.
