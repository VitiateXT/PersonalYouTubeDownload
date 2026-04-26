"""Tests for utility functions."""

from pathlib import Path

import pytest

from ytdl.utils import (
    ContentType,
    SourceType,
    ensure_dir,
    get_archive_path,
    get_output_dir,
    get_raw_dir,
    sanitize_filename,
)


class TestSanitizeFilename:
    def test_basic_name(self):
        assert sanitize_filename("My Channel") == "My Channel"

    def test_removes_slashes(self):
        assert sanitize_filename("My/Channel") == "My-Channel"
        assert sanitize_filename("My\\Channel") == "My-Channel"

    def test_removes_special_chars(self):
        result = sanitize_filename('My <Channel> "Name": test?')
        assert "<" not in result
        assert ">" not in result
        assert '"' not in result
        assert ":" not in result
        assert "?" not in result

    def test_collapses_spaces(self):
        assert sanitize_filename("My   Channel") == "My Channel"

    def test_collapses_dashes(self):
        assert sanitize_filename("My---Channel") == "My-Channel"

    def test_strips_leading_trailing(self):
        assert sanitize_filename("  My Channel  ") == "My Channel"
        assert sanitize_filename("...My Channel...") == "My Channel"

    def test_empty_string_fallback(self):
        assert sanitize_filename("") == "Unknown"
        assert sanitize_filename("...") == "Unknown"
        assert sanitize_filename("   ") == "Unknown"

    def test_null_byte_removed(self):
        assert sanitize_filename("My\0Channel") == "MyChannel"

    def test_pipe_removed(self):
        assert sanitize_filename("My|Channel") == "MyChannel"

    def test_asterisk_removed(self):
        assert sanitize_filename("My*Channel") == "MyChannel"


class TestEnsureDir:
    def test_creates_directory(self, tmp_path):
        new_dir = tmp_path / "a" / "b" / "c"
        result = ensure_dir(new_dir)
        assert new_dir.exists()
        assert new_dir.is_dir()
        assert result == new_dir

    def test_existing_directory(self, tmp_path):
        existing = tmp_path / "existing"
        existing.mkdir()
        result = ensure_dir(existing)
        assert existing.exists()
        assert result == existing


class TestGetOutputDir:
    def test_video_channel(self, tmp_path):
        result = get_output_dir(tmp_path, ContentType.VIDEO, SourceType.CHANNEL, "My Channel")
        assert result == tmp_path / "Videos" / "My Channel"
        assert result.exists()

    def test_video_playlist(self, tmp_path):
        result = get_output_dir(tmp_path, ContentType.VIDEO, SourceType.PLAYLIST, "My Playlist")
        assert result == tmp_path / "Videos" / "My Playlist"
        assert result.exists()

    def test_video_single(self, tmp_path):
        result = get_output_dir(tmp_path, ContentType.VIDEO, SourceType.SINGLE)
        assert result == tmp_path / "Videos" / "Misc"
        assert result.exists()

    def test_audio_channel(self, tmp_path):
        result = get_output_dir(tmp_path, ContentType.AUDIO, SourceType.CHANNEL, "My Channel")
        assert result == tmp_path / "Audio" / "My Channel"
        assert result.exists()

    def test_audio_single(self, tmp_path):
        result = get_output_dir(tmp_path, ContentType.AUDIO, SourceType.SINGLE)
        assert result == tmp_path / "Audio" / "Misc"
        assert result.exists()

    def test_sanitizes_channel_name(self, tmp_path):
        result = get_output_dir(
            tmp_path, ContentType.VIDEO, SourceType.CHANNEL, "My/Bad:Channel"
        )
        assert result == tmp_path / "Videos" / "My-BadChannel"

    def test_none_source_name_falls_back_to_misc(self, tmp_path):
        result = get_output_dir(
            tmp_path, ContentType.VIDEO, SourceType.CHANNEL, None
        )
        assert result == tmp_path / "Videos" / "Misc"


class TestGetRawDir:
    def test_creates_raw_subdir(self, tmp_path):
        out_dir = tmp_path / "Videos" / "Channel"
        out_dir.mkdir(parents=True)
        result = get_raw_dir(out_dir)
        assert result == out_dir / "_raw"
        assert result.exists()


class TestGetArchivePath:
    def test_returns_archive_path(self, tmp_path):
        result = get_archive_path(tmp_path)
        assert result == tmp_path / "archive.txt"
        # Should not create the file, just return the path
        assert not result.exists()
