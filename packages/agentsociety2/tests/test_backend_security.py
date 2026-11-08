"""Backend requests enforce local-origin boundaries."""

import pytest
from fastapi.testclient import TestClient

from agentsociety2.backend.app import app


@pytest.mark.parametrize("method", ["GET", "POST"])
def test_backend_rejects_untrusted_origins_before_routing(method):
    response = TestClient(app, base_url="http://localhost").request(
        method, "/health", headers={"Origin": "https://evil.example"}
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "origin",
    ["http://localhost:5173", "http://127.0.0.1:5173", "vscode-webview://a1-b2"],
)
def test_backend_allows_local_origins(origin):
    client = TestClient(app, base_url="http://localhost")
    assert client.get("/health", headers={"Origin": origin}).status_code == 200
    preflight = client.options(
        "/health", headers={"Origin": origin, "Access-Control-Request-Method": "POST"}
    )
    assert preflight.status_code == 200
    assert preflight.headers["access-control-allow-origin"] == origin


def test_backend_rejects_rebinding_host_and_null_origin():
    client = TestClient(app, base_url="http://localhost")
    assert client.get("/health", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/health", headers={"Origin": "null"}).status_code == 403
