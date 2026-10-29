"""Tests for media file checks."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from ytdl.media import check_media, is_format_piece, is_intermediate, video_id_from_name


class TestFileNames:
    @pytest.mark.parametrize("name", [
        "Title [5ZHvnPdXXxQ].f251.webm",
        "Title [5ZHvnPdXXxQ].f251.mp4",        # old bug output
        "Title [bPLKa4crk8A].f251-1.mp4",
        "Title [5ZHvnPdXXxQ].f137.mp4.part",
        "Title [5ZHvnPdXXxQ].mp4.part",
        "Title [5ZHvnPdXXxQ].mp4.ytdl",
        "Title [5ZHvnPdXXxQ].temp.mp4",
        "Title [5ZHvnPdXXxQ].part.mp4",
    ])
    def test_intermediate(self, name):
        assert is_intermediate(Path(name))

    @pytest.mark.parametrize("name", [
        "Title [5ZHvnPdXXxQ].mp4",
        "Episode f1 [5ZHvnPdXXxQ].mp4",
        "v1.5 release [5ZHvnPdXXxQ].mp3",
    ])
    def test_finished(self, name):
        assert not is_intermediate(Path(name))

    def test_format_piece(self):
        assert is_format_piece(Path("T [5ZHvnPdXXxQ].f251.mp4"))
        assert not is_format_piece(Path("T [5ZHvnPdXXxQ].mp4"))

    def test_video_id(self):
        assert video_id_from_name("A [x] B [5ZHvnPdXXxQ].f251.mp4") == "5ZHvnPdXXxQ"
        assert video_id_from_name("2025-10-27 Oxford lecture.mp3") is None


def _ffprobe(returncode=0, stdout="", stderr=""):
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def _streams(*types):
    return json.dumps({"streams": [{"codec_type": t} for t in types]})


@patch("ytdl.media.shutil.which", return_value="/usr/bin/ffprobe")
class TestCheckMedia:
    @pytest.mark.parametrize("types, require_video, ok, reason", [
        (("video", "audio"), True, True, ""),
        (("audio",), True, False, "no video stream (audio only)"),
        (("video",), True, True, "no audio track"),
        (("audio", "video"), False, True, ""),   # mp3 with cover art
        (("video",), False, False, "no audio stream"),
    ])
    def test_streams(self, _which, types, require_video, ok, reason):
        with patch("ytdl.media.subprocess.run", return_value=_ffprobe(stdout=_streams(*types))):
            check = check_media(Path("x.mp4"), require_video)
        assert (check.ok, check.reason) == (ok, reason)

    def test_unreadable_file_is_broken(self, _which):
        result = _ffprobe(1, stderr="[mov] moov atom not found\nx.mp4: Invalid data found when processing input")
        with patch("ytdl.media.subprocess.run", return_value=result):
            check = check_media(Path("x.mp4"), True)
        assert check.ok is False
        assert "Invalid data" in check.reason

    def test_disk_error_is_not_a_verdict(self, _which):
        result = _ffprobe(1, stderr="x.mp4: Input/output error")
        with patch("ytdl.media.subprocess.run", return_value=result):
            assert check_media(Path("x.mp4"), True).ok is None

    def test_timeout_is_not_a_verdict(self, _which):
        import subprocess
        with patch("ytdl.media.subprocess.run", side_effect=subprocess.TimeoutExpired("ffprobe", 120)):
            assert check_media(Path("x.mp4"), True).ok is None


def test_missing_ffprobe_is_not_a_verdict():
    with patch("ytdl.media.shutil.which", return_value=None):
        assert check_media(Path("x.mp4"), True).ok is None


@patch("ytdl.media.shutil.which", return_value="/usr/bin/ffprobe")
def test_garbled_output_is_not_a_verdict(_which):
    with patch("ytdl.media.subprocess.run", return_value=_ffprobe(stdout="video,\naudio\n")):
        assert check_media(Path("x.mp4"), True).ok is None


def test_real_ffprobe_on_generated_files(tmp_path):
    """End-to-end with the real ffprobe/ffmpeg: video+audio, audio-only, corrupt."""
    import shutil
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg or not shutil.which("ffprobe"):
        pytest.skip("ffmpeg/ffprobe not installed")

    def make(name, *inputs):
        out = tmp_path / name
        cmd = [ffmpeg, "-v", "error", "-y"]
        for spec in inputs:
            cmd += ["-f", "lavfi", "-i", spec]
        subprocess.run(cmd + ["-t", "1", "-shortest", str(out)], check=True)
        return out

    both = make("both.mp4", "testsrc=size=64x64:rate=5", "sine=frequency=440")
    audio_only = make("audio_only.mp4", "sine=frequency=440")
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(both.read_bytes()[: len(both.read_bytes()) // 3])

    assert check_media(both, True).ok is True
    assert check_media(audio_only, True).ok is False
    assert check_media(corrupt, True).ok is False
