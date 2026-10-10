"""Download audio episodes (and optional captions) from University of Oxford Podcasts."""

from __future__ import annotations

import http.client
import logging
import re
import time
import urllib.error
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
from urllib.request import Request, urlopen

from ytdl.config import Config
from ytdl.downloader import DownloadResult
from ytdl.tracker import load_archive
from ytdl.utils import ContentType, SourceType, get_archive_path, get_output_dir

logger = logging.getLogger(__name__)

OXFORD_HOST = "podcasts.ox.ac.uk"
ARCHIVE_PREFIX = "oxford"

_HEADERS = {"User-Agent": "ytdl-oxford/1.0 (personal offline listening)"}
_NS = {
    "podcast": "https://podcastindex.org/namespace/1.0",
    "itunes": "http://www.itunes.com/dtds/podcast-1.0.dtd",
}
_FEED_PATH = re.compile(r"/feeds/[0-9a-fA-F-]{36}/audio\.xml")
_AUDIO_EXT = {".mp3", ".m4a", ".mp4", ".ogg"}
_EXT_BY_TYPE = {
    "audio/mpeg": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/ogg": ".ogg",
}
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)
_NETWORK_ERRORS = (OSError, http.client.HTTPException)


@dataclass
class Episode:
    """One podcast episode parsed from the RSS feed.

    Attributes:
        guid: Stable feed identifier (falls back to the enclosure URL).
        title: Episode title.
        url: Audio enclosure URL.
        media_type: MIME type of the enclosure.
        size: Enclosure size in bytes (0 if unknown).
        captions_url: URL of the .srt captions, if the feed offers them.
        date: Publication date, if present and parseable.
        seconds: Duration in seconds (0 if unknown).
        stem: File name without extension, set by `assign_names`.
        ext: File extension including the dot, set by `assign_names`.
    """
    guid: str
    title: str
    url: str
    media_type: str = ""
    size: int = 0
    captions_url: str | None = None
    date: datetime | None = None
    seconds: int = 0
    stem: str = ""
    ext: str = ".mp3"

    @property
    def filename(self) -> str:
        """Return the audio file name."""
        return self.stem + self.ext

    @property
    def archive_entry(self) -> str:
        """Return the archive.txt line identifying this episode."""
        return f"{ARCHIVE_PREFIX} {' '.join(self.guid.split())}"


def is_oxford_url(url: str) -> bool:
    """Check whether a URL points to an Oxford Podcasts series page or feed.

    Args:
        url: URL to check.

    Returns:
        True for `podcasts.ox.ac.uk/series/...` and `podcasts.ox.ac.uk/feeds/...` URLs.
    """
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or parsed.hostname != OXFORD_HOST:
        return False
    return parsed.path.startswith(("/series/", "/feeds/"))


def _safe_url(url: str) -> str:
    """Escape spaces/non-ASCII characters but leave existing %xx escapes alone."""
    return quote(url, safe=":/?&=%+~@!$'()*,;#")


def _fetch(url: str, timeout: int = 30) -> bytes:
    """Fetch a URL and return the response body."""
    with urlopen(Request(_safe_url(url), headers=_HEADERS), timeout=timeout) as response:
        return response.read()


def load_feed(url: str) -> bytes:
    """Fetch the audio RSS feed for a series page or feed URL.

    Args:
        url: Series page URL or `audio.xml`/`video.xml` feed URL.

    Returns:
        Raw feed XML.

    Raises:
        ValueError: If no audio feed link is found on the page.
        OSError: On network failures.
    """
    url = url.replace("/video.xml", "/audio.xml")
    if urlparse(url).path.endswith(".xml"):
        return _fetch(url)

    page = _fetch(url).decode("utf-8", "replace")
    match = _FEED_PATH.search(page)
    if not match:
        raise ValueError(f"No audio feed link found on page: {url}")
    feed_url = urljoin(url, match.group(0))
    logger.debug(f"Feed: {feed_url}")
    return _fetch(feed_url)


def _parse_seconds(text: str | None) -> int:
    """Parse itunes:duration, which is either plain seconds or HH:MM:SS."""
    total = 0
    try:
        for part in (text or "").split(":"):
            total = total * 60 + int(float(part))
    except ValueError:
        return 0
    return total


def parse_feed(xml_bytes: bytes) -> tuple[str, list[Episode]]:
    """Parse an Oxford Podcasts RSS feed.

    Args:
        xml_bytes: Raw feed XML.

    Returns:
        Tuple of (series title, episodes). Items without an audio enclosure are skipped.

    Raises:
        ValueError: If the XML is not an RSS feed.
    """
    try:
        channel = ET.fromstring(xml_bytes).find("channel")
    except ET.ParseError as e:
        raise ValueError(f"Feed is not valid XML: {e}") from e
    if channel is None:
        raise ValueError("That does not look like an RSS feed.")

    series = (channel.findtext("title") or "").strip() or "Oxford Podcast"
    episodes: list[Episode] = []
    for item in channel.findall("item"):
        enclosure = item.find("enclosure")
        if enclosure is None or not enclosure.get("url"):
            continue

        captions = next(
            (
                t.get("url")
                for t in item.findall("podcast:transcript", _NS)
                if (t.get("url") or "").lower().endswith(".srt")
            ),
            None,
        )

        try:
            date = parsedate_to_datetime(item.findtext("pubDate"))
            if date.tzinfo is None:
                date = date.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            date = None

        size = enclosure.get("length", "")
        url = enclosure.get("url")
        episodes.append(Episode(
            guid=(item.findtext("guid") or "").strip() or url,
            title=(item.findtext("title") or "").strip(),
            url=url,
            media_type=enclosure.get("type", ""),
            size=int(size) if size.isdigit() else 0,
            captions_url=captions,
            date=date,
            seconds=_parse_seconds(item.findtext("itunes:duration", namespaces=_NS)),
        ))
    return series, episodes


def assign_names(episodes: list[Episode]) -> None:
    """Assign file names like '2025-10-27 Advances in Garbled Circuits.mp3'.

    Names are assigned oldest-first so duplicate titles always get the same suffix.

    Args:
        episodes: Episodes to name; `stem` and `ext` are set in place.
    """
    used: set[str] = set()
    for ep in sorted(episodes, key=lambda e: e.date or _EPOCH):
        title = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", ep.title)
        title = re.sub(r"\s+", " ", title).strip(" .")[:100] or "episode"
        stamp = ep.date.strftime("%Y-%m-%d") if ep.date else "undated"

        ext = Path(urlparse(ep.url).path).suffix.lower()
        if ext not in _AUDIO_EXT:
            ext = _EXT_BY_TYPE.get(ep.media_type, ".mp3")

        base = name = f"{stamp} {title}"
        n = 2
        while name in used:
            name = f"{base} ({n})"
            n += 1
        used.add(name)
        ep.stem, ep.ext = name, ext


def download_file(url: str, dest: Path, retries: int = 3, timeout: int = 60) -> str | None:
    """Download a URL to dest through a .part file.

    Retries network errors and HTTP 5xx/429. Other HTTP errors (e.g. 404) are
    permanent and fail immediately.

    Args:
        url: Source URL.
        dest: Final file path.
        retries: Maximum number of attempts.
        timeout: Socket timeout in seconds.

    Returns:
        None on success, otherwise a short failure reason.
    """
    part = dest.with_name(dest.name + ".part")
    reason = "unknown error"
    for attempt in range(1, max(retries, 1) + 1):
        try:
            request = Request(_safe_url(url), headers=_HEADERS)
            with urlopen(request, timeout=timeout) as response, open(part, "wb") as handle:
                total = int(response.headers.get("Content-Length") or 0)
                done = 0
                while chunk := response.read(1 << 16):
                    handle.write(chunk)
                    done += len(chunk)
            if total and done < total:
                raise OSError(f"incomplete download ({done} of {total} bytes)")
            part.replace(dest)
            return None
        except urllib.error.HTTPError as e:
            reason = f"HTTP {e.code}"
            if e.code < 500 and e.code != 429:
                break  # permanent, retrying will not help
            logger.warning(f"  Attempt {attempt}/{retries} failed: {reason}")
        except _NETWORK_ERRORS as e:
            reason = str(e) or type(e).__name__
            logger.warning(f"  Attempt {attempt}/{retries} failed: {reason}")
        if attempt < retries:
            time.sleep(min(2 * attempt, 30))

    part.unlink(missing_ok=True)
    return reason


def download_series(url: str, config: Config) -> tuple[str, Path, DownloadResult]:
    """Download all new episodes of an Oxford Podcasts series.

    Episodes already listed in the folder's archive.txt are skipped, so reruns
    only fetch new episodes.

    Args:
        url: Series page URL or audio feed URL.
        config: Application configuration.

    Returns:
        Tuple of (series title, output directory, DownloadResult).

    Raises:
        ValueError: If the feed cannot be read or contains no episodes.
    """
    try:
        series, episodes = parse_feed(load_feed(url))
    except _NETWORK_ERRORS as e:
        raise ValueError(f"Could not read the feed: {e}") from e
    if not episodes:
        raise ValueError("The feed contains no audio episodes.")

    assign_names(episodes)
    episodes.sort(key=lambda e: e.date or _EPOCH, reverse=True)

    output_dir = get_output_dir(config.base_dir, ContentType.AUDIO, SourceType.PLAYLIST, series)
    archive_path = get_archive_path(output_dir)
    archived = load_archive(output_dir)
    logger.info(f"Source: {series} ({len(episodes)} episodes) -> {output_dir}")

    result = DownloadResult()
    try:
        for i, ep in enumerate(episodes, 1):
            label = f"[{i}/{len(episodes)}] {ep.filename}"
            target = output_dir / ep.filename

            if ep.archive_entry in archived:
                result.skipped.append(ep.title)
            else:
                logger.info(f"Downloading {label}")
                error = download_file(ep.url, target, retries=config.retries)
                if error is not None:
                    logger.error(f"  Failed: {ep.title} ({error})")
                    result.failed.append((ep.title, error))
                    continue
                with open(archive_path, "a") as f:
                    f.write(ep.archive_entry + "\n")
                result.succeeded.append(ep.title)
                time.sleep(config.oxford_delay)

            if config.oxford_captions and ep.captions_url and target.exists():
                captions = output_dir / (ep.stem + ".srt")
                if not captions.exists():
                    error = download_file(ep.captions_url, captions, retries=config.retries)
                    if error is not None:
                        logger.warning(f"  Captions unavailable for {ep.title} ({error})")
    except KeyboardInterrupt:
        logger.warning("Interrupted. Run the same command again to continue.")
        raise

    return series, output_dir, result
