"""Tests for the transcoder module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytdl.config import Config
from ytdl.transcoder import batch_transcode, build_transcode_command, transcode_video


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
