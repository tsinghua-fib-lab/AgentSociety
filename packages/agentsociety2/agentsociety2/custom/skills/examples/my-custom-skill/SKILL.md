---
name: my-custom-skill
description: Example custom agent skill — a template to get started.
---

# My Custom Skill

This is a template for creating a custom agent skill.

## How Skills Work

There are **two valid skill patterns** in the current architecture:

### Pattern A: Prompt-Only (Recommended)

No `script` field in frontmatter. This SKILL.md is injected into the LLM's context
when `activate_skill` is called. The LLM then uses built-in atomic tools
(read, write, append, list, grep, ask_env) to accomplish the task.

This is the **primary extension mechanism** — like Claude Code's slash commands.

### Pattern B: Script

Add `script: scripts/my-script.py` to frontmatter. The script runs in an isolated
`skill_worker.py` subprocess via `entrypoint(argv, ctx)` when available (scripts
without a callable run as a plain subprocess). It should communicate via the
returned stdout string and file I/O under `ctx.workspace_root`. Scripts **cannot** access the LLM or
environment router directly — use this only for deterministic computation.

## Behavioral Guidelines (Edit for Your Skill)

When this skill is activated:

1. Use `ask_env` to query the environment for relevant information.
2. Use `read` / `write` / `append` to persist state.
3. Use `execute_skill_script` for deterministic computation when a script exists.
4. Call `finish` with a summary when finished.

## Example: A "Daily Journal" Skill

When activated, the agent should:
1. `ask_env` with instruction: "What happened recently? Summarize recent events."
2. `read` path `journal.jsonl` to load previous entries if it exists.
3. `append` path `journal.jsonl` to add today's entry.
4. `finish` with summary of what was journaled.
