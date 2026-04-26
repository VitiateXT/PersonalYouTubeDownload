"""Tests for the updater module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytdl.downloader import DownloadMode, DownloadResult
from ytdl.updater import check_for_updates, update
from ytdl.validator import MediaMetadata, URLType


class TestCheckForUpdates:
    @patch("ytdl.updater.extract_metadata")
    def test_detects_missing_videos(self, mock_extract, tmp_path):
        mock_extract.return_value = MediaMetadata(
            url_type=URLType.CHANNEL,
            title="Test Channel",
            source_id="UC123",
            video_count=3,
            video_ids=["vid1", "vid2", "vid3"],
            video_titles=["V1", "V2", "V3"],
        )

        # Simulate vid1 already downloaded
        archive = tmp_path / "archive.txt"
        archive.write_text("youtube vid1\n")

        missing, all_ids = check_for_updates(
            "https://www.youtube.com/@TestChannel",
            tmp_path,
        )

        assert missing == ["vid2", "vid3"]
        assert len(all_ids) == 3

    @patch("ytdl.updater.extract_metadata")
    def test_no_updates_needed(self, mock_extract, tmp_path):
        mock_extract.return_value = MediaMetadata(
            url_type=URLType.PLAYLIST,
            title="Test Playlist",
            source_id="PL123",
            video_count=2,
            video_ids=["vid1", "vid2"],
            video_titles=["V1", "V2"],
        )

        archive = tmp_path / "archive.txt"
        archive.write_text("youtube vid1\nyoutube vid2\n")

        missing, all_ids = check_for_updates(
            "https://www.youtube.com/playlist?list=PL123",
            tmp_path,
        )

        assert missing == []

    @patch("ytdl.updater.extract_metadata")
    def test_empty_local_archive(self, mock_extract, tmp_path):
        mock_extract.return_value = MediaMetadata(
            url_type=URLType.CHANNEL,
            title="Test Channel",
            source_id="UC123",
            video_count=2,
            video_ids=["vid1", "vid2"],
            video_titles=["V1", "V2"],
        )

        missing, all_ids = check_for_updates(
            "https://www.youtube.com/@TestChannel",
            tmp_path,
        )

        assert missing == ["vid1", "vid2"]


class TestUpdate:
    @patch("ytdl.updater.save_report")
    @patch("ytdl.updater.batch_transcode", return_value=(1, 0))
    @patch("ytdl.updater.VideoDownloader")
    @patch("ytdl.updater.extract_metadata")
    def test_update_downloads_new_only(
        self, mock_extract, mock_dl_class, mock_transcode, mock_save, config
    ):
        mock_extract.return_value = MediaMetadata(
            url_type=URLType.CHANNEL,
            title="Test Channel",
            source_id="UC123",
            video_count=3,
            video_ids=["vid1", "vid2", "vid3"],
            video_titles=["V1", "V2", "V3"],
        )

        mock_downloader = MagicMock()
        mock_downloader.download_batch.return_value = DownloadResult(
            succeeded=["V2", "V3"],
            skipped=["V1"],
        )
        mock_dl_class.return_value = mock_downloader

        result = update(
            "https://www.youtube.com/@TestChannel",
            DownloadMode.VIDEO,
            config,
        )

        assert len(result.succeeded) == 2
        mock_downloader.download_batch.assert_called_once()

    @patch("ytdl.updater.extract_metadata")
    def test_update_rejects_video_url(self, mock_extract, config):
        mock_extract.return_value = MediaMetadata(
            url_type=URLType.VIDEO,
            title="Single Video",
            source_id="vid1",
            video_count=1,
            video_ids=["vid1"],
            video_titles=["V1"],
        )

        with pytest.raises(ValueError, match="only supported for channels and playlists"):
            update(
                "https://www.youtube.com/watch?v=test",
                DownloadMode.VIDEO,
                config,
            )

    @patch("ytdl.updater.save_report")
    @patch("ytdl.updater.VideoDownloader")
    @patch("ytdl.updater.extract_metadata")
    def test_update_audio_mode_no_transcode(
        self, mock_extract, mock_dl_class, mock_save, config
    ):
        mock_extract.return_value = MediaMetadata(
            url_type=URLType.PLAYLIST,
            title="Test Playlist",
            source_id="PL123",
            video_count=2,
            video_ids=["vid1", "vid2"],
            video_titles=["V1", "V2"],
        )

        mock_downloader = MagicMock()
        mock_downloader.download_batch.return_value = DownloadResult(
            succeeded=["V1", "V2"],
        )
        mock_dl_class.return_value = mock_downloader

        with patch("ytdl.updater.batch_transcode") as mock_transcode:
            result = update(
                "https://www.youtube.com/playlist?list=PL123",
                DownloadMode.AUDIO,
                config,
            )
            # batch_transcode should NOT be called for audio mode
            mock_transcode.assert_not_called()

    @patch("ytdl.updater.save_report")
    @patch("ytdl.updater.VideoDownloader")
    @patch("ytdl.updater.extract_metadata")
    def test_update_all_downloaded_returns_skipped(
        self, mock_extract, mock_dl_class, mock_save, config
    ):
        """When all videos are already downloaded, return early."""
        mock_extract.return_value = MediaMetadata(
            url_type=URLType.CHANNEL,
            title="Test Channel",
            source_id="UC123",
            video_count=2,
            video_ids=["vid1", "vid2"],
            video_titles=["V1", "V2"],
        )

        # Create archive with all videos
        from ytdl.utils import ContentType, SourceType, get_output_dir
        output_dir = get_output_dir(
            config.base_dir, ContentType.VIDEO, SourceType.CHANNEL, "Test Channel"
        )
        archive = output_dir / "archive.txt"
        archive.write_text("youtube vid1\nyoutube vid2\n")

        result = update(
            "https://www.youtube.com/@TestChannel",
            DownloadMode.VIDEO,
            config,
        )

        # Should not call download_batch since nothing is missing
        mock_dl_class.return_value.download_batch.assert_not_called()
        assert len(result.skipped) > 0
