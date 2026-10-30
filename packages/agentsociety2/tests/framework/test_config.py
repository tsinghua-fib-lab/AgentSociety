"""Tests for configuration module."""

import os

from agentsociety2.config.config import Config, extract_json


class TestExtractJson:
    """Tests for extract_json utility function."""

    def test_extract_simple_json_object(self):
        """Test extracting a simple JSON object."""
        text = 'Here is some text {"key": "value"} and more text'
        result = extract_json(text)
        assert result == '{"key": "value"}'

    def test_extract_simple_json_array(self):
        """Test extracting a simple JSON array."""
        text = "Results: [1, 2, 3] done"
        result = extract_json(text)
        assert result == "[1, 2, 3]"

    def test_extract_nested_json(self):
        """Test extracting nested JSON."""
        text = 'Response: {"outer": {"inner": "value"}} end'
        result = extract_json(text)
        assert result == '{"outer": {"inner": "value"}}'

    def test_extract_json_with_markdown_fence(self):
        """Test extracting JSON from markdown code fence."""
        text = """Here is the result:
```json
{"status": "success"}
```
That's all."""
        result = extract_json(text)
        assert result == '{"status": "success"}'

    def test_extract_json_with_plain_fence(self):
        """Test extracting JSON from plain code fence."""
        text = """```
{"data": [1, 2, 3]}
```"""
        result = extract_json(text)
        assert result == '{"data": [1, 2, 3]}'

    def test_extract_multiline_json(self):
        """Test extracting multiline JSON."""
        text = """Result:
{
  "name": "test",
  "value": 123
}
End"""
        result = extract_json(text)
        assert '"name": "test"' in result
        assert '"value": 123' in result

    def test_extract_returns_none_for_no_json(self):
        """Test that None is returned when no JSON is found."""
        text = "This is just plain text with no JSON"
        result = extract_json(text)
        assert result is None

    def test_extract_returns_none_for_empty_string(self):
        """Test that None is returned for empty string."""
        result = extract_json("")
        assert result is None

    def test_extract_returns_none_for_none_input(self):
        """Test that None is returned for None input."""
        result = extract_json(None)
        assert result is None

    def test_extract_json_with_string_containing_braces(self):
        """Test JSON with string values containing braces."""
        text = '{"template": "Hello {name}!"}'
        result = extract_json(text)
        assert result == '{"template": "Hello {name}!"}'

    def test_extract_complex_nested_structure(self):
        """Test extracting complex nested JSON structure."""
        text = """```json
{
  "hypothesis": {
    "description": "Test hypothesis",
    "rationale": "Test rationale"
  },
  "groups": [
    {"name": "control", "type": "control"},
    {"name": "treatment", "type": "treatment"}
  ]
}
```"""
        result = extract_json(text)
        assert result is not None
        assert '"hypothesis"' in result
        assert '"groups"' in result


class TestConfigClass:
    """Tests for Config class attributes."""

    def test_home_dir_default(self):
        """Test HOME_DIR has a default value."""
        assert Config.HOME_DIR is not None
        assert isinstance(Config.HOME_DIR, str)

    def test_llm_api_base_default(self):
        """Test LLM_API_BASE is set (either from env or default)."""
        assert Config.LLM_API_BASE is not None
        assert isinstance(Config.LLM_API_BASE, str)
        assert len(Config.LLM_API_BASE) > 0

    def test_llm_model_default(self):
        """Test LLM_MODEL has a default value."""
        assert Config.LLM_MODEL is not None
        assert isinstance(Config.LLM_MODEL, str)

    def test_mem0_telemetry_disabled(self):
        """Test that mem0 telemetry is disabled by default."""
        # The config module sets this on import
        assert os.environ.get("MEM0_TELEMETRY", "False") == "False"

    def test_chromadb_telemetry_disabled(self):
        """Test that ChromaDB telemetry is disabled by default."""
        assert os.environ.get("ANONYMIZED_TELEMETRY", "False") == "False"

    def test_literature_search_mcp_url_default(self):
        """Test literature search MCP URL default points at gateway MCP."""
        url = Config.get_literature_search_mcp_url()
        assert url.startswith("https://")
        assert url.endswith("/mcp/")


class TestEnvBoolHelper:
    """Tests for the _env_bool env-var helper."""

    def test_unset_returns_default(self, monkeypatch):
        from agentsociety2.config.config import _env_bool

        monkeypatch.delenv("AGENTSOCIETY_TEST_BOOL_FLAG", raising=False)
        assert _env_bool("AGENTSOCIETY_TEST_BOOL_FLAG", False) is False
        assert _env_bool("AGENTSOCIETY_TEST_BOOL_FLAG", True) is True

    def test_truthy_values(self, monkeypatch):
        from agentsociety2.config.config import _env_bool

        for raw in ("1", "true", "True", "YES", "on"):
            monkeypatch.setenv("AGENTSOCIETY_TEST_BOOL_FLAG", raw)
            assert _env_bool("AGENTSOCIETY_TEST_BOOL_FLAG", False) is True

    def test_other_values_are_false(self, monkeypatch):
        from agentsociety2.config.config import _env_bool

        for raw in ("0", "false", "no", "off", "maybe"):
            monkeypatch.setenv("AGENTSOCIETY_TEST_BOOL_FLAG", raw)
            assert _env_bool("AGENTSOCIETY_TEST_BOOL_FLAG", True) is False

    def test_blank_returns_default(self, monkeypatch):
        from agentsociety2.config.config import _env_bool

        monkeypatch.setenv("AGENTSOCIETY_TEST_BOOL_FLAG", "   ")
        assert _env_bool("AGENTSOCIETY_TEST_BOOL_FLAG", False) is False


class TestConfigGetters:
    """Tests for Config getter methods."""

    def test_get_literature_search_mcp_url(self):
        """Test getting literature search MCP URL."""
        url = Config.get_literature_search_mcp_url()
        assert isinstance(url, str)
        assert url.startswith("http")
        assert "/mcp" in url

    def test_get_literature_search_api_key(self):
        """Test getting literature search API key."""
        key = Config.get_literature_search_api_key()
        # Key might be empty if not configured
        assert key is not None or key == ""

    def test_get_router_returns_router(self):
        """Test get_router returns a Router instance."""
        from litellm.router import Router

        router = Config.get_router("default")
        assert router is not None
        assert isinstance(router, Router)

    def test_get_default_router(self):
        """Test get_default_router returns a Router."""
        from litellm.router import Router

        router = Config.get_default_router()
        assert router is not None
        assert isinstance(router, Router)
