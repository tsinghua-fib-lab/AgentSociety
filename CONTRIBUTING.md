# Contributing

Thanks for contributing to AgentSociety.

## Where to contribute

| Platform                                     | Role                                                            |
| -------------------------------------------- | --------------------------------------------------------------- |
| **GitLab** (`git.fiblab.net`)                | Primary remote — MRs, CI pipelines, Docker build, GitHub mirror |
| **GitHub** (`tsinghua-fib-lab/AgentSociety`) | Public mirror — Issues, Discussions, Dependabot, CodeQL         |

Open merge requests on GitLab for code changes. GitHub Issues/Discussions are fine for public bug reports and questions.

## Quick start

- **Bug report / feature request**: [GitHub Issues](https://github.com/tsinghua-fib-lab/AgentSociety/issues)
- **Code changes**: open a Merge Request on GitLab with a clear summary and test plan
- **Questions**: [GitHub Discussions](https://github.com/tsinghua-fib-lab/AgentSociety/discussions)

## Active scope

CI, security scanning, and dependency bots focus on **AgentSociety 2** only:

- `packages/agentsociety2/`
- `extension/`
- `frontend/`

Legacy packages (`packages/agentsociety`, `agentsociety-community`, `agentsociety-benchmark`, `packages/agentsociety/docs`) are out of active CI scope. See [`.github/agentsociety2-scope.yml`](./.github/agentsociety2-scope.yml).

## Development setup

- **Python**: 3.11+
- **Package manager**: [uv](https://docs.astral.sh/uv/)

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh

# Workspace root (optional: set UV_INDEX_URL to your preferred PyPI mirror)
uv sync

cd packages/agentsociety2
uv sync --extra dev
```

### Extension

```bash
cd extension
npm ci
npm run dev          # watch TypeScript + webview
npm run lint
npm run build
npm audit --audit-level=high
```

### Frontend

```bash
cd frontend
npm ci
npm run lint
npm run build
npm audit --audit-level=high
```

## Pull request checklist

- **Scope**: keep changes focused; avoid unrelated refactors
- **Docs**: update README / CHANGELOG / CONTRIBUTING when behavior or workflow changes
- **Tests**: add or update tests for behavior changes
- **Telemetry**: set `MEM0_TELEMETRY=False` and `ANONYMIZED_TELEMETRY=False` in test environments
- **Lockfiles**: run `uv lock` when changing Python dependencies

## Branch names

Use a short, lowercase purpose prefix and a descriptive slug: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`, or `chore/<topic>`. Use `release/X.Y.Z` for release branches. For example: `docs/as2-release-polish`. Avoid temporary status names such as `ready` or `final`; keep local recovery branches separate from review branches.

GitHub is a mirror of the primary GitLab repository. Repository rules and CI maintenance are described in [the GitHub guide](./.github/README.md).

## Commit conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```text
type(scope): description
```

- **Types**: `feat`, `fix`, `perf`, `refactor`, `docs`, `test`, `chore`, `ci`
- **Scopes**: `agent`, `env`, `extension`, `frontend`, `backend`, `cli`, etc.

PR descriptions should include **Summary**, **Test plan**, and **Breaking changes** (if any).

## Changelog and versions

[CHANGELOG.md](./CHANGELOG.md) is the curated source for both GitLab and GitHub release notes. It follows [Keep a Changelog 2.0.0](https://keepachangelog.com/en/2.0.0/): maintain `Unreleased`, dated releases in newest-first order, comparison links, and the six categories `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security`. Omit empty categories. Put performance improvements under `Changed`, explain dependency changes by their user impact, and mark incompatible changes with **Breaking:** plus upgrade instructions. Keep the historical v1 archive separate from AS2 policy.

The SDK and extension use independent [Semantic Versions](https://semver.org/spec/v2.0.0.html):

| Change | SDK example | Extension example |
| --- | --- | --- |
| Compatible fixes | `2.10.1` → `2.10.2` | `1.8.1` → `1.8.2` |
| Compatible new functionality | `2.10.1` → `2.11.0` | `1.8.1` → `1.9.0` |
| Incompatible public API or configuration | Increment major; document migration | Increment major; document migration |

Only bump a component when it changes. SDK versions must match in `packages/agentsociety2/pyproject.toml`, `agentsociety2/__init__.py` and the root `uv.lock`; extension versions must match in `extension/package.json` and both root version fields in its `package-lock.json`. The frontend is private and is not separately published. A stable tag is exactly `agentsociety2-vX.Y.Z`, matching the SDK; each release entry states the bundled extension version. The current publication workflows accept stable releases only. Prerelease tags require a separate PyPI/VSIX and hosted-release policy before enabling them.

[git-cliff](https://git-cliff.org/docs/configuration/git/) remains an optional drafting tool. Review `git-cliff --unreleased` and copy useful entries into the curated changelog; do not overwrite its historical entries with generated commit subjects. No git-cliff installation is required by CI. Both hosts extract the exact tag's existing section using the same dependency-free script:

```bash
python scripts/ci/release.py check
python scripts/ci/release.py notes --tag agentsociety2-vX.Y.Z --output /tmp/as2-release-notes.md
```

## Release process

1. Create `release/X.Y.Z` from `main`; choose SDK and extension versions using the rules above.
2. Update the SDK manifest and runtime version together; run `uv lock` at the repository root. If the extension changes, update its manifest and both root version fields in `package-lock.json`, then verify installation with `npm ci`.
3. Move the reviewed `Unreleased` entries into `## [X.Y.Z] - YYYY-MM-DD`, add the SDK/extension version summary and comparison link, and leave a new `Unreleased` section for future changes. Do not invent a release date in advance or reuse a published tag.
4. Run `make check`, `make ci-docs-build`, `make ci-docs-browser` and `make ci-package`. Preview the exact release notes and validate all metadata:

   ```bash
   python scripts/ci/release.py check --tag agentsociety2-vX.Y.Z
   python scripts/ci/release.py notes --tag agentsociety2-vX.Y.Z --output /tmp/as2-release-notes.md
   ```

5. After review and merging the release changes to `main`, create an annotated tag and push it to the primary GitLab remote:

   ```bash
   git tag -a agentsociety2-vX.Y.Z -m "AgentSociety 2 X.Y.Z"
   git push origin agentsociety2-vX.Y.Z
   ```

6. GitLab validates release metadata and runs SDK, extension, frontend, documentation, packaging and CodeQL gates, creates its Release, and mirrors the tag to GitHub when `GITHUB_DEPLOY_KEY` is configured. GitHub validates the same metadata and common checks, builds Python distributions and the VSIX, then publishes PyPI and a GitHub Release with those artifacts. Both Release pages use the same curated notes. Publishing still requires the configured mirror credential, PyPI trusted publisher/environment and repository permissions; local checks do not prove these hosted settings are configured.

Versions, tags and repository changelog commits are **not automatically created**. This keeps the version choice and release timing in the review process; pushing the approved stable tag triggers the publication steps. A rerun may complete failed publication steps, but published versions and tags must never be overwritten.

Local VSIX without tagging:

```bash
cd extension && npm run package:check
# or from repo root: make package-extension
```

## CI overview

| Check             | Workflow                      |
| ----------------- | ----------------------------- |
| Python lint/test  | `ci.yml`                      |
| Extension         | `extension-ci.yml`            |
| Frontend          | `frontend-ci.yml`             |
| Documentation     | `docs-ci.yml`                 |
| Dependency review | `dependency-review.yml` (PRs) |
| CodeQL            | `codeql.yml` (scoped paths)   |
| Publish on tag    | `agentsociety2-publish.yml`   |

GitHub Actions and GitLab CI call the same root Makefile targets. Their correspondence, offline test settings, and pinned CodeQL runner are documented in [scripts/ci/README.md](./scripts/ci/README.md). CI configuration checks detect drift between the two platforms.

Local checks before pushing (install Python dev/docs dependencies and both Node projects first):

```bash
cd frontend && npx playwright install chromium
# Return to the repository root:
cd ..
make check
make ci-docs-build ci-docs-browser
```

`make check` runs CI configuration checks, Python lint/types/offline tests, extension checks, and frontend lint/build/browser tests. Browser regressions run locally during development; GitHub and GitLab CI retain frontend lint/build, SDK and extension checks, strict bilingual documentation builds, and release validation. CI does not install or run browsers. Use `make check-frontend` for frontend-only checks and `make ci-docs-browser` after changing documentation interactions. Network tests are opt-in; the default suite uses no model credentials. `AS2_PYTHON` selects an existing Python environment, while `PLAYWRIGHT_CHROMIUM_EXECUTABLE` selects an existing Chromium installation. Run `make ci-package` separately to check the SDK distributions.

Extension-only iteration: `make dev` / `make rebuild` (see `make help`). Frontend has aggregate `make lint-frontend` / `make build-frontend` targets but no dev-watch target — run `npm run dev` inside `frontend/`.

## Code style

```bash
cd packages/agentsociety2
uv run ruff check .
uv run ruff format .
uv run mypy tests/ --follow-imports=skip
```

Pre-commit hooks (optional): `pre-commit install` — `ruff` is scoped to `packages/agentsociety2/`.
