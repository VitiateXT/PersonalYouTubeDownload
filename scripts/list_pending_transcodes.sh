#!/usr/bin/env bash
# List all videos that are downloaded but still waiting for transcoding.
# Read-only: nothing is transcoded, moved or deleted.
# Usage: ./scripts/list_pending_transcodes.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
# shellcheck source=_activate_env.sh
source "$SCRIPT_DIR/_activate_env.sh"

cd "$PROJECT_DIR"
exec python -m ytdl transcode --all --list
