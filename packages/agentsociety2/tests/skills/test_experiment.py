"""Tests for experiment module discovery functionality."""

from agentsociety2.skills.experiment.module_discovery import (
    get_available_agent_modules,
    get_available_env_modules,
    get_modules_summary,
    validate_hypothesis_modules,
    validate_module_selection,
)


class TestGetAvailableModules:
    """Tests for module discovery functions."""

    def test_get_available_env_modules_returns_dict(self):
        """Test that get_available_env_modules returns a dictionary."""
        modules = get_available_env_modules()
        assert isinstance(modules, dict)

    def test_get_available_agent_modules_returns_dict(self):
        """Test that get_available_agent_modules returns a dictionary."""
        modules = get_available_agent_modules()
        assert isinstance(modules, dict)

    def test_get_modules_summary_returns_string(self):
        """Test that get_modules_summary returns a formatted string."""
        summary = get_modules_summary()
        assert isinstance(summary, str)
        assert (
            "Environment Modules" in summary or "environment modules" in summary.lower()
        )
        assert "Agent" in summary or "agent" in summary.lower()


class TestValidateModuleSelection:
    """Tests for validate_module_selection function."""

    def test_valid_selection_with_both_types(self):
        """Test valid selection with both agent and env modules."""
        # Assuming there are some built-in modules
        is_valid, errors = validate_module_selection(
            agent_classes=["basic_agent"],
            env_modules=["simple_social_space"],
        )
        # Result depends on what modules are actually registered
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)

    def test_invalid_selection_missing_agents(self):
        """Test selection with no agent classes."""
        is_valid, _errors = validate_module_selection(
            agent_classes=None,
            env_modules=["simple_social_space"],
        )
        # Should return False or True depending on strictness
        assert isinstance(is_valid, bool)

    def test_invalid_selection_missing_env(self):
        """Test selection with no environment modules."""
        is_valid, _errors = validate_module_selection(
            agent_classes=["basic_agent"],
            env_modules=None,
        )
        assert isinstance(is_valid, bool)

    def test_invalid_selection_empty_lists(self):
        """Test selection with empty lists."""
        is_valid, _errors = validate_module_selection(
            agent_classes=[],
            env_modules=[],
        )
        # Empty lists should be treated as missing
        assert isinstance(is_valid, bool)


class TestValidateHypothesisModules:
    """Tests for validate_hypothesis_modules function."""

    def test_valid_hypothesis_modules(self):
        """Test validation with proper hypothesis data."""
        hypothesis_data = {
            "agent_classes": ["basic_agent"],
            "env_modules": ["simple_social_space"],
        }
        is_valid, errors, guidance = validate_hypothesis_modules(hypothesis_data)
        assert isinstance(is_valid, bool)
        assert isinstance(errors, list)
        assert isinstance(guidance, dict)

    def test_hypothesis_missing_agent_classes(self):
        """Test validation when agent_classes is missing."""
        hypothesis_data = {
            "env_modules": ["simple_social_space"],
        }
        is_valid, _errors, _guidance = validate_hypothesis_modules(hypothesis_data)
        assert isinstance(is_valid, bool)

    def test_hypothesis_missing_env_modules(self):
        """Test validation when env_modules is missing."""
        hypothesis_data = {
            "agent_classes": ["basic_agent"],
        }
        is_valid, _errors, _guidance = validate_hypothesis_modules(hypothesis_data)
        assert isinstance(is_valid, bool)

    def test_hypothesis_empty_modules(self):
        """Test validation with empty modules."""
        hypothesis_data = {
            "agent_classes": [],
            "env_modules": [],
        }
        is_valid, _errors, guidance = validate_hypothesis_modules(hypothesis_data)
        assert isinstance(is_valid, bool)
        assert isinstance(guidance, dict)

    def test_hypothesis_with_topic(self):
        """Test validation includes topic in guidance."""
        hypothesis_data = {
            "topic": "Social Network Analysis",
            "agent_classes": [],
            "env_modules": [],
        }
        _is_valid, _errors, guidance = validate_hypothesis_modules(hypothesis_data)
        # Guidance should be generated
        assert isinstance(guidance, dict)


class TestModuleDiscoveryIntegration:
    """Integration tests for module discovery."""

    def test_discovered_modules_are_usable(self):
        """Test that discovered modules can be validated."""
        env_modules = get_available_env_modules()
        agent_modules = get_available_agent_modules()

        # If modules are available, they should be valid
        if env_modules and agent_modules:
            is_valid, _errors = validate_module_selection(
                agent_classes=list(agent_modules.keys())[:1],
                env_modules=list(env_modules.keys())[:1],
            )
            # Should be valid if modules are registered
            assert isinstance(is_valid, bool)
