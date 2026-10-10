"""Configuration loading and management."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


DEFAULTS = {
    "general": {
        "base_dir": ".",
    },
    "video": {
        "max_resolution": 1080,
        "format": "mp4",
        "file_template": "%(title)s [%(id)s].%(ext)s",
    },
    "audio": {
        "format": "mp3",
        "bitrate": "192",
        "file_template": "%(title)s [%(id)s].%(ext)s",
    },
    "transcode": {
        "codec": "libx264",
        "crf": 25,
        "audio_codec": "aac",
        "preset": "medium",
    },
    "network": {
        "sleep_interval": 10,
        "max_sleep_interval": 20,
        "sleep_requests": 0.75,
        "retries": 10,
        "fragment_retries": 10,
    },
    "oxford": {
        "captions": False,
        "delay": 1.5,
    },
}


@dataclass
class Config:
    """Application configuration.

    Attributes:
        base_dir: Root directory where Videos/ and Audio/ are created.
        max_resolution: Maximum video height for download/transcode workflows.
        video_format: Output container for video files.
        video_file_template: yt-dlp naming template for video downloads.
        audio_format: Output format for audio-only downloads.
        audio_bitrate: Audio bitrate for audio-only downloads.
        audio_file_template: yt-dlp naming template for audio downloads.
        transcode_codec: ffmpeg video codec for transcoding.
        transcode_crf: ffmpeg CRF value for transcoding quality.
        transcode_audio_codec: ffmpeg audio codec for transcoding.
        transcode_preset: ffmpeg encoding speed/compression preset.
        sleep_interval: Minimum sleep between media downloads.
        max_sleep_interval: Maximum sleep between media downloads.
        sleep_requests: Sleep between extractor/API requests.
        retries: Retry count for main download requests.
        fragment_retries: Retry count for media fragment requests.
        oxford_captions: Also download .srt captions for Oxford podcast episodes.
        oxford_delay: Seconds to pause between Oxford podcast downloads.
    """

    # General
    base_dir: Path = field(default_factory=lambda: Path("."))

    # Video
    max_resolution: int = 1080
    video_format: str = "mp4"
    video_file_template: str = "%(title)s [%(id)s].%(ext)s"

    # Audio
    audio_format: str = "mp3"
    audio_bitrate: str = "192"
    audio_file_template: str = "%(title)s [%(id)s].%(ext)s"

    # Transcode
    transcode_codec: str = "libx264"
    transcode_crf: int = 25
    transcode_audio_codec: str = "aac"
    transcode_preset: str = "medium"

    # Network
    sleep_interval: int = 10
    max_sleep_interval: int = 20
    sleep_requests: float = 0.75
    retries: int = 10
    fragment_retries: int = 10

    # Oxford podcasts
    oxford_captions: bool = False
    oxford_delay: float = 1.5


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge dictionaries recursively with override taking precedence.

    Args:
        base: Base dictionary.
        override: Dictionary with override values.

    Returns:
        A new merged dictionary.
    """
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _find_config_file(explicit_path: str | Path | None = None) -> Path | None:
    """Search for the primary config.toml in standard locations.

    Args:
        explicit_path: Optional explicit path from CLI.

    Returns:
        Path to config.toml if found; otherwise None.
    """
    if explicit_path is not None:
        p = Path(explicit_path)
        if p.is_file():
            return p
        return None

    # Check CWD
    cwd_config = Path.cwd() / "config.toml"
    if cwd_config.is_file():
        return cwd_config

    # Check project root (where this file lives: src/ytdl/config.py -> ../../config.toml)
    project_root = Path(__file__).resolve().parent.parent.parent / "config.toml"
    if project_root.is_file():
        return project_root

    return None


def load_config(path: str | Path | None = None) -> Config:
    """Load configuration from a TOML file, merged with defaults.

    Args:
        path: Explicit path to config file. If None, searches standard locations.

    Returns:
        Config instance with all settings resolved.
    """
    config_file = _find_config_file(path)

    if config_file is not None:
        with open(config_file, "rb") as f:
            user_config = tomllib.load(f)
        merged = _deep_merge(DEFAULTS, user_config)
    else:
        merged = DEFAULTS

    general = merged["general"]
    video = merged["video"]
    audio = merged["audio"]
    transcode = merged["transcode"]
    network = merged["network"]
    oxford = merged["oxford"]

    base_dir = Path(general["base_dir"])
    # Resolve relative paths against config file location or CWD
    if not base_dir.is_absolute():
        if config_file is not None:
            base_dir = config_file.parent / base_dir
        else:
            base_dir = Path.cwd() / base_dir

    return Config(
        base_dir=base_dir.resolve(),
        max_resolution=int(video["max_resolution"]),
        video_format=str(video["format"]),
        video_file_template=str(video["file_template"]),
        audio_format=str(audio["format"]),
        audio_bitrate=str(audio["bitrate"]),
        audio_file_template=str(audio["file_template"]),
        transcode_codec=str(transcode["codec"]),
        transcode_crf=int(transcode["crf"]),
        transcode_audio_codec=str(transcode["audio_codec"]),
        transcode_preset=str(transcode["preset"]),
        sleep_interval=int(network["sleep_interval"]),
        max_sleep_interval=int(network["max_sleep_interval"]),
        sleep_requests=float(network["sleep_requests"]),
        retries=int(network["retries"]),
        fragment_retries=int(network["fragment_retries"]),
        oxford_captions=bool(oxford["captions"]),
        oxford_delay=float(oxford["delay"]),
    )
