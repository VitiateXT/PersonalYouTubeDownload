"""URL validation, type detection, and metadata extraction."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse
from dataclasses import dataclass, field
from enum import Enum

from yt_dlp import YoutubeDL


class URLType(Enum):
    """Type of YouTube URL."""
    VIDEO = "video"
    PLAYLIST = "playlist"
    CHANNEL = "channel"


@dataclass
class MediaMetadata:
    """Metadata extracted from a YouTube URL."""
    url_type: URLType
    title: str  # Channel name, playlist title, or video title
    source_id: str  # Channel ID, playlist ID, or video ID
    video_count: int = 0
    video_ids: list[str] = field(default_factory=list)
    video_titles: list[str] = field(default_factory=list)


# Patterns for YouTube URL types
_CHANNEL_PATTERNS = [
    r"youtube\.com/(?:c|channel|user)/[^/?#]+",
    r"youtube\.com/@[^/?#]+",
]

_PLAYLIST_PATTERNS = [
    r"youtube\.com/playlist\?list=",
]

_VIDEO_PATTERNS = [
    r"youtube\.com/watch\?v=",
    r"youtu\.be/[^/?#]+",
    r"youtube\.com/shorts/[^/?#]+",
]

_YOUTUBE_URL_PATTERN = re.compile(
    r"^https?://(?:www\.)?(?:youtube\.com|youtu\.be)/?"
)


def validate_url(url: str) -> bool:
    """Check if a URL is a valid YouTube URL.

    Args:
        url: URL string to validate.

    Returns:
        True if the URL appears to be a valid YouTube URL.
    """
    return bool(_YOUTUBE_URL_PATTERN.match(url))


def detect_url_type(url: str) -> URLType:
    """Detect whether a URL points to a video, playlist, or channel.

    Args:
        url: A YouTube URL.

    Returns:
        The detected URLType.

    Raises:
        ValueError: If the URL type cannot be determined.
    """
    # Any YouTube URL with a real `list` query parameter should be treated as
    # a playlist target (e.g. /watch?list=..., /watch?v=...&list=...).
    query = parse_qs(urlparse(url).query)
    if "list" in query and query["list"]:
        return URLType.PLAYLIST

    for pattern in _CHANNEL_PATTERNS:
        if re.search(pattern, url):
            return URLType.CHANNEL

    for pattern in _PLAYLIST_PATTERNS:
        if re.search(pattern, url):
            return URLType.PLAYLIST

    for pattern in _VIDEO_PATTERNS:
        if re.search(pattern, url):
            return URLType.VIDEO

    raise ValueError(f"Cannot determine URL type for: {url}")


def extract_metadata(url: str) -> MediaMetadata:
    """Extract metadata from a YouTube URL without downloading.

    Uses yt-dlp to fetch channel/playlist/video info. For playlists and
    channels, uses flat extraction for speed.

    Args:
        url: A valid YouTube URL.

    Returns:
        MediaMetadata with title, ID, and video list.

    Raises:
        ValueError: If the URL is invalid or cannot be processed.
    """
    url_type = detect_url_type(url)

    # "in_playlist" (not True) so yt-dlp still follows a top-level redirect,
    # e.g. watch?list=X -> playlist?list=X, while keeping the entries flat.
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist" if url_type != URLType.VIDEO else False,
        "skip_download": True,
    }

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        raise ValueError(f"Failed to extract metadata from {url}: {e}") from e

    if info is None:
        raise ValueError(f"No metadata returned for {url}")

    if url_type == URLType.VIDEO:
        return MediaMetadata(
            url_type=URLType.VIDEO,
            title=info.get("title", "Unknown"),
            source_id=info.get("id", ""),
            video_count=1,
            video_ids=[info.get("id", "")],
            video_titles=[info.get("title", "Unknown")],
        )

    # An unresolved redirect has no title or entries; never guess a folder name.
    if info.get("_type") == "url":
        raise ValueError(f"Could not resolve {url_type.value} (yt-dlp returned a redirect only): {url}")

    # Playlist or channel — entries are flat-extracted
    entries = list(info.get("entries") or [])
    video_ids = []
    video_titles = []
    for entry in entries:
        if entry is not None:
            video_ids.append(entry.get("id", ""))
            video_titles.append(entry.get("title", "Unknown"))

    source_id = info.get("id") or info.get("channel_id") or ""
    # Fall back to the ID rather than a shared name, so different sources
    # never end up in the same folder.
    title = info.get("title") or info.get("uploader") or source_id
    if not title:
        raise ValueError(f"Could not determine the {url_type.value} name for {url}")

    return MediaMetadata(
        url_type=url_type,
        title=title,
        source_id=source_id,
        video_count=len(video_ids),
        video_ids=video_ids,
        video_titles=video_titles,
    )
