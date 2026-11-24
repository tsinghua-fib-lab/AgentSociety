---
name: agentsociety-research-pipeline
description: Use when starting or resuming an AgentSociety research workspace, deciding which research skill to invoke next, checking current pipeline state, or sizing a simulation before configuration and module creation.
---

# Research Pipeline

Orchestrates the AgentSociety research workflow. Determines which skill to invoke based on the current workspace state and user intent.

## Overview

The research pipeline is a revision-capable workflow: **literature search → hypothesis → experiment config → run → analysis → paper**, with explicit reroutes back to the smallest sufficient earlier stage. After a draft exists, `paper-review` can perform an optional robust author-side mock review using three parallel independent reviewers and a separate evidence-verifying MetaReview agent, then advise which earlier stage to revisit. The review remains read-only; the user or controlling coding agent closes the feedback loop by explicitly applying an accepted route through `research-pipeline reroute`. Supporting skills (scan-modules, create-agent, create-env-module, datasets) branch off the main trunk at specific points.

## Scale Planning Gate

Before entering `experiment-config`, `create-agent`, or `create-env-module`, confirm the simulation scale budget:

- target agent count or range
- expected step budget
- acceptable runtime or compute budget
- preferred complexity tier, such as lean, balanced, or rich

If any of these are missing, ask one round of clarifying questions first. Present 2-3 approaches with trade-offs and a recommendation, then route into the appropriate skill once the budget is fixed.

## Dataset Gate

If the task may depend on external data, treat dataset access as a first-class branch rather than an afterthought.

- Use `agentsociety-use-dataset` to search, inspect, and download datasets from the platform.
- If no suitable dataset exists locally or remotely, surface that gap before continuing with experiment design.
- Use `agentsociety-create-dataset` when the work needs packaging, validation, upload, or publishing of a dataset.
- If local files should be shared or reused, guide the user through dataset upload rather than folding the files into experiment config by hand.

## Quick Reference

At the beginning of a new session or resumption, run:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline where-am-i --json
```

This reads `.agentsociety/progress.json` to determine the current stage. If the file does not exist, fall back to file-existence detection and then bootstrap tracking with `init`.

## Git Checkpoint Discipline

Every pipeline transition must be persisted with an explicit git commit. Hook-based auto-commit approaches are unreliable — always commit manually.

### Workspace Initialization

When bootstrapping a new workspace with `research-pipeline init`:

```bash
# 1. Init the workspace directory if not already a git repo
git init
# 2. SDK-initialized workspaces already have progress.json. Create it only if absent.
test -f .agentsociety/progress.json || "$PYTHON_PATH" .agentsociety/bin/ags.py research-pipeline init --topic "TOPIC"
# 3. Initial commit
git add -A && git commit -m "init: bootstrap research pipeline"
```

### Stage Transitions

After **every** call to `research-pipeline update-stage`, commit the current iteration's changes:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline update-stage STAGE STATUS
git add -A && git commit -m "pipeline: STAGE → STATUS"
```

For example:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline update-stage literature_search completed
git add -A && git commit -m "pipeline: literature_search → completed"
```

Apply an accepted review or analysis reroute with the same checkpoint discipline:

```bash
$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline reroute experiment_config \
  --reason "MetaReview found that the control cannot identify the claimed effect" \
  --source-artifact paper/reviews/acl-arr-review-r1.md
git add -A && git commit -m "pipeline: reroute to experiment_config"
```

### Rules

- If `git` is not initialized in the workspace, run `git init` first.
- Commit messages follow the pattern: `pipeline: STAGE → STATUS`.
- Use `git add -A` to capture all changes produced by the current stage.
- Do **not** rely on git hooks (pre-commit, post-commit, etc.) for this — they are unreliable in this context. Commit explicitly.

## Entry Conditions

Use `where-am-i --json` whenever the current stage is unclear.

- If `.agentsociety/progress.json` exists, trust `current_stage` as the primary routing signal.
- If the file is missing, infer the stage from workspace artifacts, then initialize progress tracking.
- If the current stage already has a failed status, route to the owning skill for repair rather than restarting the pipeline.
- If the current stage has `needs_revision`, route to the owning skill with the active reroute reason and source artifact as required context.
- If the work depends on simulation size or runtime budget and those values are missing, resolve the scale planning gate before routing onward.

| `current_stage` | Route to Skill |
|-----------------|----------------|
| `literature_search` | literature-search |
| `hypothesis` | hypothesis |
| `experiment_config` | experiment-config |
| `run_experiment` | run-experiment |
| `analysis` | analysis |
| `generate_paper` | paper-toolkit |

Post-paper review is routed by user intent rather than `current_stage`: when a complete draft exists and the user asks for an internal review, venue score, or revision-stage advice, invoke `agentsociety-paper-review`. For PDF input, prepare one frozen page-aware intake and pass the same text, layout, and page renders to every agent; stop when its quality gate fails. A normal result requires three isolated reviewer subagents running concurrently followed by a separately spawned MetaReview subagent. The review bundle is advisory and must not update `.agentsociety/progress.json`; only the user or controlling coding agent may subsequently accept a stage-valued reroute and call `research-pipeline reroute`.

### Progress File Quick Reference

| Command | Purpose |
|---------|---------|
| `$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline init --topic "TEXT"` | Bootstrap `progress.json` (also `git init` + initial commit if needed) |
| `$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline status` | Show progress summary |
| `$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline where-am-i --json` | Get current stage as JSON |
| `$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline update-stage STAGE STATUS` | Update stage status (then `git add -A && git commit`) |
| `$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline reroute STAGE --reason "TEXT" --source-artifact PATH` | Start an auditable revision round at the current or an earlier stage |
| `$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline set-verification STAGE STATUS` | Update stage verification status |
| `$PYTHON_PATH .agentsociety/bin/ags.py research-pipeline next-action --json` | Get the recommended next action |

## Workflow

```dot
digraph research_pipeline {
    rankdir=LR;
    node [shape=box, style=filled, fillcolor="#E8F4FD"];
    decide [label="where-am-i"];
    lit [label="literature-search"];
    hypo [label="hypothesis"];
    scan [label="scan-modules\noptional helper"];
    exp [label="experiment-config"];
    run [label="run-experiment"];
    analysis [label="analysis"];
    paper [label="paper-toolkit"];
    review [label="paper-review\n3 reviewers + MetaReview"];
    agent [label="create-agent"];
    env [label="create-env-module"];
    create_ds [label="create-dataset"];
    use_ds [label="use-dataset"];

    decide -> lit;
    decide -> hypo;
    decide -> exp;
    decide -> run;
    decide -> analysis;
    decide -> paper;

    lit -> hypo;
    hypo -> scan [style=dashed, label="names uncertain"];
    scan -> hypo;
    hypo -> exp;
    exp -> scan [style=dashed, label="need discovery or validation"];
    scan -> exp;
    exp -> agent [style=dashed, label="missing agent"];
    agent -> exp;
    exp -> env [style=dashed, label="missing env"];
    env -> exp;
    exp -> create_ds [style=dashed, label="publish dataset"];
    exp -> use_ds [style=dashed, label="need external data"];
    use_ds -> exp;
    exp -> run;
    run -> analysis;
    analysis -> paper;
    paper -> review [style=dashed, label="internal mock review"];
    review -> lit [style=dashed, label="accepted reroute"];
    review -> hypo [style=dashed, label="accepted reroute"];
    review -> exp [style=dashed, label="accepted reroute"];
    review -> run [style=dashed, label="accepted reroute"];
    review -> analysis [style=dashed, label="accepted reroute"];
    review -> paper [style=dashed, label="accepted reroute"];
    analysis -> hypo [style=dashed, label="revise hypothesis"];
    analysis -> use_ds [style=dashed, label="comparison data"];
    analysis -> web [style=dashed, label="supplementary context"];
}
```

## Pipeline Map

| # | Skill | Produces | Consumes |
|---|-------|----------|----------|
| 1 | **literature-search** | `papers/`, `papers/literature_index.json` | `TOPIC.md` |
| 2 | **hypothesis** | `hypothesis_{id}/HYPOTHESIS.md`, `SIM_SETTINGS.json` | literature index |
| 3 | **experiment-config** | `init_config.json`, `steps.yaml`, `config_params.py` | `SIM_SETTINGS.json` |
| 4 | **run-experiment** | `run/replay/_schema.json`, sharded replay JSONL, `run/stdout.log`, `run/artifacts/` | `init_config.json` + `steps.yaml` |
| 5 | **analysis** | `presentation/hypothesis_{id}/report_{zh,en}.md`, HTML, charts, data | `run/replay/` |
| 6 | **paper-toolkit** | paper deliverables | analysis report + literature index |
| 7 (optional) | **paper-review** | frozen input manifest + 3 independent reviews under `paper/reviews/<venue>-review-r<N>/`; final `paper/reviews/<venue>-review-r<N>.md` MetaReview | complete paper draft + selected evidence artifacts |

Run `paper scan --workspace <research-workspace>` from the workspace containing the hypothesis and presentation directories. Check the scan's hypothesis and report counts before drafting. With JSONL replay, the toolkit's SQLite count can be zero. Cite the scored analysis table and its source questionnaires or replay datasets in the evidence graph.

### Branch Skills (called from trunk)

| Branch Skill | Called By | When |
|-------------|-----------|------|
| **scan-modules** | hypothesis, experiment-config | When module names are unknown or need validation |
| **create-agent** | experiment-config | When needed agent class doesn't exist |
| **create-env-module** | experiment-config | When needed env module doesn't exist |
| **create-dataset** | experiment-config | When packaging data for upload or publishing |
| **use-dataset** | literature-search, hypothesis, experiment-config, analysis | When searching, downloading, or inspecting datasets |

## Skill Index

| Skill | Trigger Keywords |
|-------|-----------------|
| literature-search | "literature", "papers", "related work", "background research" |
| hypothesis | "hypothesis", "research question", "control", "treatment", "experiment groups" |
| experiment-config | "configure experiment", "init_config", "steps.yaml", "set up experiment" |
| run-experiment | "run experiment", "start simulation", "check status", "stop experiment" |
| analysis | "analyze", "results", "visualization", "chart", "report" |
| paper-toolkit | "write paper", "academic paper", "generate paper", "Nature paper" |
| paper-review | "review paper", "paper score", "mock review", "review feedback", "where should revision go" |
| scan-modules | "available modules", "list agents", "find environment" |
| create-agent | "create agent", "custom agent", "new agent type" |
| create-env-module | "create environment", "custom module", "env module" |
| create-dataset | "create dataset", "upload dataset", "publish data" |
| use-dataset | "download dataset", "find data", "browse datasets", "search datasets", "dataset search" |

## Iterative Cycles

- **Analysis → Hypothesis**: results may refine or revise the hypothesis
- **Experiment-config → Create-agent/Create-env-module**: missing modules trigger creation
- **Experiment-config → Scan-modules**: names can be confirmed when discovery is needed
- **Run → Config**: failed validation or execution loops back to config fixes
- **Paper → Review → Earlier stage**: paper-review emits advisory reroutes; the user or controlling coding agent decides whether to apply one with `research-pipeline reroute`

`reroute` is the only supported backward transition. It:

1. rejects forward jumps;
2. increments `workspace.revision_round`;
3. changes the accepted target and already-completed downstream stages to `needs_revision` without deleting artifacts;
4. resets stale verification and stage metadata for those stages;
5. records the reason, source artifact, previous stage-state snapshots, and invalidated stages in the append-only `transitions` log;
6. keeps `active_reroute` until all invalidated stages are completed or explicitly skipped.

Do not apply `human_decision` or `none` as stages. Pause for accountable input on `human_decision`; leave pipeline state unchanged for `none`. When several review routes exist, apply the earliest accepted stage once—the normal forward flow will revisit its invalidated downstream stages.

## Persistence Files

| File | Git | Purpose |
|------|-----|---------|
| `.agentsociety/progress.json` | Committable | Stage tracker with status, revision round, active reroute, attempts, and append-only transition history |

## Hard Constraints

- Never run analysis before `run-experiment` produces `run/replay/_schema.json`
- Always run `experiment-config check` before `run-experiment`
- `paper-toolkit` requires analysis reports to exist
- `paper-review` requires a complete draft, a passing shared PDF intake when applicable, and a valid 3-reviewer ensemble before MetaReview; it writes only the reserved review bundle and never updates pipeline stage or executes reroute advice
- Apply backward movement only through `research-pipeline reroute`; do not edit `current_stage` or downstream statuses by hand
- Keep the controlling agent as the single writer of `progress.json`; subagents return artifacts and must not perform pipeline transitions
- Always call `research-pipeline update-stage` after completing a pipeline stage
- Always git commit after `research-pipeline update-stage` — see **Git Checkpoint Discipline**
- On workspace init, run `git init` (if needed) followed by an initial commit
- Do not rely on git hooks for auto-commit; commit explicitly after every stage transition
