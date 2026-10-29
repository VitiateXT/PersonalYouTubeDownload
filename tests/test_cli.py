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
