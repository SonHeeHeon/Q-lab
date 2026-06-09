#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT_DIR"

if [[ ! -x ".venv/bin/jupyter" ]]; then
  echo "Jupyter is not installed in .venv."
  echo "Run: .venv/bin/python -m pip install -e '.[dev]'"
  exit 1
fi

export PYTHONPATH="$ROOT_DIR:${PYTHONPATH:-}"

echo "Starting JupyterLab for Q-Lab research sandbox..."
echo "Project: $ROOT_DIR"
echo "Notebooks: research/notebooks"

exec .venv/bin/jupyter lab \
  --notebook-dir="$ROOT_DIR" \
  --ServerApp.root_dir="$ROOT_DIR" \
  --ServerApp.open_browser=True
