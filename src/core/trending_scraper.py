"""Trending scraper: search YouTube via yt-dlp, filter by niche, auto-queue CC
videos for download, write non-CC candidates to manual_review.txt.

No API key needed - uses yt-dlp's ytsearch. Full metadata extraction is used
(not --flat-playlist) because license / view_count / upload_date are only
available with full extraction.
"""
import os
import sys
import json
from datetime import datetime, timezone
from core.utils import (
    load_config, setup_logger, read_json, write_json, run_cmd
)

LOG = setup_logger("scraper")


def parse_upload_date(raw):
    """yt-dlp upload_date is 'YYYYMMDD'. Return datetime or None."""
    if not raw:
        return None
    try:
        return datetime.strptime(str(raw), "%Y%m%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def is_creative_commons(v):
    """True if the video is Creative Commons licensed."""
    lic = (v.get("license") or "").lower()
    return "creative commons" in lic


def search_keyword(keyword, count):
    """Run a yt-dlp search, return list of full metadata dicts."""
    query = f"ytsearch{count}:{keyword}"
    LOG.info(f"Searching -> {query}")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "--dump-json",
        "--no-warnings",
        "--ignore-errors",
        "--no-check-certificate",
        "--extractor-args", "youtube:player_client=android,ios,web",
        query,
    ]
    result = run_cmd(cmd, capture=True)
    videos = []
    for line in (result.stdout or "").strip().splitlines():
        try:
            videos.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if not videos and result.returncode != 0:
        LOG.warning(f"Search issue for '{keyword}': {(result.stderr or '')[:150]}")
    return videos


def passes_filters(v, cfg, now):
    """Return (ok, reason). Applies duration/views/recency filters."""
    dur = v.get("duration") or 0
    if dur < cfg["min_duration"]:
        return False, f"too short ({dur}s)"
    if dur > cfg["max_duration"]:
        return False, f"too long ({dur}s)"

    views = v.get("view_count") or 0
    if views < cfg["min_views"]:
        return False, f"low views ({views})"

    up = parse_upload_date(v.get("upload_date"))
    if up is not None:
        age_days = (now - up).days
        if age_days > cfg["upload_within_days"]:
            return False, f"too old ({age_days}d)"
    return True, "ok"


def append_manual_review(path, entry):
    """Append one non-CC candidate: 'id | title | url'."""
    line = f"{entry['id']} | {entry['title']} | {entry['url']}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def run(cfg):
    """Main scrape routine. Returns list of CC videos queued for download."""
    now = datetime.now(timezone.utc)

    search_log = read_json(cfg["search_log_file"], {"seen_ids": [], "downloaded_ids": []})
    seen = set(search_log.get("seen_ids", []))
    downloaded = set(search_log.get("downloaded_ids", []))

    cc_new, non_cc_new = [], []

    for kw in cfg["keywords"]:
        for v in search_keyword(kw, cfg["search_count"]):
            vid = v.get("id")
            if not vid or vid in seen:
                continue
            seen.add(vid)

            ok, reason = passes_filters(v, cfg, now)
            if not ok:
                LOG.debug(f"skip {vid}: {reason}")
                continue

            entry = {
                "id": vid,
                "title": (v.get("title") or "").strip(),
                "url": v.get("webpage_url") or f"https://youtu.be/{vid}",
                "duration": v.get("duration"),
                "view_count": v.get("view_count"),
                "upload_date": v.get("upload_date"),
                "keyword": kw,
                "license": v.get("license"),
                "is_cc": is_creative_commons(v),
            }
            (cc_new if entry["is_cc"] else non_cc_new).append(entry)

    cc_new.sort(key=lambda e: e.get("view_count") or 0, reverse=True)
    LOG.info(f"New candidates -> CC: {len(cc_new)} | non-CC: {len(non_cc_new)}")

    # Non-CC -> manual review file (skip anything already downloaded)
    manual_added = 0
    for e in non_cc_new:
        if e["id"] not in downloaded:
            append_manual_review(cfg["manual_review_file"], e)
            manual_added += 1
    if manual_added:
        LOG.info(f"Wrote {manual_added} non-CC videos to {cfg['manual_review_file']}")

    # Top-N CC -> download queue
    to_download = [e for e in cc_new if e["id"] not in downloaded][: cfg["auto_download_top_cc"]]
    write_json(cfg["queue_file"], to_download)
    if to_download:
        LOG.info(f"Queued {len(to_download)} CC videos in {cfg['queue_file']}:")
        for e in to_download:
            LOG.info(f"  - {e['id']} | {e['title'][:55]} | {e['view_count']} views")
    else:
        LOG.info("No new CC videos to auto-download this run.")

    # Persist dedupe log
    search_log["seen_ids"] = sorted(seen)
    search_log["downloaded_ids"] = sorted(downloaded)
    write_json(cfg["search_log_file"], search_log)
    LOG.info(f"Updated {cfg['search_log_file']} ({len(seen)} ids seen total)")

    return to_download


def main():
    cfg = load_config()
    run(cfg)


if __name__ == "__main__":
    main()
