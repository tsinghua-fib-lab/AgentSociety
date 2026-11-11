# GitHub maintenance

GitLab is the primary repository; `.gitlab-ci.yml` mirrors `main` and `agentsociety2-v*` tags to GitHub with a deploy key. GitHub hosts public issues, dependency updates, and additional checks. Active code scope is defined in [agentsociety2-scope.yml](./agentsociety2-scope.yml).

## Protection rules

The JSON files in [rulesets/](./rulesets/) are **disabled REST request drafts**. Checking them in does not change GitHub settings. After review, an administrator can set `enforcement` to `active` and apply the payload through GitHub's repository rulesets API. Inspect existing effective rules first to avoid duplicates.

| Draft | Behavior when enabled |
| --- | --- |
| [main-mirror.json](./rulesets/main-mirror.json) | Prevent deletion and non-fast-forward updates to the default branch; allow the mirror's normal fast-forward push. |
| [main-mirror-writers.json](./rulesets/main-mirror-writers.json) | Optional additional rule: allow updates only from repository deploy keys with write access. Human/API pushes and GitHub PR merges are blocked. |
| [as2-release-tags.json](./rulesets/as2-release-tags.json) | Allow creation of `agentsociety2-v*` tags; prevent later updates and deletion. |

The main draft provides basic history protection. It does not restrict who may make fast-forward pushes. The optional writers draft restricts updates separately. GitHub represents the DeployKey bypass as `actor_id: null`, which covers the deploy-key actor type, not one key ID. Audit write-enabled keys before enabling it and whenever keys change. Keep the history rule without bypasses so even the mirror cannot force-push or delete main. See the [rulesets API](https://docs.github.com/en/rest/repos/rules#create-a-repository-ruleset).

Do not require GitHub PR merges, linear history, signatures, or pre-existing status checks on mirror pushes without checking the GitLab release and mirror flow. The current primary branch includes merge commits, and the mirror pushes changes before GitHub checks run. Review and merge gates belong on the primary GitLab branch unless the mirror has an explicitly reviewed bypass.

GitHub workflows use path filters. Making every workflow a required check can leave unrelated PRs waiting for checks that never run. Introduce an always-running gate before requiring path-filtered checks; do not use the same job name in different workflows. See [GitHub's status-check guidance](https://docs.github.com/en/pull-requests/how-tos/merge-and-close-pull-requests/troubleshooting-required-status-checks).

Keep legacy tag rules separate from the AS2 release namespace. Consider enabling secret-scanning push protection and deleting merged PR branches automatically; these are repository settings, not effects of these JSON files.

## Checks and templates

- SDK CI runs lint, type checking, tests, and package builds with frozen project dependencies. SDK and documentation installs use official PyPI on GitHub runners; local index configuration is unchanged.
- Extension CI runs `npm run check`, including regression tests.
- Frontend CI tests the production build in Chromium, including map, plot, questionnaire, and skill interactions.
- Documentation CI builds Chinese and English with `-n -W`, checks local assets and generated HTML links, tests real search and documentation controls in Chromium, and uploads a short-lived preview artifact.

GitHub Actions 与 GitLab CI 共用根目录的 `make ci-*` 入口，配置一致性检查覆盖命令、Node 版本、离线测试环境与 CodeQL 语言矩阵。CodeQL 两处使用同一版本清单和查询配置；本地复现方法见 [scripts/ci/README.md](../scripts/ci/README.md)。GitLab 保留现有清华源设置，本地源配置也不作调整。
- Dependency audits remain advisory; the dependency-review workflow blocks high-severity dependency changes on applicable PRs.
- Vulnerability reports go through private GitHub reporting or the contact in [SECURITY.md](../SECURITY.md). Public issue templates should never ask users to disclose exploits or credentials.

Remote rules and Actions runs require a separate review from local checks. A locally valid workflow has not yet been executed on a GitHub runner. Documentation authoring and local previews are described in [READTHEDOCS.md](../READTHEDOCS.md).
