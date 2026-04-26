"""Tests for the tracker module."""

from pathlib import Path

import pytest

from ytdl.downloader import DownloadResult
from ytdl.tracker import (
    DownloadReport,
    format_report,
    generate_report,
    get_archived_video_ids,
    get_missing_videos,
    load_archive,
    save_report,
)


class TestGenerateReport:
    def test_generates_report_from_result(self):
        result = DownloadResult(
            succeeded=["Video A", "Video B"],
            failed=[("Video C", "HTTP 403")],
            skipped=["Video D"],
        )
        report = generate_report(result, "Test Playlist", "https://youtube.com/playlist?list=test")

        assert report.source_name == "Test Playlist"
        assert report.succeeded == 2
        assert report.failed == 1
        assert report.skipped == 1
        assert report.total == 4

    def test_empty_result(self):
        result = DownloadResult()
        report = generate_report(result, "Empty", "https://youtube.com")
        assert report.total == 0


class TestFormatReport:
    def test_contains_key_info(self):
        report = DownloadReport(
            source_name="My Playlist",
            source_url="https://youtube.com/playlist?list=test",
            timestamp="2024-01-01T00:00:00+00:00",
            total=3,
            succeeded=2,
            failed=1,
            skipped=0,
            failed_details=[("Bad Video", "HTTP 403 Forbidden")],
            succeeded_titles=["Good Video 1", "Good Video 2"],
        )
        text = format_report(report)

        assert "My Playlist" in text
        assert "Succeeded: 2" in text
        assert "Failed:" in text and "1" in text
        assert "Good Video 1" in text
        assert "Bad Video" in text
        assert "HTTP 403" in text

    def test_skipped_section(self):
        report = DownloadReport(
            source_name="Test",
            source_url="https://youtube.com",
            timestamp="2024-01-01T00:00:00+00:00",
            total=1,
            succeeded=0,
            failed=0,
            skipped=1,
            skipped_titles=["Already Downloaded"],
        )
        text = format_report(report)
        assert "Already Downloaded" in text
        assert "already downloaded" in text.lower()


class TestSaveReport:
    def test_saves_report_file(self, tmp_path):
        result = DownloadResult(succeeded=["Video A"])
        report = generate_report(result, "Test", "https://youtube.com")

        path = save_report(report, tmp_path)
        assert path.exists()
        assert path.name == "download_report.txt"
        content = path.read_text()
        assert "Test" in content

    def test_appends_on_second_save(self, tmp_path):
        result1 = DownloadResult(succeeded=["Video A"])
        report1 = generate_report(result1, "First Run", "https://youtube.com")
        save_report(report1, tmp_path)

        result2 = DownloadResult(succeeded=["Video B"])
        report2 = generate_report(result2, "Second Run", "https://youtube.com")
        save_report(report2, tmp_path)

        content = (tmp_path / "download_report.txt").read_text()
        assert "First Run" in content
        assert "Second Run" in content


class TestLoadArchive:
    def test_empty_when_no_file(self, tmp_path):
        assert load_archive(tmp_path) == set()

    def test_loads_archive_entries(self, tmp_path):
        archive = tmp_path / "archive.txt"
        archive.write_text("youtube dQw4w9WgXcQ\nyoutube abcdefg\n")

        result = load_archive(tmp_path)
        assert "youtube dQw4w9WgXcQ" in result
        assert "youtube abcdefg" in result
        assert len(result) == 2

    def test_skips_empty_lines(self, tmp_path):
        archive = tmp_path / "archive.txt"
        archive.write_text("youtube vid1\n\n\nyoutube vid2\n")

        result = load_archive(tmp_path)
        assert len(result) == 2


class TestGetArchivedVideoIds:
    def test_extracts_ids(self, tmp_path):
        archive = tmp_path / "archive.txt"
        archive.write_text("youtube vid1\nyoutube vid2\n")

        ids = get_archived_video_ids(tmp_path)
        assert ids == {"vid1", "vid2"}

    def test_empty_archive(self, tmp_path):
        assert get_archived_video_ids(tmp_path) == set()


class TestGetMissingVideos:
    def test_finds_missing(self):
        expected = ["vid1", "vid2", "vid3", "vid4"]
        archived = {"vid1", "vid3"}

        missing = get_missing_videos(expected, archived)
        assert missing == ["vid2", "vid4"]

    def test_all_archived(self):
        expected = ["vid1", "vid2"]
        archived = {"vid1", "vid2"}

        assert get_missing_videos(expected, archived) == []

    def test_none_archived(self):
        expected = ["vid1", "vid2"]
        archived: set[str] = set()

        assert get_missing_videos(expected, archived) == ["vid1", "vid2"]
