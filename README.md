# KnowClips YouTube Shorts Automation

Automation pipeline for creating YouTube Shorts from podcast clips, investor talks, science videos, and technology content.

## Features
- Auto-download and clip YouTube videos with CC license or manual approval
- Intelligent trending video discovery
- Audio-based clip segmentation (45-58s)
- Auto watermarking with "KnowClips" and subtitles
- Scheduled publishing to YouTube
- Configurable through YAML

## Prerequisites
- Windows 10/11
- Python 3.8+
- yt-dlp (bundled)
- ffmpeg (Windows build)
- Python dependencies (see requirements.txt)
- Google Cloud project with YouTube Data API v3 enabled

## Setup
1. Install dependencies:
```powershell
python -m pip install -r requirements.txt
```

2. Set up ffmpeg: Install to `C:\ffmpeg\bin\ffmpeg.exe` or modify `ffmpeg_path` in config.yaml
   (download: https://www.gyan.dev/ffmpeg/builds/ — get the "full" build)

3. Set up yt-dlp: `python -m pip install yt-dlp` (already in requirements.txt) — no separate exe needed

4. Edit `config.yaml` with your preferences

5. YouTube API: place your `client_secret.json` (OAuth desktop credentials) in the project root

## Usage
Run the main script to start the pipeline:

```powershell
python main.py --config config.yaml --mode all
```

Use `--mode` to run specific components:
- `--mode downloader` - just download videos
- `--mode clipper` - process clips
- `--mode brand` - add watermark and subtitles
- `--mode upload` - process uploads
- `--mode all` - run entire pipeline

## Configuration
Edit `config.yaml` to customize:
- Licensing preferences (CC only vs manual review)
- Clip duration timing
- Search keywords and filters
- Upload scheduling parameters
- API credentials location