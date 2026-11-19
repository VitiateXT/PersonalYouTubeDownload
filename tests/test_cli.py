"""Tests for CLI commands."""

from argparse import Namespace
from unittest.mock import patch

from ytdl.cli import cmd_check, main
from ytdl.media import MediaCheck


def _all_ok(paths, require_video, workers=8):
    return {p: MediaCheck(True) for p in paths}


class TestCheckCommand:
    def test_reports_without_changing_anything(self, config, capsys):
        folder = config.base_dir / "Videos" / "High Yield - Videos"
        folder.mkdir(parents=True)
        piece = folder / "Apple A15 [5ZHvnPdXXxQ].f251.mp4"
        piece.touch()
        (folder / "archive.txt").write_text("")
        (config.base_dir / "Audio" / "Clean").mkdir(parents=True)

        with patch("ytdl.repair.check_many", side_effect=_all_ok), \
             patch("ytdl.repair.ffprobe_available", return_value=True):
            code = cmd_check(Namespace(dir=None, mode=None), config)

        out = capsys.readouterr().out
        assert code == 1
        assert "re-download" in out and "Apple A15" in out
        assert "Checked 2 folder(s): 1 need repair." in out
        assert piece.exists()
        assert not (folder / "_broken").exists()

    def test_clean_library(self, config, capsys):
        (config.base_dir / "Videos" / "Clean").mkdir(parents=True)

        with patch("ytdl.repair.check_many", side_effect=_all_ok), \
             patch("ytdl.repair.ffprobe_available", return_value=True):
            code = cmd_check(Namespace(dir=None, mode=None), config)

        assert code == 0
        assert "0 need repair" in capsys.readouterr().out

    def test_check_does_not_create_log_file(self, config, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text(f'[general]\nbase_dir = "{config.base_dir}"\n')
        with patch("ytdl.repair.ffprobe_available", return_value=True):
            main(["-c", str(cfg), "check"])
        assert not (config.base_dir / "logs").exists()


class TestTranscodeCommand:
    @staticmethod
    def _library(config):
        videos = config.base_dir / "Videos"
        raw = videos / "Chan A" / "_raw"
        raw.mkdir(parents=True)
        (raw / "Ready [aaaaaaaaaaa].mp4").write_bytes(b"x" * 10)
        (raw / "Half [bbbbbbbbbbb].f251.webm").touch()       # unfinished piece
        (raw / "Half [bbbbbbbbbbb].f137.mp4.part").touch()
        (videos / "Chan B" / "_raw").mkdir(parents=True)     # empty _raw
        (videos / "Chan C").mkdir()                          # no _raw
        return videos

    def test_list_is_read_only(self, config, capsys):
        from ytdl.cli import cmd_transcode

        videos = self._library(config)
        with patch("ytdl.cli.batch_transcode") as mock_transcode:
            code = cmd_transcode(Namespace(dir=None, all=True, list=True), config)

        out = capsys.readouterr().out
        assert code == 0
        mock_transcode.assert_not_called()
        assert "Chan A: 1 to transcode" in out and "Ready [aaaaaaaaaaa].mp4" in out
        assert "Half" not in out.split("Total:")[0].split("unfinished")[-1]
        assert "Total: 1 video(s)" in out and "1 unfinished download piece(s)" in out
        assert "Chan B" not in out and "Chan C" not in out
        assert (videos / "Chan A" / "_raw" / "Ready [aaaaaaaaaaa].mp4").exists()

    def test_all_transcodes_only_folders_with_pending_videos(self, config):
        from ytdl.cli import cmd_transcode

        self._library(config)
        with patch("ytdl.cli.batch_transcode", return_value=(1, 0)) as mock_transcode:
            code = cmd_transcode(Namespace(dir=None, all=True, list=False), config)

        assert code == 0
        assert [c.args[0].name for c in mock_transcode.call_args_list] == ["Chan A"]

    def test_failures_give_nonzero_exit(self, config):
        from ytdl.cli import cmd_transcode

        self._library(config)
        with patch("ytdl.cli.batch_transcode", return_value=(0, 1)):
            assert cmd_transcode(Namespace(dir=None, all=True, list=False), config) == 1

    def test_needs_dir_or_all(self, config):
        from ytdl.cli import cmd_transcode

        assert cmd_transcode(Namespace(dir=None, all=False, list=False), config) == 1

    def test_list_does_not_create_log_file(self, config, tmp_path):
        cfg = tmp_path / "config.toml"
        cfg.write_text(f'[general]\nbase_dir = "{config.base_dir}"\n')
        main(["-c", str(cfg), "transcode", "--all", "--list"])
        assert not (config.base_dir / "logs").exists()
