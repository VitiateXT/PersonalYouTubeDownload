"""Tests for the downloader module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytdl.config import Config
from ytdl.downloader import DownloadMode, DownloadResult, VideoDownloader
from ytdl.utils import SourceType


class TestDownloadResult:
    def test_total_count(self):
        result = DownloadResult(
            succeeded=["a", "b"],
            failed=[("c", "error")],
            skipped=["d"],
        )
        assert result.total == 4

    def test_empty_result(self):
        result = DownloadResult()
        assert result.total == 0
        assert result.succeeded == []
        assert result.failed == []
        assert result.skipped == []


class TestVideoDownloader:
    def test_build_video_opts(self, config, tmp_base_dir):
        downloader = VideoDownloader(config)
        out_dir = tmp_base_dir / "Videos" / "Test"
        out_dir.mkdir(parents=True)
        archive_path = out_dir / "archive.txt"

        opts = downloader._build_video_opts(out_dir, archive_path)

        assert "bv[height<=1080]" in opts["format"]
        assert opts["merge_output_format"] == "mp4"
        assert opts["download_archive"] == str(archive_path)
        assert "lang" in opts["format_sort"]
        assert opts["sleep_interval"] == 10
        assert opts["retries"] == 10

    def test_build_audio_opts(self, config, tmp_base_dir):
        downloader = VideoDownloader(config)
        out_dir = tmp_base_dir / "Audio" / "Test"
        out_dir.mkdir(parents=True)
        archive_path = out_dir / "archive.txt"

        opts = downloader._build_audio_opts(out_dir, archive_path)

        assert opts["format"] == "ba/b"
        assert "lang" in opts["format_sort"]
        assert len(opts["postprocessors"]) == 1
        pp = opts["postprocessors"][0]
        assert pp["key"] == "FFmpegExtractAudio"
        assert pp["preferredcodec"] == "mp3"
        assert pp["preferredquality"] == "192"

    def test_video_opts_raw_dir_in_template(self, config, tmp_base_dir):
        """Video downloads should go to _raw/ subdirectory."""
        downloader = VideoDownloader(config)
        out_dir = tmp_base_dir / "Videos" / "Test"
        out_dir.mkdir(parents=True)
        archive_path = out_dir / "archive.txt"

        opts = downloader._build_video_opts(out_dir, archive_path)
        assert "_raw" in opts["outtmpl"]

    def test_audio_opts_no_raw_dir(self, config, tmp_base_dir):
        """Audio downloads should go directly to output dir (no _raw/)."""
        downloader = VideoDownloader(config)
        out_dir = tmp_base_dir / "Audio" / "Test"
        out_dir.mkdir(parents=True)
        archive_path = out_dir / "archive.txt"

        opts = downloader._build_audio_opts(out_dir, archive_path)
        # Check that the output template path does not route through a _raw/ subdirectory
        template_relative = opts["outtmpl"].replace(str(out_dir), "")
        assert "_raw" not in template_relative

    @patch("ytdl.downloader.YoutubeDL")
    def test_download_single_video(self, mock_ydl_class, config, sample_video_info):
        mock_instance = MagicMock()
        mock_instance.extract_info.return_value = sample_video_info
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_ydl_class.return_value = mock_instance

        downloader = VideoDownloader(config)
        result = downloader.download_single(
            "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            DownloadMode.VIDEO,
        )

        assert isinstance(result, DownloadResult)
        mock_instance.extract_info.assert_called_once()

    @patch("ytdl.downloader.YoutubeDL")
    def test_download_batch(self, mock_ydl_class, config, sample_playlist_info):
        mock_instance = MagicMock()
        mock_instance.extract_info.return_value = sample_playlist_info
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_ydl_class.return_value = mock_instance

        downloader = VideoDownloader(config)
        result = downloader.download_batch(
            "https://www.youtube.com/playlist?list=PLtest",
            DownloadMode.VIDEO,
            SourceType.PLAYLIST,
            "Test Playlist",
        )

        assert isinstance(result, DownloadResult)

    @patch("ytdl.downloader.YoutubeDL")
    def test_download_handles_fatal_error(self, mock_ydl_class, config):
        mock_instance = MagicMock()
        mock_instance.extract_info.side_effect = Exception("Network error")
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_ydl_class.return_value = mock_instance

        downloader = VideoDownloader(config)
        result = downloader.download_single(
            "https://www.youtube.com/watch?v=test",
            DownloadMode.VIDEO,
        )

        assert len(result.failed) == 1

    def test_build_common_opts_uses_config(self, config):
        downloader = VideoDownloader(config)
        opts = downloader._build_common_opts()

        assert opts["sleep_interval"] == config.sleep_interval
        assert opts["max_sleep_interval"] == config.max_sleep_interval
        assert opts["sleep_interval_requests"] == config.sleep_requests
        assert opts["retries"] == config.retries
        assert opts["fragment_retries"] == config.fragment_retries
        assert opts["ignoreerrors"] is True


class TestHonestResults:
    """A video only counts as downloaded once yt-dlp archived it (all streams merged)."""

    @staticmethod
    def _ydl(mock_ydl_class, info, archive_ids):
        def make(opts):
            instance = MagicMock()
            instance.__enter__ = MagicMock(return_value=instance)
            instance.__exit__ = MagicMock(return_value=False)

            def extract_info(url, download):
                if archive_ids:
                    with open(opts["download_archive"], "a") as fh:
                        fh.writelines(f"youtube {i}\n" for i in archive_ids)
                return info

            instance.extract_info.side_effect = extract_info
            return instance

        mock_ydl_class.side_effect = make

    @patch("ytdl.downloader.YoutubeDL")
    def test_unarchived_entry_is_failed(self, mock_ydl_class, config, sample_playlist_info):
        # yt-dlp returns all three entries (with requested_downloads), but the
        # merge only succeeded for video1.
        for entry in sample_playlist_info["entries"]:
            entry["requested_downloads"] = [{"filepath": "x"}]
        self._ydl(mock_ydl_class, sample_playlist_info, ["video1"])

        result = VideoDownloader(config).download_batch(
            "https://www.youtube.com/playlist?list=PLtest",
            DownloadMode.VIDEO, SourceType.PLAYLIST, "Test Playlist",
        )

        assert result.succeeded == ["First Video"]
        assert [title for title, _ in result.failed] == ["Second Video", "Third Video"]
        assert "incomplete download" in result.failed[0][1]

    @patch("ytdl.downloader.YoutubeDL")
    def test_previously_archived_entry_is_skipped(self, mock_ydl_class, config, sample_playlist_info, tmp_base_dir):
        folder = tmp_base_dir / "Videos" / "Test Playlist"
        folder.mkdir(parents=True)
        (folder / "archive.txt").write_text("youtube video1\n")
        self._ydl(mock_ydl_class, sample_playlist_info, ["video2", "video3"])

        result = VideoDownloader(config).download_batch(
            "https://www.youtube.com/playlist?list=PLtest",
            DownloadMode.VIDEO, SourceType.PLAYLIST, "Test Playlist",
        )

        assert result.skipped == ["First Video"]
        assert result.succeeded == ["Second Video", "Third Video"]
        assert result.failed == []

    @patch("ytdl.downloader.YoutubeDL")
    def test_nested_channel_tabs_are_flattened(self, mock_ydl_class, config):
        info = {"id": "UC1", "title": "Ch", "entries": [
            {"id": "tab", "title": "Ch - Videos", "entries": [{"id": "v1", "title": "One"}]},
            {"id": "v2", "title": "Two"},
            None,
        ]}
        self._ydl(mock_ydl_class, info, ["v1", "v2"])

        result = VideoDownloader(config).download_batch(
            "https://www.youtube.com/@Ch", DownloadMode.VIDEO, SourceType.CHANNEL, "Ch",
        )

        assert result.succeeded == ["One", "Two"]
        assert len(result.failed) == 1  # the None entry


class TestYDLLogger:
    def test_errors_are_attributed_to_the_current_video(self):
        from ytdl.downloader import _YDLLogger

        log = _YDLLogger()
        log.debug("[youtube] 5ZHvnPdXXxQ: Downloading webpage")
        log.error("ERROR: unable to download video data: HTTP Error 403: Forbidden")
        log.debug("[youtube] bPLKa4crk8A: Downloading webpage")

        assert log.errors_by_id == {
            "5ZHvnPdXXxQ": "ERROR: unable to download video data: HTTP Error 403: Forbidden"
        }
