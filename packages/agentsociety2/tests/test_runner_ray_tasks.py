"""Regression: the public runner entry points must stay Ray-wrapped.

A cleanup pass once removed ``query_agent_task`` with a regex that also ate
the ``@_ray_remote`` decorator of the *following* function
(``step_agent_batch``). The unit suite stayed green while every real run died
at ``'function' object has no attribute 'remote'`` — Ray-task wrapping is
invisible to every other test, so it gets its own.
"""

from agentsociety2.agent import runner


def test_public_runner_tasks_are_ray_remote_wrapped():
    for name in (
        "step_agent_batch",
        "create_agents_batch",
        "questionnaire_agent_batch",
    ):
        fn = getattr(runner, name)
        # ray.remote returns a RemoteFunction-like object exposing .remote(...);
        # a bare function would raise AttributeError on .remote (the bug).
        assert hasattr(fn, "remote"), f"{name} lost its @_ray_remote decorator"
        assert callable(fn.remote)
