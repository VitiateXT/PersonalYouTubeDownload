"""CLI entry point for the YouTube Downloader."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from ytdl.config import Config, load_config
from ytdl.downloader import DownloadMode, VideoDownloader
from ytdl.tracker import format_report, generate_report, save_report
from ytdl.transcoder import batch_transcode
from ytdl.updater import update
from ytdl.utils import ContentType, SourceType, get_output_dir
from ytdl.validator import URLType, detect_url_type, extract_metadata, validate_url

logger = logging.getLogger("ytdl")


def setup_logging(verbose: bool = False) -> None:
    """Configure application logging.

    Args:
        verbose: If True, enable DEBUG logs.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def cmd_download(args: argparse.Namespace, config: Config) -> int:
    """Handle the `download` subcommand.

    Args:
        args: Parsed CLI arguments.
        config: Resolved application configuration.

    Returns:
        Process exit code.
    """
    url = args.url
    mode = DownloadMode(args.mode)

    if not validate_url(url):
        logger.error(f"Invalid YouTube URL: {url}")
        return 1

    # Detect URL type unless user forces a specific type.
    if args.type == "auto":
        try:
            url_type = detect_url_type(url)
        except ValueError as e:
            logger.error(str(e))
            return 1
    else:
        url_type = URLType(args.type)

    # Reject mismatches early so wrapper scripts fail fast and clearly.
    try:
        detected = detect_url_type(url)
        if args.type != "auto" and detected != url_type:
            logger.error(
                f"URL appears to be a {detected.value}, "
                f"but --type={args.type} was specified."
            )
            return 1
    except ValueError:
        pass  # Let it proceed; yt-dlp will handle invalid URLs

    logger.info(f"Downloading {url_type.value}: {url}")
    logger.info(f"Mode: {mode.value}")

    # Metadata title drives channel/playlist folder naming.
    try:
        metadata = extract_metadata(url)
    except ValueError as e:
        logger.error(f"Failed to get metadata: {e}")
        return 1

    source_name = metadata.title

    if url_type == URLType.VIDEO:
        source_type = SourceType.SINGLE
    elif url_type == URLType.PLAYLIST:
        source_type = SourceType.PLAYLIST
    else:
        source_type = SourceType.CHANNEL

    logger.info(f"Source: {source_name} ({metadata.video_count} videos)")

    # Execute download through yt-dlp wrapper.
    downloader = VideoDownloader(config)
    if source_type == SourceType.SINGLE:
        result = downloader.download_single(url, mode)
    else:
        result = downloader.download_batch(url, mode, source_type, source_name)

    # Video mode always runs a batch transcode pass after download.
    content_type = ContentType.VIDEO if mode == DownloadMode.VIDEO else ContentType.AUDIO
    output_dir = get_output_dir(config.base_dir, content_type, source_type, source_name)

    if mode == DownloadMode.VIDEO:
        logger.info("Starting batch transcode...")
        t_ok, t_fail = batch_transcode(output_dir, config)
        logger.info(f"Transcode complete: {t_ok} succeeded, {t_fail} failed")

    # Always print and persist a report for user visibility.
    report = generate_report(result, source_name, url)
    report_text = format_report(report)
    print(report_text)
    save_report(report, output_dir)

    return 1 if result.failed else 0


def cmd_update(args: argparse.Namespace, config: Config) -> int:
    """Handle the `update` subcommand.

    Args:
        args: Parsed CLI arguments.
        config: Resolved application configuration.

    Returns:
        Process exit code.
    """
    url = args.url
    mode = DownloadMode(args.mode)

    if not validate_url(url):
        logger.error(f"Invalid YouTube URL: {url}")
        return 1

    try:
        url_type = detect_url_type(url)
    except ValueError as e:
        logger.error(str(e))
        return 1

    if url_type == URLType.VIDEO:
        logger.error("Update is only supported for channels and playlists, not individual videos.")
        return 1

    logger.info(f"Updating {url_type.value}: {url}")

    try:
        result = update(url, mode, config)
    except ValueError as e:
        logger.error(str(e))
        return 1

    return 1 if result.failed else 0


def cmd_transcode(args: argparse.Namespace, config: Config) -> int:
    """Handle the `transcode` subcommand.

    Args:
        args: Parsed CLI arguments.
        config: Resolved application configuration.

    Returns:
        Process exit code.
    """
    target_dir = Path(args.dir).resolve()

    if not target_dir.exists():
        logger.error(f"Directory not found: {target_dir}")
        return 1

    logger.info(f"Transcoding files in: {target_dir}")
    t_ok, t_fail = batch_transcode(target_dir, config)

    if t_ok == 0 and t_fail == 0:
        logger.info("No files to transcode.")
    else:
        logger.info(f"Transcode complete: {t_ok} succeeded, {t_fail} failed")

    return 1 if t_fail > 0 else 0


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level CLI parser.

    Returns:
        Configured ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="ytdl",
        description="YouTube Downloader - Download videos and audio from YouTube",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to config.toml file (default: auto-detect)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose/debug logging",
    )

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # download subcommand
    dl_parser = subparsers.add_parser("download", help="Download videos or audio")
    dl_parser.add_argument(
        "--url", "-u",
        required=True,
        help="YouTube URL (video, playlist, or channel)",
    )
    dl_parser.add_argument(
        "--mode", "-m",
        choices=["video", "audio"],
        default="video",
        help="Download mode: video (video+audio) or audio (audio-only)",
    )
    dl_parser.add_argument(
        "--type", "-t",
        choices=["auto", "video", "playlist", "channel"],
        default="auto",
        help="URL type (default: auto-detect)",
    )

    # update subcommand
    up_parser = subparsers.add_parser(
        "update", help="Incrementally update a channel or playlist"
    )
    up_parser.add_argument(
        "--url", "-u",
        required=True,
        help="YouTube channel or playlist URL",
    )
    up_parser.add_argument(
        "--mode", "-m",
        choices=["video", "audio"],
        default="video",
        help="Download mode: video or audio",
    )

    # transcode subcommand
    tc_parser = subparsers.add_parser(
        "transcode", help="Batch transcode files in a directory"
    )
    tc_parser.add_argument(
        "--dir", "-d",
        required=True,
        help="Directory containing files to transcode (must have _raw/ subdirectory)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """Run CLI entrypoint.

    Args:
        argv: Optional list of CLI arguments. Uses sys.argv when None.

    Returns:
        Process exit code.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    setup_logging(args.verbose)

    if args.command is None:
        parser.print_help()
        return 0

    config = load_config(args.config)
    logger.debug(f"Config loaded: base_dir={config.base_dir}")

    commands = {
        "download": cmd_download,
        "update": cmd_update,
        "transcode": cmd_transcode,
    }

    handler = commands.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args, config)


if __name__ == "__main__":
    sys.exit(main())
