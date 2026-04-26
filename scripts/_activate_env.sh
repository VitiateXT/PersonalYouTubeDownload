#!/usr/bin/env bash
# Sourced (not executed) by the download scripts to ensure the `ytdl` conda
# env is active before running `python -m ytdl`. No-op if the env is already
# active. Requires `conda` to be on PATH.
if [[ "${CONDA_DEFAULT_ENV:-}" != "ytdl" ]]; then
    if ! command -v conda >/dev/null 2>&1; then
        echo "Error: conda not found on PATH; cannot activate 'ytdl' env." >&2
        exit 1
    fi
    CONDA_BASE="$(conda info --base)"
    # shellcheck disable=SC1091
    source "$CONDA_BASE/etc/profile.d/conda.sh"
    conda activate ytdl
fi
