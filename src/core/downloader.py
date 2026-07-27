"""Downloader: download queued CC videos (or manually approved ones) via yt-dlp.
Reads queue.json (from the scraper) and records downloaded ids in search_log.json
so the same video is never fetched twice.
"""
import os
import sys
import json
from core.utils import (
    load_config, setup_logger, read_json, write_json, storage_paths, run_cmd, find_ffmpeg
)

LOG = setup_logger("downloader")


def load_manual_approved(path):
    """Parse manual_review.txt lines 'id | title | url' into dicts."""
    out = []
    if not os.path.exists(path):
        return out
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "|" in line:
                parts = [p.strip() for p in line.split("|", 2)]
                if len(parts) == 3 and parts[0]:
                    out.append({"id": parts[0], "title": parts[1], "url": parts[2]})
            else:
                # Raw URL directly from prompt
                vid_id = line.split("/")[-1].split("?")[0].replace("watch", "")
                out.append({"id": vid_id, "title": "Manual Entry", "url": line})
    return out


def probe_duration(url):
    """Return video duration in seconds via yt-dlp (no download), or 0."""
    cmd = [sys.executable, "-m", "yt_dlp", "--no-warnings", "--skip-download",
           "--socket-timeout", "30", "--js-runtimes", "node",
           "--cookies", "cookies.txt",
           "--extractor-args", "youtube:player_client=android,ios,web",
           "--print", "%(duration)s", url]
    r = run_cmd(cmd, capture=True)
    try:
        return int(float((r.stdout or "0").strip().splitlines()[0]))
    except (ValueError, IndexError):
        return 0


def pick_longest(videos):
    """Probe durations, return the single longest video dict (with 'duration')."""
    best = None
    for v in videos:
        dur = probe_duration(v.get("url") or f"https://youtu.be/{v['id']}")
        v["duration"] = dur
        mins = dur // 60
        LOG.info(f"  {v['id']} -> {mins}m{dur % 60:02d}s | {v.get('title','')[:45]}")
        if best is None or dur > best["duration"]:
            best = v
    return best


def check_subtitles(url, target_lang="id"):
    """Return True if the video has automatic or manual subtitles (VTT)."""
    LOG.info(f"Checking subtitles for {url}...")
    cmd = [
        sys.executable, "-m", "yt_dlp", "--dump-json", "--no-warnings", 
        "--skip-download", "--socket-timeout", "30", "--js-runtimes", "node", "--cookies", "cookies.txt",
        "--extractor-args", "youtube:player_client=android,ios,web", url
    ]
    r = run_cmd(cmd, capture=True)
    if r.returncode != 0:
        return False
    try:
        data = json.loads(r.stdout)
        subs = data.get("subtitles", {})
        auto_subs = data.get("automatic_captions", {})
        
        # Cek apakah bahasa target kita tersedia
        if target_lang in subs or target_lang in auto_subs:
            return True
        return False
    except Exception:
        return False


def download_one(entry, dest_dir, cfg, ffmpeg_bin=None):
    """Download a single video into dest_dir. Returns True on success."""
    url = entry.get("url") or f"https://youtu.be/{entry['id']}"
    target_lang = cfg.get("target_language", "id")
    


    out_tpl = os.path.join(dest_dir, "%(title).80s [%(id)s].%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/bestvideo[height<=720]+bestaudio[ext=m4a]/best[height<=720]",
        "--merge-output-format", "mp4",
        "--no-warnings",
        "--no-check-certificate",
        "--socket-timeout", "30",
        "--js-runtimes", "node",
        "--cookies", "cookies.txt",
        "--retries", "3",
        "--write-info-json",
        "--write-auto-subs",
        "--sub-format", "vtt",
        "--sub-langs", "id,en",
        "--ignore-errors",
        "-o", out_tpl,
    ]
    if ffmpeg_bin:
        cmd.extend(["--ffmpeg-location", ffmpeg_bin])
    else:
        import shutil
        sys_ffmpeg = shutil.which("ffmpeg")
        if sys_ffmpeg:
            cmd.extend(["--ffmpeg-location", os.path.dirname(sys_ffmpeg)])
        else:
            LOG.error("ffmpeg tidak ditemukan! Install ffmpeg dulu.")
            return False
    cmd.append(url)
    LOG.info(f"Downloading {entry['id']}: {entry.get('title', '')[:55]}")
    result = run_cmd(cmd, capture=False)
    if result.returncode != 0:
        LOG.error(f"Failed {entry['id']} (see console for details)")
        return False
    return True


def run(cfg, source="queue", approve_first=False):
    """Download from 'queue' (queue.json) or 'manual' (manual_review.txt).

    approve_first: from manual_review.txt, probe durations and download ONLY
    the single longest video (most material to clip).
    """
    paths = storage_paths(cfg)
    dest = paths["downloads"]

    if approve_first:
        candidates = load_manual_approved(cfg["manual_review_file"])
        LOG.info(f"Probing durations of {len(candidates)} manual candidates...")
        best = pick_longest(candidates) if candidates else None
        if not best:
            LOG.info("No candidates in manual_review.txt.")
            return []
        LOG.info(f"Longest = {best['id']} ({best['duration'] // 60}m{best['duration'] % 60:02d}s) -> downloading")
        videos = [best]
    elif source == "manual":
        videos = load_manual_approved(cfg["manual_review_file"])
        LOG.info(f"Loaded {len(videos)} manually approved videos")
    else:
        videos = read_json(cfg["queue_file"], [])
        LOG.info(f"Loaded {len(videos)} queued videos")

    if not videos:
        LOG.info("Nothing to download.")
        return []

    search_log = read_json(cfg["search_log_file"], {"seen_ids": [], "downloaded_ids": []})
    downloaded = set(search_log.get("downloaded_ids", []))

    # Resolve ffmpeg binary so yt-dlp can merge video+audio into one mp4
    ffmpeg_bin = find_ffmpeg(cfg, "ffmpeg")
    if not ffmpeg_bin:
        LOG.warning("ffmpeg not found - downloads may not merge into a single mp4.")

    done = []
    for entry in videos:
        vid = entry.get("id")
        if not vid or vid in downloaded:
            LOG.info(f"Skip {vid} (already downloaded)")
            continue
        if download_one(entry, dest, cfg, ffmpeg_bin):
            downloaded.add(vid)
            done.append(entry)

    search_log["downloaded_ids"] = sorted(downloaded)
    write_json(cfg["search_log_file"], search_log)
    LOG.info(f"Downloaded {len(done)} new video(s) into {dest}")
    return done


def main():
    cfg = load_config()
    run(cfg, source="queue")


if __name__ == "__main__":
    main()
