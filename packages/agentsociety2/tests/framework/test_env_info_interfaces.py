from agentsociety2.contrib.env.economy_space import EconomySpace
from agentsociety2.contrib.env.mobility_space.environment import MobilitySpace
from agentsociety2.registry import (
    get_registered_agent_modules,
    get_registered_env_modules,
)


def test_registered_modules_expose_description_and_init_description():
    for module_type, env_class in get_registered_env_modules():
        description = env_class.description()
        init_description = env_class.init_description()

        assert isinstance(description, str), module_type
        assert description.strip(), module_type
        assert isinstance(init_description, str), module_type
        assert init_description.strip(), module_type

    for agent_type, agent_class in get_registered_agent_modules():
        description = agent_class.description()
        init_description = agent_class.init_description()

        assert isinstance(description, str), agent_type
        assert description.strip(), agent_type
        assert isinstance(init_description, str), agent_type
        assert init_description.strip(), agent_type


def test_env_skill_dirs_use_new_classmethod_interface():
    mobility_dirs = MobilitySpace.skill_dirs()
    economy_dirs = EconomySpace.skill_dirs()

    assert any(path.name == "agent_skills" for path in mobility_dirs)
    assert any(path.name == "economy_space_agent_skills" for path in economy_dirs)
    assert all(path.is_dir() for path in mobility_dirs + economy_dirs)
