# YouTube Downloader — Project Plan

## Overview

A Python CLI application to download YouTube videos and audio from individual videos, playlists, and channels using yt-dlp. Videos are downloaded at max 1080p with separate video+audio streams merged into MP4. After batch download, files are transcoded with ffmpeg (H.264, CRF 25). An audio-only mode produces MP3 files at 192 kbps. Per-folder archive tracking enables incremental updates.

## Requirements

### Functional
- Download individual videos, full playlists, and full channels
- Max 1080p resolution; allow lower if source is lower
- Download video and audio streams separately, merge to MP4
- Audio-only download mode (MP3, 192 kbps)
- Video downloads always include audio
- Use native audio stream (original language, not dubbed)
- Batch transcode after all downloads complete (H.264, CRF 25, 1080p cap)
- Organized folder structure: `Videos/{Channel|Playlist|Misc}/`, `Audio/{Channel|Playlist|Misc}/`
- Per-folder download archive for tracking
- Incremental updates for channels/playlists (only download new content)
- Never delete existing files, even if removed from YouTube
- Verification report after playlist/channel downloads listing successes and failures
- Sleep between requests to avoid rate limiting
- Six specialized shell scripts for each download type
- TOML configuration file for all settings

### Non-Functional
- Python 3.11+
- Uses yt-dlp Python API
- ffmpeg for merging and transcoding
- Comprehensive test suite (mocked, no network calls)
- Documentation in `.docs/`

## Architecture

See [architecture.md](architecture.md) for module design and data flow.

## Phases

### Phase 1: Project Scaffolding
- `pyproject.toml` with dependencies and entry point
- `config.toml` with all tunable settings
- `src/ytdl/config.py` — Config dataclass, TOML loader

### Phase 2: Core Utilities
- `src/ytdl/utils.py` — Path sanitization, directory helpers
- `src/ytdl/validator.py` — URL validation, type detection, metadata extraction

### Phase 3: Download Engine
- `src/ytdl/downloader.py` — yt-dlp wrapper with video/audio modes
- `src/ytdl/tracker.py` — Archive management, download reports

### Phase 4: Transcoding
- `src/ytdl/transcoder.py` — ffmpeg integration, batch transcode

### Phase 5: Update Logic
- `src/ytdl/updater.py` — Incremental updates for channels/playlists

### Phase 6: CLI & Scripts
- `src/ytdl/cli.py` — argparse with download/update/transcode subcommands
- `scripts/*.sh` — Six shell wrapper scripts

### Phase 7: Testing
- `tests/` — Full test suite with mocked yt-dlp and ffmpeg

### Phase 8: Documentation
- `.docs/plan.md`, `.docs/architecture.md`, `.docs/usage.md`
- `README.md`

## Decisions

| Decision | Rationale |
|----------|-----------|
| ffmpeg over HandBrake | More scriptable, universally available, yt-dlp already requires it |
| Per-folder archive.txt | Simpler incremental updates, no cross-contamination |
| Batch transcode after download | Downloads to `_raw/`, avoids partial state on interruption |
| Shell scripts as thin wrappers | Validate URL type, delegate to Python CLI |
| TOML config | `tomllib` built into Python 3.11+ |
| `format_sort: ['lang']` | yt-dlp prioritizes native language audio |
| `Title [VideoID].ext` naming | Video ID ensures uniqueness |
| H.264 + MP4 | Maximum compatibility |
| MP3 192 kbps | Good quality/size balance |
