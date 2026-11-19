#!/usr/bin/env bash
# Transcode every video that is still waiting for transcoding, in all Videos/ folders.
# Safe to stop with Ctrl-C at any time; run it again to continue.
# Usage: ./scripts/transcode_all.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
# shellcheck source=_activate_env.sh
source "$SCRIPT_DIR/_activate_env.sh"

cd "$PROJECT_DIR"
exec python -m ytdl transcode --all
