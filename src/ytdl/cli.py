"""CLI entry point for the YouTube Downloader."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from ytdl.config import Config, load_config
from ytdl.downloader import DownloadMode, VideoDownloader
from ytdl.oxford import download_series, is_oxford_url
from ytdl.repair import inspect_folder, repair_after_download, repair_before_download
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


def add_file_logging(base_dir: Path) -> None:
    """Also append log messages to `{base_dir}/logs/ytdl-YYYY-MM-DD.log`.

    The terminal output is lost once the window is closed; the log file keeps
    the actual yt-dlp/ffmpeg errors behind failed downloads.

    Args:
        base_dir: Configured base directory.
    """
    log_dir = base_dir / "logs"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / f"ytdl-{date.today().isoformat()}.log", encoding="utf-8")
    except OSError as e:
        logger.warning(f"Could not open a log file in {log_dir}: {e}")
        return
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.getLogger().addHandler(handler)


def _run_oxford(url: str, config: Config) -> int:
    """Download new episodes of an Oxford Podcasts series.

    Podcasts are audio-only, so --mode and --type do not apply. Downloads are
    archive-incremental, which makes `download` and `update` equivalent.

    Args:
        url: Oxford Podcasts series page or feed URL.
        config: Resolved application configuration.

    Returns:
        Process exit code.
    """
    logger.info(f"Downloading Oxford podcast (audio only): {url}")

    try:
        series, output_dir, result = download_series(url, config)
    except ValueError as e:
        logger.error(str(e))
        return 1
    except KeyboardInterrupt:
        return 1

    report = generate_report(result, series, url)
    print(format_report(report))
    save_report(report, output_dir)

    return 1 if result.failed else 0


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

    if is_oxford_url(url):
        return _run_oxford(url, config)

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

    content_type = ContentType.VIDEO if mode == DownloadMode.VIDEO else ContentType.AUDIO
    output_dir = get_output_dir(config.base_dir, content_type, source_type, source_name)

    # Queue broken files from earlier runs for re-download before yt-dlp
    # consults the archive.
    try:
        repair_before_download(output_dir, mode, config)
    except ValueError as e:
        logger.error(str(e))
        return 1

    # Execute download through yt-dlp wrapper.
    downloader = VideoDownloader(config)
    if source_type == SourceType.SINGLE:
        result = downloader.download_single(url, mode)
    else:
        result = downloader.download_batch(url, mode, source_type, source_name)

    # Video mode always runs a batch transcode pass after download.
    if mode == DownloadMode.VIDEO:
        logger.info("Starting batch transcode...")
        t_ok, t_fail = batch_transcode(output_dir, config)
        logger.info(f"Transcode complete: {t_ok} succeeded, {t_fail} failed")

    repair_after_download(output_dir, mode, config)

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

    if is_oxford_url(url):
        return _run_oxford(url, config)

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


def _guess_mode(folder: Path) -> DownloadMode:
    """Guess a folder's mode from its location (`.../Audio/<name>` is audio)."""
    return DownloadMode.AUDIO if folder.parent.name == ContentType.AUDIO.value else DownloadMode.VIDEO


def cmd_check(args: argparse.Namespace, config: Config) -> int:
    """Handle the `check` subcommand: report what the next run would repair.

    Read-only: nothing is moved, deleted or written.

    Args:
        args: Parsed CLI arguments.
        config: Resolved application configuration.

    Returns:
        0 if nothing needs repair, 1 otherwise.
    """
    if args.dir:
        target = Path(args.dir).expanduser().resolve()
        if not target.is_dir():
            logger.error(f"Directory not found: {target}")
            return 1
        mode = DownloadMode(args.mode) if args.mode else _guess_mode(target)
        folders = [(target, mode)]
    else:
        folders = []
        for content_type, mode in ((ContentType.VIDEO, DownloadMode.VIDEO),
                                   (ContentType.AUDIO, DownloadMode.AUDIO)):
            root = config.base_dir / content_type.value
            if root.is_dir():
                folders += [(d, mode) for d in sorted(root.iterdir()) if d.is_dir()]

    needs_repair = 0
    for folder, mode in folders:
        report = inspect_folder(folder, mode, config)
        if report.needs_action or report.error or report.warnings or report.unchecked:
            print(report.format())
            print()
        if report.needs_action or report.error:
            needs_repair += 1

    print(f"Checked {len(folders)} folder(s): {needs_repair} need repair.")
    if needs_repair:
        print("Re-run the download/update for those channels or playlists to repair them.")
    return 1 if needs_repair else 0


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
        help="YouTube URL (video, playlist, or channel) or Oxford Podcasts series URL",
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
        help="YouTube channel or playlist URL, or Oxford Podcasts series URL",
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

    # check subcommand
    ck_parser = subparsers.add_parser(
        "check", help="Report broken files the next download/update would repair (read-only)"
    )
    ck_parser.add_argument(
        "--dir", "-d",
        help="Channel/playlist folder to check (default: every folder under Videos/ and Audio/)",
    )
    ck_parser.add_argument(
        "--mode", "-m",
        choices=["video", "audio"],
        default=None,
        help="Folder type (default: audio for folders under Audio/, else video)",
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

    # `check` stays read-only, so it does not create a log file.
    if args.command != "check":
        add_file_logging(config.base_dir)

    commands = {
        "download": cmd_download,
        "update": cmd_update,
        "transcode": cmd_transcode,
        "check": cmd_check,
    }

    handler = commands.get(args.command)
    if handler is None:
        parser.print_help()
        return 1

    return handler(args, config)


if __name__ == "__main__":
    sys.exit(main())
