#!/usr/bin/env python3
"""Resolve installed agentsociety2 source locations for this skill."""

from __future__ import annotations

import argparse
import json
from importlib import metadata
from pathlib import Path


DEFAULT_MODULES = [
    "agentsociety2.env.base",
    "agentsociety2.env.router_codegen",
    "agentsociety2.custom.envs.examples.advanced_env",
    "agentsociety2.contrib.env.simple_social_space",
    "agentsociety2.contrib.env.economy_space",
    "agentsociety2.contrib.env.mobility_space.environment",
    "agentsociety2.registry.modules",
    "agentsociety2.registry.base",
]


def parse_args() -> argparse.Namespace:
    """Parse CLI args."""

    parser = argparse.ArgumentParser(
        description="Resolve installed file paths for agentsociety2 modules used by the create-env skill.",
    )
    parser.add_argument(
        "--module",
        action="append",
        dest="modules",
        help="Specific module name to resolve. Can be passed multiple times.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    return parser.parse_args()


def _distribution() -> metadata.Distribution:
    """Return the installed distribution metadata for agentsociety2."""

    return metadata.distribution("agentsociety2")


def _editable_roots(distribution: metadata.Distribution) -> list[Path]:
    """Return editable roots from .pth files when present."""

    roots: list[Path] = []
    site_root = Path(distribution.locate_file("")).resolve()
    for pth_name in ("_agentsociety2.pth", "agentsociety2.pth"):
        pth_path = site_root / pth_name
        if not pth_path.exists():
            continue
        for line in pth_path.read_text(encoding="utf-8").splitlines():
            candidate = line.strip()
            if not candidate or candidate.startswith("#"):
                continue
            candidate_path = Path(candidate).resolve()
            if candidate_path.exists():
                roots.append(candidate_path)
    return roots


def resolve_module_path(
    module_name: str,
    distribution: metadata.Distribution,
) -> dict[str, str]:
    """Resolve the file path for a module without importing it."""

    relative_parts = module_name.split(".")
    module_relpath = "/".join(relative_parts) + ".py"
    package_relpath = "/".join(relative_parts) + "/__init__.py"

    candidates = []
    for file_entry in distribution.files or []:
        file_posix = str(file_entry).replace("\\", "/")
        if file_posix.endswith(module_relpath) or file_posix.endswith(package_relpath):
            candidates.append(file_entry)

    for candidate in candidates:
        candidate_path = Path(distribution.locate_file(candidate)).resolve()
        if candidate_path.exists():
            return {
                "module": module_name,
                "status": "ok",
                "path": str(candidate_path),
            }

    # Fallback for environments where distribution.files is incomplete.
    root = Path(distribution.locate_file("")).resolve()
    search_roots = [root, *_editable_roots(distribution)]
    fallback_candidates = []
    for search_root in search_roots:
        fallback_candidates.extend(
            [
                search_root.joinpath(*relative_parts).with_suffix(".py"),
                search_root.joinpath(*relative_parts, "__init__.py"),
                search_root.joinpath(*relative_parts[1:]).with_suffix(".py"),
                search_root.joinpath(*relative_parts[1:], "__init__.py"),
            ]
        )
    for candidate_path in fallback_candidates:
        if candidate_path.exists():
            return {
                "module": module_name,
                "status": "ok",
                "path": str(candidate_path.resolve()),
            }

    return {
        "module": module_name,
        "status": "error",
        "error": "module file not found in installed distribution",
    }


def main() -> int:
    """Resolve configured modules."""

    args = parse_args()
    module_names = args.modules or DEFAULT_MODULES
    try:
        distribution = _distribution()
    except metadata.PackageNotFoundError:
        message = "agentsociety2 is not installed in the current Python environment"
        if args.json:
            print(json.dumps([{"module": "agentsociety2", "status": "error", "error": message}], ensure_ascii=False, indent=2))
        else:
            print(f"agentsociety2: ERROR: {message}")
        return 1

    results = [
        resolve_module_path(module_name, distribution)
        for module_name in module_names
    ]

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        for item in results:
            if item["status"] == "ok":
                print(f"{item['module']}: {item['path']}")
            else:
                print(f"{item['module']}: ERROR: {item['error']}")

    return 0 if all(item["status"] == "ok" for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
