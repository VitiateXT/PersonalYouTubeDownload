"""Utility functions for path management and file operations."""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path


class ContentType(Enum):
    """Type of content being downloaded."""
    VIDEO = "Videos"
    AUDIO = "Audio"


class SourceType(Enum):
    """Source of the content."""
    CHANNEL = "channel"
    PLAYLIST = "playlist"
    SINGLE = "single"


def sanitize_filename(name: str) -> str:
    """Remove or replace characters that are unsafe for filenames.

    Args:
        name: Raw name string (e.g. channel or playlist name).

    Returns:
        Sanitized string safe for use as a directory/file name.
    """
    # Replace path separators and null bytes
    name = name.replace("/", "-").replace("\\", "-").replace("\0", "")
    # Remove other problematic characters
    name = re.sub(r'[<>:"|?*]', "", name)
    # Collapse multiple spaces/dashes
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"-{2,}", "-", name)
    # Strip leading/trailing whitespace and dots (Windows issue)
    name = name.strip(" .")
    # Fallback for empty result
    if not name:
        name = "Unknown"
    return name


def ensure_dir(path: Path) -> Path:
    """Create directory (and parents) if it doesn't exist.

    Args:
        path: Directory path to create.

    Returns:
        The same path, for chaining.
    """
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_output_dir(
    base_dir: Path,
    content_type: ContentType,
    source_type: SourceType,
    source_name: str | None = None,
) -> Path:
    """Build the correct output directory path based on content and source type.

    Args:
        base_dir: Root directory (from config).
        content_type: VIDEO or AUDIO.
        source_type: CHANNEL, PLAYLIST, or SINGLE.
        source_name: Channel or playlist name. Ignored for SINGLE.

    Returns:
        Path to the output directory (e.g. base_dir/Videos/ChannelName/).
    """
    base = base_dir / content_type.value

    if source_type == SourceType.SINGLE:
        return ensure_dir(base / "Misc")

    if source_name is None:
        return ensure_dir(base / "Misc")

    folder_name = sanitize_filename(source_name)
    return ensure_dir(base / folder_name)


def get_raw_dir(output_dir: Path) -> Path:
    """Get the _raw/ subdirectory for pre-transcode downloads.

    Args:
        output_dir: The final output directory.

    Returns:
        Path to the _raw/ subdirectory, created if needed.
    """
    return ensure_dir(output_dir / "_raw")


def get_archive_path(output_dir: Path) -> Path:
    """Get the path to the per-folder archive file.

    Args:
        output_dir: The output directory for this channel/playlist/misc.

    Returns:
        Path to archive.txt within that directory.
    """
    return output_dir / "archive.txt"
