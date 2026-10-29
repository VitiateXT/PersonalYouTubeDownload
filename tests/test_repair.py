"""Tests for finding, re-queuing and cleaning up broken downloads."""

from pathlib import Path
from unittest.mock import patch

import pytest

from ytdl.downloader import DownloadMode
from ytdl.media import MediaCheck
from ytdl.repair import cleanup, inspect_folder, reconcile

A, B, C, D = "aaaaaaaaaaa", "bbbbbbbbbbb", "ccccccccccc", "ddddddddddd"
VIDEO = DownloadMode.VIDEO
AUDIO = DownloadMode.AUDIO


@pytest.fixture
def folder(tmp_path) -> Path:
    path = tmp_path / "Videos" / "Channel"
    path.mkdir(parents=True)
    return path


@pytest.fixture
def bad():
    """Names listed here are reported broken by the (fake) ffprobe check."""
    broken: dict[str, MediaCheck] = {}

    def fake_check_many(paths, require_video, workers=8):
        return {p: broken.get(p.name, MediaCheck(True)) for p in paths}

    with patch("ytdl.repair.check_many", side_effect=fake_check_many), \
         patch("ytdl.repair.ffprobe_available", return_value=True):
        yield broken


def touch(path: Path, text: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def archive(folder: Path, *ids: str) -> None:
    (folder / "archive.txt").write_text("".join(f"youtube {i}\n" for i in ids))


def archived(folder: Path) -> list[str]:
    return (folder / "archive.txt").read_text().split()[1::2]


class TestReconcile:
    def test_piece_without_good_copy_is_set_aside_and_requeued(self, folder, config, bad):
        touch(folder / f"T [{A}].f251.mp4")
        archive(folder, A, B)

        report = reconcile(folder, VIDEO, config)

        assert (folder / "_broken" / f"T [{A}].f251.mp4").exists()
        assert not (folder / f"T [{A}].f251.mp4").exists()
        assert archived(folder) == [B]
        assert len(report.requeued) == 1

    def test_piece_with_good_copy_is_deleted(self, folder, config, bad):
        touch(folder / f"T [{A}].f251.mp4")
        touch(folder / f"T [{A}].mp4")
        archive(folder, A)

        report = reconcile(folder, VIDEO, config)

        assert not (folder / f"T [{A}].f251.mp4").exists()
        assert (folder / f"T [{A}].mp4").exists()
        assert archived(folder) == [A]
        assert len(report.removed) == 1 and not report.requeued

    def test_corrupt_archived_file_is_requeued(self, folder, config, bad):
        touch(folder / f"T [{A}].mp4", "corrupt")
        touch(folder / f"T [{B}].mp4")
        archive(folder, A, B)
        bad[f"T [{A}].mp4"] = MediaCheck(False, "unreadable")

        reconcile(folder, VIDEO, config)

        assert (folder / "_broken" / f"T [{A}].mp4").read_text() == "corrupt"
        assert archived(folder) == [B]

    def test_broken_raw_download_is_requeued(self, folder, config, bad):
        touch(folder / "_raw" / f"T [{A}].mp4")
        archive(folder, A)
        bad[f"T [{A}].mp4"] = MediaCheck(False, "no video stream (audio only)")

        reconcile(folder, VIDEO, config)

        assert (folder / "_broken" / f"T [{A}].mp4").exists()
        assert archived(folder) == []

    def test_unfinished_raw_pieces_are_left_for_yt_dlp(self, folder, config, bad):
        piece = touch(folder / "_raw" / f"T [{A}].f137.mp4.part")
        audio = touch(folder / "_raw" / f"T [{A}].f251.webm")

        report = reconcile(folder, VIDEO, config)

        assert piece.exists() and audio.exists()
        assert not report.needs_action

    def test_missing_audio_track_is_only_a_warning(self, folder, config, bad):
        touch(folder / f"T [{A}].mp4")
        archive(folder, A)
        bad[f"T [{A}].mp4"] = MediaCheck(True, "no audio track")

        report = reconcile(folder, VIDEO, config)

        assert (folder / f"T [{A}].mp4").exists()
        assert report.warnings and not report.needs_action

    def test_files_without_video_id_are_ignored(self, folder, config, bad):
        touch(folder / "my own clip.mp4")
        bad["my own clip.mp4"] = MediaCheck(False, "unreadable")

        report = reconcile(folder, VIDEO, config)

        assert (folder / "my own clip.mp4").exists()
        assert not report.needs_action

    def test_dry_run_changes_nothing(self, folder, config, bad):
        touch(folder / f"T [{A}].f251.mp4")
        touch(folder / f"T [{B}].mp4")
        archive(folder, A, B)
        bad[f"T [{B}].mp4"] = MediaCheck(False, "unreadable")

        report = inspect_folder(folder, VIDEO, config)

        assert len(report.requeued) == 2
        assert (folder / f"T [{A}].f251.mp4").exists()
        assert archived(folder) == [A, B]
        assert not (folder / "_broken").exists()

    def test_audio_mode_requeues_broken_mp3(self, tmp_path, config, bad):
        folder = tmp_path / "Audio" / "Playlist"
        touch(folder / f"T [{A}].mp3")
        archive(folder, A)
        bad[f"T [{A}].mp3"] = MediaCheck(False, "no audio stream")

        reconcile(folder, AUDIO, config)

        assert (folder / "_broken" / f"T [{A}].mp3").exists()
        assert archived(folder) == []


class TestInterruptions:
    def test_unarchived_but_not_yet_moved(self, folder, config, bad):
        """Interrupted after rewriting archive.txt, before moving the file."""
        touch(folder / f"T [{A}].mp4")
        archive(folder, B)
        bad[f"T [{A}].mp4"] = MediaCheck(False, "unreadable")

        reconcile(folder, VIDEO, config)

        assert (folder / "_broken" / f"T [{A}].mp4").exists()
        assert archived(folder) == [B]

    def test_set_aside_but_still_archived(self, folder, config, bad):
        """A file in _broken/ whose video is still archived gets re-queued."""
        touch(folder / "_broken" / f"T [{A}].mp4")
        archive(folder, A, B)

        report = reconcile(folder, VIDEO, config)

        assert archived(folder) == [B]
        assert report.requeued

    def test_set_aside_twice_keeps_both(self, folder, config, bad):
        touch(folder / "_broken" / f"T [{A}].f251.mp4", "first")
        touch(folder / f"T [{A}].f251.mp4", "second")

        reconcile(folder, VIDEO, config)

        names = sorted(p.name for p in (folder / "_broken").iterdir())
        assert names == [f"T [{A}].f251 (2).mp4", f"T [{A}].f251.mp4"]


class TestSafety:
    def test_many_broken_files_change_nothing(self, folder, config, bad):
        ids = [chr(ord("a") + i) * 11 for i in range(8)]
        for vid in ids:
            touch(folder / f"T [{vid}].mp4")
            bad[f"T [{vid}].mp4"] = MediaCheck(False, "unreadable")
        archive(folder, *ids)

        report = reconcile(folder, VIDEO, config)

        assert report.error and "disk" in report.error
        assert archived(folder) == ids
        assert not (folder / "_broken").exists()

    def test_read_only_folder_changes_nothing(self, folder, config, bad):
        touch(folder / f"T [{A}].f251.mp4")
        archive(folder, A)

        with patch("ytdl.repair.os.access", return_value=False):
            report = reconcile(folder, VIDEO, config)

        assert report.error and "not writable" in report.error
        assert (folder / f"T [{A}].f251.mp4").exists()
        assert archived(folder) == [A]

    def test_without_ffprobe_nothing_is_touched(self, folder, config):
        touch(folder / f"T [{A}].f251.mp4")

        with patch("ytdl.repair.ffprobe_available", return_value=False):
            report = reconcile(folder, VIDEO, config)
            cleaned = cleanup(folder, VIDEO, config)

        assert report.unchecked and not report.needs_action and not cleaned.removed
        assert (folder / f"T [{A}].f251.mp4").exists()

    def test_unverifiable_copy_does_not_allow_deletion(self, folder, config, bad):
        touch(folder / "_broken" / f"T [{A}].f251.mp4")
        touch(folder / f"T [{A}].mp4")
        archive(folder, A)
        bad[f"T [{A}].mp4"] = MediaCheck(None, "Input/output error")

        cleanup(folder, VIDEO, config)

        assert (folder / "_broken" / f"T [{A}].f251.mp4").exists()


class TestCleanup:
    def test_set_aside_file_deleted_once_replacement_verified(self, folder, config, bad):
        touch(folder / "_broken" / f"T [{A}].f251.mp4")
        touch(folder / "_broken" / f"T [{B}].mp4")
        touch(folder / f"T [{A}].mp4")  # re-downloaded, valid
        archive(folder, A)

        report = cleanup(folder, VIDEO, config)

        assert not (folder / "_broken" / f"T [{A}].f251.mp4").exists()
        assert (folder / "_broken" / f"T [{B}].mp4").exists()  # no replacement yet
        assert len(report.removed) == 1

    def test_broken_dir_removed_when_empty(self, folder, config, bad):
        touch(folder / "_broken" / f"T [{A}].f251.mp4")
        touch(folder / f"T [{A}].mp4")
        archive(folder, A)

        cleanup(folder, VIDEO, config)

        assert not (folder / "_broken").exists()

    def test_stale_pieces_of_finished_videos_deleted(self, folder, config, bad):
        stale = touch(folder / "_raw" / f"T [{A}].f137.mp4.part")
        pending = touch(folder / "_raw" / f"T [{B}].f399.mp4.part")
        touch(folder / f"T [{A}].mp4")
        archive(folder, A)

        cleanup(folder, VIDEO, config)

        assert not stale.exists()
        assert pending.exists()  # B is not finished; yt-dlp may resume it

    def test_invalid_replacement_keeps_broken_file(self, folder, config, bad):
        touch(folder / "_broken" / f"T [{A}].f251.mp4")
        touch(folder / f"T [{A}].mp4")
        archive(folder, A)
        bad[f"T [{A}].mp4"] = MediaCheck(False, "no video stream (audio only)")

        cleanup(folder, VIDEO, config)

        assert (folder / "_broken" / f"T [{A}].f251.mp4").exists()

    def test_audio_leftovers_deleted_after_mp3_verified(self, tmp_path, config, bad):
        folder = tmp_path / "Audio" / "Playlist"
        leftover = touch(folder / f"T [{A}].webm.part")
        source = touch(folder / f"T [{B}].webm")
        touch(folder / f"T [{A}].mp3")
        archive(folder, A)

        cleanup(folder, AUDIO, config)

        assert not leftover.exists()
        assert source.exists()  # B not converted yet

    def test_full_repair_cycle(self, folder, config, bad):
        """Reconcile, simulated re-download, cleanup: the folder ends up clean."""
        touch(folder / f"T [{A}].f251.mp4")              # audio-only bug output
        touch(folder / "_raw" / f"T [{A}].f137.mp4.part")  # its half video stream
        touch(folder / f"T [{B}].mp4", "corrupt")
        archive(folder, B)
        bad[f"T [{B}].mp4"] = MediaCheck(False, "unreadable")

        reconcile(folder, VIDEO, config)
        assert archived(folder) == []

        # The user's next run downloads, merges and transcodes both videos.
        bad.clear()
        touch(folder / f"T [{A}].mp4")
        touch(folder / f"T [{B}].mp4")
        archive(folder, A, B)

        cleanup(folder, VIDEO, config)

        assert sorted(p.name for p in folder.iterdir()) == [
            "T [aaaaaaaaaaa].mp4", "T [bbbbbbbbbbb].mp4", "_raw", "archive.txt",
        ]
        assert not any((folder / "_raw").iterdir())
