#!/bin/bash
# Build the AS2 documentation with its locked workspace dependencies.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
PROJECT_DIR="$(dirname "${SCRIPT_DIR}")"
cd "${PROJECT_DIR}"
uv sync --frozen --package agentsociety2 --extra docs
make html SPHINXBUILD="${PROJECT_DIR}/.venv/bin/sphinx-build"
