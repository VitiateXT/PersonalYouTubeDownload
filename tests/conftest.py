"""Shared test fixtures."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ytdl.config import Config


@pytest.fixture
def tmp_base_dir(tmp_path: Path) -> Path:
    """Provide a temporary base directory for downloads."""
    return tmp_path


@pytest.fixture
def config(tmp_base_dir: Path) -> Config:
    """Provide a Config instance pointing to a temp directory."""
    return Config(
        base_dir=tmp_base_dir,
        max_resolution=1080,
        video_format="mp4",
        video_file_template="%(title)s [%(id)s].%(ext)s",
        audio_format="mp3",
        audio_bitrate="192",
        audio_file_template="%(title)s [%(id)s].%(ext)s",
        transcode_codec="libx264",
        transcode_crf=25,
        transcode_audio_codec="aac",
        transcode_preset="medium",
        sleep_interval=10,
        max_sleep_interval=20,
        sleep_requests=0.75,
        retries=10,
        fragment_retries=10,
    )


@pytest.fixture
def mock_ydl():
    """Provide a mock YoutubeDL instance."""
    mock = MagicMock()
    mock.__enter__ = MagicMock(return_value=mock)
    mock.__exit__ = MagicMock(return_value=False)
    return mock


@pytest.fixture
def sample_video_info() -> dict:
    """Sample yt-dlp info dict for a single video."""
    return {
        "id": "dQw4w9WgXcQ",
        "title": "Rick Astley - Never Gonna Give You Up",
        "uploader": "Rick Astley",
        "channel": "Rick Astley",
        "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
        "duration": 212,
        "formats": [],
        "requested_downloads": [{"filepath": "/tmp/test.mp4"}],
    }


@pytest.fixture
def sample_playlist_info() -> dict:
    """Sample yt-dlp info dict for a playlist."""
    return {
        "id": "PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf",
        "title": "Test Playlist",
        "uploader": "Test Channel",
        "entries": [
            {"id": "video1", "title": "First Video"},
            {"id": "video2", "title": "Second Video"},
            {"id": "video3", "title": "Third Video"},
        ],
    }


@pytest.fixture
def sample_channel_info() -> dict:
    """Sample yt-dlp info dict for a channel."""
    return {
        "id": "UCuAXFkgsw1L7xaCfnd5JJOw",
        "title": "Test Channel",
        "uploader": "Test Channel",
        "channel_id": "UCuAXFkgsw1L7xaCfnd5JJOw",
        "entries": [
            {"id": "ch_vid1", "title": "Channel Video 1"},
            {"id": "ch_vid2", "title": "Channel Video 2"},
        ],
    }
