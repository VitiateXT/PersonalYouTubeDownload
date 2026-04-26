#!/usr/bin/env bash
# Download a single YouTube video (video + audio).
# Usage: ./scripts/download_video.sh <URL>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
# shellcheck source=_activate_env.sh
source "$SCRIPT_DIR/_activate_env.sh"

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <YouTube-Video-URL>"
    echo "Example: $0 'https://www.youtube.com/watch?v=dQw4w9WgXcQ'"
    exit 1
fi

URL="$1"

# Validate URL type
URL_TYPE=$(python -c "
from ytdl.validator import validate_url, detect_url_type
url = '$URL'
if not validate_url(url):
    print('INVALID')
else:
    try:
        print(detect_url_type(url).value)
    except ValueError:
        print('UNKNOWN')
" 2>/dev/null) || { echo "Error: Failed to validate URL. Is the project installed?"; exit 1; }

if [[ "$URL_TYPE" == "INVALID" ]]; then
    echo "Error: Not a valid YouTube URL."
    exit 1
fi

if [[ "$URL_TYPE" != "video" ]]; then
    echo "Error: Expected a single video URL, but detected: $URL_TYPE"
    echo "Use the appropriate script for ${URL_TYPE}s."
    exit 1
fi

cd "$PROJECT_DIR"
exec python -m ytdl download --url "$URL" --mode video --type video
