# AgentSociety — Agent Guide

Cursor / coding agents: start here. Full architecture and module map live in [CLAUDE.md](./CLAUDE.md).

## Active scope

Only these paths are in active CI, security scanning, and Dependabot scope:

| Path | Role |
| ---- | ---- |
| `packages/agentsociety2/` | Python SDK (primary) |
| `examples/v2/daily_mobility/` | Daily Mobility simulation and dashboard |
| `extension/` | VS Code extension |
| `frontend/` | React web UI |

Legacy (`packages/agentsociety`, `agentsociety-community`, `agentsociety-benchmark`, `packages/agentsociety/docs`) is reference-only. See [`.github/agentsociety2-scope.yml`](./.github/agentsociety2-scope.yml).

## Repository layout

```text
AgentSociety/
├── packages/agentsociety2/   # v2 SDK — import as agentsociety2
├── extension/                # VS Code extension (ai-social-scientist)
├── frontend/                 # React + Vite dashboard
├── pyproject.toml + uv.lock  # uv workspace root
├── Makefile                  # extension build + Sphinx docs
├── CONTRIBUTING.md           # setup, PR checklist, release
├── CHANGELOG.md              # Keep a Changelog (AS2)
└── CLAUDE.md                 # deep architecture reference
```

Primary remote is GitLab (`git.fiblab.net`); GitHub is a public mirror with Dependabot / CodeQL.

## Maintainer workflow

For dependency-bot and CodeQL triage, use [$agentsociety-maintain](.agents/skills/agentsociety-maintain/SKILL.md). Create a dedicated local branch before editing. Review mirror PRs locally, validate the changes, and prepare an MR only after verification.

## Setup

```bash
# Python 3.11.5 through 3.13, from the workspace root
uv sync --locked --package agentsociety2 --no-default-groups --extra dev

# Extension
cd extension && npm ci && npm run lint && npm run build

# Frontend
cd frontend && npm ci && npm run lint && npm run build
```

Required env vars: `AGENTSOCIETY_LLM_API_KEY`, `AGENTSOCIETY_LLM_API_BASE`. Default model when unset: `gpt-5.5`. See `.env.example`.

## Before you change code

1. **Scope** — stay inside AS2 paths unless explicitly asked for legacy.
2. **Import** — use `import agentsociety2`; do not treat `packages/agentsociety2/` as a runtime path.
3. **Tests** — `cd packages/agentsociety2 && uv run pytest` for behavior changes.
4. **Lockfiles** — run `uv lock` at repo root when Python deps change; use `npm ci` (not `npm install`) in extension/frontend.
5. **Telemetry** — set `MEM0_TELEMETRY=False` and `ANONYMIZED_TELEMETRY=False` in tests.
6. **Commits** — Conventional Commits (`feat`, `fix`, `docs`, `chore`, `ci`, …). Release tag: `agentsociety2-vX.Y.Z`.

## Key subsystems (pointers)

| Area | Entry | Notes |
| ---- | ----- | ----- |
| Simulation CLI | `agentsociety2/society/cli.py` | `--log-file` required for background runs |
| PersonAgent | `agentsociety2/agent/` | metadata-first skill loop; built-in: daily-guidance |
| Env routers | `agentsociety2/env/` | ReAct, PlanExecute, CodeGen, TwoTier variants |
| Analysis harness | `agentsociety2/skills/analysis/harness/` | phase gates, EDA embed, experience memory (`draft-reflection` / `promote-reflection`) |
| Backend API | `agentsociety2/backend/run.py` | FastAPI on `:8001`, separate from CLI |
| Paper workflow | external `paper-toolkit` plugin | built-in `paper` skill removed in 2.5.2 |

## Local verification (pre-push)

```bash
make check
```

Or run each stack separately — see [CONTRIBUTING.md](./CONTRIBUTING.md).

## Docs

- User docs (v2): [agentsociety2.readthedocs.io](https://agentsociety2.readthedocs.io/) — config in `packages/agentsociety2/.readthedocs.yaml`
- v1 docs: root `.readthedocs.yaml` → `packages/agentsociety/docs/` (legacy)
- Authoring guide: [READTHEDOCS.md](./READTHEDOCS.md)
- Changelog: `git-cliff --unreleased` (see `cliff.toml`)
