"""FFmpeg-based video transcoding."""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from ytdl.config import Config

logger = logging.getLogger(__name__)


def _check_ffmpeg() -> str:
    """Find ffmpeg binary path.

    Returns:
        Path to ffmpeg binary.

    Raises:
        RuntimeError: If ffmpeg is not found.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            "ffmpeg not found. Please install ffmpeg and ensure it is on your PATH."
        )
    return ffmpeg


def build_transcode_command(
    ffmpeg: str,
    input_path: Path,
    output_path: Path,
    config: Config,
) -> list[str]:
    """Build the ffmpeg transcode command.

    Encodes to H.264 with the configured CRF, scales down to max resolution
    while preserving aspect ratio (videos already at or below the resolution
    are not upscaled), and re-encodes audio to AAC.

    Args:
        ffmpeg: Path to ffmpeg binary.
        input_path: Path to the input video file.
        output_path: Path for the output file.
        config: Application configuration.

    Returns:
        List of command arguments.
    """
    max_res = config.max_resolution

    # Scale filter: scale down to max_res height if larger, don't upscale.
    # -2 ensures width is divisible by 2 (required by H.264).
    scale_filter = (
        f"scale=-2:'min({max_res},ih)'"
    )

    return [
        ffmpeg,
        "-i", str(input_path),
        "-c:v", config.transcode_codec,
        "-crf", str(config.transcode_crf),
        "-preset", config.transcode_preset,
        "-vf", scale_filter,
        "-c:a", config.transcode_audio_codec,
        "-movflags", "+faststart",
        "-y",  # Overwrite output without asking
        str(output_path),
    ]


def _partial_path(output_path: Path) -> Path:
    """Temp path that ffmpeg writes to before an atomic rename on success.

    The `.part` marker sits before the real extension (e.g. `name.part.mp4`)
    so ffmpeg still sees a valid container extension — it rejects trailing
    `.part` as an unknown format.

    Args:
        output_path: Final output path.

    Returns:
        Temporary partial-file path.
    """
    return output_path.with_name(f"{output_path.stem}.part{output_path.suffix}")


def _remove_if_exists(path: Path) -> None:
    """Remove a file if present.

    Args:
        path: File path to remove.
    """
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    except OSError as e:
        logger.warning(f"Could not remove {path}: {e}")


def transcode_video(
    input_path: Path,
    output_path: Path,
    config: Config,
) -> bool:
    """Transcode a single video file.

    ffmpeg writes to `<output_path>.part` and the temp file is renamed to
    `output_path` only after ffmpeg exits successfully. That way, a file at
    `output_path` is always a complete transcode; a leftover `.part` always
    means the previous run was interrupted and can be safely discarded.

    Args:
        input_path: Path to the raw downloaded video.
        output_path: Path for the transcoded output.
        config: Application configuration.

    Returns:
        True if transcoding succeeded, False otherwise.
    """
    ffmpeg = _check_ffmpeg()
    temp_path = _partial_path(output_path)
    _remove_if_exists(temp_path)
    cmd = build_transcode_command(ffmpeg, input_path, temp_path, config)

    logger.info(f"Transcoding: {input_path.name} -> {output_path.name}")
    logger.debug(f"Command: {' '.join(cmd)}")

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=7200,  # 2 hour timeout per file
        )
        if proc.returncode != 0:
            logger.error(f"Transcode failed for {input_path.name}: {proc.stderr[-500:]}")
            _remove_if_exists(temp_path)
            return False
        temp_path.replace(output_path)
        logger.info(f"Transcode complete: {output_path.name}")
        return True
    except subprocess.TimeoutExpired:
        logger.error(f"Transcode timed out for {input_path.name}")
        _remove_if_exists(temp_path)
        return False
    except KeyboardInterrupt:
        _remove_if_exists(temp_path)
        raise
    except Exception as e:
        logger.error(f"Transcode error for {input_path.name}: {e}")
        _remove_if_exists(temp_path)
        return False


def batch_transcode(output_dir: Path, config: Config) -> tuple[int, int]:
    """Transcode all video files in the _raw/ subdirectory.

    Transcoded files are placed in the parent directory (output_dir).
    Raw files are deleted after successful transcode, kept on failure.

    Args:
        output_dir: The output directory containing a _raw/ subfolder.
        config: Application configuration.

    Returns:
        Tuple of (succeeded_count, failed_count).
    """
    raw_dir = output_dir / "_raw"
    if not raw_dir.exists():
        logger.info(f"No _raw/ directory found in {output_dir}, nothing to transcode.")
        return 0, 0

    # Clean up any `.part` files left behind by a previous interrupted run.
    # Thanks to the atomic-rename pattern in transcode_video(), every `.part`
    # file is by definition an aborted transcode and safe to remove.
    for stale in output_dir.glob(f"*.part.{config.video_format}"):
        logger.info(f"Removing stale partial transcode: {stale.name}")
        _remove_if_exists(stale)

    # Find all video files in _raw/
    video_extensions = {".mp4", ".mkv", ".webm", ".avi", ".mov"}
    raw_files = sorted(
        f for f in raw_dir.iterdir()
        if f.is_file() and f.suffix.lower() in video_extensions
    )

    if not raw_files:
        logger.info(f"No video files found in {raw_dir}")
        return 0, 0

    total = len(raw_files)
    succeeded = 0
    failed = 0

    logger.info(f"Transcoding {total} files from {raw_dir}")

    for i, raw_file in enumerate(raw_files, 1):
        # Output file goes in parent directory with same name but .mp4 extension
        output_file = output_dir / raw_file.with_suffix(f".{config.video_format}").name

        logger.info(f"[{i}/{total}] Processing {raw_file.name}")

        # If a fully transcoded output already exists (prior run was killed
        # after the rename but before the raw was removed), just drop the raw.
        if output_file.exists():
            logger.info(
                f"  Output {output_file.name} already exists; removing orphan raw."
            )
            _remove_if_exists(raw_file)
            succeeded += 1
            continue

        if transcode_video(raw_file, output_file, config):
            # Remove raw file after successful transcode
            raw_file.unlink()
            logger.info(f"  Removed raw file: {raw_file.name}")
            succeeded += 1
        else:
            logger.warning(f"  Keeping raw file due to transcode failure: {raw_file.name}")
            failed += 1

    # Remove _raw/ directory if empty
    try:
        if raw_dir.exists() and not any(raw_dir.iterdir()):
            raw_dir.rmdir()
            logger.info(f"Removed empty _raw/ directory")
    except OSError:
        pass  # Directory not empty, that's fine

    logger.info(f"Batch transcode complete: {succeeded} succeeded, {failed} failed")
    return succeeded, failed
