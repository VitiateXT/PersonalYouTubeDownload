#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ -n "${VIRTUAL_ENV:-}" ]; then
  echo "Using active virtual environment: $VIRTUAL_ENV"
elif [ -n "${CONDA_PREFIX:-}" ]; then
  echo "Using active conda environment: $CONDA_PREFIX"
else
  VENV_DIR="${VENV_DIR:-${ROOT_DIR}/.venv}"

  if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/activate" ]; then
    echo "Activating project virtual environment: $VENV_DIR"
    . "$VENV_DIR/bin/activate"
  elif command -v conda >/dev/null 2>&1; then
    # shellcheck disable=SC1090
    eval "$(conda shell.bash hook)"
    if conda env list | awk '{print $1}' | grep -qx "ytdl"; then
      echo "Activating conda environment: ytdl"
      conda activate ytdl
    else
      echo "Creating project virtual environment at $VENV_DIR"
      python3 -m venv "$VENV_DIR"
      . "$VENV_DIR/bin/activate"
    fi
  else
    echo "Creating project virtual environment at $VENV_DIR"
    python3 -m venv "$VENV_DIR"
    . "$VENV_DIR/bin/activate"
  fi
fi

echo "Upgrading pip and project dependencies using: $(python -c 'import sys; print(sys.executable)')"
python -m pip install --upgrade pip setuptools wheel
python -m pip install --upgrade -e ".[dev]"

echo "Package update complete."
