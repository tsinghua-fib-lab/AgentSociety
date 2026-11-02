import os


def _ensure_llm_env_for_tests() -> None:
    # Disable telemetry before any imports
    os.environ.setdefault("MEM0_TELEMETRY", "False")
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

    if not (os.environ.get("AGENTSOCIETY_LLM_API_KEY") or "").strip():
        os.environ["AGENTSOCIETY_LLM_API_KEY"] = "test-key"
    if not (os.environ.get("AGENTSOCIETY_LLM_API_BASE") or "").strip():
        os.environ["AGENTSOCIETY_LLM_API_BASE"] = "https://api.openai.com/v1"
    # Perf/regression knobs must exercise the *code defaults* — drop any value
    # exported by a developer's shell for local experiments (read at import time
    # by agentsociety2.config, so this has to happen before the first import).
    os.environ.pop("AGENTSOCIETY_ENV_ACTOR_MAX_CONCURRENCY", None)
    os.environ.pop("AGENTSOCIETY_ENV_RESTORE_ALLOW_FRESH", None)


_ensure_llm_env_for_tests()
