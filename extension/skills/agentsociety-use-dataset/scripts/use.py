#!/usr/bin/env python3
"""Dataset usage CLI — search, download, and inspect datasets from agentsociety2-web."""

import argparse
import json
import sys
import time
import zipfile
from pathlib import Path
from urllib.request import Request, urlopen

DEFAULT_SERVER_URL = "https://agentsociety2.fiblab.net"


def _api_get(url, timeout=30):
    """GET request returning parsed JSON."""
    req = Request(url, headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _api_post(url, timeout=120):
    """POST request returning parsed JSON."""
    req = Request(url, method="POST", headers={"Accept": "application/json"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _download_file(url, dest, timeout=300):
    """Download file from URL to local path using GET (direct URL)."""
    req = Request(url, headers={"Accept": "application/zip, application/json"})
    with urlopen(req, timeout=timeout) as resp:
        with open(dest, "wb") as f:
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                f.write(chunk)


def _format_size(n):
    """Format byte count as human-readable string."""
    if n is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.0f} TB"


# --- Metadata helpers ---


def _normalize_metadata(api_resp, source="remote"):
    """Normalize API response to unified local metadata format."""
    return {
        "id": api_resp.get("id", ""),
        "name": api_resp.get("name", ""),
        "description": api_resp.get("description", ""),
        "category": api_resp.get("category", ""),
        "version": api_resp.get("version", ""),
        "tags": api_resp.get("tags", []),
        "author": api_resp.get("author", ""),
        "license": api_resp.get("license", ""),
        "source": source,
        "installed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "package_size_bytes": api_resp.get("package_size_bytes"),
        "created_at": str(api_resp.get("created_at", "")),
        "updated_at": str(api_resp.get("updated_at", "")),
    }


def _parse_version(v):
    """Parse semantic version string to (major, minor, patch) tuple."""
    if not v:
        return (0, 0, 0)
    parts = v.lstrip("v").split(".")
    result = []
    for p in parts[:3]:
        try:
            result.append(int(p))
        except ValueError:
            result.append(0)
    while len(result) < 3:
        result.append(0)
    return tuple(result)


def _compare_versions(local_ver, remote_ver):
    """Compare two version strings. Returns: 'installed' | 'outdated' | 'newer'."""
    lp, rp = _parse_version(local_ver), _parse_version(remote_ver)
    if lp == rp:
        return "installed"
    elif lp < rp:
        return "outdated"
    else:
        return "newer"


def _load_local_datasets(datasets_dir):
    """Load all local dataset metadata. Returns dict of {id: metadata_dict}."""
    datasets_dir = Path(datasets_dir)
    result = {}
    if not datasets_dir.exists():
        return result
    for entry in sorted(datasets_dir.iterdir()):
        if not entry.is_dir():
            continue
        meta_path = entry / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            did = meta.get("id", entry.name)
            result[did] = meta
        except (json.JSONDecodeError, OSError):
            continue
    return result


def _fetch_remote_datasets(server, limit=100, skip=0):
    """Fetch remote dataset list from API. Returns dict of {id: metadata_dict}."""
    try:
        resp = _api_get(f"{server}/api/v1/data/datasets?limit={limit}&skip={skip}")
    except Exception:
        return {}
    datasets = resp.get("datasets", resp) if isinstance(resp, dict) else resp
    if isinstance(datasets, dict):
        datasets = datasets.get("datasets", [])
    if not isinstance(datasets, list):
        return {}
    result = {}
    for ds in datasets:
        did = ds.get("id", "")
        if did:
            result[did] = ds
    return result


# --- Subcommands ---


def _cmd_search(args):
    """List/search available datasets."""
    server = args.server
    params = []
    params.append(f"limit={args.limit}")
    params.append(f"skip={args.skip}")
    if args.category:
        params.append(f"category={args.category}")
    if args.tags:
        params.append(f"tags={args.tags}")

    qs = "&".join(params)
    resp = _api_get(f"{server}/api/v1/data/datasets?{qs}")

    datasets = resp.get("datasets", resp) if isinstance(resp, dict) else resp
    if isinstance(datasets, list) and len(datasets) > 0 and isinstance(datasets[0], dict):
        pass
    elif isinstance(datasets, dict):
        datasets = datasets.get("datasets", [])

    if not datasets:
        print("No datasets found.")
        return 0

    # Table output
    print(f"{'ID':<30} {'Name':<25} {'Category':<20} {'Version':<10} {'Size':<10}")
    print("-" * 95)
    for ds in datasets:
        did = ds.get("id", "")
        name = ds.get("name", "")[:24]
        cat = ds.get("category", "")
        ver = ds.get("version", "")
        size = _format_size(ds.get("package_size_bytes"))
        print(f"{did:<30} {name:<25} {cat:<20} {ver:<10} {size:<10}")

    print(f"\nTotal: {len(datasets)} dataset(s)")
    return 0


def _cmd_info(args):
    """Show dataset metadata (local + remote merged view)."""
    server = args.server
    dataset_id = args.dataset_id
    datasets_dir = Path(args.datasets_dir)

    # Try local first
    local_meta = None
    local_path = datasets_dir / dataset_id / "metadata.json"
    if local_path.exists():
        try:
            local_meta = json.loads(local_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

    # Try remote
    remote_meta = None
    try:
        remote_meta = _api_get(f"{server}/api/v1/data/datasets/{dataset_id}")
    except Exception:
        pass

    # Show info
    if remote_meta:
        print(f"ID:          {remote_meta.get('id', '')}")
        print(f"Name:        {remote_meta.get('name', '')}")
        print(f"Description: {remote_meta.get('description', '')}")
        print(f"Category:    {remote_meta.get('category', '')}")
        print(f"Version:     {remote_meta.get('version', '')}")
        print(f"Tags:        {', '.join(remote_meta.get('tags', [])) or '—'}")
        print(f"Author:      {remote_meta.get('author', '')}")
        print(f"License:     {remote_meta.get('license', '')}")
        print(f"Size:        {_format_size(remote_meta.get('package_size_bytes'))}")
        print(f"Updated:     {remote_meta.get('updated_at', '—')}")
    elif local_meta:
        print(f"ID:          {local_meta.get('id', '')}")
        print(f"Name:        {local_meta.get('name', '')}")
        print(f"Description: {local_meta.get('description', '')}")
        print(f"Category:    {local_meta.get('category', '')}")
        print(f"Version:     {local_meta.get('version', '')}")
        print(f"Tags:        {', '.join(local_meta.get('tags', [])) or '—'}")
        print(f"Author:      {local_meta.get('author', '')}")
        print(f"License:     {local_meta.get('license', '')}")
        print(f"Size:        {_format_size(local_meta.get('package_size_bytes'))}")
        print(f"Installed:   {local_meta.get('installed_at', '—')}")
        print(f"(offline — remote unreachable)")
    else:
        print(f"Dataset '{dataset_id}' not found (locally or remotely).")
        return 1

    # Version comparison
    if local_meta and remote_meta:
        status = _compare_versions(local_meta.get("version", ""), remote_meta.get("version", ""))
        if status == "outdated":
            print(f"\n  ** Local version {local_meta.get('version')} is outdated. Remote: {remote_meta.get('version')}")
            print(
                f"     Update: $PYTHON_PATH .agentsociety/bin/ags.py use-dataset download {dataset_id}"
            )
        elif status == "newer":
            print(f"\n  Local version {local_meta.get('version')} is newer than remote {remote_meta.get('version')}.")
        elif local_meta:
            print(f"\n  (installed, up to date)")

    return 0


def _cmd_readme(args):
    """Display dataset README."""
    server = args.server
    resp = _api_get(f"{server}/api/v1/data/datasets/{args.dataset_id}/readme")
    content = resp.get("content", "")
    print(content)
    return 0


def _cmd_files(args):
    """List dataset file tree."""
    server = args.server
    resp = _api_get(f"{server}/api/v1/data/datasets/{args.dataset_id}/file-tree")
    files = resp.get("files", [])
    if not files:
        print("No files found.")
        return 0
    # Backend may return [{"path": "...", "size_bytes": N}, ...] or ["..."]
    if files and isinstance(files[0], dict):
        for f in sorted(files, key=lambda x: x.get("path", "")):
            path = f.get("path", "?")
            size = f.get("size_bytes")
            size_str = f" ({_format_size(size)})" if size is not None else ""
            print(f"  {path}{size_str}")
    else:
        for f in sorted(files):
            print(f"  {f}")
    return 0


def _cmd_download(args):
    """Download and extract a dataset."""
    server = args.server
    dataset_id = args.dataset_id
    output = Path(args.output)

    # Get metadata
    print(f"Fetching metadata for '{dataset_id}'...")
    meta = _api_get(f"{server}/api/v1/data/datasets/{dataset_id}")

    # Get presigned download URL
    print(f"Requesting download URL...")
    try:
        url_resp = _api_post(f"{server}/api/v1/data/datasets/{dataset_id}/download")
    except Exception as e:
        print(f"Error getting download URL: {e}")
        return 1

    download_url = url_resp.get("url")
    if not download_url:
        print(f"Error: no download URL returned")
        return 1

    # Download ZIP via presigned URL
    dest_dir = output / dataset_id
    zip_path = output / f"{dataset_id}.zip"

    print(f"Downloading...")
    try:
        _download_file(download_url, zip_path)
    except Exception as e:
        print(f"Error downloading: {e}")
        return 1

    # Extract
    dest_dir.mkdir(parents=True, exist_ok=True)
    print(f"Extracting to {dest_dir}/...")
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = zf.namelist()
        # Strip common top-level directory if present
        if names and "/" in names[0]:
            prefix = names[0].split("/")[0] + "/"
            if all(n.startswith(prefix) or n == prefix.rstrip("/") for n in names):
                for name in names:
                    if name == prefix or name == prefix.rstrip("/"):
                        continue
                    stripped = name[len(prefix):]
                    if not stripped:
                        continue
                    target = dest_dir / stripped
                    if name.endswith("/"):
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(name) as src, open(target, "wb") as dst:
                            dst.write(src.read())
            else:
                zf.extractall(dest_dir)
        else:
            zf.extractall(dest_dir)

    # Save normalized metadata
    metadata_path = dest_dir / "metadata.json"
    normalized = _normalize_metadata(meta, source="remote")
    metadata_path.write_text(json.dumps(normalized, indent=2, ensure_ascii=False), encoding="utf-8")

    # Cleanup ZIP
    zip_path.unlink()

    # Show README if present
    readme_path = None
    for candidate in dest_dir.rglob("*"):
        if candidate.is_file() and candidate.name.lower() == "readme.md":
            readme_path = candidate
            break
    if readme_path:
        print(f"\n--- README.md ---")
        print(readme_path.read_text(encoding="utf-8"))

    # Show file list
    file_list = sorted(f.relative_to(dest_dir) for f in dest_dir.rglob("*") if f.is_file())
    print(f"\nFiles ({len(file_list)}):")
    for f in file_list:
        print(f"  {f}")

    return 0


def _cmd_list(args):
    """List datasets (local, remote, or merged view)."""
    server = args.server
    datasets_dir = args.datasets_dir
    show_all = args.all
    show_remote = args.remote

    if show_all:
        # Merged view: local + remote
        local = _load_local_datasets(datasets_dir)
        remote = _fetch_remote_datasets(server)
        all_ids = sorted(set(list(local.keys()) + list(remote.keys())))

        if not all_ids:
            print("No datasets found (local or remote).")
            return 0

        print(f"{'ID':<30} {'Name':<25} {'Category':<20} {'Version':<10} {'Status':<20}")
        print("-" * 105)
        for did in all_ids:
            loc = local.get(did)
            rem = remote.get(did)
            if loc and rem:
                status = _compare_versions(loc.get("version", ""), rem.get("version", ""))
                if status == "outdated":
                    status_str = f"outdated (local: {loc.get('version', '?')})"
                elif status == "newer":
                    status_str = f"newer (local: {loc.get('version', '?')})"
                else:
                    status_str = "installed"
                name = rem.get("name", "")[:24]
                cat = rem.get("category", "")
                ver = rem.get("version", "")
            elif loc:
                status_str = "installed (offline)"
                name = loc.get("name", "")[:24]
                cat = loc.get("category", "")
                ver = loc.get("version", "")
            else:
                status_str = "available"
                name = rem.get("name", "")[:24]
                cat = rem.get("category", "")
                ver = rem.get("version", "")
            print(f"{did:<30} {name:<25} {cat:<20} {ver:<10} {status_str:<20}")

        print(f"\nTotal: {len(all_ids)} dataset(s) ({len(local)} installed, {len(remote)} remote)")
    elif show_remote:
        # Remote only
        remote = _fetch_remote_datasets(server)
        if not remote:
            print("No remote datasets found.")
            return 0

        print(f"{'ID':<30} {'Name':<25} {'Category':<20} {'Version':<10} {'Size':<10}")
        print("-" * 95)
        for did, ds in sorted(remote.items()):
            name = ds.get("name", "")[:24]
            cat = ds.get("category", "")
            ver = ds.get("version", "")
            size = _format_size(ds.get("package_size_bytes"))
            print(f"{did:<30} {name:<25} {cat:<20} {ver:<10} {size:<10}")

        print(f"\nTotal: {len(remote)} remote dataset(s)")
    else:
        # Local only (default)
        local = _load_local_datasets(datasets_dir)
        if not local:
            print("No installed datasets found.")
            return 0

        print(f"{'ID':<30} {'Name':<25} {'Category':<20} {'Version':<10} {'Source':<10}")
        print("-" * 95)
        for did, meta in sorted(local.items()):
            name = meta.get("name", "")[:24]
            cat = meta.get("category", "")
            ver = meta.get("version", "")
            source = meta.get("source", "unknown")
            print(f"{did:<30} {name:<25} {cat:<20} {ver:<10} {source:<10}")

        print(f"\nTotal: {len(local)} installed dataset(s)")

    return 0


def _cmd_cat(args):
    """Read a file from a locally installed dataset."""
    datasets_dir = Path(args.datasets_dir)
    file_path = datasets_dir / args.dataset_id / args.file_path

    if not file_path.exists():
        print(f"File not found: {file_path}")
        print(
            f"Run: $PYTHON_PATH .agentsociety/bin/ags.py use-dataset download {args.dataset_id}"
        )
        return 1

    # Security: ensure resolved path is under datasets_dir
    try:
        file_path.resolve().relative_to(datasets_dir.resolve())
    except ValueError:
        print("Error: invalid file path")
        return 1

    print(file_path.read_text(encoding="utf-8", errors="replace"))
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Search, download, and inspect datasets from agentsociety2-web",
    )
    parser.add_argument(
        "--server", default=DEFAULT_SERVER_URL, help="Backend API URL",
    )
    sub = parser.add_subparsers(dest="command")

    # search
    p_search = sub.add_parser("search", help="List/search datasets")
    p_search.add_argument("--category", help="Filter by category")
    p_search.add_argument("--tags", help="Comma-separated tags")
    p_search.add_argument("--limit", type=int, default=20, help="Max results")
    p_search.add_argument("--skip", type=int, default=0, help="Offset")

    # info
    p_info = sub.add_parser("info", help="Show dataset metadata (local + remote)")
    p_info.add_argument("dataset_id", help="Dataset ID")
    p_info.add_argument("--datasets-dir", default="./datasets/", help="Local datasets directory")

    # readme
    p_readme = sub.add_parser("readme", help="Read dataset README")
    p_readme.add_argument("dataset_id", help="Dataset ID")

    # files
    p_files = sub.add_parser("files", help="List dataset file tree")
    p_files.add_argument("dataset_id", help="Dataset ID")

    # download
    p_dl = sub.add_parser("download", help="Download and extract dataset")
    p_dl.add_argument("dataset_id", help="Dataset ID")
    p_dl.add_argument("--output", default="./datasets/", help="Output directory")

    # list (replaces list-installed)
    p_list = sub.add_parser("list", help="List datasets (local by default)")
    list_mode = p_list.add_mutually_exclusive_group()
    list_mode.add_argument("--all", action="store_true", help="Show local + remote merged view")
    list_mode.add_argument("--remote", action="store_true", help="Show remote datasets only")
    p_list.add_argument("--datasets-dir", default="./datasets/", help="Local datasets directory")

    # list-installed (alias for list, backward compat)
    p_ls = sub.add_parser("list-installed", help="List locally downloaded datasets")
    p_ls.add_argument("--datasets-dir", default="./datasets/", help="Datasets directory")

    # cat
    p_cat = sub.add_parser("cat", help="Read file from a local dataset")
    p_cat.add_argument("dataset_id", help="Dataset ID")
    p_cat.add_argument("file_path", help="Relative file path within dataset")
    p_cat.add_argument("--datasets-dir", default="./datasets/", help="Datasets directory")

    args = parser.parse_args()

    handlers = {
        "search": _cmd_search,
        "info": _cmd_info,
        "readme": _cmd_readme,
        "files": _cmd_files,
        "download": _cmd_download,
        "list": _cmd_list,
        "list-installed": _cmd_list,  # alias
        "cat": _cmd_cat,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
