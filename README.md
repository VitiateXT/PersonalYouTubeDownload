# YouTube Downloader

Download YouTube videos or audio from:
- a single video URL
- a playlist URL
- a channel URL

It can also download University of Oxford podcast series (audio, with optional captions).

Video downloads are capped at 1080p (or lower if source is lower), merged with audio, and then transcoded.

## What This Does

- Downloads video and audio streams separately, then merges them
- Downloads audio-only when you choose audio mode
- Uses a folder structure by source type:
	- `Videos/<ChannelName>/...`
	- `Videos/<PlaylistName>/...`
	- `Videos/Misc/...` for individual video URLs
	- `Audio/<ChannelName>/...`
	- `Audio/<PlaylistName>/...`
	- `Audio/Misc/...` for individual audio URLs
- Keeps per-folder archives so reruns only fetch missing/new content
- Writes `download_report.txt` with success/failure/skipped details

## Installation

### 1) Install prerequisites

- Python 3.11+
- ffmpeg
- conda (recommended for easiest setup)

Install ffmpeg:

```bash
# Ubuntu/Debian
sudo apt update
sudo apt install ffmpeg
```

### 2) Clone and install

```bash
git clone <your-repo-url>
cd YouTubeDownloader

conda create -n ytdl python=3.11 -y
conda activate ytdl

pip install -e .
```

## Script Usage (Recommended)

All scripts are in the `scripts/` directory and accept exactly one URL argument.

```bash
cd scripts
```

### Video scripts

```bash
./download_video.sh "https://www.youtube.com/watch?v=<VIDEO_ID>"
./download_playlist_video.sh "https://www.youtube.com/playlist?list=<PLAYLIST_ID>"
./download_channel_video.sh "https://www.youtube.com/@<CHANNEL_HANDLE>"
```

### Audio-only scripts

```bash
./download_audio.sh "https://www.youtube.com/watch?v=<VIDEO_ID>"
./download_playlist_audio.sh "https://www.youtube.com/playlist?list=<PLAYLIST_ID>"
./download_channel_audio.sh "https://www.youtube.com/@<CHANNEL_HANDLE>"
```

### Oxford Podcasts

Pass a series page (or its "Audio RSS Feed" link) from <https://podcasts.ox.ac.uk>:

```bash
./download_oxford_podcast.sh "https://podcasts.ox.ac.uk/series/strachey-lectures"
# or, equivalently:
ytdl download --url "https://podcasts.ox.ac.uk/series/strachey-lectures"
```

- Podcasts are audio-only; `--mode` and `--type` are ignored for Oxford URLs.
- Episodes are saved as `Audio/<Series>/YYYY-MM-DD <Title>.mp3`.
- Rerunning (`download` or `update`) only fetches episodes not yet in `archive.txt`.
- Most series offer `.srt` captions, handy for shadowing practice (listen, read, and
  repeat along). They are off by default; enable them in `config.toml`:

```toml
[oxford]
captions = true   # saves "<episode>.srt" next to each mp3
delay = 1.5       # seconds between downloads
```

Oxford states that the content is free to download and listen to; check their copyright
page before using it for anything beyond personal listening.

## Important URL Rules

If your URL contains `&`, quote it or escape it.

```bash
# Good (quoted)
./download_playlist_video.sh "https://www.youtube.com/watch?v=QBH6IpRkVDs&list=PL..."

# Good (escaped)
./download_playlist_video.sh https://www.youtube.com/watch?v=QBH6IpRkVDs\&list=PL...
```

Without quoting/escaping, shell treats `&` as a control operator and breaks the command.

Playlist detection accepts any valid YouTube URL containing `list=` (for example `playlist?list=...`, `watch?list=...`, or `watch?v=...&list=...`).

## CLI Usage (Optional)

You can also use the CLI directly:

```bash
ytdl download --url "https://www.youtube.com/watch?v=<VIDEO_ID>" --mode video
ytdl download --url "https://www.youtube.com/playlist?list=<PLAYLIST_ID>" --mode audio
ytdl update --url "https://www.youtube.com/@<CHANNEL_HANDLE>" --mode video
ytdl download --url "https://podcasts.ox.ac.uk/series/<SERIES_NAME>"
ytdl transcode --dir "Videos/Misc"
```

## Configuration

The project uses a single configuration file: `config.toml`.

Use it to set output location, download limits, retry/sleep behavior, and
transcoding quality.

Example:

```toml
[general]
base_dir = "."

[transcode]
max_resolution = 1080
codec = "libx264"
crf = 25
audio_codec = "aac"
preset = "medium"
```

## Output Structure

Generated folders:

```text
Videos/
Audio/
```

Each channel/playlist/misc folder contains:
- media files
- `archive.txt` (download history)
- `download_report.txt`

Video folders may temporarily contain `_raw/` while transcoding is running.

## License

This project is licensed under the MIT License. See `LICENSE`.
