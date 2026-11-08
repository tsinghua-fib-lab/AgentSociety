from fastapi.testclient import TestClient

from agentsociety2 import __version__
from agentsociety2.backend.app import app

# TrustedHostMiddleware 白名单(2026-11-06 审计修复)后,TestClient 默认
# Host(testserver)会被拒——本机端点测试统一显式带 localhost Host。
_HEADERS = {"Host": "localhost"}


def test_root_returns_service_metadata():
    client = TestClient(app)
    response = client.get("/", headers=_HEADERS)
    assert response.status_code == 200
    body = response.json()
    assert app.version == __version__
    assert body.get("version") == __version__
    assert body.get("status") == "running"
    assert "endpoints" in body


def test_health_returns_healthy():
    client = TestClient(app)
    response = client.get("/health", headers=_HEADERS)
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}
