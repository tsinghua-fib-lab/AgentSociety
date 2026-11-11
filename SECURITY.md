# Security Policy

## Supported versions

We actively investigate and patch security issues in the **current AgentSociety 2 release line**:

| Component                | Source                             | Actively maintained             |
| ------------------------ | ---------------------------------- | ------------------------------- |
| `agentsociety2` (Python) | `packages/agentsociety2/`          | Yes                             |
| VS Code extension        | `extension/`                       | Yes                             |
| Web frontend             | `frontend/`                        | Yes                             |
| `agentsociety` v1.x      | `packages/agentsociety/`           | Legacy — best-effort only       |
| `agentsociety-community` | `packages/agentsociety-community/` | Legacy — not in active CI scope |
| `agentsociety-benchmark` | `packages/agentsociety-benchmark/` | Legacy — not in active CI scope |

Upgrade to the latest [PyPI release](https://pypi.org/project/agentsociety2/) before reporting an issue.

Security scanning (CodeQL, Dependabot, CI audits) is scoped to AgentSociety 2 paths. See [`.github/agentsociety2-scope.yml`](./.github/agentsociety2-scope.yml).

## Reporting a vulnerability

**Do not** open a public GitHub issue for exploitable vulnerabilities or exposed credentials.

Report privately with:

- Description and impact
- Steps to reproduce (PoC if possible)
- Affected component, version, or commit hash
- Suggested fix or mitigation (optional)

**Contact**

- [Report privately through GitHub](https://github.com/tsinghua-fib-lab/AgentSociety/security/advisories/new)
- Email: agentsociety.fiblab2025@gmail.com
- For general hardening suggestions without vulnerability details, use a normal feature request.

## Disclosure

We will acknowledge receipt, investigate, and coordinate a fix and release. We aim to provide an initial response within a reasonable timeframe.

## Security practices for contributors

- Never commit API keys, tokens, or `.env` files
- Run `pre-commit` hooks (`detect-private-key` is enabled)
- Extension `.env` writes escape sensitive values; do not log API keys
- Backend path helpers reject `..` and null bytes in user-supplied paths
