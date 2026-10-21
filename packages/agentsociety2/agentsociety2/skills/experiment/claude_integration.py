"""Claude Code integration helpers for Skills

This module provides convenience functions for Claude Code to use when
working with AgentSociety skills. These functions bridge the gap between
the skill scripts (which handle validation) and Claude Code (which handles
coding/implementation in the main loop).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def suggest_modules_for_topic(topic: str) -> dict[str, Any]:
    """Suggest appropriate agent and environment modules for a research topic

    This function analyzes the research topic and suggests suitable
    agent types and environment modules based on keywords and common patterns.

    :param topic: Research topic or description

    :returns: Dictionary with suggested modules and rationale
    """
    from agentsociety2.skills.experiment.module_discovery import (
        get_available_agent_modules,
        get_available_env_modules,
    )

    topic_lower = topic.lower()

    # Default suggestions
    suggested_agents = ["person_agent"]
    suggested_envs = ["simple_social_space"]
    rationale = []

    # Analyze topic for keywords
    keywords = {
        # Social/interaction topics
        "social": (["person_agent"], ["simple_social_space", "global_information"]),
        "interaction": (["person_agent"], ["simple_social_space"]),
        "communication": (
            ["person_agent"],
            ["simple_social_space", "global_information"],
        ),
        "information": (
            ["person_agent"],
            ["global_information", "simple_social_space"],
        ),
        "influence": (["person_agent"], ["simple_social_space", "global_information"]),
        "network": (["person_agent"], ["simple_social_space", "global_information"]),
        # Economic topics
        "economic": (["llm_donor_agent"], ["economy_space"]),
        "money": (["llm_donor_agent"], ["economy_space"]),
        "donat": (["llm_donor_agent"], ["economy_space", "reputation_game"]),
        "trade": (["llm_donor_agent"], ["economy_space"]),
        # Game theory topics
        "prisoner": (["prisoners_dilemma_agent"], ["prisoners_dilemma"]),
        "dilemma": (["prisoners_dilemma_agent"], ["prisoners_dilemma"]),
        "public good": (["public_goods_agent"], ["public_goods"]),
        "commons": (["commons_tragedy_agent"], ["commons_tragedy"]),
        "trust": (["trust_game_agent"], ["trust_game"]),
        "volunteer": (["volunteer_dilemma_agent"], ["volunteer_dilemma"]),
        # Mobility topics
        "mobility": (["person_agent"], ["mobility_space", "simple_social_space"]),
        "movement": (["person_agent"], ["mobility_space"]),
        "location": (["person_agent"], ["mobility_space"]),
        # Social media topics
        "social media": (["person_agent"], ["social_media"]),
        "platform": (["person_agent"], ["social_media"]),
        "post": (["person_agent"], ["social_media"]),
    }

    # Check for matching keywords
    for keyword, (agents, envs) in keywords.items():
        if keyword in topic_lower:
            suggested_agents = list(set(suggested_agents + agents))
            suggested_envs = list(set(suggested_envs + envs))
            rationale.append(f"Keyword '{keyword}' detected")

    # Get available modules
    available_agents = get_available_agent_modules()
    available_envs = get_available_env_modules()

    # Filter to only available modules
    suggested_agents = [a for a in suggested_agents if a in available_agents]
    suggested_envs = [e for e in suggested_envs if e in available_envs]

    # Build rationale
    if not rationale:
        rationale.append("Using default modules for general social simulation")
    else:
        rationale = [f"Suggestions based on: {', '.join(rationale)}"]

    return {
        "suggested_agents": suggested_agents,
        "suggested_envs": suggested_envs,
        "rationale": rationale,
        "available_agents": list(available_agents.keys()),
        "available_envs": list(available_envs.keys()),
    }


def generate_hypothesis_config(
    topic: str,
    description: str,
    rationale: str,
    groups: list[dict[str, Any]],
    agent_classes: list[str] | None = None,
    env_modules: list[str] | None = None,
) -> dict[str, Any]:
    """Generate a complete hypothesis configuration

    This function creates a properly formatted hypothesis configuration
    that can be passed to add_hypothesis_with_validation().

    :param topic: Research topic
    :param description: Hypothesis description
    :param rationale: Theoretical basis
    :param groups: List of experiment groups
    :param agent_classes: Agent types (optional, will suggest if not provided)
    :param env_modules: Environment modules (optional, will suggest if not provided)

    :returns: Complete hypothesis configuration dictionary
    """
    # Suggest modules if not provided
    if not agent_classes or not env_modules:
        suggestions = suggest_modules_for_topic(topic + " " + description)
        if not agent_classes:
            agent_classes = suggestions["suggested_agents"]
        if not env_modules:
            env_modules = suggestions["suggested_envs"]

    return {
        "topic": topic,
        "hypothesis": {
            "description": description,
            "rationale": rationale,
        },
        "groups": groups,
        "agent_classes": agent_classes,
        "env_modules": env_modules,
    }


def validate_experiment_ready(
    workspace_path: Path,
    hypothesis_id: str,
    experiment_id: str,
) -> tuple[bool, list[str], dict[str, Any]]:
    """Check if an experiment is ready to run

    This function validates that all necessary configuration is in place
    for an experiment to be executed.

    :param workspace_path: Path to workspace directory
    :param hypothesis_id: Hypothesis ID
    :param experiment_id: Experiment ID

    :returns: Tuple of (is_ready, missing_items, context)
    """
    from agentsociety2.skills.experiment.config import (
        get_experiment_paths,
        read_sim_settings,
    )

    missing = []
    context = {
        "hypothesis_id": hypothesis_id,
        "experiment_id": experiment_id,
        "has_config": False,
        "has_agents": False,
        "has_env_args": False,
    }

    paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id)

    # Check if hypothesis exists
    if not paths["hypothesis"].exists():
        missing.append(f"Hypothesis directory not found: {paths['hypothesis']}")
        return False, missing, context

    # Check if experiment directory exists
    if not paths["experiment"].exists():
        missing.append(f"Experiment directory not found: {paths['experiment']}")
        return False, missing, context

    # Read SIM_SETTINGS
    sim_settings = read_sim_settings(paths["hypothesis"])
    agent_classes = sim_settings.get("agentClasses", [])
    env_modules = sim_settings.get("envModules", [])

    if not agent_classes:
        missing.append("No agent classes selected in SIM_SETTINGS.json")
    else:
        context["has_agents"] = True

    if not env_modules:
        missing.append("No environment modules selected in SIM_SETTINGS.json")
    else:
        context["has_env_args"] = True

    # Check for init config
    if paths["init_config"].exists():
        context["has_config"] = True
    else:
        missing.append("init_config.json not found - run init action first")

    context["sim_settings"] = sim_settings
    context["agent_classes"] = agent_classes
    context["env_modules"] = env_modules

    is_ready = len(missing) == 0
    return is_ready, missing, context


def get_experiment_template(
    workspace_path: Path,
    hypothesis_id: str,
    experiment_id: str,
) -> dict[str, Any]:
    """Get a template for experiment configuration

    This function provides a template structure that Claude Code can
    use to generate the full experiment configuration.

    :param workspace_path: Path to workspace directory
    :param hypothesis_id: Hypothesis ID
    :param experiment_id: Experiment ID

    :returns: Template dictionary with structure to fill in
    """
    from agentsociety2.skills.experiment.config import (
        get_experiment_paths,
        read_experiment_info,
        read_sim_settings,
    )

    paths = get_experiment_paths(workspace_path, hypothesis_id, experiment_id)

    # Read SIM_SETTINGS
    sim_settings = read_sim_settings(paths["hypothesis"])
    agent_classes = sim_settings.get("agentClasses", [])
    env_modules = sim_settings.get("envModules", [])

    # Read experiment info
    exp_info = read_experiment_info(paths["experiment"])

    # Build template
    template = {
        "hypothesis_id": hypothesis_id,
        "experiment_id": experiment_id,
        "agent_classes": agent_classes,
        "env_modules": env_modules,
        "experiment_info": exp_info,
        "configuration": {
            "num_agents": 10,
            "num_steps": 20,
            "env_args": {},
            "agent_args": [],
        },
        "instructions": {
            "env_args": f"Configure environment parameters for: {', '.join(env_modules)}",
            "agent_args": f"Create {10} agent configurations with profile.custom_fields",
            "num_agents": "Should match the length of agent_args list",
        },
    }

    return template


def format_module_suggestion_message(suggestions: dict[str, Any]) -> str:
    """Format module suggestions into a helpful message

    :param suggestions: Dictionary from suggest_modules_for_topic()

    :returns: Formatted message string
    """
    lines = []
    lines.append("# Suggested Modules")
    lines.append("")
    lines.append("## Agent Types")
    for agent in suggestions["suggested_agents"]:
        lines.append(f"- `{agent}`")
    lines.append("")
    lines.append("## Environment Modules")
    for env in suggestions["suggested_envs"]:
        lines.append(f"- `{env}`")
    lines.append("")
    lines.append("## Rationale")
    for reason in suggestions["rationale"]:
        lines.append(f"- {reason}")
    lines.append("")
    lines.append("## All Available Modules")
    lines.append("")
    lines.append("### Agent Types")
    for agent in suggestions["available_agents"]:
        status = " [SUGGESTED]" if agent in suggestions["suggested_agents"] else ""
        lines.append(f"- `{agent}`{status}")
    lines.append("")
    lines.append("### Environment Modules")
    for env in suggestions["available_envs"]:
        status = " [SUGGESTED]" if env in suggestions["suggested_envs"] else ""
        lines.append(f"- `{env}`{status}")

    return "\n".join(lines)


__all__ = [
    "format_module_suggestion_message",
    "generate_hypothesis_config",
    "get_experiment_template",
    "suggest_modules_for_topic",
    "validate_experiment_ready",
]
