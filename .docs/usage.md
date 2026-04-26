# Usage Guide

## Installation

```bash
cd YouTubeDownloader
pip install -e ".[dev]"
```

This installs the `ytdl` CLI command and all dependencies (yt-dlp, pytest).

### Prerequisites

- **Python 3.11+**
- **ffmpeg**: Required for merging video+audio streams and transcoding.
  ```bash
  # Ubuntu/Debian
  sudo apt install ffmpeg

  # macOS
  brew install ffmpeg

  # Arch
  sudo pacman -S ffmpeg
  ```

## Configuration

Edit `config.toml` in the project root to customize settings:

```toml
[general]
base_dir = "."          # Where Videos/ and Audio/ folders are created
                        # (may be absolute, e.g. "/home/user/Media/YTDownloader")

[video]
max_resolution = 1080   # Maximum video height in pixels
format = "mp4"          # Output container

[audio]
format = "mp3"          # Audio format for audio-only downloads
bitrate = "192"         # Audio bitrate in kbps

[transcode]
codec = "libx264"       # Video codec
crf = 25                # Quality (lower = better, larger file)
preset = "medium"       # Encoding speed/compression tradeoff

[network]
sleep_interval = 10     # Min seconds between downloads
max_sleep_interval = 20 # Max seconds (random between min/max)
sleep_requests = 0.75   # Seconds between API requests
retries = 10            # Retry count for failed downloads
```

## CLI Usage

### Download a Single Video

```bash
ytdl download --url "https://www.youtube.com/watch?v=VIDEO_ID" --mode video
```

Output: `Videos/Misc/Title [VIDEO_ID].mp4`

### Download a Single Audio

```bash
ytdl download --url "https://www.youtube.com/watch?v=VIDEO_ID" --mode audio
```

Output: `Audio/Misc/Title [VIDEO_ID].mp3`

### Download a Playlist (Video)

```bash
ytdl download --url "https://www.youtube.com/playlist?list=PLAYLIST_ID" --mode video
```

Output: `Videos/PlaylistName/Title [VIDEO_ID].mp4` (for each video)

### Download a Channel (Video)

```bash
ytdl download --url "https://www.youtube.com/@ChannelName" --mode video
```

Output: `Videos/ChannelName/Title [VIDEO_ID].mp4` (for each video)

### Download a Playlist (Audio Only)

```bash
ytdl download --url "https://www.youtube.com/playlist?list=PLAYLIST_ID" --mode audio
```

Output: `Audio/PlaylistName/Title [VIDEO_ID].mp3`

### Download a Channel (Audio Only)

```bash
ytdl download --url "https://www.youtube.com/@ChannelName" --mode audio
```

Output: `Audio/ChannelName/Title [VIDEO_ID].mp3`

### Verbose Output

Add `-v` for debug-level logging:

```bash
ytdl -v download --url "https://www.youtube.com/watch?v=VIDEO_ID"
```

### Custom Config File

```bash
ytdl --config /path/to/config.toml download --url "..."
```

## Shell Scripts

Each script validates the URL type and delegates to the CLI. They only accept a single URL argument.

| Script | URL type | Output |
| --- | --- | --- |
| [`download_video.sh`](../scripts/download_video.sh) | single video | `{base_dir}/Videos/Misc/...mp4` |
| [`download_playlist_video.sh`](../scripts/download_playlist_video.sh) | playlist | `{base_dir}/Videos/{Playlist}/...mp4` |
| [`download_channel_video.sh`](../scripts/download_channel_video.sh) | channel | `{base_dir}/Videos/{Channel}/...mp4` |
| [`download_audio.sh`](../scripts/download_audio.sh) | single video | `{base_dir}/Audio/Misc/...mp3` |
| [`download_playlist_audio.sh`](../scripts/download_playlist_audio.sh) | playlist | `{base_dir}/Audio/{Playlist}/...mp3` |
| [`download_channel_audio.sh`](../scripts/download_channel_audio.sh) | channel | `{base_dir}/Audio/{Channel}/...mp3` |

```bash
./scripts/download_video.sh "https://www.youtube.com/watch?v=VIDEO_ID"
./scripts/download_playlist_video.sh "https://www.youtube.com/playlist?list=PLAYLIST_ID"
./scripts/download_channel_video.sh "https://www.youtube.com/@ChannelName"
./scripts/download_audio.sh "https://www.youtube.com/watch?v=VIDEO_ID"
./scripts/download_playlist_audio.sh "https://www.youtube.com/playlist?list=PLAYLIST_ID"
./scripts/download_channel_audio.sh "https://www.youtube.com/@ChannelName"
```

If you pass the wrong URL type (e.g., a video URL to the channel script), the script will reject it with an error message.

### Conda environment auto-activation

The `ytdl` package is installed into the conda env `ytdl` (not a project-local venv). Every script sources [`scripts/_activate_env.sh`](../scripts/_activate_env.sh) at startup, which runs `conda activate ytdl` if that env isn't already active. Requirements:

- `conda` must be on `PATH` (miniconda/Anaconda standard install).
- The `ytdl` env must exist with the project installed (`pip install -e ".[dev]"` from within that env).

To run the CLI manually without the scripts, activate the env first:

```bash
conda activate ytdl
ytdl download --url "..."
```

## Updating Channels & Playlists

To incrementally add new videos from a channel or playlist:

```bash
# Update a channel (video)
ytdl update --url "https://www.youtube.com/@ChannelName" --mode video

# Update a playlist (audio)
ytdl update --url "https://www.youtube.com/playlist?list=PLAYLIST_ID" --mode audio
```

The updater:
1. Fetches the current video list from YouTube
2. Compares with the local archive (`archive.txt`)
3. Downloads only new/missing videos
4. Transcodes all pending raws in `_raw/` (video mode only) — this includes leftovers from any previously interrupted run, even if this invocation downloaded nothing new
5. Generates a download report

**Important**: Existing files are never deleted, even if they've been removed from YouTube.

## Manual Transcoding

If you need to re-transcode files or transcode files from a specific directory:

```bash
ytdl transcode --dir "Videos/ChannelName"
```

This looks for video files in `Videos/ChannelName/_raw/` and transcodes them to the parent directory.

## Interrupt & Resume Behavior

You can safely Ctrl-C any download or update script. Re-running the same command picks up where it left off — nothing that already finished is redone.

### Downloads

- Fully-downloaded videos are recorded in `archive.txt` and skipped by yt-dlp on the next run.
- A video that was mid-download leaves a `.part` file in `_raw/`; yt-dlp resumes it from the existing bytes.
- Audio mode: the archive is only updated after the mp3 postprocess completes, so any partially-extracted audio is re-downloaded cleanly on the next run.

### Transcoding

The transcode step always runs when a download/update command is invoked in video mode, even if yt-dlp has nothing new — this is what picks up raws left behind by an interrupted prior run.

Transcoding is made crash-safe with an atomic-rename pattern:

1. ffmpeg writes to `<output>.part.mp4` (never directly to the final path). The `.part` sits before the extension because ffmpeg refuses to write to a file ending in `.part` — it can't infer the container format.
2. On clean exit, the temp file is atomically renamed to `<output>.mp4`.
3. Only then is the corresponding `_raw/` file deleted.

Consequences:

- A file at the final output path is **always** a complete transcode.
- A leftover `*.part.mp4` is **always** junk from an interrupted run and is auto-deleted at the start of the next `batch_transcode`. The raw is then re-transcoded from scratch.
- If the process is killed in the tiny window between rename and raw-unlink, the next run detects that the final output already exists, removes the orphan raw, and moves on.

Ctrl-C during a transcode also removes the in-progress `.part` immediately so state on disk stays clean.

### Manual recovery

If you want to force the transcode step to run without invoking a download at all:

```bash
ytdl transcode --dir "/home/user/Media/YTDownloader/Videos/ChannelName"
```

## Download Reports

After each download or update, a `download_report.txt` is saved in the output folder. It lists:
- Total, succeeded, failed, and skipped counts
- Titles of succeeded downloads
- Failed downloads with reasons
- Skipped downloads (already in archive)

Example:
```
============================================================
Download Report: My Playlist
============================================================
URL:       https://www.youtube.com/playlist?list=PLxxxx
Timestamp: 2024-01-15T10:30:00+00:00
Total:     25
Succeeded: 23
Failed:    1
Skipped:   1 (already downloaded)

--- Succeeded ---
  ✓ Video Title 1
  ✓ Video Title 2
  ...

--- Failed ---
  ✗ Private Video
    Reason: This video is private

--- Skipped (already downloaded) ---
  - Previously Downloaded Video
============================================================
```

## Troubleshooting

### "ffmpeg not found"
Install ffmpeg and ensure it's on your PATH.

### Rate limiting / HTTP 429
Increase `sleep_interval` and `max_sleep_interval` in `config.toml`.

### Age-restricted videos
yt-dlp supports cookies for age-restricted content. You can pass cookies via yt-dlp's configuration (not yet exposed in config.toml — planned for future releases).

### Video unavailable
Some videos may be region-locked, private, or removed. These will appear in the "Failed" section of the download report.

## Running Tests

```bash
pytest                    # Run all tests
pytest -v                 # Verbose output
pytest tests/test_config.py  # Run specific test file
pytest --cov=ytdl         # With coverage report
```
