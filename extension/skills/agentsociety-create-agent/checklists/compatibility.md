# Agent Compatibility Checklist

Verify the generated Agent meets the current `AgentBase` contract.

## Required abstract methods (all three MUST be async)

- [ ] `async def to_workspace(self, workspace_path: Path) -> None`
- [ ] `async def ask(self, message: str, readonly: bool = True, *, t: datetime | None = None) -> str`
- [ ] `async def step(self, tick: int, t: datetime) -> str`

## Construction model

- [ ] Runtime state setup lives in `restore`.
- [ ] If keeping a custom `AGENT.json` shape (minimal / game templates): `create(workspace_path, profile, config)` and `from_workspace(workspace_path, service_proxy)` are reimplemented as classmethods, and `restore` binds services via `self._bind_services(service_proxy)` without calling `super().restore(...)`.
- [ ] If using the base workspace FS + skill runtime (full template): `create` / `from_workspace` are **inherited** unchanged; `restore` calls `await super().restore(workspace_path, service_proxy)` FIRST, then adds business state.

## Recommended methods

- [ ] Override `@classmethod def description(cls) -> str` with a short module-list summary.
- [ ] Override `@classmethod def init_description(cls) -> str` with profile / config-key guidance.
- [ ] If you call `self.run_react_loop(...)`: override `build_react_messages(...)` (the base raises `NotImplementedError`).

## Inheritance

- [ ] Class inherits from `AgentBase` (or `PersonAgent`, which subclasses `AgentBase`). Runtime registration accepts any `AgentBase` subclass in the file; this skill's `validate.py` only recognizes **direct** bases named `AgentBase` or `PersonAgent` in the AST.
- [ ] Class is not abstract (all three required methods implemented).

## Code quality

- [ ] All required methods are `async`.
- [ ] `to_workspace` writes JSON-serializable data; `restore` reads it back symmetrically.
- [ ] Profile accessed via `self.get_profile()` then `.get(key, default)`.
- [ ] Clear policy for `ask_env` / env failures (retry, default, or re-raise) — avoid silent swallowing.
- [ ] `ask_env` message strings are natural-language instructions ("Please call `tool()` using … from `ctx['variables']`"), not Python call literals — see `references/pitfalls.md` P2.
- [ ] `template_mode=True` only on `readonly=True` queries or verified-idempotent writes with non-colliding arg names — see `references/pitfalls.md` P3.

## Registration

- [ ] File lives under workspace `custom/agents/` (not under an `examples/` path if you want it scanned).
- [ ] The agent **class is defined in that file** (`cls.__module__` must match the loaded file); importing a ready-made class from another module without re-declaring it here will not register.
- [ ] File name matches class concept.
- [ ] Overridden `init_description()` documents profile + config fields when behavior is non-trivial.
