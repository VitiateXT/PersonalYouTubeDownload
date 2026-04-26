"""Download tracking, archive management, and report generation."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from ytdl.downloader import DownloadResult

logger = logging.getLogger(__name__)


@dataclass
class DownloadReport:
    """Human-readable download report."""
    source_name: str
    source_url: str
    timestamp: str
    total: int
    succeeded: int
    failed: int
    skipped: int
    failed_details: list[tuple[str, str]] = field(default_factory=list)
    succeeded_titles: list[str] = field(default_factory=list)
    skipped_titles: list[str] = field(default_factory=list)


def generate_report(
    result: DownloadResult,
    source_name: str,
    source_url: str,
) -> DownloadReport:
    """Generate a download report from a DownloadResult.

    Args:
        result: The result from a download operation.
        source_name: Name of the channel/playlist/video.
        source_url: The original URL.

    Returns:
        DownloadReport with all details.
    """
    return DownloadReport(
        source_name=source_name,
        source_url=source_url,
        timestamp=datetime.now(timezone.utc).isoformat(),
        total=result.total,
        succeeded=len(result.succeeded),
        failed=len(result.failed),
        skipped=len(result.skipped),
        failed_details=list(result.failed),
        succeeded_titles=list(result.succeeded),
        skipped_titles=list(result.skipped),
    )


def format_report(report: DownloadReport) -> str:
    """Format a DownloadReport as a human-readable string.

    Args:
        report: The report to format.

    Returns:
        Formatted report string.
    """
    lines = [
        "=" * 60,
        f"Download Report: {report.source_name}",
        "=" * 60,
        f"URL:       {report.source_url}",
        f"Timestamp: {report.timestamp}",
        f"Total:     {report.total}",
        f"Succeeded: {report.succeeded}",
        f"Failed:    {report.failed}",
        f"Skipped:   {report.skipped} (already downloaded)",
        "",
    ]

    if report.succeeded_titles:
        lines.append("--- Succeeded ---")
        for title in report.succeeded_titles:
            lines.append(f"  ✓ {title}")
        lines.append("")

    if report.failed_details:
        lines.append("--- Failed ---")
        for title, reason in report.failed_details:
            lines.append(f"  ✗ {title}")
            lines.append(f"    Reason: {reason}")
        lines.append("")

    if report.skipped_titles:
        lines.append("--- Skipped (already downloaded) ---")
        for title in report.skipped_titles:
            lines.append(f"  - {title}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


def save_report(report: DownloadReport, output_dir: Path) -> Path:
    """Save a download report to a file in the output directory.

    Args:
        report: The report to save.
        output_dir: Directory to write the report file.

    Returns:
        Path to the saved report file.
    """
    report_path = output_dir / "download_report.txt"
    text = format_report(report)

    # Append if report already exists (for incremental updates)
    mode = "a" if report_path.exists() else "w"
    with open(report_path, mode) as f:
        if mode == "a":
            f.write("\n\n")
        f.write(text)

    logger.info(f"Report saved to {report_path}")
    return report_path


def load_archive(output_dir: Path) -> set[str]:
    """Load the set of already-downloaded video IDs from an archive file.

    Args:
        output_dir: Directory containing archive.txt.

    Returns:
        Set of archive entries (e.g. "youtube dQw4w9WgXcQ").
    """
    archive_path = output_dir / "archive.txt"
    if not archive_path.exists():
        return set()
    return {
        line.strip()
        for line in archive_path.read_text().splitlines()
        if line.strip()
    }


def get_archived_video_ids(output_dir: Path) -> set[str]:
    """Extract just the video IDs from an archive file.

    Args:
        output_dir: Directory containing archive.txt.

    Returns:
        Set of video IDs (without the extractor prefix).
    """
    archive = load_archive(output_dir)
    ids = set()
    for entry in archive:
        parts = entry.split(" ", 1)
        if len(parts) == 2:
            ids.add(parts[1])
    return ids


def get_missing_videos(
    expected_ids: list[str],
    archived_ids: set[str],
) -> list[str]:
    """Find video IDs that are expected but not yet downloaded.

    Args:
        expected_ids: List of video IDs from the remote source.
        archived_ids: Set of IDs already in the local archive.

    Returns:
        List of video IDs that are missing from the archive.
    """
    return [vid for vid in expected_ids if vid not in archived_ids]
