# Architecture

## Module Overview

```
src/ytdl/
├── cli.py          ← Entry point. Parses args, orchestrates workflow.
├── config.py       ← Loads TOML config, provides Config dataclass.
├── validator.py    ← URL validation, type detection, metadata extraction.
├── downloader.py   ← Core download logic wrapping yt-dlp.
├── tracker.py      ← Archive management, download reports.
├── transcoder.py   ← ffmpeg transcoding (single + batch).
├── updater.py      ← Incremental update logic.
└── utils.py        ← Path sanitization, directory helpers.
```

## Module Dependencies

```
cli.py
├── config.py
├── validator.py
├── downloader.py
│   ├── config.py
│   └── utils.py
├── tracker.py
│   └── downloader.py (DownloadResult type)
├── transcoder.py
│   └── config.py
└── updater.py
    ├── config.py
    ├── validator.py
    ├── downloader.py
    ├── tracker.py
    ├── transcoder.py
    └── utils.py
```

## Data Flow

### Download Workflow

```
URL
 │
 ▼
validate_url() ──→ Invalid? → Error
 │
 ▼
detect_url_type() → VIDEO / PLAYLIST / CHANNEL
 │
 ▼
extract_metadata() → title, video IDs, count
 │
 ▼
get_output_dir() → e.g. Videos/ChannelName/
 │
 ▼
VideoDownloader.download()
 ├── Video mode: downloads to _raw/ subdirectory
 │   format: bv[height<=1080]+ba/b → merged .mp4
 └── Audio mode: downloads directly to output dir
     format: ba/b → post-processed to .mp3
 │
 ▼
generate_report() → DownloadReport
 │
 ▼
[Video mode] batch_transcode()            ← runs unconditionally in video
 ├── Deletes stale *.part.mp4 (from       mode, so interrupted prior runs
 │   interrupted prior runs)               get picked up automatically.
 ├── Reads _raw/*.mp4
 ├── ffmpeg writes to <out>.part.mp4
 │   (H.264, CRF 25, ≤1080p, AAC)
 ├── Atomic rename → <out>.mp4 on success
 └── Removes raw file on success
 │
 ▼
save_report() → download_report.txt
```

### Update Workflow

```
URL (channel/playlist)
 │
 ▼
extract_metadata() → remote video ID list
 │
 ▼
load_archive() → local archived IDs
 │
 ▼
get_missing_videos() → new IDs
 │
 ▼
VideoDownloader.download_batch()
 │  (yt-dlp --download-archive skips existing)
 ▼
batch_transcode() [video mode only]
 │
 ▼
save_report()
```

## Folder Structure

```
{base_dir}/
├── Videos/
│   ├── {ChannelName}/
│   │   ├── _raw/                 ← Pre-transcode downloads (temporary)
│   │   │   └── Title [ID].mp4   ← Raw; removed after successful transcode
│   │   ├── Title [ID].mp4       ← Transcoded final file (always complete)
│   │   ├── Title [ID].part.mp4  ← Only present if a prior transcode was
│   │   │                           interrupted; auto-cleaned next run
│   │   ├── archive.txt          ← Downloaded video IDs
│   │   └── download_report.txt
│   ├── {PlaylistName}/
│   │   └── (same structure)
│   └── Misc/
│       └── (individual video downloads)
└── Audio/
    ├── {ChannelName}/
    │   ├── Title [ID].mp3
    │   ├── archive.txt
    │   └── download_report.txt
    ├── {PlaylistName}/
    │   └── (same structure)
    └── Misc/
        └── (individual audio downloads)
```

## Configuration

Config is loaded from `config.toml` with this precedence:
1. Explicit `--config` path (CLI flag)
2. `config.toml` in current working directory
3. `config.toml` in project root
4. Hardcoded defaults

Relative `base_dir` is resolved against the config file's parent directory.

## Archive Format

Each folder gets its own `archive.txt`. Format matches yt-dlp's archive format:

```
youtube dQw4w9WgXcQ
youtube abcdefghijk
```

One line per video: `{extractor} {video_id}`. This file is managed by yt-dlp directly via the `download_archive` option and is also read by the updater for incremental checks.

## Key Design Decisions

1. **Separate video+audio download**: yt-dlp's `bv+ba` format spec downloads the best video-only and audio-only streams, then merges with ffmpeg. This gets higher quality than pre-muxed formats.

2. **`_raw/` subdirectory + atomic rename**: Video downloads go to `_raw/` first, then ffmpeg transcodes to `<name>.part.mp4` in the parent directory (the `.part` marker precedes the extension because ffmpeg refuses a trailing `.part` as an unknown container). On successful exit the temp file is atomically renamed to `<name>.mp4` and only then is the raw removed. Invariants:
   - A file at the final path is always a complete transcode.
   - A leftover `.part.mp4` is always junk from an interrupted run — `batch_transcode` deletes them on startup and re-transcodes from raw.
   - The raw is removed only after rename succeeds, so an interrupted transcode never loses the source file.

   The transcode step runs on every download/update invocation regardless of whether yt-dlp reports anything new, so raws left behind by an interrupted prior run are automatically picked up. Users can also invoke it directly via `ytdl transcode --dir <path>`.

3. **Native language audio**: `format_sort: ['lang']` tells yt-dlp to prefer the original language audio track over dubbed/translated tracks.

4. **Per-folder archives**: Each channel/playlist/Misc folder has its own `archive.txt`. This makes incremental updates trivial and avoids any cross-contamination between different download targets.

5. **Never delete**: The updater only adds new content. Existing files are never removed, even if they've been deleted from YouTube. This preserves the user's collection.
