# Backend Selection

`agentsociety-analysis` uses a fixed Python backend for plotting and figure assembly.

## Fixed Backend

The following subcommands all depend on the Python analysis tool layer from `agentsociety2`:

- `run-eda`
- `compose-figure`
- `collect-assets`

For this skill, the backend is therefore:

```text
Python only
```

## Why the Backend Is Fixed

- experiment data is primarily stored in `run/replay/` with `_schema.json` and sharded JSONL files
- analysis and plotting are routed through `agentsociety2.skills.analysis`
- `compose-figure` is currently implemented with Pillow on the Python side
- report asset collection and naming rules are built around Python-generated outputs

## Execution Rule

- generate charts with Python + matplotlib
- generate EDA outputs with the Python analysis helpers
- assemble composite figures with `compose-figure`
- if the Python runtime or required packages are missing, stop before rendering and report the exact blocker

## Scope Boundary

This skill is for interactive analysis of AgentSociety experiment outputs. If the task is a general-purpose,
standalone manuscript plotting job outside this analysis workflow, route it to a plotting workflow that is
designed for that purpose instead of stretching this skill beyond its toolchain.
