#!/usr/bin/env bash
# Download audio episodes of a University of Oxford Podcasts series.
# Usage: ./scripts/download_oxford_podcast.sh <URL>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
# shellcheck source=_activate_env.sh
source "$SCRIPT_DIR/_activate_env.sh"

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <Oxford-Podcasts-Series-URL>"
    echo "Example: $0 'https://podcasts.ox.ac.uk/series/strachey-lectures'"
    exit 1
fi

URL="$1"

# The URL is passed as an argument (not interpolated into the code) to avoid quoting issues.
VALID=$(python -c "
import sys
from ytdl.oxford import is_oxford_url
print('OK' if is_oxford_url(sys.argv[1]) else 'INVALID')
" "$URL" 2>/dev/null) || { echo "Error: Failed to validate URL. Is the project installed?"; exit 1; }

if [[ "$VALID" != "OK" ]]; then
    echo "Error: Not an Oxford Podcasts series URL (expected https://podcasts.ox.ac.uk/series/...)."
    exit 1
fi

cd "$PROJECT_DIR"
exec python -m ytdl download --url "$URL" --mode audio
