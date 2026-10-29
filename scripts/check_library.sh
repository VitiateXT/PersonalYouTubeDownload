#!/usr/bin/env bash
# Report broken downloads that the next download/update run would repair.
# Read-only: nothing is moved, deleted or downloaded.
# Usage: ./scripts/check_library.sh [FOLDER]   (default: every channel/playlist folder)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
# shellcheck source=_activate_env.sh
source "$SCRIPT_DIR/_activate_env.sh"

if [[ $# -gt 1 ]]; then
    echo "Usage: $0 [FOLDER]"
    echo "Example: $0 '/home/moritz/Media/YTDownloader/Videos/High Yield - Videos'"
    exit 1
fi

if [[ $# -eq 1 ]]; then
    DIR="$(realpath "$1")"   # resolve before changing directory
    cd "$PROJECT_DIR"
    exec python -m ytdl check --dir "$DIR"
fi

cd "$PROJECT_DIR"
exec python -m ytdl check
