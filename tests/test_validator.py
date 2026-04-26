"""Tests for URL validation and type detection."""

from unittest.mock import MagicMock, patch

import pytest

from ytdl.validator import URLType, detect_url_type, extract_metadata, validate_url


class TestValidateUrl:
    def test_valid_video_url(self):
        assert validate_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True

    def test_valid_short_url(self):
        assert validate_url("https://youtu.be/dQw4w9WgXcQ") is True

    def test_valid_playlist_url(self):
        assert validate_url(
            "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
        ) is True

    def test_valid_channel_url(self):
        assert validate_url("https://www.youtube.com/@ChannelName") is True

    def test_valid_channel_url_old_format(self):
        assert validate_url("https://www.youtube.com/channel/UCxxxxxxx") is True

    def test_valid_shorts_url(self):
        assert validate_url("https://www.youtube.com/shorts/abcdefg") is True

    def test_invalid_url_not_youtube(self):
        assert validate_url("https://www.vimeo.com/12345") is False

    def test_invalid_url_random_string(self):
        assert validate_url("not-a-url") is False

    def test_invalid_url_empty(self):
        assert validate_url("") is False

    def test_http_without_www(self):
        assert validate_url("http://youtube.com/watch?v=test") is True


class TestDetectUrlType:
    def test_video_url(self):
        assert (
            detect_url_type("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
            == URLType.VIDEO
        )

    def test_short_video_url(self):
        assert detect_url_type("https://youtu.be/dQw4w9WgXcQ") == URLType.VIDEO

    def test_shorts_url(self):
        assert (
            detect_url_type("https://www.youtube.com/shorts/abcdefg")
            == URLType.VIDEO
        )

    def test_playlist_url(self):
        assert (
            detect_url_type(
                "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
            )
            == URLType.PLAYLIST
        )

    def test_watch_url_with_list_only_is_playlist(self):
        assert (
            detect_url_type(
                "https://www.youtube.com/watch?list=PLpOuhygfD7QnP46wUgQudOySX_z2UOhXs"
            )
            == URLType.PLAYLIST
        )

    def test_watch_url_with_video_and_list_is_playlist(self):
        assert (
            detect_url_type(
                "https://www.youtube.com/watch?v=QBH6IpRkVDs&list=PLpOuhygfD7QnP46wUgQudOySX_z2UOhXs"
            )
            == URLType.PLAYLIST
        )

    def test_channel_at_url(self):
        assert (
            detect_url_type("https://www.youtube.com/@ChannelName")
            == URLType.CHANNEL
        )

    def test_channel_old_url(self):
        assert (
            detect_url_type("https://www.youtube.com/channel/UCxxxxxxx")
            == URLType.CHANNEL
        )

    def test_channel_c_url(self):
        assert (
            detect_url_type("https://www.youtube.com/c/ChannelName")
            == URLType.CHANNEL
        )

    def test_channel_user_url(self):
        assert (
            detect_url_type("https://www.youtube.com/user/SomeName")
            == URLType.CHANNEL
        )

    def test_channel_url_with_playlist_param(self):
        """Channel URL with list= param should be detected as playlist."""
        url = "https://www.youtube.com/@Channel?list=PLxxxxxxx"
        assert detect_url_type(url) == URLType.PLAYLIST

    def test_unknown_url_raises(self):
        with pytest.raises(ValueError, match="Cannot determine URL type"):
            detect_url_type("https://www.youtube.com/")


class TestExtractMetadata:
    @patch("ytdl.validator.YoutubeDL")
    def test_extract_video_metadata(self, mock_ydl_class, sample_video_info):
        mock_instance = MagicMock()
        mock_instance.extract_info.return_value = sample_video_info
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_ydl_class.return_value = mock_instance

        result = extract_metadata("https://www.youtube.com/watch?v=dQw4w9WgXcQ")

        assert result.url_type == URLType.VIDEO
        assert result.title == "Rick Astley - Never Gonna Give You Up"
        assert result.source_id == "dQw4w9WgXcQ"
        assert result.video_count == 1
        assert result.video_ids == ["dQw4w9WgXcQ"]

    @patch("ytdl.validator.YoutubeDL")
    def test_extract_playlist_metadata(self, mock_ydl_class, sample_playlist_info):
        mock_instance = MagicMock()
        mock_instance.extract_info.return_value = sample_playlist_info
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_ydl_class.return_value = mock_instance

        result = extract_metadata(
            "https://www.youtube.com/playlist?list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf"
        )

        assert result.url_type == URLType.PLAYLIST
        assert result.title == "Test Playlist"
        assert result.video_count == 3
        assert result.video_ids == ["video1", "video2", "video3"]

    @patch("ytdl.validator.YoutubeDL")
    def test_extract_channel_metadata(self, mock_ydl_class, sample_channel_info):
        mock_instance = MagicMock()
        mock_instance.extract_info.return_value = sample_channel_info
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_ydl_class.return_value = mock_instance

        result = extract_metadata("https://www.youtube.com/@TestChannel")

        assert result.url_type == URLType.CHANNEL
        assert result.title == "Test Channel"
        assert result.video_count == 2

    @patch("ytdl.validator.YoutubeDL")
    def test_extract_metadata_failure(self, mock_ydl_class):
        mock_instance = MagicMock()
        mock_instance.extract_info.side_effect = Exception("Network error")
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_ydl_class.return_value = mock_instance

        with pytest.raises(ValueError, match="Failed to extract metadata"):
            extract_metadata("https://www.youtube.com/watch?v=invalid")

    @patch("ytdl.validator.YoutubeDL")
    def test_extract_metadata_none_result(self, mock_ydl_class):
        mock_instance = MagicMock()
        mock_instance.extract_info.return_value = None
        mock_instance.__enter__ = MagicMock(return_value=mock_instance)
        mock_instance.__exit__ = MagicMock(return_value=False)
        mock_ydl_class.return_value = mock_instance

        with pytest.raises(ValueError, match="No metadata returned"):
            extract_metadata("https://www.youtube.com/watch?v=test")
