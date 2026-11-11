"""Validate AS2 release metadata and derive hosted notes from CHANGELOG.md."""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import json
import os
import re
import sys
from pathlib import Path

import tomllib

ROOT = Path(__file__).resolve().parents[2]
VERSION = r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
TAG = re.compile(rf"agentsociety2-v(?P<version>{VERSION})")
CATEGORIES = {"Added", "Changed", "Deprecated", "Removed", "Fixed", "Security"}


def stable_version(value: str) -> tuple[int, int, int]:
    """Require the stable SemVer syntax supported by the publishing workflows."""
    if not re.fullmatch(VERSION, value):
        raise ValueError(f"Expected a stable MAJOR.MINOR.PATCH version: {value}")
    return tuple(int(part) for part in value.split("."))


def read_versions(root: Path) -> tuple[str, str]:
    """Check package, runtime and lock metadata without importing the SDK."""
    package = root / "packages/agentsociety2"
    sdk = tomllib.loads((package / "pyproject.toml").read_text())["project"]["version"]
    stable_version(sdk)
    runtime = ast.parse((package / "agentsociety2/__init__.py").read_text())
    declared = [
        ast.literal_eval(node.value)
        for node in runtime.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "__version__"
            for target in node.targets
        )
    ]
    if declared != [sdk]:
        raise ValueError("SDK pyproject.toml and __version__ differ")
    lock = tomllib.loads((root / "uv.lock").read_text())
    locked = [
        item["version"] for item in lock["package"] if item["name"] == "agentsociety2"
    ]
    if locked != [sdk]:
        raise ValueError("SDK version and uv.lock differ; run uv lock")
    extension = json.loads((root / "extension/package.json").read_text())["version"]
    stable_version(extension)
    npm_lock = json.loads((root / "extension/package-lock.json").read_text())
    if (
        npm_lock["version"] != extension
        or npm_lock["packages"][""]["version"] != extension
    ):
        raise ValueError("Extension package.json and package-lock.json versions differ")
    return sdk, extension


def changelog_sections(text: str) -> dict[str, str]:
    """Validate the AS2 sections; preserve the separate historical v1 archive."""
    active = text.split("## AgentSociety 1.x", 1)[0]
    headings = list(re.finditer(r"^## \[([^\]]+)\](.*)$", active, re.MULTILINE))
    if not headings or headings[0].group(1) != "Unreleased":
        raise ValueError("CHANGELOG must start with one [Unreleased] section")
    sections = {}
    previous = None
    for index, heading in enumerate(headings):
        version, suffix = heading.groups()
        if version in sections:
            raise ValueError(f"Duplicate changelog section: {version}")
        if version == "Unreleased":
            if suffix.strip():
                raise ValueError("Unreleased must not have a release date")
        else:
            current = stable_version(version)
            if previous is not None and current >= previous:
                raise ValueError("Changelog releases must be newest first")
            previous = current
            if not re.fullmatch(r" - \d{4}-\d{2}-\d{2}", suffix):
                raise ValueError(f"Missing YYYY-MM-DD release date: {version}")
            date = dt.date.fromisoformat(suffix.removeprefix(" - "))
            if date > dt.datetime.now(dt.timezone.utc).date():
                raise ValueError(f"Release date is in the future: {version}")
        end = headings[index + 1].start() if index + 1 < len(headings) else len(active)
        section = active[heading.start() : end].strip()
        categories = re.findall(r"^### (.+)$", section, re.MULTILINE)
        if any(category not in CATEGORIES for category in categories):
            raise ValueError(f"Use the six Keep a Changelog categories: {version}")
        if len(categories) != len(set(categories)):
            raise ValueError(f"Duplicate changelog category: {version}")
        for content in re.split(r"^### .+$", section, flags=re.MULTILINE)[1:]:
            if not re.search(r"^- \S", content, re.MULTILINE):
                raise ValueError(f"Remove empty changelog categories: {version}")
        if not re.search(
            rf"^\[{re.escape(version)}\]: https://\S+$",
            text,
            re.MULTILINE | re.IGNORECASE,
        ):
            raise ValueError(f"Missing changelog comparison/release link: {version}")
        sections[version] = section
    return sections


def validate(root: Path, tag: str | None = None) -> tuple[str, str]:
    """Check component versions, curated changelog and an optional release tag."""
    sdk, extension = read_versions(root)
    sections = changelog_sections((root / "CHANGELOG.md").read_text())
    published = [version for version in sections if version != "Unreleased"]
    if published and stable_version(sdk) < stable_version(published[0]):
        raise ValueError("SDK version is older than the newest changelog release")
    if tag is not None:
        match = TAG.fullmatch(tag)
        if match is None or match["version"] != sdk:
            raise ValueError(
                f"Release tag must match SDK version: agentsociety2-v{sdk}"
            )
        if sdk not in sections or not re.search(
            r"^### (?:Added|Changed|Deprecated|Removed|Fixed|Security)$",
            sections[sdk],
            re.MULTILINE,
        ):
            raise ValueError(f"Add a dated, non-empty CHANGELOG entry for {sdk}")
        for name, version in [("agentsociety2", sdk), ("extension", extension)]:
            component = re.search(rf"\*\*{name}\*\*\s+`([^`]+)`", sections[sdk])
            if component is None or component[1] != version:
                raise ValueError(
                    f"Release changelog must state the packaged {name} version"
                )
    elif sdk not in sections and not re.search(
        r"^- ", sections["Unreleased"], re.MULTILINE
    ):
        raise ValueError("A new SDK version needs notable changes under Unreleased")
    return sdk, extension


def release_notes(root: Path, tag: str) -> str:
    """Use the exact tagged version's curated notes on both hosting platforms."""
    sdk, _ = validate(root, tag)
    text = (root / "CHANGELOG.md").read_text()
    section = changelog_sections(text)[sdk].rstrip()
    # Reference definitions are shared by the file, outside individual releases.
    references = [
        match[0]
        for match in re.finditer(r"^\[([^\]]+)\]: https://\S+$", text, re.MULTILINE)
        if f"[{match[1]}]" in section
    ]
    return section + "\n\n" + "\n".join(references) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "notes"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--tag", help="Stable agentsociety2-vX.Y.Z tag to validate")
    parser.add_argument(
        "--release",
        action="store_true",
        help="Require the CI release tag from AS2_RELEASE_TAG or CI_COMMIT_TAG",
    )
    parser.add_argument("--output", type=Path, help="Write release notes to a file")
    args = parser.parse_args()
    try:
        tag = args.tag
        if args.release:
            tag = (
                tag
                or os.environ.get("AS2_RELEASE_TAG")
                or os.environ.get("CI_COMMIT_TAG")
            )
            if not tag:
                raise ValueError("Release validation requires a tag")
        if args.command == "notes":
            if not tag:
                raise ValueError("Select the exact release with --tag or --release")
            notes = release_notes(args.root, tag)
            if args.output:
                args.output.write_text(notes, encoding="utf-8")
            else:
                print(notes, end="")
        else:
            if args.output:
                raise ValueError("--output is only supported by notes")
            sdk, extension = validate(args.root, tag)
            print(
                f"Release metadata valid: SDK {sdk}, extension {extension}"
                + (f", tag {tag}" if tag else "")
            )
    except (KeyError, ValueError, OSError, SyntaxError) as error:
        print(f"Release check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
