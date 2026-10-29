"""Tests for the transcoder module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytdl.config import Config
from ytdl.media import MediaCheck
from ytdl.transcoder import batch_transcode, build_transcode_command, transcode_video


@pytest.fixture(autouse=True)
def media_ok():
    """Treat every file as a valid video unless a test says otherwise (no real ffprobe)."""
    with patch("ytdl.transcoder.check_media", return_value=MediaCheck(True)) as mock:
        yield mock


class TestBuildTranscodeCommand:
    def test_basic_command(self, config):
        cmd = build_transcode_command(
            "/usr/bin/ffmpeg",
            Path("/input/video.mp4"),
            Path("/output/video.mp4"),
            config,
        )

        assert cmd[0] == "/usr/bin/ffmpeg"
        assert "-i" in cmd
        assert "/input/video.mp4" in cmd
        assert "/output/video.mp4" in cmd

    def test_codec_settings(self, config):
        cmd = build_transcode_command(
            "ffmpeg",
            Path("/input/video.mp4"),
            Path("/output/video.mp4"),
            config,
        )

        idx_cv = cmd.index("-c:v")
        assert cmd[idx_cv + 1] == "libx264"

        idx_crf = cmd.index("-crf")
        assert cmd[idx_crf + 1] == "25"

        idx_preset = cmd.index("-preset")
        assert cmd[idx_preset + 1] == "medium"

    def test_scale_filter_included(self, config):
        cmd = build_transcode_command(
            "ffmpeg",
            Path("/input/video.mp4"),
            Path("/output/video.mp4"),
            config,
        )

        idx_vf = cmd.index("-vf")
        assert "1080" in cmd[idx_vf + 1]
        assert "min" in cmd[idx_vf + 1]

    def test_audio_codec(self, config):
        cmd = build_transcode_command(
            "ffmpeg",
            Path("/input/video.mp4"),
            Path("/output/video.mp4"),
            config,
        )

        idx_ca = cmd.index("-c:a")
        assert cmd[idx_ca + 1] == "aac"

    def test_faststart_flag(self, config):
        cmd = build_transcode_command(
            "ffmpeg",
            Path("/input/video.mp4"),
            Path("/output/video.mp4"),
            config,
        )

        assert "-movflags" in cmd
        idx = cmd.index("-movflags")
        assert cmd[idx + 1] == "+faststart"

    def test_custom_config_values(self, tmp_base_dir):
        custom_config = Config(
            base_dir=tmp_base_dir,
            max_resolution=720,
            transcode_codec="libx265",
            transcode_crf=20,
            transcode_preset="slow",
            transcode_audio_codec="opus",
        )
        cmd = build_transcode_command(
            "ffmpeg",
            Path("/input/video.mp4"),
            Path("/output/video.mp4"),
            custom_config,
        )

        idx_cv = cmd.index("-c:v")
        assert cmd[idx_cv + 1] == "libx265"
        idx_crf = cmd.index("-crf")
        assert cmd[idx_crf + 1] == "20"
        idx_vf = cmd.index("-vf")
        assert "720" in cmd[idx_vf + 1]


class TestTranscodeVideo:
    @patch("ytdl.transcoder.subprocess.run")
    @patch("ytdl.transcoder._check_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_successful_transcode(self, mock_ffmpeg, mock_run, config, tmp_base_dir):
        input_path = tmp_base_dir / "input.mp4"
        output_path = tmp_base_dir / "output.mp4"
        input_path.touch()

        # Simulate ffmpeg writing to the `.part` temp file.
        def fake_run(*args, **kwargs):
            (tmp_base_dir / "output.part.mp4").touch()
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_run

        result = transcode_video(input_path, output_path, config)

        assert result is True
        assert output_path.exists()
        assert not (tmp_base_dir / "output.part.mp4").exists()
        mock_run.assert_called_once()

    @patch("ytdl.transcoder.subprocess.run")
    @patch("ytdl.transcoder._check_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_failed_transcode(self, mock_ffmpeg, mock_run, config, tmp_base_dir):
        mock_run.return_value = MagicMock(
            returncode=1, stderr="Error: invalid input"
        )

        result = transcode_video(
            tmp_base_dir / "input.mp4", tmp_base_dir / "output.mp4", config
        )

        assert result is False

    @patch("ytdl.transcoder.subprocess.run")
    @patch("ytdl.transcoder._check_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_timeout_transcode(self, mock_ffmpeg, mock_run, config, tmp_base_dir):
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=7200)

        result = transcode_video(
            tmp_base_dir / "input.mp4", tmp_base_dir / "output.mp4", config
        )

        assert result is False


class TestBatchTranscode:
    @patch("ytdl.transcoder.transcode_video")
    @patch("ytdl.transcoder._check_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_no_raw_dir(self, mock_ffmpeg, mock_transcode, config, tmp_base_dir):
        """No _raw/ dir should result in 0, 0."""
        ok, fail = batch_transcode(tmp_base_dir, config)
        assert ok == 0
        assert fail == 0

    @patch("ytdl.transcoder.transcode_video", return_value=True)
    @patch("ytdl.transcoder._check_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_batch_transcode_success(self, mock_ffmpeg, mock_transcode, config, tmp_base_dir):
        raw_dir = tmp_base_dir / "_raw"
        raw_dir.mkdir()
        (raw_dir / "video1.mp4").touch()
        (raw_dir / "video2.mp4").touch()

        ok, fail = batch_transcode(tmp_base_dir, config)

        assert ok == 2
        assert fail == 0
        assert mock_transcode.call_count == 2

    @patch("ytdl.transcoder.transcode_video", return_value=False)
    @patch("ytdl.transcoder._check_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_batch_transcode_failure(self, mock_ffmpeg, mock_transcode, config, tmp_base_dir):
        raw_dir = tmp_base_dir / "_raw"
        raw_dir.mkdir()
        (raw_dir / "video1.mp4").touch()

        ok, fail = batch_transcode(tmp_base_dir, config)

        assert ok == 0
        assert fail == 1

    def test_batch_empty_raw_dir(self, config, tmp_base_dir):
        raw_dir = tmp_base_dir / "_raw"
        raw_dir.mkdir()

        ok, fail = batch_transcode(tmp_base_dir, config)
        assert ok == 0
        assert fail == 0

    @patch("ytdl.transcoder.transcode_video", return_value=True)
    @patch("ytdl.transcoder._check_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_ignores_non_video_files(self, mock_ffmpeg, mock_transcode, config, tmp_base_dir):
        raw_dir = tmp_base_dir / "_raw"
        raw_dir.mkdir()
        (raw_dir / "video.mp4").touch()
        (raw_dir / "readme.txt").touch()
        (raw_dir / "image.jpg").touch()

        ok, fail = batch_transcode(tmp_base_dir, config)

        assert ok == 1  # Only the .mp4
        assert mock_transcode.call_count == 1


class TestUnfinishedAndBrokenFiles:
    @patch("ytdl.transcoder.transcode_video", return_value=True)
    def test_skips_stream_pieces_and_temp_files(self, mock_transcode, config, tmp_base_dir):
        """Single-stream pieces must never become 'finished' videos (the .f251.mp4 bug)."""
        raw_dir = tmp_base_dir / "_raw"
        raw_dir.mkdir()
        (raw_dir / "A [aaaaaaaaaaa].f251.webm").touch()   # audio-only piece
        (raw_dir / "A [aaaaaaaaaaa].f137.mp4").touch()    # video-only piece
        (raw_dir / "B [bbbbbbbbbbb].f251-1.webm").touch()
        (raw_dir / "C [ccccccccccc].temp.mp4").touch()    # interrupted merge
        (raw_dir / "D [ddddddddddd].f299.mp4.part").touch()
        (raw_dir / "E [eeeeeeeeeee].mp4").touch()         # real merged download

        ok, fail = batch_transcode(tmp_base_dir, config)

        assert (ok, fail) == (1, 0)
        assert mock_transcode.call_args.args[0].name == "E [eeeeeeeeeee].mp4"
        assert (raw_dir / "A [aaaaaaaaaaa].f251.webm").exists()  # kept for yt-dlp to resume

    @patch("ytdl.transcoder.transcode_video")
    def test_broken_input_is_skipped_and_kept(self, mock_transcode, media_ok, config, tmp_base_dir):
        raw_dir = tmp_base_dir / "_raw"
        raw_dir.mkdir()
        raw = raw_dir / "A [aaaaaaaaaaa].mp4"
        raw.touch()
        media_ok.return_value = MediaCheck(False, "no video stream (audio only)")

        ok, fail = batch_transcode(tmp_base_dir, config)

        assert (ok, fail) == (0, 1)
        mock_transcode.assert_not_called()
        assert raw.exists()

    @patch("ytdl.transcoder.transcode_video", return_value=True)
    def test_broken_existing_output_is_replaced(self, mock_transcode, media_ok, config, tmp_base_dir):
        raw_dir = tmp_base_dir / "_raw"
        raw_dir.mkdir()
        (raw_dir / "A [aaaaaaaaaaa].mp4").touch()
        broken_output = tmp_base_dir / "A [aaaaaaaaaaa].mp4"
        broken_output.write_text("corrupt")
        media_ok.side_effect = lambda path, require_video: (
            MediaCheck(False, "unreadable") if path == broken_output else MediaCheck(True)
        )

        ok, fail = batch_transcode(tmp_base_dir, config)

        assert ok == 1
        mock_transcode.assert_called_once()
        assert (tmp_base_dir / "_broken" / "A [aaaaaaaaaaa].mp4").read_text() == "corrupt"

    @patch("ytdl.transcoder.transcode_video")
    def test_valid_existing_output_drops_raw(self, mock_transcode, config, tmp_base_dir):
        raw_dir = tmp_base_dir / "_raw"
        raw_dir.mkdir()
        raw = raw_dir / "A [aaaaaaaaaaa].mp4"
        raw.touch()
        (tmp_base_dir / "A [aaaaaaaaaaa].mp4").touch()

        ok, fail = batch_transcode(tmp_base_dir, config)

        assert ok == 1
        mock_transcode.assert_not_called()
        assert not raw.exists()

    @patch("ytdl.transcoder.subprocess.run")
    @patch("ytdl.transcoder._check_ffmpeg", return_value="/usr/bin/ffmpeg")
    def test_unusable_ffmpeg_output_is_not_renamed(self, mock_ffmpeg, mock_run, media_ok, config, tmp_base_dir):
        input_path = tmp_base_dir / "input.mp4"
        output_path = tmp_base_dir / "output.mp4"
        input_path.touch()

        def fake_run(*args, **kwargs):
            (tmp_base_dir / "output.part.mp4").touch()
            return MagicMock(returncode=0, stderr="")

        mock_run.side_effect = fake_run
        media_ok.return_value = MediaCheck(False, "no video stream (audio only)")

        assert transcode_video(input_path, output_path, config) is False
        assert not output_path.exists()
        assert not (tmp_base_dir / "output.part.mp4").exists()
