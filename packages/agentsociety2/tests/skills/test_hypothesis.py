"""Tests for hypothesis management functionality."""

from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from agentsociety2.skills.hypothesis.manager import (
    add_hypothesis,
    create_hypothesis_structure,
    delete_hypothesis,
    find_existing_hypotheses,
    generate_hypothesis_markdown,
    generate_sim_settings,
    get_hypothesis,
    get_next_hypothesis_id,
    list_hypotheses,
    validate_hypothesis_schema,
    validate_hypothesis_with_modules,
)
from agentsociety2.skills.hypothesis.models import (
    ExperimentGroupModel,
    HypothesisDataModel,
    HypothesisModel,
)

# --- Shared fixtures ---

VALID_HYPOTHESIS_DATA: dict[str, Any] = {
    "hypothesis": {
        "description": "Agents with collectivist values will cooperate more.",
        "rationale": "Based on social identity theory, collectivist orientations promote group goals.",
    },
    "groups": [
        {
            "name": "Control Group",
            "group_type": "control",
            "description": "Agents with neutral personality settings",
        }
    ],
}


# --- Model tests ---


class TestHypothesisModels:
    """Tests for hypothesis Pydantic models."""

    def test_hypothesis_model_valid(self):
        hypothesis = HypothesisModel(
            description="Agents with collectivist values will cooperate more.",
            rationale="Based on social identity theory.",
        )
        assert (
            hypothesis.description
            == "Agents with collectivist values will cooperate more."
        )

    def test_experiment_group_model_valid(self):
        group = ExperimentGroupModel(
            name="Control Group",
            group_type="control",
            description="Agents with neutral personality settings",
            agent_selection_criteria="agents with moderate personality scores",
        )
        assert group.name == "Control Group"
        assert group.group_type == "control"

    def test_hypothesis_data_model_minimal(self):
        data = HypothesisDataModel(
            hypothesis=HypothesisModel(
                description="Test hypothesis",
                rationale="Test rationale",
            ),
            groups=[
                ExperimentGroupModel(
                    name="Group 1",
                    group_type="control",
                    description="Test group",
                )
            ],
        )
        assert data.hypothesis.description == "Test hypothesis"
        assert len(data.groups) == 1

    def test_hypothesis_data_model_with_modules(self):
        data = HypothesisDataModel(
            hypothesis=HypothesisModel(
                description="Test hypothesis",
                rationale="Test rationale",
            ),
            groups=[
                ExperimentGroupModel(
                    name="Group 1",
                    group_type="control",
                    description="Test group",
                )
            ],
            agent_classes=["basic_agent", "social_agent"],
            env_modules=["simple_social_space", "economy_module"],
        )
        assert data.agent_classes == ["basic_agent", "social_agent"]
        assert data.env_modules == ["simple_social_space", "economy_module"]

    def test_hypothesis_data_model_requires_at_least_one_group(self):
        with pytest.raises(ValidationError, match="groups"):
            HypothesisDataModel(
                hypothesis=HypothesisModel(
                    description="Test hypothesis",
                    rationale="Test rationale",
                ),
                groups=[],
            )


# --- Schema validation tests ---


class TestValidateHypothesisSchema:
    """Tests for validate_hypothesis_schema function."""

    def test_valid_hypothesis_schema(self):
        is_valid, error, model = validate_hypothesis_schema(VALID_HYPOTHESIS_DATA)
        assert is_valid is True
        assert error is None
        assert model is not None
        assert (
            model.hypothesis.description
            == "Agents with collectivist values will cooperate more."
        )

    def test_invalid_hypothesis_schema_missing_field(self):
        data = {
            "hypothesis": {
                "description": "Test hypothesis",
            },
            "groups": [
                {
                    "name": "Control",
                    "group_type": "control",
                    "description": "Control group",
                }
            ],
        }
        is_valid, error, _model = validate_hypothesis_schema(data)
        assert is_valid is False
        assert error is not None
        assert "rationale" in error.lower()

    def test_invalid_hypothesis_schema_empty_groups(self):
        data = {
            "hypothesis": {
                "description": "Test hypothesis",
                "rationale": "Test rationale",
            },
            "groups": [],
        }
        is_valid, error, _model = validate_hypothesis_schema(data)
        assert is_valid is False
        assert error is not None

    def test_valid_hypothesis_with_optional_fields(self):
        data = {
            **VALID_HYPOTHESIS_DATA,
            "agent_classes": ["basic_agent"],
            "env_modules": ["simple_social_space"],
        }
        is_valid, _error, model = validate_hypothesis_schema(data)
        assert is_valid is True
        assert model.agent_classes == ["basic_agent"]
        assert model.env_modules == ["simple_social_space"]


class TestValidateHypothesisWithModules:
    """Tests for validate_hypothesis_with_modules function."""

    def test_valid_hypothesis_returns_tuple(self):
        is_valid, error, _model, guidance = validate_hypothesis_with_modules(
            VALID_HYPOTHESIS_DATA
        )
        assert isinstance(is_valid, bool)
        assert isinstance(error, (str, type(None)))
        assert isinstance(guidance, (dict, type(None)))

    def test_invalid_schema_returns_false(self):
        data = {"hypothesis": {"description": "missing rationale"}, "groups": []}
        is_valid, error, _model, _guidance = validate_hypothesis_with_modules(data)
        assert is_valid is False
        assert error is not None


# --- Markdown / settings generation tests ---


class TestGenerationHelpers:
    """Tests for markdown and settings generation."""

    def test_generate_hypothesis_markdown(self):
        model = HypothesisDataModel(**VALID_HYPOTHESIS_DATA)
        md = generate_hypothesis_markdown(model)
        assert "Description" in md
        assert "Agents with collectivist values" in md

    def test_generate_sim_settings(self):
        model = HypothesisDataModel(**VALID_HYPOTHESIS_DATA)
        settings = generate_sim_settings(model)
        assert isinstance(settings, dict)


# --- Workspace CRUD tests ---


class TestHypothesisWorkspaceOperations:
    """Tests for hypothesis workspace CRUD operations."""

    def test_find_existing_hypotheses_empty(self, tmp_path: Path):
        result = find_existing_hypotheses(tmp_path)
        assert result == []

    def test_get_next_hypothesis_id_first(self, tmp_path: Path):
        hyp_id = get_next_hypothesis_id(tmp_path)
        assert hyp_id == "1"

    def test_get_next_hypothesis_id_increments(self, tmp_path: Path):
        (tmp_path / "hypothesis_1").mkdir()
        (tmp_path / "hypothesis_2").mkdir()
        hyp_id = get_next_hypothesis_id(tmp_path)
        assert hyp_id == "3"

    def test_create_hypothesis_structure(self, tmp_path: Path):
        model = HypothesisDataModel(**VALID_HYPOTHESIS_DATA)
        hyp_dir = create_hypothesis_structure(tmp_path, "1", model)

        assert hyp_dir.exists()
        assert (hyp_dir / "HYPOTHESIS.md").exists()
        assert (hyp_dir / "SIM_SETTINGS.json").exists()
        # One experiment group = one experiment dir
        assert (hyp_dir / "experiment_1").exists()

    def test_add_hypothesis(self, tmp_path: Path):
        result = add_hypothesis(tmp_path, VALID_HYPOTHESIS_DATA)
        assert result["success"] is True
        assert result["hypothesis_id"] == "1"
        assert (tmp_path / "hypothesis_1").exists()

    def test_add_hypothesis_invalid_data(self, tmp_path: Path):
        result = add_hypothesis(tmp_path, {"hypothesis": {}, "groups": []})
        assert result["success"] is False

    def test_add_multiple_hypotheses(self, tmp_path: Path):
        r1 = add_hypothesis(tmp_path, VALID_HYPOTHESIS_DATA)
        assert r1["hypothesis_id"] == "1"

        r2 = add_hypothesis(tmp_path, VALID_HYPOTHESIS_DATA)
        assert r2["hypothesis_id"] == "2"

        assert (tmp_path / "hypothesis_1").exists()
        assert (tmp_path / "hypothesis_2").exists()

    def test_get_hypothesis_by_id(self, tmp_path: Path):
        add_hypothesis(tmp_path, VALID_HYPOTHESIS_DATA)
        result = get_hypothesis(tmp_path, hypothesis_id="1")
        assert result["success"] is True
        assert result["hypothesis_id"] == "1"

    def test_get_hypothesis_nonexistent(self, tmp_path: Path):
        result = get_hypothesis(tmp_path, hypothesis_id="999")
        assert result["success"] is False

    def test_get_hypothesis_missing_params(self, tmp_path: Path):
        result = get_hypothesis(tmp_path)
        assert result["success"] is False

    def test_list_hypotheses(self, tmp_path: Path):
        add_hypothesis(tmp_path, VALID_HYPOTHESIS_DATA)
        add_hypothesis(tmp_path, VALID_HYPOTHESIS_DATA)
        result = list_hypotheses(tmp_path)
        assert result["success"] is True
        assert result["total"] == 2

    def test_list_hypotheses_empty(self, tmp_path: Path):
        result = list_hypotheses(tmp_path)
        assert result["success"] is True
        assert result["total"] == 0
        assert result["hypotheses"] == []

    def test_delete_hypothesis_by_id(self, tmp_path: Path):
        add_hypothesis(tmp_path, VALID_HYPOTHESIS_DATA)
        assert (tmp_path / "hypothesis_1").exists()

        result = delete_hypothesis(tmp_path, hypothesis_id="1")
        assert result["success"] is True
        assert not (tmp_path / "hypothesis_1").exists()

    def test_delete_hypothesis_nonexistent(self, tmp_path: Path):
        result = delete_hypothesis(tmp_path, hypothesis_id="999")
        assert result["success"] is False

    def test_delete_hypothesis_missing_params(self, tmp_path: Path):
        result = delete_hypothesis(tmp_path)
        assert result["success"] is False
