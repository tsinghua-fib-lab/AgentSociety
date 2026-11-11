"""验证 Swagger / ReDoc 文档完整性及其与实际接口契约的一致性。"""

from typing import Any

import pytest
from fastapi.openapi.utils import get_openapi
from fastapi.testclient import TestClient

from agentsociety2.backend.app import app

_DISPLAY_KEYS = {
    "title",
    "description",
    "summary",
    "example",
    "examples",
    "tags",
    "externalDocs",
}


def _without_display_metadata(value: Any, property_names: bool = False) -> Any:
    if isinstance(value, dict):
        return {
            key: _without_display_metadata(item, key in {"properties", "schemas"})
            for key, item in value.items()
            if property_names or key not in _DISPLAY_KEYS
        }
    if isinstance(value, list):
        return [_without_display_metadata(item) for item in value]
    return value


@pytest.fixture()
def schema(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setattr(app, "openapi_schema", None)
    return app.openapi()


def test_openapi_documents_every_operation_and_parameter(
    schema: dict[str, Any],
) -> None:
    tags = {tag["name"] for tag in schema["tags"]}
    assert len(tags) == 7
    assert all(tag.get("description") for tag in schema["tags"])
    for operations in schema["paths"].values():
        for operation in operations.values():
            assert operation.get("summary")
            assert operation.get("description")
            assert set(operation["tags"]) <= tags
            assert not any(
                marker in operation["description"]
                for marker in (":param", ":returns:", ":raises", ":meth:", "``")
            )
            for parameter in operation.get("parameters", []):
                assert parameter.get("description"), parameter["name"]
                assert "example" in parameter, parameter["name"]


def test_documentation_preserves_the_generated_api_contract(
    schema: dict[str, Any],
) -> None:
    baseline = get_openapi(title=app.title, version=app.version, routes=app.routes)
    assert _without_display_metadata(schema["paths"]) == _without_display_metadata(
        baseline["paths"]
    )
    assert _without_display_metadata(schema["components"]) == _without_display_metadata(
        baseline["components"]
    )


def test_request_fields_and_health_example_are_explained(
    schema: dict[str, Any],
) -> None:
    models = schema["components"]["schemas"]
    for path in (
        "/api/v1/agent-skills/create",
        "/api/v1/agent-skills/import",
        "/api/v1/agent-skills/scan",
        "/api/v1/custom/test",
    ):
        body = schema["paths"][path]["post"]["requestBody"]["content"][
            "application/json"
        ]
        name = body["schema"]["$ref"].rsplit("/", 1)[-1]
        for field in models[name]["properties"].values():
            assert field.get("description")
    example = schema["paths"]["/health"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["example"]
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == example


def test_docs_use_the_proxy_prefix_and_schema_cache(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app, "openapi_schema", None)
    monkeypatch.setattr(app, "servers", [])
    with TestClient(
        app, base_url="http://127.0.0.1", root_path="/proxy/13339"
    ) as client:
        for path in ("/docs", "/redoc"):
            response = client.get("/proxy/13339" + path)
            assert response.status_code == 200
            assert "/proxy/13339/openapi.json" in response.text
        html = client.get("/proxy/13339/docs").text
        assert "/proxy/13339/docs-assets/api-docs.css" in html
        assert "/proxy/13339/docs-assets/api-docs.js" in html
        assert 'href="/proxy/13339/redoc"' in html
        for asset in ("api-docs.css", "api-docs.js"):
            asset_response = client.get(f"/proxy/13339/docs-assets/{asset}")
            assert asset_response.status_code == 200
            assert len(asset_response.content) > 100
        assert client.get("/proxy/13339/docs/oauth2-redirect").status_code == 200
        response = client.get("/proxy/13339/openapi.json")
        assert response.status_code == 200
        assert response.json()["servers"] == [{"url": "/proxy/13339"}]
        assert app.openapi() is app.openapi()
