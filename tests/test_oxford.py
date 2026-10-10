"""Tests for Oxford Podcasts support."""

from __future__ import annotations

import urllib.error
from dataclasses import replace
from unittest.mock import MagicMock, patch

import pytest

from ytdl import oxford
from ytdl.cli import cmd_download
from ytdl.oxford import (
    Episode,
    assign_names,
    download_file,
    download_series,
    is_oxford_url,
    load_feed,
    parse_feed,
)

FEED_URL = "https://podcasts.ox.ac.uk/feeds/d0738fa9-936d-4713-963b-e6b953232877/audio.xml"
SERIES_URL = "https://podcasts.ox.ac.uk/series/strachey-lectures"

FEED_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:podcast="https://podcastindex.org/namespace/1.0">
<channel>
  <title>Strachey Lectures</title>
  <item>
    <title>Advances in Garbled Circuits</title>
    <guid isPermaLink="false">guid-new</guid>
    <pubDate>Mon, 27 Oct 2025 09:46:47 GMT</pubDate>
    <itunes:duration>2892</itunes:duration>
    <enclosure url="https://media.podcasts.ox.ac.uk/a/new.mp3" type="audio/mpeg" length="100"/>
    <podcast:transcript url="https://media.podcasts.ox.ac.uk/a/new-720p.srt"
        type="application/srt" language="en" rel="captions"/>
  </item>
  <item>
    <title>Old: Lecture?</title>
    <guid isPermaLink="false">guid-old</guid>
    <pubDate>Mon, 01 Sep 2025 09:00:00 GMT</pubDate>
    <itunes:duration>00:10:05</itunes:duration>
    <enclosure url="https://media.podcasts.ox.ac.uk/a/old.mp3" type="audio/mpeg" length="50"/>
  </item>
  <item>
    <title>No audio here</title>
    <guid>guid-none</guid>
  </item>
</channel>
</rss>
"""

PAGE_HTML = (
    b'<html><a href="/feeds/d0738fa9-936d-4713-963b-e6b953232877/audio.xml">Audio</a>'
    b'<a href="/feeds/d0738fa9-936d-4713-963b-e6b953232877/video.xml">Video</a></html>'
)


def _response(body: bytes, length: int | None = None) -> MagicMock:
    """Build a urlopen() context-manager mock that streams body."""
    response = MagicMock()
    chunks = [body, b""]
    response.read.side_effect = lambda *a: chunks.pop(0) if chunks else b""
    response.headers = {"Content-Length": str(len(body) if length is None else length)}
    response.__enter__ = MagicMock(return_value=response)
    response.__exit__ = MagicMock(return_value=False)
    return response


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "err", {}, None)


@pytest.fixture(autouse=True)
def no_sleep():
    with patch("ytdl.oxford.time.sleep"):
        yield


class TestIsOxfordUrl:
    def test_series_and_feed(self):
        assert is_oxford_url(SERIES_URL)
        assert is_oxford_url(FEED_URL)

    @pytest.mark.parametrize("url", [
        "https://www.youtube.com/watch?v=abc",
        "https://podcasts.ox.ac.uk/",
        "https://podcasts.ox.ac.uk/some-episode",
        "https://evil.example.com/series/x?u=podcasts.ox.ac.uk",
        "ftp://podcasts.ox.ac.uk/series/x",
    ])
    def test_rejects_others(self, url):
        assert not is_oxford_url(url)


class TestLoadFeed:
    def test_discovers_feed_from_series_page(self):
        with patch("ytdl.oxford._fetch", side_effect=[PAGE_HTML, FEED_XML]) as fetch:
            assert load_feed(SERIES_URL) == FEED_XML
        assert fetch.call_args_list[1].args[0] == FEED_URL

    def test_video_feed_is_rewritten_to_audio(self):
        with patch("ytdl.oxford._fetch", return_value=FEED_XML) as fetch:
            load_feed(FEED_URL.replace("audio.xml", "video.xml"))
        fetch.assert_called_once_with(FEED_URL)

    def test_page_without_feed_raises(self):
        with patch("ytdl.oxford._fetch", return_value=b"<html></html>"):
            with pytest.raises(ValueError, match="No audio feed"):
                load_feed(SERIES_URL)


class TestParseFeed:
    def test_parses_episodes(self):
        series, episodes = parse_feed(FEED_XML)
        assert series == "Strachey Lectures"
        assert [e.guid for e in episodes] == ["guid-new", "guid-old"]  # item without enclosure skipped
        new, old = episodes
        assert new.seconds == 2892
        assert old.seconds == 605  # HH:MM:SS
        assert new.captions_url.endswith("new-720p.srt")
        assert old.captions_url is None
        assert new.size == 100
        assert new.date.year == 2025

    def test_guid_falls_back_to_enclosure_url(self):
        xml = (b'<rss><channel><title>T</title><item><title>x</title>'
               b'<enclosure url="http://h/a.mp3"/></item></channel></rss>')
        _, episodes = parse_feed(xml)
        assert episodes[0].guid == "http://h/a.mp3"
        assert episodes[0].date is None

    def test_invalid_xml_raises(self):
        with pytest.raises(ValueError):
            parse_feed(b"not xml")

    def test_not_rss_raises(self):
        with pytest.raises(ValueError):
            parse_feed(b"<html/>")


class TestAssignNames:
    def test_date_title_and_extension(self):
        _, episodes = parse_feed(FEED_XML)
        assign_names(episodes)
        assert episodes[0].filename == "2025-10-27 Advances in Garbled Circuits.mp3"
        assert episodes[1].filename == "2025-09-01 Old Lecture.mp3"  # illegal chars removed

    def test_duplicates_get_stable_suffix_oldest_first(self):
        a = Episode("a", "Same", "http://h/a.mp3", date=None)
        b = Episode("b", "Same", "http://h/b.mp3", date=None)
        assign_names([a, b])
        assert {a.stem, b.stem} == {"undated Same", "undated Same (2)"}

    def test_extension_from_media_type(self):
        ep = Episode("a", "T", "http://h/download?id=1", media_type="audio/x-m4a")
        assign_names([ep])
        assert ep.ext == ".m4a"


class TestDownloadFile:
    def test_success_writes_file_and_removes_part(self, tmp_path):
        dest = tmp_path / "a.mp3"
        with patch("ytdl.oxford.urlopen", return_value=_response(b"audio")):
            assert download_file("http://h/a.mp3", dest) is None
        assert dest.read_bytes() == b"audio"
        assert not (tmp_path / "a.mp3.part").exists()

    def test_404_is_not_retried(self, tmp_path):
        with patch("ytdl.oxford.urlopen", side_effect=_http_error(404)) as urlopen:
            assert download_file("http://h/a.mp3", tmp_path / "a.mp3", retries=3) == "HTTP 404"
        assert urlopen.call_count == 1

    def test_503_is_retried(self, tmp_path):
        dest = tmp_path / "a.mp3"
        with patch("ytdl.oxford.urlopen",
                   side_effect=[_http_error(503), _response(b"ok")]) as urlopen:
            assert download_file("http://h/a.mp3", dest, retries=3) is None
        assert urlopen.call_count == 2
        assert dest.read_bytes() == b"ok"

    def test_truncated_download_fails_and_cleans_part(self, tmp_path):
        dest = tmp_path / "a.mp3"
        with patch("ytdl.oxford.urlopen", return_value=_response(b"abc", length=10)):
            error = download_file("http://h/a.mp3", dest, retries=1)
        assert "incomplete" in error
        assert not dest.exists()
        assert not (tmp_path / "a.mp3.part").exists()


class TestDownloadSeries:
    @pytest.fixture
    def fake_network(self):
        """Serve the feed plus audio/caption bodies keyed by URL suffix."""
        def fake_download(url, dest, retries=3, timeout=60):
            dest.write_bytes(b"data")
            return None
        with patch("ytdl.oxford.load_feed", return_value=FEED_XML), \
             patch("ytdl.oxford.download_file", side_effect=fake_download) as dl:
            yield dl

    def test_downloads_into_audio_series_folder(self, config, fake_network):
        series, out, result = download_series(SERIES_URL, config)
        assert series == "Strachey Lectures"
        assert out == config.base_dir / "Audio" / "Strachey Lectures"
        assert len(result.succeeded) == 2
        assert (out / "2025-10-27 Advances in Garbled Circuits.mp3").exists()
        archive = (out / "archive.txt").read_text().splitlines()
        assert sorted(archive) == ["oxford guid-new", "oxford guid-old"]
        assert not list(out.glob("*.srt"))  # captions are opt-in

    def test_rerun_skips_archived(self, config, fake_network):
        download_series(SERIES_URL, config)
        fake_network.reset_mock()
        _, _, result = download_series(SERIES_URL, config)
        assert result.succeeded == []
        assert len(result.skipped) == 2
        fake_network.assert_not_called()

    def test_captions_when_enabled(self, config, fake_network):
        _, out, _ = download_series(SERIES_URL, replace(config, oxford_captions=True))
        assert (out / "2025-10-27 Advances in Garbled Circuits.srt").exists()
        assert len(list(out.glob("*.srt"))) == 1  # only the episode that has captions

    def test_failure_is_reported_and_not_archived(self, config):
        with patch("ytdl.oxford.load_feed", return_value=FEED_XML), \
             patch("ytdl.oxford.download_file", return_value="HTTP 404"):
            _, out, result = download_series(SERIES_URL, config)
        assert len(result.failed) == 2
        assert result.failed[0][1] == "HTTP 404"
        assert not (out / "archive.txt").exists()

    def test_network_error_becomes_value_error(self, config):
        with patch("ytdl.oxford.load_feed", side_effect=OSError("boom")):
            with pytest.raises(ValueError, match="Could not read the feed"):
                download_series(SERIES_URL, config)

    def test_empty_feed_raises(self, config):
        xml = b"<rss><channel><title>T</title></channel></rss>"
        with patch("ytdl.oxford.load_feed", return_value=xml):
            with pytest.raises(ValueError, match="no audio episodes"):
                download_series(SERIES_URL, config)


class TestCliDispatch:
    def test_download_routes_oxford_url_without_youtube_checks(self, config, tmp_path):
        args = MagicMock(url=SERIES_URL, mode="video", type="auto")
        with patch("ytdl.cli.download_series") as ds, \
             patch("ytdl.cli.validate_url") as validate, \
             patch("ytdl.cli.VideoDownloader") as ydl:
            from ytdl.downloader import DownloadResult
            ds.return_value = ("Strachey Lectures", tmp_path, DownloadResult(succeeded=["x"]))
            assert cmd_download(args, config) == 0
        validate.assert_not_called()
        ydl.assert_not_called()

    def test_failed_episode_gives_nonzero_exit(self, config, tmp_path):
        from ytdl.downloader import DownloadResult
        args = MagicMock(url=SERIES_URL, mode="audio", type="auto")
        with patch("ytdl.cli.download_series",
                   return_value=("S", tmp_path, DownloadResult(failed=[("x", "HTTP 404")]))):
            assert cmd_download(args, config) == 1

    def test_feed_error_gives_nonzero_exit(self, config):
        args = MagicMock(url=SERIES_URL, mode="audio", type="auto")
        with patch("ytdl.cli.download_series", side_effect=ValueError("bad feed")):
            assert cmd_download(args, config) == 1
