import importlib.util
import json
from pathlib import Path

import aiohttp
import pytest

from agentsociety2.society import workspace


class _FakeContent:
    async def iter_chunked(self, chunk_size: int):
        assert chunk_size == 8192
        for chunk in (b"map-", b"data"):
            yield chunk


class _FakeResponse:
    content = _FakeContent()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    def raise_for_status(self) -> None:
        return None


class _FakeSession:
    def __init__(self, request: dict):
        self._request = request

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    def get(self, url: str, *, timeout: aiohttp.ClientTimeout):
        self._request["url"] = url
        self._request["timeout"] = timeout.total
        return _FakeResponse()


@pytest.mark.asyncio
async def test_download_map_file_uses_working_official_url(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    request: dict = {}
    monkeypatch.setattr(
        workspace.aiohttp,
        "ClientSession",
        lambda: _FakeSession(request),
    )

    result = await workspace.download_map_file(tmp_path, timeout=17)
    map_path = tmp_path / ".agentsociety" / "data" / "beijing_map.pb"

    assert result["success"] is True
    assert result["errors"] == []
    assert result["file_path"] == str(map_path.resolve())
    assert request == {"url": workspace.BEIJING_MAP_URL, "timeout": 17}
    assert request["url"] == (
        "https://cloud.tsinghua.edu.cn/f/f5c777485d2748fa8535/?dl=1"
    )
    assert map_path.read_bytes() == b"map-data"


@pytest.mark.asyncio
async def test_init_workspace_skip_map_avoids_network_and_keeps_init_successful(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def fail_download(*args, **kwargs):
        raise AssertionError("download_map_file must not run with --skip-map")

    monkeypatch.setattr(workspace, "download_map_file", fail_download)

    result = await workspace.init_workspace(
        tmp_path, components=["agentsociety"], skip_map=True
    )
    prefill = json.loads(
        (tmp_path / ".agentsociety" / "prefill_params.json").read_text()
    )

    assert result["success"] is True
    assert any("--skip-map" in item for item in result["skipped"])
    assert prefill["env_modules"] == {}


@pytest.mark.asyncio
async def test_init_workspace_reuses_existing_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    map_path = tmp_path / ".agentsociety" / "data" / "beijing_map.pb"
    map_path.parent.mkdir(parents=True)
    map_path.write_bytes(b"existing-map")

    async def fail_download(*args, **kwargs):
        raise AssertionError("existing map must not be downloaded again")

    monkeypatch.setattr(workspace, "download_map_file", fail_download)

    result = await workspace.init_workspace(tmp_path, components=["agentsociety"])
    prefill = json.loads(
        (tmp_path / ".agentsociety" / "prefill_params.json").read_text()
    )

    assert result["success"] is True
    assert any("already exists" in item for item in result["skipped"])
    assert prefill["env_modules"]["mobility_space"]["file_path"] == str(
        map_path.resolve()
    )


@pytest.mark.asyncio
async def test_init_workspace_map_failure_is_recorded_but_not_fatal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def failing_download(*args, **kwargs):
        return {
            "success": False,
            "message": "network unavailable",
            "file_path": "",
            "errors": ["network unavailable"],
        }

    monkeypatch.setattr(workspace, "download_map_file", failing_download)

    result = await workspace.init_workspace(tmp_path, components=["agentsociety"])
    prefill = json.loads(
        (tmp_path / ".agentsociety" / "prefill_params.json").read_text()
    )

    assert result["success"] is True
    assert result["errors"] == []
    assert any("download failed" in item for item in result["skipped"])
    assert prefill["env_modules"] == {}


@pytest.mark.asyncio
async def test_init_workspace_preserves_existing_prefill_params(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prefill_path = tmp_path / ".agentsociety" / "prefill_params.json"
    prefill_path.parent.mkdir(parents=True)
    prefill_path.write_text('{"version": "1.0", "agents": {"mine": {}}}')

    async def fail_download(*args, **kwargs):
        raise AssertionError("download_map_file must not run with --skip-map")

    monkeypatch.setattr(workspace, "download_map_file", fail_download)

    result = await workspace.init_workspace(
        tmp_path, components=["agentsociety"], skip_map=True
    )

    assert result["success"] is True
    assert any(
        "prefill_params.json (already exists)" in item for item in result["skipped"]
    )
    assert json.loads(prefill_path.read_text()) == {
        "version": "1.0",
        "agents": {"mine": {}},
    }


@pytest.mark.asyncio
async def test_init_workspace_force_download_failure_falls_back_to_existing_map(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    map_path = tmp_path / ".agentsociety" / "data" / "beijing_map.pb"
    map_path.parent.mkdir(parents=True)
    map_path.write_bytes(b"existing-map")

    async def failing_download(*args, **kwargs):
        return {
            "success": False,
            "message": "network unavailable",
            "file_path": "",
            "errors": ["network unavailable"],
        }

    monkeypatch.setattr(workspace, "download_map_file", failing_download)

    result = await workspace.init_workspace(
        tmp_path, components=["agentsociety"], force=True
    )
    prefill = json.loads(
        (tmp_path / ".agentsociety" / "prefill_params.json").read_text()
    )

    assert result["success"] is True
    assert any("using existing map" in item for item in result["skipped"])
    assert prefill["env_modules"]["mobility_space"]["file_path"] == str(
        map_path.resolve()
    )


def _load_launcher():
    repo_root = Path(__file__).resolve().parents[3]
    script_path = repo_root / "extension/runtime/agentsociety/bin/ags.py"
    spec = importlib.util.spec_from_file_location("ags_launcher", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_dotenv_keeps_selected_workspace_root(tmp_path):
    launcher = _load_launcher()
    (tmp_path / ".env").write_text(
        "AGENTSOCIETY_WORKSPACE=/old\nWORKSPACE_PATH=/old\nRESEARCH_LABEL=test\n"
    )
    env = launcher._load_workspace_env(tmp_path)
    assert env["AGENTSOCIETY_WORKSPACE"] == env["WORKSPACE_PATH"] == str(tmp_path)
    assert env["RESEARCH_LABEL"] == "test"
