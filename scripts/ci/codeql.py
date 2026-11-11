"""Run the pinned CodeQL bundle and shared queries in GitLab or locally."""

from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import logging
import os
import platform
import re
import shutil
import signal
import ssl
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
BUNDLE = Path(__file__).with_name("codeql-bundle.json")
LANGUAGES = ("python", "javascript-typescript", "actions")
LOG = logging.getLogger(__name__)
NETWORK_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    ConnectionError,
    http.client.HTTPException,
    ssl.SSLError,
)


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


@contextmanager
def download_deadline(seconds: float):
    """Bound the entire Linux download, including slow but active responses."""

    def expired(signum, frame):
        raise RuntimeError(
            f"CodeQL download exceeded its {seconds:g}s total budget; "
            "partial archive saved. Prewarm the Runner cache, configure "
            "CODEQL_BUNDLE_URL for an internal mirror, or provide --codeql"
        )

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def download_bundle(
    cache: Path,
    bundle: dict[str, str],
    *,
    url: str | None = None,
    timeout: float = 30,
    attempts: int = 2,
    total_timeout: float = 300,
) -> Path:
    """Verify cached archives or download within one shared wall-clock budget."""
    with download_deadline(total_timeout):
        return _download_bundle(
            cache, bundle, url=url, timeout=timeout, attempts=attempts
        )


def _download_bundle(
    cache: Path,
    bundle: dict[str, str],
    *,
    url: str | None = None,
    timeout: float = 30,
    attempts: int = 2,
) -> Path:
    """Resume interrupted transfers; accept only the pinned SHA256 archive."""
    downloads = cache / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    archive = downloads / (bundle["sha256"] + ".tar.gz")
    partial = archive.with_suffix(archive.suffix + ".part")
    for candidate in (archive, partial):
        if candidate.is_file() and sha256(candidate) == bundle["sha256"]:
            if candidate != archive:
                os.replace(candidate, archive)
            LOG.info("Using verified CodeQL archive from cache")
            return archive
    archive.unlink(missing_ok=True)
    urls = list(dict.fromkeys([url] if url else [bundle["url"], bundle["api_url"]]))
    for source in urls:
        if urlsplit(source).scheme not in {"https", "http"}:
            raise ValueError("CodeQL downloads require an HTTP(S) URL")
    last_error = None
    for attempt in range(attempts):
        for source in urls:
            offset = partial.stat().st_size if partial.exists() else 0
            LOG.info(
                "CodeQL download attempt %s/%s via %s; resuming at %s bytes",
                attempt + 1,
                attempts,
                urlsplit(source).hostname,
                offset,
            )
            headers = {
                "User-Agent": "AgentSociety-CodeQL",
                "Accept": "application/octet-stream",
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
            }
            if offset:
                headers["Range"] = f"bytes={offset}-"
            try:
                request = urllib.request.Request(source, headers=headers)
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    if "json" in response.headers.get(
                        "Content-Type", ""
                    ) or "text/html" in response.headers.get("Content-Type", ""):
                        raise urllib.error.URLError(
                            "Download endpoint returned a document instead of the bundle"
                        )
                    content_range = response.headers.get("Content-Range", "")
                    if response.status == 206:
                        match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", content_range)
                        if match is None or int(match[1]) != offset:
                            partial.unlink(missing_ok=True)
                            raise urllib.error.URLError("Invalid download resume range")
                        total = int(match[3])
                    elif response.status == 200:
                        offset = 0
                        total = (
                            int(response.headers["Content-Length"])
                            if response.headers.get("Content-Length")
                            else None
                        )
                    else:
                        raise urllib.error.URLError(
                            f"Unexpected download HTTP status {response.status}"
                        )
                    progress = time.monotonic()
                    with partial.open("ab" if offset else "wb") as output:
                        while chunk := response.read(1024 * 1024):
                            output.write(chunk)
                            if time.monotonic() - progress >= 30:
                                LOG.info(
                                    "Downloaded %.1f MiB", output.tell() / 1024 / 1024
                                )
                                progress = time.monotonic()
                    if total is not None and partial.stat().st_size != total:
                        raise http.client.IncompleteRead(b"")
                if sha256(partial) != bundle["sha256"]:
                    partial.unlink(missing_ok=True)
                    raise RuntimeError("CodeQL bundle checksum mismatch")
                os.replace(partial, archive)
                return archive
            except NETWORK_ERRORS as error:
                last_error = error
                if isinstance(error, urllib.error.HTTPError):
                    if error.code == 416:
                        partial.unlink(missing_ok=True)
                    error.close()
                detail = (
                    f"HTTP {error.code}"
                    if isinstance(error, urllib.error.HTTPError)
                    else type(error).__name__
                )
                LOG.warning("CodeQL download interrupted: %s", detail)
        if attempt + 1 < attempts:
            time.sleep(min(2**attempt, 10))
    raise RuntimeError(
        f"CodeQL download failed after {attempts} attempts per endpoint ({type(last_error).__name__}); retry with the saved partial archive, configure CODEQL_BUNDLE_URL for an internal mirror, or provide --codeql"
    ) from last_error


def install_bundle(cache: Path, bundle: dict[str, str], **download_options) -> Path:
    """Install a verified archive once and reuse it for every selected language."""
    target = cache / bundle["version"]
    executable = target / "codeql/codeql"
    marker = target / "verified.sha256"
    if (
        executable.is_file()
        and marker.is_file()
        and marker.read_text().strip() == bundle["sha256"]
    ):
        LOG.info("Using installed CodeQL %s", bundle["version"])
        return executable
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "AMD64"}:
        raise RuntimeError(
            "The pinned bundle requires Linux x64; use --codeql for another platform"
        )
    cache.mkdir(parents=True, exist_ok=True)
    archive = download_bundle(cache, bundle, **download_options)
    with tempfile.TemporaryDirectory(prefix="codeql-extract-", dir=cache) as temporary:
        extracted = Path(temporary) / "extracted"
        extracted.mkdir()
        with tarfile.open(archive) as source:
            source.extractall(extracted, filter="data")
        if not (extracted / "codeql/codeql").is_file():
            raise RuntimeError("CodeQL archive is missing its executable")
        (extracted / "verified.sha256").write_text(bundle["sha256"] + "\n")
        if target.exists():
            shutil.rmtree(target)
        os.replace(extracted, target)
    return executable


def analyze(executable: Path, language: str, args: argparse.Namespace) -> None:
    database = args.databases.resolve() / language
    subprocess.run(
        [
            str(executable),
            "database",
            "create",
            str(database),
            f"--language={language}",
            "--build-mode=none",
            f"--source-root={ROOT}",
            f"--codescanning-config={ROOT / '.github/codeql/codeql-config.yml'}",
            f"--threads={args.threads}",
            f"--ram={args.ram}",
        ],
        check=True,
        cwd=ROOT,
    )
    subprocess.run(
        [
            str(executable),
            "database",
            "analyze",
            str(database),
            "--format=sarif-latest",
            f"--output={args.output.resolve() / (language + '.sarif')}",
            f"--threads={args.threads}",
            f"--ram={args.ram}",
        ],
        check=True,
        cwd=ROOT,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--language", choices=(*LANGUAGES, "all"))
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--codeql", type=Path)
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache/codeql")
    parser.add_argument("--databases", type=Path, default=ROOT / "codeql-databases")
    parser.add_argument("--output", type=Path, default=ROOT / "codeql-results")
    parser.add_argument("--threads", type=int, default=2)
    parser.add_argument("--ram", type=int, default=4096)
    parser.add_argument("--bundle-url", default=os.environ.get("CODEQL_BUNDLE_URL"))
    parser.add_argument("--download-timeout", type=float, default=30)
    parser.add_argument("--download-attempts", type=int, default=2)
    parser.add_argument("--download-total-timeout", type=float, default=300)
    args = parser.parse_args()
    bundle = json.loads(BUNDLE.read_text())
    if args.github_output:
        with args.github_output.open("a") as output:
            output.write(f"url={bundle['url']}\n")
        return 0
    if not args.language:
        parser.error("--language is required for analysis")
    if (
        args.download_timeout <= 0
        or args.download_total_timeout <= 0
        or args.download_attempts < 1
    ):
        parser.error("Download timeout and attempts must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(args.output / "runner.log"),
        ],
    )
    status = {
        "version": bundle["version"],
        "phase": "setup",
        "status": "running",
        "languages": {},
    }
    try:
        executable = (
            args.codeql.resolve()
            if args.codeql
            else install_bundle(
                args.cache.resolve(),
                bundle,
                url=args.bundle_url,
                timeout=args.download_timeout,
                attempts=args.download_attempts,
                total_timeout=args.download_total_timeout,
            )
        )
        version = json.loads(
            subprocess.check_output(
                [str(executable), "version", "--format=json"], text=True
            )
        )
        if version["version"] != bundle["version"]:
            raise RuntimeError(
                f"Expected CodeQL {bundle['version']}, got {version['version']}"
            )
        args.databases.mkdir(parents=True, exist_ok=True)
        status["phase"] = "analysis"
        for language in LANGUAGES if args.language == "all" else (args.language,):
            LOG.info("Analyzing %s with CodeQL %s", language, bundle["version"])
            try:
                analyze(executable, language, args)
                status["languages"][language] = "passed"
            except subprocess.CalledProcessError:
                status["languages"][language] = "failed"
                LOG.error("CodeQL analysis failed: %s", language)
        status["status"] = (
            "failed" if "failed" in status["languages"].values() else "passed"
        )
    except (
        RuntimeError,
        OSError,
        ValueError,
        tarfile.TarError,
        subprocess.SubprocessError,
    ) as error:
        status.update(status="failed", error=str(error))
        LOG.error("CodeQL %s failed: %s", status["phase"], error)
    finally:
        (args.output / "status.json").write_text(json.dumps(status, indent=2) + "\n")
    return 0 if status["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
