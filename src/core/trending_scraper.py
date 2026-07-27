"""Trending scraper: search YouTube via yt-dlp, filter by niche, auto-queue CC
videos for download, write non-CC candidates to manual_review.txt.

No API key needed - uses yt-dlp's ytsearch. Full metadata extraction is used
(not --flat-playlist) because license / view_count / upload_date are only
available with full extraction.
"""
import os
import sys
import json
from datetime import datetime, timezone, timedelta
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


def passes_filters(v, scraper_cfg, now):
    """Return (ok, reason). Applies duration/views/recency filters."""
    dur = v.get("duration") or 0
    if dur < scraper_cfg.get("min_duration_seconds", scraper_cfg.get("min_duration", 300)):
        return False, f"too short ({dur}s)"
    if dur > scraper_cfg.get("max_duration_seconds", scraper_cfg.get("max_duration", 7200)):
        return False, f"too long ({dur}s)"

    views = v.get("view_count") or 0
    if views < scraper_cfg.get("min_views", 10000):
        return False, f"low views ({views})"

    up = parse_upload_date(v.get("upload_date"))
    if up is not None:
        age_days = (now - up).days
        if age_days > scraper_cfg.get("upload_within_days", 30):
            return False, f"too old ({age_days}d)"
    return True, "ok"


def append_manual_review(path, entry):
    """Append one non-CC candidate: 'id | title | url | source_channel'."""
    line = f"{entry['id']} | {entry['title']} | {entry['url']} | {entry.get('source_channel', 'Unknown')}\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def run(cfg):
    """Main scrape routine. Returns list of CC videos queued for download."""
    now = datetime.now(timezone.utc)

    search_log = read_json(cfg["search_log_file"], {"seen_ids": [], "downloaded_ids": []})
    seen = set(search_log.get("seen_ids", []))
    downloaded = set(search_log.get("downloaded_ids", []))
    
    upload_state = read_json("upload_state.json", {})
    sources_used = upload_state.get("sources_used", {})
    
    wib_tz = timezone(timedelta(hours=7))
    today_date = now.astimezone(wib_tz).date()
    min_gap_days = cfg.get("content_rules", {}).get("min_gap_same_source_days", 5)

    cc_new, non_cc_new = [], []
    cooldown_count = 0
    
    scraper_cfg = cfg.get("scraper", {})
    keywords = scraper_cfg.get("keywords", [])

    for kw in keywords:
        for v in search_keyword(kw, cfg["search_count"]):
            vid = v.get("id")
            if not vid or vid in seen:
                continue
            seen.add(vid)

            ok, reason = passes_filters(v, scraper_cfg, now)
            if not ok:
                LOG.debug(f"skip {vid}: {reason}")
                continue

            source_channel = v.get("channel") or v.get("uploader") or "Unknown"
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
                "source_channel": source_channel,
                "on_cooldown": False
            }
            
            # Check rotation logic
            last_used_date_str = sources_used.get(source_channel)
            if last_used_date_str:
                last_used_date = datetime.strptime(last_used_date_str, "%Y-%m-%d").date()
                if (today_date - last_used_date).days < min_gap_days:
                    entry["on_cooldown"] = True
                    cooldown_count += 1
            
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

    # Top-N CC -> download queue (Prioritize non-cooldown)
    fresh_cc = [e for e in cc_new if e["id"] not in downloaded and not e["on_cooldown"]]
    cooldown_cc = [e for e in cc_new if e["id"] not in downloaded and e["on_cooldown"]]
    
    if len(fresh_cc) == 0 and len(cooldown_cc) > 0:
        LOG.warning("Warning: Source pool depleted. Consider adding new sources to config.")
        
    to_download = (fresh_cc + cooldown_cc)[: cfg["auto_download_top_cc"]]
    
    write_json(cfg["queue_file"], to_download)
    if to_download:
        LOG.info(f"Queued {len(to_download)} CC videos in {cfg['queue_file']}:")
        for e in to_download:
            cooldown_status = "[COOLDOWN]" if e["on_cooldown"] else "[FRESH]"
            LOG.info(f"  - {cooldown_status} {e['source_channel']} | {e['id']} | {e['title'][:40]} | {e['view_count']} views")
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
