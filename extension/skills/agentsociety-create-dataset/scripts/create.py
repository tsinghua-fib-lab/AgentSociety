#!/usr/bin/env python3
"""Dataset creation CLI — create, validate, package, and upload datasets."""

import argparse
import calendar
import json
import os
import re
import sys
import time
import webbrowser
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

# --- Defaults ---
DEFAULT_CASDOOR_URL = "https://login.fiblab.net"
DEFAULT_SERVER_URL = "https://agentsociety2.fiblab.net"
DEFAULT_CLIENT_ID = "7ffcbfe4ae0fcb2c0d63"
CREDENTIALS_DIR = Path.home() / ".agentsociety"
CREDENTIALS_FILE = CREDENTIALS_DIR / "credentials.json"
PART_SIZE = 10 * 1024 * 1024  # 10 MB per part (must match backend)

VALID_CATEGORIES = [
    "agent_profiles",
    "surveys",
    "experiments",
    "literature",
    "simulation_results",
    "other",
]


# --- HTTP helpers (stdlib only) ---


def _api_request(url, method="GET", data=None, headers=None, timeout=30):
    """Make an HTTP request and return parsed JSON or raw bytes."""
    hdrs = {"Accept": "application/json"}
    if headers:
        hdrs.update(headers)
    body = None
    if data is not None:
        if isinstance(data, dict):
            body = json.dumps(data).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
        elif isinstance(data, bytes):
            body = data
    req = Request(url, data=body, headers=hdrs, method=method)
    with urlopen(req, timeout=timeout) as resp:
        ct = resp.headers.get("Content-Type", "")
        raw = resp.read()
        if "application/json" in ct:
            return json.loads(raw)
        return raw


def _api_get(url, headers=None, timeout=30):
    return _api_request(url, "GET", headers=headers, timeout=timeout)


def _api_post(url, data=None, headers=None, timeout=30):
    return _api_request(url, "POST", data=data, headers=headers, timeout=timeout)


def _api_post_form(url, data=None, headers=None, timeout=30):
    """POST with application/x-www-form-urlencoded body. Required by OAuth endpoints."""
    from urllib.parse import urlencode
    hdrs = headers or {}
    hdrs["Content-Type"] = "application/x-www-form-urlencoded"
    body = urlencode(data).encode("utf-8") if data else None
    return _api_request(url, "POST", data=body, headers=hdrs, timeout=timeout)


# --- Credential management ---


def _load_credentials():
    """Load credentials from file. Returns dict or None."""
    if not CREDENTIALS_FILE.exists():
        return None
    try:
        return json.loads(CREDENTIALS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _save_credentials(creds):
    """Save credentials to file with secure permissions."""
    CREDENTIALS_DIR.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_FILE.write_text(json.dumps(creds, indent=2, ensure_ascii=False), encoding="utf-8")
    os.chmod(CREDENTIALS_FILE, 0o600)
    try:
        os.chmod(CREDENTIALS_DIR, 0o700)
    except OSError:
        pass


def _clear_credentials():
    """Delete credentials file."""
    if CREDENTIALS_FILE.exists():
        CREDENTIALS_FILE.unlink()
        print("Credentials cleared.")
    else:
        print("No credentials file found.")


def _refresh_token(creds):
    """Attempt to refresh an expired token. Returns updated creds or None."""
    casdoor_url = creds.get("casdoor_url", DEFAULT_CASDOOR_URL)
    client_id = creds.get("client_id", DEFAULT_CLIENT_ID)
    refresh_token = creds.get("refresh_token")
    if not refresh_token:
        return None
    try:
        resp = _api_post_form(
            f"{casdoor_url}/api/login/oauth/access_token",
            data={
                "grant_type": "refresh_token",
                "client_id": client_id,
                "refresh_token": refresh_token,
            },
        )
        if isinstance(resp, dict) and resp.get("access_token"):
            creds["token"] = resp["access_token"]
            if resp.get("refresh_token"):
                creds["refresh_token"] = resp["refresh_token"]
            expires_in = resp.get("expires_in", 3600)
            creds["expires_at"] = (
                time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + expires_in))
            )
            _save_credentials(creds)
            return creds
    except Exception:
        pass
    return None


def _get_valid_token():
    """Load credentials and ensure token is valid. Returns (creds, token) or (None, None)."""
    creds = _load_credentials()
    if not creds:
        print("Not logged in. Run: $PYTHON_PATH .agentsociety/bin/ags.py create-dataset login")
        return None, None
    expires_at = creds.get("expires_at", "")
    if expires_at:
        try:
            exp = calendar.timegm(time.strptime(expires_at, "%Y-%m-%dT%H:%M:%SZ"))
            if time.time() > exp:
                refreshed = _refresh_token(creds)
                if refreshed:
                    return refreshed, refreshed["token"]
                print(
                    "Token expired and refresh failed. Run: $PYTHON_PATH .agentsociety/bin/ags.py create-dataset login"
                )
                return None, None
        except (ValueError, OSError):
            pass
    return creds, creds.get("token")


# --- Multipart upload helpers ---


def _api_delete(url, headers=None, timeout=30):
    return _api_request(url, "DELETE", headers=headers, timeout=timeout)


def _multipart_upload(server, dataset_id, zip_path, auth_headers):
    """Upload a file via multipart direct-to-OSS.

    Flow: init-upload → PUT parts to presigned URLs → complete-upload.
    Validation happens server-side during complete-upload (synchronous).
    """
    file_size = zip_path.stat().st_size
    print(f"  File size: {file_size / (1024*1024):.1f} MB — using multipart upload")

    # 1. Init
    print("  Initiating multipart upload...")
    init_resp = _api_post(
        f"{server}/api/user/data/datasets/{dataset_id}/init-upload",
        data={"file_size": file_size},
        headers=auth_headers,
        timeout=30,
    )
    upload_id = init_resp["upload_id"]
    part_size = init_resp["part_size"]
    part_urls = init_resp["part_urls"]
    print(f"  Upload ID: {upload_id}, {len(part_urls)} parts")

    # 2. Upload parts (Content-Type must be empty to match OSS presigned signature)
    parts = []
    with open(zip_path, "rb") as f:
        for i, pu in enumerate(part_urls):
            blob = f.read(part_size)
            req = Request(
                pu["upload_url"],
                data=blob,
                method="PUT",
                headers={"Content-Type": ""},
            )
            with urlopen(req, timeout=300) as resp:
                if resp.status >= 400:
                    raise RuntimeError(f"Part {i+1} upload failed: HTTP {resp.status}")
            parts.append({"part_number": pu["part_number"]})
            pct = (i + 1) / len(part_urls) * 95
            print(f"  Part {i+1}/{len(part_urls)} uploaded ({pct:.0f}%)")

    # 3. Complete (server fetches ETags from OSS, validates + caches metadata)
    print("  Completing upload (validating)...")
    try:
        _api_post(
            f"{server}/api/user/data/datasets/{dataset_id}/complete-upload",
            data={"upload_id": upload_id, "parts": parts},
            headers=auth_headers,
            timeout=600,  # long timeout for validation
        )
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Upload completion failed: {e.code} — {body}")

    print("  Upload complete!")


# --- Auth subcommands ---


def _cmd_login(args):
    """Authenticate via Casdoor Device Code Flow."""
    casdoor_url = args.casdoor_url or DEFAULT_CASDOOR_URL
    client_id = args.client_id or DEFAULT_CLIENT_ID
    server_url = args.server_url or DEFAULT_SERVER_URL

    # Step 1: Request device code
    try:
        resp = _api_post_form(
            f"{casdoor_url}/api/device-auth",
            data={"client_id": client_id, "scope": "openid,profile"},
        )
    except Exception as e:
        print(f"Error requesting device code: {e}")
        return 1

    device_code = resp.get("device_code")
    user_code = resp.get("user_code")
    verification_uri = resp.get("verification_uri")
    expires_in = resp.get("expires_in", 120)
    interval = resp.get("interval", 1)

    if not device_code or not verification_uri:
        print(f"Error: unexpected response from device-auth: {resp}")
        return 1

    # Step 2: Display and open browser
    print(f"\nTo authenticate, visit:\n  {verification_uri}\n")
    print(f"Enter code: {user_code}\n")
    try:
        webbrowser.open(verification_uri)
    except Exception:
        pass

    # Step 3: Poll for token
    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        try:
            resp = _api_post_form(
                f"{casdoor_url}/api/login/oauth/access_token",
                data={
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": client_id,
                    "device_code": device_code,
                },
            )
        except Exception as e:
            print(f"Polling error: {e}")
            continue

        error = resp.get("error")
        if error == "authorization_pending":
            continue
        elif error == "slow_down":
            interval += 5
            continue
        elif error == "expired_token":
            print("Device code expired. Please try again.")
            return 1
        elif error:
            print(f"Auth error: {error} — {resp.get('error_description', '')}")
            return 1

        # Success
        access_token = resp.get("access_token")
        refresh_tok = resp.get("refresh_token")
        expires_in_val = resp.get("expires_in", 3600)

        # Step 4: Get user info
        try:
            userinfo = _api_get(
                f"{casdoor_url}/api/userinfo",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            username = (
                userinfo.get("displayName")
                or userinfo.get("name")
                or userinfo.get("sub", "unknown")
            )
        except Exception:
            username = "unknown"

        creds = {
            "server": server_url,
            "token": access_token,
            "refresh_token": refresh_tok or "",
            "username": username,
            "expires_at": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + expires_in_val)
            ),
            "casdoor_url": casdoor_url,
            "client_id": client_id,
        }
        _save_credentials(creds)
        print(f"Logged in as: {username}")
        return 0

    print("Timed out waiting for authorization.")
    return 1


def _cmd_logout(args):
    """Clear saved credentials."""
    _clear_credentials()
    return 0


# --- Dataset subcommands ---


def _fetch_categories(server_url):
    """Fetch categories from API. Returns list of strings, or None on error."""
    try:
        resp = _api_get(f"{server_url}/api/v1/data/categories")
        if isinstance(resp, dict) and "categories" in resp:
            raw = resp["categories"]
            # Backend may return [{"value": "...", "label": "..."}] or ["..."]
            if raw and isinstance(raw[0], dict):
                return [c["value"] for c in raw]
            return raw
    except Exception:
        pass
    return None


def _cmd_init(args):
    """Initialize dataset directory structure."""
    name = args.name
    slug = re.sub(r"[^a-z0-9_-]", "-", name.lower())

    dataset_dir = Path(name)
    if dataset_dir.exists():
        print(f"Error: directory '{name}' already exists.")
        return 1

    # Interactive or flag-driven metadata
    description = args.description if args.description is not None else input("Description: ").strip()
    author = args.author if args.author is not None else input("Author: ").strip()

    # Category: try API first, fall back to hardcoded
    categories = _fetch_categories(args.server) or VALID_CATEGORIES
    if args.category:
        category = args.category
    else:
        print("\nCategories:")
        for i, c in enumerate(categories, 1):
            print(f"  {i}. {c}")
        choice = input(f"Select category [1-{len(categories)}]: ").strip()
        try:
            category = categories[int(choice) - 1]
        except (ValueError, IndexError):
            category = categories[-1]

    tags_str = args.tags if args.tags is not None else input("Tags (comma-separated): ").strip()
    tags = [t.strip() for t in tags_str.split(",") if t.strip()] if tags_str else []

    # Create directory structure
    data_dir = dataset_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / ".gitkeep").touch()

    # Write README.md template
    (dataset_dir / "README.md").write_text(
        f"# {name}\n\n"
        f"## Description\n{description}\n\n"
        f"## Data Format\nDescribe the file formats and their schemas here.\n\n"
        f"## Columns\n"
        f"| Column | Type | Description |\n"
        f"|--------|------|-------------|\n"
        f"| ... | ... | ... |\n\n"
        f"## Usage\nHow to use this dataset in agentsociety2.\n",
        encoding="utf-8",
    )

    # Write dataset.json
    (dataset_dir / "dataset.json").write_text(
        json.dumps(
            {
                "id": slug,
                "name": name,
                "description": description,
                "category": category,
                "version": "1.0.0",
                "tags": tags,
                "author": author,
                "license": "CC BY 4.0",
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    print(f"\nCreated: {name}/")
    print(f"  README.md")
    print(f"  dataset.json  (id: {slug})")
    print(f"  data/")
    print(f"\nNext: add your data files under {name}/data/, then run:")
    print(f"  $PYTHON_PATH .agentsociety/bin/ags.py create-dataset validate {name}/")
    return 0


def _validate_dataset_metadata(meta, errors):
    """Validate parsed dataset metadata shared by directory and ZIP checks."""
    required_fields = ["id", "name", "description", "category", "version", "author"]
    for field in required_fields:
        if not meta.get(field):
            errors.append(f"dataset.json: missing or empty field '{field}'")

    if meta.get("id") and not re.match(r"^[a-z0-9_-]+$", meta["id"]):
        errors.append(f"dataset.json: id '{meta['id']}' must match ^[a-z0-9_-]+$")

    if meta.get("category") and meta["category"] not in VALID_CATEGORIES:
        errors.append(f"dataset.json: unknown category '{meta['category']}'")


def _validate_dataset_dir(path):
    """Validate a dataset directory. Returns (errors, warnings)."""
    errors = []
    warnings = []
    p = Path(path)

    if not p.exists():
        return [f"Path does not exist: {p}"], warnings

    # Check root-level README.md (case-insensitive basename)
    has_root_readme = any(
        f.is_file() and f.name.lower() == "readme.md" for f in p.iterdir()
    )
    if not has_root_readme:
        errors.append("README.md not found at package root (checked case-insensitively)")

    # Check dataset.json
    dataset_json = p / "dataset.json"
    if not dataset_json.exists():
        errors.append("dataset.json not found")
    else:
        try:
            meta = json.loads(dataset_json.read_text(encoding="utf-8"))
            _validate_dataset_metadata(meta, errors)
        except json.JSONDecodeError as e:
            errors.append(f"dataset.json: invalid JSON: {e}")

    # Check data/ directory
    data_dir = p / "data"
    if not data_dir.exists():
        warnings.append("data/ directory not found")
    elif not any(data_dir.iterdir()):
        warnings.append("data/ directory is empty")

    # Check total size
    total_size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
    if total_size > 5 * 1024**4:
        errors.append(f"Total size {total_size / 1024**3:.1f}GB exceeds 5TB limit")

    return errors, warnings


def _validate_dataset_zip(path):
    """Validate a dataset ZIP file. Returns (errors, warnings)."""
    errors = []
    warnings = []
    p = Path(path)

    if not p.exists():
        return [f"Path does not exist: {p}"], warnings

    if not p.suffix.lower() == ".zip":
        return ["Not a ZIP file"], warnings

    if p.stat().st_size > 5 * 1024**4:
        errors.append(f"ZIP size {p.stat().st_size / 1024**3:.1f}GB exceeds 5TB limit")

    try:
        with zipfile.ZipFile(p, "r") as zf:
            names = zf.namelist()
            # Strip common prefix, keeping mapping to original names
            stripped_to_original = {}
            if names:
                prefix = names[0].split("/")[0] + "/"
                if all(n.startswith(prefix) for n in names):
                    for n in names:
                        s = n[len(prefix):]
                        if s:
                            stripped_to_original[s] = n
                else:
                    for n in names:
                        if n:
                            stripped_to_original[n] = n
            stripped = list(stripped_to_original.keys())

            # Check root-level README.md
            root_entries = [n for n in stripped if n and "/" not in n.rstrip("/")]
            has_root_readme = any(n.lower() == "readme.md" for n in root_entries)
            if not has_root_readme:
                errors.append(
                    "README.md not found at package root in ZIP (checked case-insensitively)"
                )

            # Check data/ directory
            has_data = any(n.startswith("data/") for n in stripped)
            if not has_data:
                warnings.append("data/ directory not found in ZIP")

            # Check root-level dataset.json
            dj_stripped = [n for n in root_entries if n == "dataset.json"]
            if not dj_stripped:
                errors.append("dataset.json not found at package root in ZIP")
            else:
                try:
                    original_name = stripped_to_original[dj_stripped[0]]
                    meta = json.loads(zf.read(original_name))
                    _validate_dataset_metadata(meta, errors)
                except json.JSONDecodeError as e:
                    errors.append(f"dataset.json: invalid JSON: {e}")
    except zipfile.BadZipFile:
        errors.append("Invalid ZIP file")

    return errors, warnings


def _cmd_validate(args):
    """Validate a dataset directory or ZIP file."""
    path = args.path
    p = Path(path)

    if p.is_dir():
        errors, warnings = _validate_dataset_dir(path)
    elif p.suffix.lower() == ".zip":
        errors, warnings = _validate_dataset_zip(path)
    else:
        print(f"Error: '{path}' is neither a directory nor a ZIP file")
        return 1

    if warnings:
        for w in warnings:
            print(f"  WARNING: {w}")
    if errors:
        for e in errors:
            print(f"  ERROR: {e}")
        print("\nFAIL")
        return 1

    print("PASS")
    return 0


def _cmd_pack(args):
    """Package dataset directory into a ZIP file."""
    dir_path = Path(args.dir)
    if not dir_path.is_dir():
        print(f"Error: '{dir_path}' is not a directory")
        return 1

    # Validate first
    errors, warnings = _validate_dataset_dir(dir_path)
    if errors:
        print("Validation failed — fix errors before packing:")
        for e in errors:
            print(f"  ERROR: {e}")
        return 1

    zip_path = Path(f"{dir_path.name}.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in dir_path.rglob("*"):
            if f.is_file() and not f.name.startswith("."):
                arcname = f.relative_to(dir_path.parent)
                zf.write(f, arcname)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"Created: {zip_path} ({size_mb:.1f} MB)")
    return 0


def _cmd_upload(args):
    """Upload dataset ZIP to the platform."""
    zip_path = Path(args.zip)
    if not zip_path.exists():
        print(f"Error: file not found: {zip_path}")
        return 1
    if zip_path.suffix.lower() != ".zip":
        print("Error: only ZIP files can be uploaded")
        return 1

    # Auth
    creds, token = _get_valid_token()
    if not token:
        return 1
    server = creds.get("server", args.server)
    auth_headers = {"Authorization": f"Bearer {token}"}

    # Read dataset.json from ZIP
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            # Find dataset.json (may be under a top-level dir)
            dj_names = [n for n in names if Path(n).name == "dataset.json"]
            if not dj_names:
                print("Error: dataset.json not found in ZIP")
                return 1
            meta = json.loads(zf.read(dj_names[0]))
    except (zipfile.BadZipFile, json.JSONDecodeError) as e:
        print(f"Error reading ZIP: {e}")
        return 1

    dataset_id = meta.get("id")
    if not dataset_id:
        print("Error: dataset.json has no 'id' field")
        return 1

    # Step 1: Create dataset metadata
    print(f"Creating dataset '{dataset_id}'...")
    try:
        create_resp = _api_post(
            f"{server}/api/user/data/datasets",
            data={
                "id": meta["id"],
                "name": meta.get("name", dataset_id),
                "description": meta.get("description", ""),
                "category": meta.get("category", "other"),
                "version": meta.get("version", "1.0.0"),
                "tags": meta.get("tags", []),
                "author": meta.get("author", ""),
                "license": meta.get("license", "CC BY 4.0"),
            },
            headers=auth_headers,
        )
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Error creating dataset: {e.code} — {body}")
        return 1
    except Exception as e:
        print(f"Error creating dataset: {e}")
        return 1

    print(f"  Created: {create_resp.get('id', dataset_id)}")

    # Step 2: Upload ZIP file (always multipart direct-to-OSS)
    print(f"Uploading {zip_path.name}...")
    try:
        _multipart_upload(server, dataset_id, zip_path, auth_headers)
    except RuntimeError as e:
        print(f"Error uploading: {e}")
        return 1
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        print(f"Error uploading: {e.code} — {body}")
        return 1
    except Exception as e:
        print(f"Error uploading: {e}")
        return 1

    print(f"  Upload complete!")
    print(
        f"  Submit for review: $PYTHON_PATH .agentsociety/bin/ags.py create-dataset submit {dataset_id}"
    )
    return 0


def _cmd_submit(args):
    """Submit dataset for admin review."""
    dataset_id = args.dataset_id

    # Auth
    creds, token = _get_valid_token()
    if not token:
        return 1
    server = creds.get("server", args.server)
    auth_headers = {"Authorization": f"Bearer {token}"}

    try:
        _api_post(
            f"{server}/api/user/data/datasets/{dataset_id}/submit",
            headers=auth_headers,
        )
    except HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        if e.code == 400 and "upload" in body.lower():
            print(f"Error: please upload a file first.")
            print(
                f"  Run: $PYTHON_PATH .agentsociety/bin/ags.py create-dataset upload {dataset_id}.zip"
            )
        else:
            print(f"Error: {e.code} — {body}")
        return 1
    except Exception as e:
        print(f"Error: {e}")
        return 1

    print(f"Dataset '{dataset_id}' submitted for review.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Create and upload datasets to agentsociety2-web",
    )
    parser.add_argument(
        "--server", default=DEFAULT_SERVER_URL, help="Backend API URL",
    )
    sub = parser.add_subparsers(dest="command")

    # login
    p_login = sub.add_parser("login", help="Authenticate via Casdoor Device Code Flow")
    p_login.add_argument("--casdoor-url", help="Casdoor URL")
    p_login.add_argument("--client-id", help="OAuth2 client ID")
    p_login.add_argument("--server-url", help="Backend server URL")

    # logout
    sub.add_parser("logout", help="Clear saved credentials")

    # init
    p_init = sub.add_parser("init", help="Initialize dataset directory")
    p_init.add_argument("name", help="Dataset name (used as directory name)")
    p_init.add_argument("--category", help="Dataset category")
    p_init.add_argument("--description", help="Dataset description")
    p_init.add_argument("--author", help="Author name")
    p_init.add_argument("--tags", help="Comma-separated tags")

    # validate
    p_validate = sub.add_parser("validate", help="Validate dataset directory or ZIP")
    p_validate.add_argument("path", help="Path to dataset directory or ZIP file")

    # pack
    p_pack = sub.add_parser("pack", help="Package directory into ZIP")
    p_pack.add_argument("dir", help="Dataset directory path")

    # upload
    p_upload = sub.add_parser("upload", help="Upload dataset ZIP to platform")
    p_upload.add_argument("zip", help="Path to dataset ZIP file")

    # submit
    p_submit = sub.add_parser("submit", help="Submit dataset for review")
    p_submit.add_argument("dataset_id", help="Dataset ID (slug)")

    args = parser.parse_args()

    handlers = {
        "login": _cmd_login,
        "logout": _cmd_logout,
        "init": _cmd_init,
        "validate": _cmd_validate,
        "pack": _cmd_pack,
        "upload": _cmd_upload,
        "submit": _cmd_submit,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
