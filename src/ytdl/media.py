"""Media file checks (via ffprobe) and detection of yt-dlp work files."""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

VIDEO_EXTENSIONS = {".mp4", ".mkv", ".webm", ".avi", ".mov"}

# yt-dlp downloads video and audio as separate pieces named "<name>.f<format id>.<ext>"
# (format ids look like "137", "251" or "251-1") and merges them afterwards.
_FORMAT_PIECE = re.compile(r"\.f\d+(?:-[0-9A-Za-z]+)?\.[0-9A-Za-z]+$")
# Unfinished files: yt-dlp ".part"/".ytdl", the transcoder's "<name>.part.mp4",
# and yt-dlp merger/post-processor output "<name>.temp.<ext>".
_UNFINISHED = re.compile(r"(?:\.part|\.ytdl|\.(?:part|temp)\.[0-9A-Za-z]+)$")
_VIDEO_ID = re.compile(r"\[([A-Za-z0-9_-]{11})\]")

# ffprobe messages that point at the disk, not at a broken video.
_DISK_ERRORS = ("Input/output error", "Permission denied", "No such file or directory")


def is_format_piece(path: Path) -> bool:
    """Check whether a file is a single-stream piece (e.g. `name [id].f251.webm`).

    Args:
        path: File path.

    Returns:
        True for yt-dlp per-format files that still need merging.
    """
    return bool(_FORMAT_PIECE.search(path.name))


def is_intermediate(path: Path) -> bool:
    """Check whether a file is unfinished yt-dlp/transcoder work rather than a result.

    Args:
        path: File path.

    Returns:
        True for format pieces, `.part`/`.ytdl` files and `.temp.`/`.part.` outputs.
    """
    return is_format_piece(path) or bool(_UNFINISHED.search(path.name))


def video_id_from_name(name: str) -> str | None:
    """Extract the YouTube video ID from a file name like `Title [dQw4w9WgXcQ].mp4`.

    Args:
        name: File name.

    Returns:
        The last bracketed 11-character ID, or None if the name has none.
    """
    matches = _VIDEO_ID.findall(name)
    return matches[-1] if matches else None


def ffprobe_available() -> bool:
    """Return True if ffprobe is on PATH."""
    return shutil.which("ffprobe") is not None


@dataclass
class MediaCheck:
    """Result of checking one media file.

    Attributes:
        ok: True if usable, False if broken, None if it could not be checked
            (ffprobe missing, disk error, timeout). None must never lead to changes.
        reason: Why the file is broken or unchecked, or a warning for a usable file.
    """
    ok: bool | None
    reason: str = ""


def check_media(path: Path, require_video: bool) -> MediaCheck:
    """Check that a file is readable and has the streams it needs.

    Video files need a video stream. A missing audio track is reported as a
    warning only, so genuinely silent videos are not re-downloaded forever.
    Audio files need an audio stream.

    Args:
        path: File to check.
        require_video: True for videos, False for audio files.

    Returns:
        MediaCheck describing the file.
    """
    ffprobe = shutil.which("ffprobe")
    if ffprobe is None:
        return MediaCheck(None, "ffprobe not found")

    # JSON, not CSV: CSV lines can carry extra fields (e.g. "video,"), which is ambiguous.
    cmd = [ffprobe, "-v", "error", "-show_entries", "stream=codec_type", "-of", "json", str(path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return MediaCheck(None, "ffprobe timed out")
    except OSError as e:
        return MediaCheck(None, f"ffprobe failed: {e}")

    message = (proc.stderr or "").strip().splitlines()
    message = message[-1] if message else ""
    if proc.returncode != 0:
        if any(err in message for err in _DISK_ERRORS):
            return MediaCheck(None, message)
        return MediaCheck(False, f"unreadable ({message or 'ffprobe error'})")

    try:
        streams = {s.get("codec_type") for s in json.loads(proc.stdout or "{}").get("streams", [])}
    except (ValueError, AttributeError):
        return MediaCheck(None, "could not parse ffprobe output")
    if require_video:
        if "video" not in streams:
            return MediaCheck(False, "no video stream (audio only)" if "audio" in streams else "no streams")
        if "audio" not in streams:
            return MediaCheck(True, "no audio track")
        return MediaCheck(True)
    if "audio" not in streams:
        return MediaCheck(False, "no audio stream")
    return MediaCheck(True)


def check_many(paths: list[Path], require_video: bool, workers: int = 8) -> dict[Path, MediaCheck]:
    """Check several files in parallel.

    Args:
        paths: Files to check.
        require_video: True for videos, False for audio files.
        workers: Number of parallel ffprobe processes.

    Returns:
        Mapping of path to MediaCheck.
    """
    if not paths:
        return {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = pool.map(lambda p: check_media(p, require_video), paths)
        return dict(zip(paths, results))
