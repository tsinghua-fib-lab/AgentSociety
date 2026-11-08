"""Download a versioned routing binary and verify it before publication."""

import hashlib
import os
import platform
import re
import tempfile
from pathlib import Path

import requests

from agentsociety2.logger import get_logger

__all__ = ["download_binary"]

ROUTING_VERSION = "v2.0.10"
BIN_SOURCES = {
    "routing": {
        "linux_x86_64": f"https://tsinghua-agentsociety.oss-cn-beijing.aliyuncs.com/routing/{ROUTING_VERSION}/routing_linux_amd64",
        "darwin_arm64": f"https://tsinghua-agentsociety.oss-cn-beijing.aliyuncs.com/routing/{ROUTING_VERSION}/routing_darwin_arm64",
    },
}

# Digests captured from the publisher's versioned HTTPS artifacts on 2026-11-07.
# macOS matches the original branch's separately recorded digest. The publisher
# supplies no detached signature; these pins prevent later content replacement,
# and are not evidence of reproducible builds or independent provenance.
ROUTING_SHA256 = {
    "linux_x86_64": "8484cd3b96aaceea29b3feffa3fa3caee9dad8de4c44754b239c4f93bea9e74c",
    "darwin_arm64": "38c5c98cbb3e423b5f9f4bdb5f01175e0d7201338949f1761eb1c236bbd21fa5",
}


def download_binary(home_dir: str) -> str:
    """Return a verified executable, preserving the previous file on failure."""
    system, machine = platform.system(), platform.machine()
    if system == "Linux" and machine == "x86_64":
        key = "linux_x86_64"
    elif system == "Darwin" and machine in {"arm64", "aarch64"}:
        key = "darwin_arm64"
    else:
        raise RuntimeError("routing supports Linux x86_64 and macOS arm64 only")
    expected = os.environ.get(
        f"AGENTSOCIETY_ROUTING_SHA256_{key.upper()}", ROUTING_SHA256.get(key, "")
    )
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected):
        raise ValueError(f"Missing or invalid routing SHA-256 for {key}")
    expected = expected.lower()
    destination = Path(home_dir).absolute() / "routing"
    if destination.is_file():
        actual = hashlib.sha256(destination.read_bytes()).hexdigest()
        if actual == expected:
            destination.chmod(0o700)
            return str(destination)
        get_logger().warning(
            f"Pre-existing routing binary SHA-256 mismatch for {key}; replacing after verification"
        )

    response = requests.get(BIN_SOURCES["routing"][key], timeout=120)
    if response.status_code != 200:
        raise RuntimeError("Download failed for routing")
    data = response.content
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise ValueError(
            f"routing binary SHA-256 mismatch for {key}: expected {expected}, got {actual}"
        )

    # The executable path is visible only after the verified bytes are complete.
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".routing-", dir=destination.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            os.fchmod(stream.fileno(), 0o700)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    get_logger().info(f"Downloaded verified routing to {destination}")
    return str(destination)


if __name__ == "__main__":
    print(download_binary("."))
