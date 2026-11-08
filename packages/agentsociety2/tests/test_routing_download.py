"""Routing downloads validate integrity before publishing executables."""

import hashlib
from types import SimpleNamespace

import pytest


@pytest.mark.parametrize("value", ["", "invalid", "f" * 63])
def test_routing_rejects_invalid_digest_without_network(tmp_path, monkeypatch, value):
    from agentsociety2.contrib.env.mobility_space import download_sim

    monkeypatch.setattr(download_sim.platform, "system", lambda: "Linux")
    monkeypatch.setattr(download_sim.platform, "machine", lambda: "x86_64")
    monkeypatch.setenv("AGENTSOCIETY_ROUTING_SHA256_LINUX_X86_64", value)
    monkeypatch.setattr(
        download_sim.requests,
        "get",
        lambda *a, **k: pytest.fail("network should not be reached"),
    )
    with pytest.raises(ValueError):
        download_sim.download_binary(str(tmp_path))


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
