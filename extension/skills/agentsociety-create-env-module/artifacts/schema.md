# Artifact Schema

Optional trace artifacts live under:

``
.agentsociety/custom_env_skill/runs/<run_id>/
``

Files:

- `run_state.json`
- `request.json`
- `clarifications.jsonl`
- `design_spec.json`
- `design_summary.md`
- `generation_input.json`
- `generation_summary.md`
- `validation_report.json`
- `validation_summary.md`
- `run.log`

Notes:

- `design_spec.json` should include the approved persistence plan when the module is stateful.
- `generation_input.json` is optional. Add it when the generation step involved nontrivial tradeoffs or prompts worth reviewing later.
- A run directory is optional. Use it when you want reviewable trace, not as a required execution gate.
- `generation_summary.md` is optional but recommended when the generation step involved meaningful tradeoffs or fixes.
- Reusing a run directory for validation should preserve earlier design and generation references in `run_state.json` instead of overwriting them.
