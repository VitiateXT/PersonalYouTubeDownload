"""Core download logic wrapping yt-dlp."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from yt_dlp import YoutubeDL

from ytdl.config import Config
from ytdl.utils import (
    ContentType,
    SourceType,
    get_archive_path,
    get_output_dir,
    get_raw_dir,
)

logger = logging.getLogger(__name__)


class DownloadMode(Enum):
    """Download modes supported by the downloader."""
    VIDEO = "video"
    AUDIO = "audio"


@dataclass
class DownloadResult:
    """Result of a download operation.

    Attributes:
        succeeded: Titles that were downloaded successfully.
        failed: Tuples of (title_or_id, reason) for failed entries.
        skipped: Titles skipped because they were already archived.
    """
    succeeded: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)  # (id/title, reason)
    skipped: list[str] = field(default_factory=list)  # already in archive

    @property
    def total(self) -> int:
        """Return total number of processed entries.

        Returns:
            Combined count of succeeded, failed, and skipped items.
        """
        return len(self.succeeded) + len(self.failed) + len(self.skipped)


class _YDLLogger:
    """Custom logger for yt-dlp that captures messages."""

    def __init__(self) -> None:
        """Initialize in-memory warning/error capture buffers."""
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def debug(self, msg: str) -> None:
        """Handle yt-dlp debug messages.

        Args:
            msg: Message emitted by yt-dlp.
        """
        if msg.startswith("[debug]"):
            logger.debug(msg)
        else:
            logger.info(msg)

    def info(self, msg: str) -> None:
        """Handle yt-dlp info messages.

        Args:
            msg: Message emitted by yt-dlp.
        """
        logger.info(msg)

    def warning(self, msg: str) -> None:
        """Handle yt-dlp warning messages.

        Args:
            msg: Message emitted by yt-dlp.
        """
        self.warnings.append(msg)
        logger.warning(msg)

    def error(self, msg: str) -> None:
        """Handle yt-dlp error messages.

        Args:
            msg: Message emitted by yt-dlp.
        """
        self.errors.append(msg)
        logger.error(msg)


class VideoDownloader:
    """Downloads YouTube content using yt-dlp."""

    def __init__(self, config: Config) -> None:
        """Create a downloader instance.

        Args:
            config: Resolved application configuration.
        """
        self.config = config

    def _build_common_opts(self) -> dict:
        """Build yt-dlp options common to all download modes.

        Returns:
            Dictionary of yt-dlp options.
        """
        return {
            "sleep_interval": self.config.sleep_interval,
            "max_sleep_interval": self.config.max_sleep_interval,
            "sleep_interval_requests": self.config.sleep_requests,
            "retries": self.config.retries,
            "fragment_retries": self.config.fragment_retries,
            "ignoreerrors": True,
            "no_warnings": False,
            "skip_unavailable_fragments": True,
        }

    def _build_video_opts(self, output_dir: Path, archive_path: Path) -> dict:
        """Build yt-dlp options for video+audio download.

        Args:
            output_dir: Target output directory.
            archive_path: Per-folder archive.txt path.

        Returns:
            Dictionary of yt-dlp options for video mode.
        """
        raw_dir = get_raw_dir(output_dir)
        opts = self._build_common_opts()
        opts.update({
            "format": f"bv[height<={self.config.max_resolution}]+ba/b[height<={self.config.max_resolution}]/bv+ba/b",
            "format_sort": ["lang", f"res:{self.config.max_resolution}"],
            "merge_output_format": self.config.video_format,
            "outtmpl": str(raw_dir / self.config.video_file_template),
            "download_archive": str(archive_path),
        })
        return opts

    def _build_audio_opts(self, output_dir: Path, archive_path: Path) -> dict:
        """Build yt-dlp options for audio-only download.

        Args:
            output_dir: Target output directory.
            archive_path: Per-folder archive.txt path.

        Returns:
            Dictionary of yt-dlp options for audio mode.
        """
        opts = self._build_common_opts()
        opts.update({
            "format": "ba/b",
            "format_sort": ["lang"],
            "outtmpl": str(output_dir / self.config.audio_file_template),
            "download_archive": str(archive_path),
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": self.config.audio_format,
                    "preferredquality": self.config.audio_bitrate,
                }
            ],
        })
        return opts

    def download(
        self,
        url: str,
        mode: DownloadMode,
        source_type: SourceType,
        source_name: str | None = None,
    ) -> DownloadResult:
        """Download content from a YouTube URL.

        Args:
            url: YouTube URL (video, playlist, or channel).
            mode: VIDEO or AUDIO.
            source_type: CHANNEL, PLAYLIST, or SINGLE.
            source_name: Name for the channel/playlist folder.

        Returns:
            DownloadResult with succeeded/failed/skipped lists.
        """
        content_type = ContentType.VIDEO if mode == DownloadMode.VIDEO else ContentType.AUDIO
        out_dir = get_output_dir(
            self.config.base_dir, content_type, source_type, source_name
        )
        archive_path = get_archive_path(out_dir)

        # Load existing archive to detect skipped items
        existing_archive = set()
        if archive_path.exists():
            existing_archive = {
                line.strip() for line in archive_path.read_text().splitlines() if line.strip()
            }

        ydl_logger = _YDLLogger()

        if mode == DownloadMode.VIDEO:
            opts = self._build_video_opts(out_dir, archive_path)
        else:
            opts = self._build_audio_opts(out_dir, archive_path)

        opts["logger"] = ydl_logger

        result = DownloadResult()

        # Hook logs transfer progress without changing behavior.

        def progress_hook(d: dict) -> None:
            """Emit concise progress logs for yt-dlp hook events.

            Args:
                d: Hook event dictionary from yt-dlp.
            """
            if d["status"] == "downloading":
                filename = d.get("filename", "")
                pct = d.get("_percent_str", "?%")
                speed = d.get("_speed_str", "?")
                logger.info(f"  Downloading {Path(filename).name}: {pct} at {speed}")
            elif d["status"] == "finished":
                filename = d.get("filename", "unknown")
                logger.info(f"  Finished downloading: {Path(filename).name}")

        opts["progress_hooks"] = [progress_hook]

        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as e:
            logger.error(f"Fatal download error: {e}")
            result.failed.append((url, str(e)))
            return result

        if info is None:
            result.failed.append((url, "No info returned"))
            return result

        # Process results
        entries = info.get("entries", [info]) if "entries" in info else [info]
        for entry in entries:
            if entry is None:
                result.failed.append(("Unknown", "Entry was None (possibly unavailable)"))
                continue

            video_id = entry.get("id", "unknown")
            title = entry.get("title", "unknown")
            archive_id = f"youtube {video_id}"

            if archive_id in existing_archive:
                result.skipped.append(title)
            elif entry.get("requested_downloads") or entry.get("filepath"):
                result.succeeded.append(title)
            else:
                # Check if it was an error
                if ydl_logger.errors:
                    result.failed.append((title, ydl_logger.errors[-1]))
                else:
                    result.succeeded.append(title)

        logger.info(
            f"Download complete: {len(result.succeeded)} succeeded, "
            f"{len(result.failed)} failed, {len(result.skipped)} skipped"
        )

        return result

    def download_single(
        self,
        url: str,
        mode: DownloadMode,
    ) -> DownloadResult:
        """Download a single video or audio file.

        Args:
            url: YouTube video URL.
            mode: VIDEO or AUDIO download mode.

        Returns:
            DownloadResult.
        """
        return self.download(
            url=url,
            mode=mode,
            source_type=SourceType.SINGLE,
        )

    def download_batch(
        self,
        url: str,
        mode: DownloadMode,
        source_type: SourceType,
        source_name: str,
    ) -> DownloadResult:
        """Download a playlist or channel.

        Args:
            url: YouTube playlist or channel URL.
            mode: VIDEO or AUDIO download mode.
            source_type: CHANNEL or PLAYLIST.
            source_name: Name for the output folder.

        Returns:
            DownloadResult.
        """
        return self.download(
            url=url,
            mode=mode,
            source_type=source_type,
            source_name=source_name,
        )
