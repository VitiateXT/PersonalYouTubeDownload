"""Incremental update logic for channels and playlists."""

from __future__ import annotations

import logging
from pathlib import Path

from ytdl.config import Config
from ytdl.downloader import DownloadMode, DownloadResult, VideoDownloader
from ytdl.tracker import (
    format_report,
    generate_report,
    get_archived_video_ids,
    get_missing_videos,
    save_report,
)
from ytdl.transcoder import batch_transcode
from ytdl.utils import ContentType, SourceType, get_output_dir
from ytdl.validator import URLType, extract_metadata

logger = logging.getLogger(__name__)


def check_for_updates(
    url: str,
    output_dir: Path,
) -> tuple[list[str], list[str]]:
    """Check which videos from a channel/playlist are not yet downloaded.

    Args:
        url: YouTube channel or playlist URL.
        output_dir: The local directory for this channel/playlist.

    Returns:
        Tuple of (missing_ids, all_remote_ids).
    """
    logger.info(f"Checking for updates: {url}")

    metadata = extract_metadata(url)
    remote_ids = metadata.video_ids
    local_ids = get_archived_video_ids(output_dir)

    missing = get_missing_videos(remote_ids, local_ids)

    logger.info(
        f"Remote: {len(remote_ids)} videos, "
        f"Local: {len(local_ids)} archived, "
        f"Missing: {len(missing)} new"
    )

    return missing, remote_ids


def update(
    url: str,
    mode: DownloadMode,
    config: Config,
) -> DownloadResult:
    """Incrementally update a channel or playlist directory.

    Downloads only videos that are not already in the local archive.
    Never deletes existing files, even if they've been removed from YouTube.

    Args:
        url: YouTube channel or playlist URL.
        mode: VIDEO or AUDIO download mode.
        config: Application configuration.

    Returns:
        DownloadResult for the update operation.
    """
    metadata = extract_metadata(url)
    source_name = metadata.title

    if metadata.url_type == URLType.CHANNEL:
        source_type = SourceType.CHANNEL
    elif metadata.url_type == URLType.PLAYLIST:
        source_type = SourceType.PLAYLIST
    else:
        raise ValueError("Update is only supported for channels and playlists.")

    content_type = ContentType.VIDEO if mode == DownloadMode.VIDEO else ContentType.AUDIO
    output_dir = get_output_dir(config.base_dir, content_type, source_type, source_name)

    # Check what's missing
    missing_ids, all_remote_ids = check_for_updates(url, output_dir)

    result: DownloadResult
    if not missing_ids:
        logger.info(f"No new content to download for '{source_name}'.")
        result = DownloadResult(
            skipped=[f"All {len(all_remote_ids)} videos already downloaded"]
        )
    else:
        logger.info(f"Found {len(missing_ids)} new items to download for '{source_name}'.")

        # yt-dlp archive handling ensures existing items are skipped safely.
        downloader = VideoDownloader(config)
        result = downloader.download_batch(
            url=url,
            mode=mode,
            source_type=source_type,
            source_name=source_name,
        )

    # Transcode any pending videos in _raw/ (includes leftovers from an
    # interrupted prior run, even when this run downloaded nothing new).
    if mode == DownloadMode.VIDEO:
        logger.info("Transcoding pending videos...")
        t_ok, t_fail = batch_transcode(output_dir, config)
        logger.info(f"Transcode: {t_ok} succeeded, {t_fail} failed")

    # Generate and save report
    report = generate_report(result, source_name, url)
    report_text = format_report(report)
    print(report_text)
    save_report(report, output_dir)

    return result
