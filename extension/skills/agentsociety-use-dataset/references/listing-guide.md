# Package-Manager-Style Listing Guide

## List All Datasets (Local + Remote)

```bash
$PYTHON_PATH .agentsociety/bin/ags.py use-dataset list --all
```

Output shows a merged view with status:

```
ID                  Name                     Category    Version   Status
my-survey           My Survey                surveys     1.0.0     installed
agent-demographics  Agent Demographics       agent_prof  2.0.0     outdated (local: 1.0.0)
weather-data        Weather Station Data     simulation  1.0.0     available
```

### Status Values

| Status | Meaning |
|--------|---------|
| `installed` | Local version matches remote |
| `outdated (local: X.Y.Z)` | Remote has a newer version |
| `newer (local: X.Y.Z)` | Local version is ahead of remote |
| `available` | Remote only, not yet downloaded |
| `installed (offline)` | Local only, remote unreachable |

## List Local Only

```bash
$PYTHON_PATH .agentsociety/bin/ags.py use-dataset list
$PYTHON_PATH .agentsociety/bin/ags.py use-dataset list-installed
```

## List Remote Only

```bash
$PYTHON_PATH .agentsociety/bin/ags.py use-dataset list --remote
```

## Info with Version Comparison

```bash
$PYTHON_PATH .agentsociety/bin/ags.py use-dataset info <dataset_id>
```

Shows remote metadata by default. If locally installed and outdated, displays a warning with update command.
