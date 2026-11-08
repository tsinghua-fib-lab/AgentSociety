"""Cached data and routing binaries are verified before reuse."""

import hashlib
import hmac
from types import SimpleNamespace

import pytest

from agentsociety2.env.router_codegen import TemplateCacheDB


@pytest.mark.parametrize("secret", [b"", b"short"])
def test_template_cache_rejects_invalid_secret_before_unpickling(
    tmp_path, monkeypatch, secret
):
    import agentsociety2.env.router_codegen as codegen

    key = tmp_path / "secret"
    key.write_bytes(secret)
    monkeypatch.setattr(codegen, "_CACHE_SECRET_FILE", str(key))
    payload = b"fake pickle"
    cache = tmp_path / "template.cache"
    cache.write_bytes(
        codegen._CACHE_MAGIC
        + hmac.new(secret, payload, hashlib.sha256).digest()
        + payload
    )
    calls = []
    monkeypatch.setattr(
        codegen.pickle, "loads", lambda data: calls.append(data) or {"bad": True}
    )
    assert TemplateCacheDB(str(cache), 3)._load_data() == {"next_id": 1, "by_env": {}}
    assert calls == []


def test_cache_key_concurrent_publication_returns_one_complete_secret(tmp_path):
    from concurrent.futures import ThreadPoolExecutor

    from agentsociety2.cache_integrity import cache_secret

    target = tmp_path / "secret"
    with ThreadPoolExecutor(max_workers=16) as pool:
        secrets = list(pool.map(lambda _: cache_secret(str(target)), range(64)))
    assert len(set(secrets)) == 1
    assert len(secrets[0]) == 32
    assert target.read_bytes() == secrets[0]
    assert target.stat().st_mode & 0o777 == 0o600


def test_map_rejects_unsigned_pickle_and_reuses_signed_cache(tmp_path, monkeypatch):
    from pycityproto.city.map.v2 import map_pb2

    from agentsociety2.contrib.env.mobility_space import map as maps

    monkeypatch.setattr(maps, "_MAP_CACHE_SECRET_FILE", str(tmp_path / "map-key"))
    pb = map_pb2.Map()
    pb.header.projection = "EPSG:3857"
    source = tmp_path / "map.pb"
    source.write_bytes(pb.SerializeToString())
    cache = tmp_path / "map.pb.cache"
    cache.write_bytes(b"unsigned pickle")
    loads = maps.pickle.loads
    monkeypatch.setattr(
        maps.pickle,
        "loads",
        lambda *args: pytest.fail("unsigned cache must not be deserialized"),
    )
    first = maps.Map(str(source))
    assert first.header["projection"] == "EPSG:3857"
    monkeypatch.setattr(maps.pickle, "loads", loads)
    monkeypatch.setattr(
        maps.Map,
        "_parse_map",
        lambda *args: pytest.fail("verified cache should be reused"),
    )
    second = maps.Map(str(source))
    assert second.header == first.header


@pytest.mark.parametrize("existing", [False, True])
def test_routing_checks_download_and_existing_binary(tmp_path, monkeypatch, existing):
    from agentsociety2.contrib.env.mobility_space import download_sim

    monkeypatch.setattr(download_sim.platform, "system", lambda: "Linux")
    monkeypatch.setattr(download_sim.platform, "machine", lambda: "x86_64")
    trusted = b"verified fixture bytes"
    monkeypatch.setenv(
        "AGENTSOCIETY_ROUTING_SHA256_LINUX_X86_64", hashlib.sha256(trusted).hexdigest()
    )
    destination = tmp_path / "routing"
    if existing:
        destination.write_bytes(b"tampered")
    get = lambda *a, **k: SimpleNamespace(status_code=200, content=b"tampered download")
    monkeypatch.setattr(download_sim.requests, "get", get)
    with pytest.raises(ValueError):
        download_sim.download_binary(str(tmp_path))
    assert destination.exists() is existing
    if existing:
        assert destination.read_bytes() == b"tampered"
    monkeypatch.setattr(
        download_sim.requests,
        "get",
        lambda *a, **k: SimpleNamespace(status_code=200, content=trusted),
    )
    assert download_sim.download_binary(str(tmp_path)) == str(destination)
    assert destination.read_bytes() == trusted
    monkeypatch.setattr(
        download_sim.requests,
        "get",
        lambda *a, **k: pytest.fail("verified file should be reused"),
    )
    assert download_sim.download_binary(str(tmp_path)) == str(destination)
    assert destination.stat().st_mode & 0o777 == 0o700
