"""检查 GitLab / GitHub 的必需步骤、运行版本和 CodeQL 配置是否一致。"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml
from codeql import LANGUAGES

ROOT = Path(__file__).resolve().parents[2]
CHECKS = (
    ("ci.yml", "lint", "lint", "ci-python-lint"),
    ("ci.yml", "test", "test", "ci-python-test"),
    ("ci.yml", "build", "build-package", "ci-package"),
    ("extension-ci.yml", "build", "lint-extension", "ci-extension"),
    ("frontend-ci.yml", "build", "lint-frontend", "ci-frontend"),
    ("docs-ci.yml", "docs", "documentation", "ci-docs-build"),
    ("agentsociety2-publish.yml", "validate", "release-check", "ci-release-check"),
)
STABLE_TAG_RULE = r"$CI_COMMIT_TAG =~ /^agentsociety2-v[0-9]+\.[0-9]+\.[0-9]+$/"


def load(path: Path) -> dict:
    return yaml.load(path.read_text(), Loader=yaml.BaseLoader)


def commands(job: dict) -> str:
    if "steps" in job:
        return "\n".join(step.get("run", "") for step in job["steps"])
    return "\n".join(job.get("script", []))


def audit(root: Path) -> list[str]:
    errors = []
    gitlab = load(root / ".gitlab-ci.yml")
    for filename in (root / ".github/workflows").glob("*.yml"):
        for name, job in load(filename).get("jobs", {}).items():
            if re.search(
                r"\bplaywright\b|\bci-docs-browser\b|\btest:(docs|e2e)\b", commands(job)
            ):
                errors.append(
                    f"GitHub {filename.name}/{name}: browser checks run locally"
                )
    for name, job in gitlab.items():
        if name.startswith(".") or not isinstance(job, dict):
            continue
        setup = "\n".join(job.get("before_script", []))
        if re.search(
            r"\bplaywright\b|\bci-docs-browser\b|\btest:(docs|e2e)\b",
            setup + "\n" + commands(job),
        ):
            errors.append(f"GitLab {name}: browser checks run locally")
        for need in job.get("needs", []):
            dependency = need["job"] if isinstance(need, dict) else need
            if dependency not in gitlab:
                errors.append(f"GitLab {name} needs missing job {dependency}")
    for filename, github_job, gitlab_job, target in CHECKS:
        github = load(root / ".github/workflows" / filename)
        for label, job in [
            (f"GitHub {filename}/{github_job}", github["jobs"][github_job]),
            (f"GitLab {gitlab_job}", gitlab[gitlab_job]),
        ]:
            pattern = rf"\bmake\b[^\n]*\b{re.escape(target)}\b"
            if not re.search(pattern, commands(job)):
                errors.append(f"{label} must run shared {target}")
    python_workflow = load(root / ".github/workflows/ci.yml")
    test_step = next(
        step
        for step in python_workflow["jobs"]["test"]["steps"]
        if "ci-python-test" in step.get("run", "")
    )
    if test_step.get("env") != gitlab["test"].get("variables"):
        errors.append("Python test environments differ")
    version = (root / "extension/.nvmrc").read_text().strip()
    if (root / "frontend/.nvmrc").read_text().strip() != version:
        errors.append("extension and frontend Node versions differ")
    for job in ["lint-extension", "lint-frontend"]:
        if gitlab[job].get("image") != f"node:{version}-bookworm":
            errors.append(f"GitLab {job} Node image differs from .nvmrc")
    github = load(root / ".github/workflows/codeql.yml")
    github_languages = set(github["jobs"]["analyze"]["strategy"]["matrix"]["language"])
    if github_languages != set(LANGUAGES):
        errors.append("CodeQL language matrices differ")
    if "--language all" not in commands(gitlab["codeql"]):
        errors.append("GitLab CodeQL must scan all shared languages in one job")
    for job in ["documentation", "codeql"]:
        if not any(
            "mirrors.tuna.tsinghua.edu.cn/debian" in command
            for command in gitlab[job].get("before_script", [])
        ):
            errors.append(f"GitLab {job} must prepare Debian HTTPS mirrors")
    if not any(
        re.search(r"\bapt-get install\b[^\n]*\bnodejs\b", command)
        for command in gitlab["codeql"].get("before_script", [])
    ):
        errors.append("GitLab CodeQL must install Node.js for TypeScript extraction")
    if "scripts/ci/codeql.py" not in commands(github["jobs"]["analyze"]):
        errors.append("GitHub CodeQL must read the shared bundle manifest")
    if "scripts/ci/codeql.py" not in commands(gitlab["codeql"]):
        errors.append("GitLab CodeQL must use the shared runner")
    init = next(
        step
        for step in github["jobs"]["analyze"]["steps"]
        if "codeql-action/init@" in step.get("uses", "")
    )
    if init["with"].get("config-file") != ".github/codeql/codeql-config.yml":
        errors.append("GitHub CodeQL configuration path differs from the shared runner")
    if init["with"].get("tools") != "${{ steps.bundle.outputs.url }}":
        errors.append("GitHub CodeQL must use the shared bundle URL")
    bundle = json.loads((root / "scripts/ci/codeql-bundle.json").read_text())
    if f"codeql-bundle-v{bundle['version']}/" not in bundle["url"] or not re.fullmatch(
        r"[a-f0-9]{64}", bundle["sha256"]
    ):
        errors.append("Invalid CodeQL bundle version or checksum")
    if not re.fullmatch(
        r"https://api\.github\.com/repos/github/codeql-action/releases/assets/[0-9]+",
        bundle.get("api_url", ""),
    ):
        errors.append("CodeQL fallback must use the official GitHub asset API")
    release = load(root / ".github/workflows/agentsociety2-publish.yml")
    docs_workflow = load(root / ".github/workflows/docs-ci.yml")
    for label, setup in [
        ("GitHub docs", commands(docs_workflow["jobs"]["docs"])),
        ("GitHub release/docs", commands(release["jobs"]["documentation"])),
        ("GitLab docs", "\n".join(gitlab["documentation"].get("before_script", []))),
    ]:
        if not re.search(r"\bapt-get install\b[^\n]*\bgraphviz\b", setup):
            errors.append(f"{label} must install Graphviz for documentation diagrams")
    for job, targets in [
        ("validate", ["ci-config", "ci-python-lint", "ci-python-test", "ci-extension"]),
        ("documentation", ["ci-frontend", "ci-docs-build"]),
    ]:
        for target in targets:
            if not re.search(
                rf"\bmake\b[^\n]*\b{re.escape(target)}\b",
                commands(release["jobs"][job]),
            ):
                errors.append(f"GitHub release/{job} must run shared {target}")
    for job in [
        "release-check",
        "lint",
        "lint-extension",
        "lint-frontend",
        "test",
        "codeql",
        "build-package",
        "documentation",
        "generate-changelog",
        "create-release",
        "mirror-to-github",
    ]:
        if not any(
            rule.get("if") == STABLE_TAG_RULE and "changes" not in rule
            for rule in gitlab[job].get("rules", [])
        ):
            errors.append(f"GitLab {job} must run on stable release tags")
    for job in [
        "docker-publish",
        "docker-publish-extension",
        "docker-publish-dockerfile",
    ]:
        needs = {item["job"]: item for item in gitlab[job].get("needs", [])}
        if "test" not in needs or "parallel" in needs["test"]:
            errors.append(f"GitLab {job} must wait for the full Python test matrix")
        if "lint-frontend" not in needs:
            errors.append(f"GitLab {job} must wait for frontend checks when present")
        if gitlab[job].get("resource_group") != "agentsociety2-runtime-image":
            errors.append(f"GitLab {job} must serialize updates to the runtime image")
        if job == "docker-publish-dockerfile" and "lint-extension" not in needs:
            errors.append(f"GitLab {job} must wait for extension checks when present")
    notes_command = "scripts/ci/release.py notes --release --output release_notes.md"
    if any(
        notes_command not in commands(job)
        for job in [release["jobs"]["github-release"], gitlab["generate-changelog"]]
    ):
        errors.append(
            "Both hosts must derive release notes from the shared curated changelog"
        )
    if release["jobs"]["publish-to-pypi"].get("needs") != [
        "build-python",
        "build-vscode",
        "documentation",
    ]:
        errors.append(
            "PyPI publication must wait for Python, VSIX and documentation checks"
        )
    github_release = next(
        step
        for step in release["jobs"]["github-release"]["steps"]
        if "action-gh-release@" in step.get("uses", "")
    )
    if (
        github_release["with"].get("body_path") != "release_notes.md"
        or gitlab["create-release"]["release"].get("description")
        != "./release_notes.md"
    ):
        errors.append("Both hosts must publish the extracted release notes file")
    return errors


def main() -> int:
    errors = audit(ROOT)
    if errors:
        print("\n".join(errors))
        return 1
    print(
        "GitLab/GitHub shared checks, Node versions and CodeQL configuration are aligned."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
