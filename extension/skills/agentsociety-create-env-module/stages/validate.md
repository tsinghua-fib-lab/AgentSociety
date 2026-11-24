# Validate

Validate the generated module through `$PYTHON_PATH .agentsociety/bin/ags.py create-env-module-validate`.

If traceability matters, keep the validation report in the same run directory as your design and generation notes. If not, validate directly and treat any run artifacts as lightweight notes.
Reusing `--run-id` should extend an existing note trail, not replace earlier design or generation artifacts.

If validation fails, run `$PYTHON_PATH .agentsociety/bin/ags.py create-env-module-resolve-sources` if needed, then read `references/runtime-sources.md` again. Use the bundled local validator implementation as the source of truth for fixes.
If the module has mutable state or replay expectations, also re-read `references/persistence-patterns.md` and compare the code against the built-in persistence examples.
For replay-related validation, explicitly inspect whether step-keyed tables advance over multiple simulation steps instead of silently overwriting the same primary key.

Preferred paths:

- Local CLI: `$PYTHON_PATH .agentsociety/bin/ags.py create-env-module-validate --file custom/envs/<module>.py --workspace <repo> --run-id <run_id>`
- Or directly: `$PYTHON_PATH .agentsociety/bin/ags.py create-env-module-validate --file custom/envs/<module>.py --workspace <repo>`

Read and persist:

- `validation_report.json`
- `validation_summary.md`

If you need stronger traceability, keep the design and generation notes in the same run directory. If you do not, the validation result still stands on its own.

Failure mapping:

- Design mismatch: go back to `design`
- Import or codegen failure: go back to `generate`
- Compatibility or tester failure: inspect structured checks first, then choose `design` or `generate`
- Mutable state exists but replay-write logic is missing: go back to `design`, fix the persistence plan (declare `_agent_state_columns` / `_env_state_columns`, write via `_write_*`), then regenerate. Replay is the only persistence channel.
- Replay rows exist but only one step survives after a multi-step run: treat this as a persistence design bug first. Check whether the code used `tick` (duration) where it needed a monotonically increasing replay `step`.
- Registry visibility failure: fix registry integration, not the prompt wording
