"""Find broken downloads, queue them for re-download, and clean up once repaired.

Every download/update run on a folder does: reconcile -> download -> transcode -> cleanup.

- `reconcile` sets broken files aside in `_broken/` and removes their IDs from
  `archive.txt`, so the following yt-dlp run fetches them again.
- `cleanup` deletes set-aside files and leftover download pieces only once a
  verified copy (checked with ffprobe) of the same video exists.

Both steps are idempotent, so stopping a run at any point is repaired by the next run.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

from ytdl.config import Config
from ytdl.downloader import DownloadMode
from ytdl.media import (
    VIDEO_EXTENSIONS,
    MediaCheck,
    check_many,
    ffprobe_available,
    is_format_piece,
    is_intermediate,
    video_id_from_name,
)
from ytdl.tracker import get_archived_video_ids
from ytdl.utils import BROKEN_DIR_NAME, get_archive_path, set_aside

logger = logging.getLogger(__name__)

# More broken files than this (both limits exceeded) means a disk or ffprobe
# problem rather than broken downloads, so nothing is changed.
MAX_BROKEN_FILES = 5
MAX_BROKEN_SHARE = 0.2

_AUDIO_SOURCE_EXTENSIONS = {".webm", ".m4a", ".opus", ".ogg", ".mp4", ".aac", ".flac", ".wav"}


@dataclass
class RepairReport:
    """What a repair step found and did (or would do, in a dry run).

    Attributes:
        folder: The channel/playlist folder.
        requeued: (file, reason) set aside and queued for re-download.
        removed: (file, reason) deleted because a verified copy exists.
        warnings: (file, reason) usable files with something worth knowing.
        unchecked: (file, reason) files that could not be checked; never changed.
        error: Set when the step refused to change anything.
        dry_run: True if nothing was changed on purpose.
    """
    folder: Path
    requeued: list[tuple[str, str]] = field(default_factory=list)
    removed: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[tuple[str, str]] = field(default_factory=list)
    unchecked: list[tuple[str, str]] = field(default_factory=list)
    error: str | None = None
    dry_run: bool = False

    @property
    def needs_action(self) -> bool:
        """Return True if files are (or would be) re-queued or removed."""
        return bool(self.requeued or self.removed)

    def merge(self, other: RepairReport) -> RepairReport:
        """Append another report's findings to this one.

        Args:
            other: Report for the same folder.

        Returns:
            This report, for chaining.
        """
        self.requeued += other.requeued
        self.removed += other.removed
        self.warnings += other.warnings
        self.unchecked += other.unchecked
        self.error = self.error or other.error
        return self

    def summary(self) -> str:
        """Return a one-line summary for logs."""
        would = "would be " if self.dry_run else ""
        parts = []
        if self.requeued:
            parts.append(f"{len(self.requeued)} broken file(s) {would}set aside and re-queued")
        if self.removed:
            parts.append(f"{len(self.removed)} leftover file(s) {would}removed")
        return ", ".join(parts) or "nothing to repair"

    def format(self) -> str:
        """Return a readable multi-line description for `ytdl check`."""
        lines = [f"{self.folder.name}: {self.summary()}"]
        if self.error:
            lines.append(f"  ERROR        {self.error}")
        for label, items in (
            ("re-download", self.requeued),
            ("delete", self.removed),
            ("warning", self.warnings),
            ("not checked", self.unchecked),
        ):
            for name, reason in items:
                lines.append(f"  {label:<12} {name}  ({reason})")
        return "\n".join(lines)


def _final_ext(mode: DownloadMode, config: Config) -> str:
    """Return the extension of finished files for a mode (e.g. `.mp4` or `.mp3`)."""
    fmt = config.video_format if mode == DownloadMode.VIDEO else config.audio_format
    return f".{fmt.lower()}"


def _files(directory: Path) -> list[Path]:
    """Return the regular files of a directory, or [] if it does not exist."""
    if not directory.is_dir():
        return []
    return sorted(f for f in directory.iterdir() if f.is_file())


def _unarchive(output_dir: Path, ids: set[str]) -> None:
    """Remove `youtube <id>` lines from archive.txt, atomically.

    Args:
        output_dir: Folder containing archive.txt.
        ids: Video IDs to remove.
    """
    archive = get_archive_path(output_dir)
    if not ids or not archive.exists():
        return
    lines = archive.read_text().splitlines()
    keep = [
        line for line in lines
        if not (line.startswith("youtube ") and line.split(" ", 1)[1].strip() in ids)
    ]
    if len(keep) == len(lines):
        return
    tmp = archive.with_name(archive.name + ".tmp")
    tmp.write_text("".join(f"{line}\n" for line in keep))
    tmp.replace(archive)


def _too_many_broken(bad: int, checked: int) -> bool:
    """Return True if so many files look bad that the disk is the likelier cause."""
    return bad > MAX_BROKEN_FILES and bad > MAX_BROKEN_SHARE * checked


def reconcile(
    output_dir: Path,
    mode: DownloadMode,
    config: Config,
    dry_run: bool = False,
) -> RepairReport:
    """Set broken files aside and queue their videos for re-download.

    Handles: finished files that are unreadable or missing their main stream,
    single-stream pieces (`name [id].f251.mp4`) left in the folder by older
    versions, and broken merged files in `_raw/`. A piece whose video already has
    a verified copy is deleted directly.

    Args:
        output_dir: Channel/playlist folder.
        mode: VIDEO or AUDIO; decides which files and streams are expected.
        config: Application configuration.
        dry_run: Only report what would be done.

    Returns:
        RepairReport; `error` is set if nothing was changed for safety reasons.
    """
    report = RepairReport(folder=output_dir, dry_run=dry_run)
    if not output_dir.is_dir():
        return report
    if not ffprobe_available():
        report.unchecked.append(("*", "ffprobe not found, existing files were not checked"))
        return report

    video = mode == DownloadMode.VIDEO
    final_ext = _final_ext(mode, config)
    raw_dir = output_dir / "_raw"
    broken_dir = output_dir / BROKEN_DIR_NAME

    files = [f for f in _files(output_dir) if video_id_from_name(f.name)]
    finals = [f for f in files if f.suffix.lower() == final_ext and not is_intermediate(f)]
    pieces = [f for f in files if f.suffix.lower() == final_ext and is_format_piece(f)]
    raw_merged = [
        f for f in _files(raw_dir)
        if f.suffix.lower() in VIDEO_EXTENSIONS and not is_intermediate(f)
        and video_id_from_name(f.name)
    ] if video else []

    checks: dict[Path, MediaCheck] = check_many(finals + raw_merged, require_video=video)

    def rel(path: Path) -> str:
        return str(path.relative_to(output_dir))

    valid_ids = {video_id_from_name(f.name) for f in finals if checks[f].ok}
    pending_ids = {video_id_from_name(f.name) for f in raw_merged if checks[f].ok}

    broken = [(f, checks[f].reason) for f in finals + raw_merged if checks[f].ok is False]
    for path, check in checks.items():
        if check.ok and check.reason:
            report.warnings.append((rel(path), check.reason))
        elif check.ok is None:
            report.unchecked.append((rel(path), check.reason))

    if _too_many_broken(len(broken) + len(report.unchecked), len(checks)):
        report.error = (
            f"{len(broken)} broken and {len(report.unchecked)} unreadable of {len(checks)} files; "
            "this looks like a disk problem, so nothing was changed"
        )
        return report

    to_requeue: list[tuple[Path, str]] = list(broken)
    to_remove: list[tuple[Path, str]] = []
    for piece in pieces:
        vid = video_id_from_name(piece.name)
        if vid in valid_ids:
            to_remove.append((piece, "leftover piece, a complete copy exists"))
        else:
            to_requeue.append((piece, "single-stream piece of an unfinished download"))

    # Anything set aside earlier stays queued until a good copy exists (makes
    # an interrupted reconcile, or a failed retry, safe on the next run).
    requeue_ids = {video_id_from_name(p.name) for p, _ in to_requeue}
    for item in _files(broken_dir):
        vid = video_id_from_name(item.name)
        if vid and vid not in valid_ids:
            requeue_ids.add(vid)
    requeue_ids -= valid_ids | pending_ids
    archived_requeue = requeue_ids & get_archived_video_ids(output_dir)

    listed_ids = {video_id_from_name(p.name) for p, _ in to_requeue}
    report.requeued = [(rel(p), reason) for p, reason in to_requeue]
    report.requeued += [
        (rel(item), "set aside earlier, still marked as downloaded")
        for item in _files(broken_dir)
        if video_id_from_name(item.name) in archived_requeue - listed_ids
    ]
    report.removed = [(rel(p), reason) for p, reason in to_remove]

    if dry_run or not (to_requeue or to_remove or archived_requeue):
        return report
    if not os.access(output_dir, os.W_OK):
        report.error = "folder is not writable (read-only disk?), nothing was changed"
        return report

    # Un-archive first, then move: if interrupted in between, the file is
    # simply found broken again next time.
    _unarchive(output_dir, archived_requeue)
    for path, reason in to_requeue:
        logger.warning(f"Broken: {rel(path)} ({reason}) -> {BROKEN_DIR_NAME}/, will be downloaded again")
        set_aside(path, broken_dir)
    for path, reason in to_remove:
        logger.info(f"Removing {rel(path)} ({reason})")
        path.unlink(missing_ok=True)
    return report


def cleanup(
    output_dir: Path,
    mode: DownloadMode,
    config: Config,
    dry_run: bool = False,
) -> RepairReport:
    """Delete set-aside files and leftover pieces whose video now has a verified copy.

    Args:
        output_dir: Channel/playlist folder.
        mode: VIDEO or AUDIO.
        config: Application configuration.
        dry_run: Only report what would be deleted.

    Returns:
        RepairReport listing the removed files.
    """
    report = RepairReport(folder=output_dir, dry_run=dry_run)
    if not output_dir.is_dir() or not ffprobe_available():
        return report

    video = mode == DownloadMode.VIDEO
    final_ext = _final_ext(mode, config)
    broken_dir = output_dir / BROKEN_DIR_NAME

    broken_items = [f for f in _files(broken_dir) if video_id_from_name(f.name)]
    if video:
        pieces = [f for f in _files(output_dir / "_raw") if is_intermediate(f) and video_id_from_name(f.name)]
    else:
        # Audio mode: downloaded sources not yet converted, and their partial files.
        pieces = [
            f for f in _files(output_dir)
            if video_id_from_name(f.name)
            and (is_intermediate(f) or f.suffix.lower() in _AUDIO_SOURCE_EXTENSIONS)
            and f.suffix.lower() != final_ext
        ]
    if not broken_items and not pieces:
        return report

    wanted = {video_id_from_name(f.name) for f in broken_items + pieces}
    finals = [
        f for f in _files(output_dir)
        if f.suffix.lower() == final_ext and not is_intermediate(f)
        and video_id_from_name(f.name) in wanted
    ]
    checks = check_many(finals, require_video=video)
    valid_ids = {video_id_from_name(f.name) for f in finals if checks[f].ok}
    archived = get_archived_video_ids(output_dir)

    to_delete = [
        (f, f"{BROKEN_DIR_NAME}/{f.name}", "replaced by a verified copy")
        for f in broken_items if video_id_from_name(f.name) in valid_ids
    ]
    to_delete += [
        (f, str(f.relative_to(output_dir)), "leftover piece of a finished download")
        for f in pieces
        if video_id_from_name(f.name) in valid_ids and video_id_from_name(f.name) in archived
    ]
    report.removed = [(name, reason) for _, name, reason in to_delete]

    if dry_run or not to_delete:
        return report
    if not os.access(output_dir, os.W_OK):
        report.error = "folder is not writable (read-only disk?), nothing was deleted"
        return report

    for path, name, reason in to_delete:
        logger.info(f"Removing {name} ({reason})")
        path.unlink(missing_ok=True)
    if broken_dir.is_dir() and not any(broken_dir.iterdir()):
        broken_dir.rmdir()
    return report


def inspect_folder(output_dir: Path, mode: DownloadMode, config: Config) -> RepairReport:
    """Report what the next run would repair in a folder, without changing anything.

    Args:
        output_dir: Channel/playlist folder.
        mode: VIDEO or AUDIO.
        config: Application configuration.

    Returns:
        Combined dry-run report of reconcile and cleanup.
    """
    report = reconcile(output_dir, mode, config, dry_run=True)
    if report.error:
        return report
    return report.merge(cleanup(output_dir, mode, config, dry_run=True))


def repair_before_download(output_dir: Path, mode: DownloadMode, config: Config) -> None:
    """Reconcile a folder before downloading into it, logging what was done.

    Args:
        output_dir: Channel/playlist folder.
        mode: VIDEO or AUDIO.
        config: Application configuration.

    Raises:
        ValueError: If the folder looks unsafe to touch (disk problem, read-only).
    """
    report = reconcile(output_dir, mode, config)
    for name, reason in report.unchecked:
        logger.warning(f"Could not check {name}: {reason}")
    if report.error:
        raise ValueError(f"{output_dir.name}: {report.error}")
    if report.needs_action:
        logger.info(f"Repair: {report.summary()}")


def repair_after_download(output_dir: Path, mode: DownloadMode, config: Config) -> None:
    """Clean up a folder after download and transcode, logging what was removed.

    Args:
        output_dir: Channel/playlist folder.
        mode: VIDEO or AUDIO.
        config: Application configuration.
    """
    report = cleanup(output_dir, mode, config)
    if report.error:
        logger.warning(f"Cleanup skipped: {report.error}")
    elif report.removed:
        logger.info(f"Cleanup: {report.summary()}")
