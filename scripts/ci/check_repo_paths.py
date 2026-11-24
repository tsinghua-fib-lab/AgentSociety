"""Check Git-tracked files for developer-machine paths and conflicting ignore rules."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Require a path boundary so a URL's /en/home/ or a relative project directory
# such as docs/users/ does not look like an operating system home directory.
LOCAL_PATH = re.compile(
    rb"""(?:^|[\s"'=(<`]|file://)(?:(?:/|(?:\.\./)+)(?:(?:data\d+/)?home/|Users/)[\w.-]+"""
    rb"""|/(?:data\d+|Volumes|mnt|media|scratch|private/var/folders)/[\w.-]+"""
    rb"""|[a-zA-Z]:[\\/]+Users[\\/]+[\w.-]+)"""
)

# These files specify container mount points or synthetic file-access inputs.
TEMP_PATH_FIXTURES = {
    "Dockerfile",
    ".agents/skills/agentsociety-maintain/SKILL.md",
    "packages/agentsociety2/security_benchmark.py",
}
TEMP_PATH = re.compile(rb"""(?:^|[\s"'=(<`]|file://)/(?:tmp|var/tmp|dev/shm)/[\w.-]+""")


def git_files(*args: str) -> list[str]:
    result = subprocess.check_output(["git", "ls-files", "-z", *args], cwd=ROOT)
    return [os.fsdecode(item) for item in result.split(b"\0") if item]


def main() -> int:
    errors = [
        f"{name}: tracked file matches .gitignore"
        for name in git_files(
            "--cached", "--ignored", "--exclude-per-directory=.gitignore"
        )
    ]
    for name in sys.argv[1:] or git_files():
        path = ROOT / name
        if path.is_symlink():
            data = os.fsencode(os.readlink(path))
        elif path.is_file():
            data = path.read_bytes()
        else:
            continue
        if b"\0" in data:
            continue
        # PO files contain plain references; JSON may escape the separators.
        data = data.replace(rb"\/", b"/")
        check_temp = name not in TEMP_PATH_FIXTURES
        if not (LOCAL_PATH.search(data) or (check_temp and TEMP_PATH.search(data))):
            continue
        for number, line in enumerate(data.splitlines(), 1):
            if not (LOCAL_PATH.search(line) or (check_temp and TEMP_PATH.search(line))):
                continue
            # The runtime image declares a home for its own container user.
            if name == "Dockerfile" and re.fullmatch(rb"WORKDIR /home/[\w-]+", line):
                continue
            errors.append(f"{name}:{number}: machine-specific path")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
