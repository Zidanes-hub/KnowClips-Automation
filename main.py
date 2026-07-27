#!/usr/bin/env python3
"""KnowClips YouTube Shorts Automation - entry point.

Usage:
  python main.py --mode scrape     # search + queue CC / write manual_review.txt
  python main.py --mode download   # download queued CC videos
  python main.py --mode manual     # download from manual_review.txt (approved)
  python main.py --mode clip       # cut highlight clips from downloads
  python main.py --mode brand      # add watermark + subtitles
  python main.py --mode upload     # schedule uploads to YouTube
  python main.py --mode all        # scrape -> download -> clip -> brand -> upload
"""
import os
import sys
import argparse

# Make src/ importable regardless of where the script is launched from
BASE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE, "src"))

from core.utils import load_config, setup_logger  # noqa: E402
from core import trending_scraper                       # noqa: E402
from core import downloader                             # noqa: E402
from core import auto_clipper                           # noqa: E402
from core import branding                               # noqa: E402
from core import upload_scheduler                       # noqa: E402

LOG = setup_logger("main")


def main():
    parser = argparse.ArgumentParser(description="KnowClips Automation")
    parser.add_argument(
        "--mode",
        choices=["scrape", "download", "manual", "clip", "brand", "upload", "all", "test_subtitle"],
        default="all",
        help="Pipeline step to run",
    )
    parser.add_argument(
        "--approve_first",
        action="store_true",
        help="Wait for user confirmation before downloading",
    )
    parser.add_argument(
        "--config",
        default=os.path.join(BASE, "config", "config.yaml"),
        help="Path to config file",
    )
    parser.add_argument(
        "--url",
        help="YouTube URL for manual mode",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the pipeline without actually downloading or uploading",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.mode == "manual":
        # Interactive bypass for a single URL
        url = args.url if args.url else input("Enter YouTube URL to process immediately: ").strip()
        if not url:
            LOG.error("No URL provided.")
            sys.exit(1)
            
        with open(cfg.get("manual_review_file", "manual_review.txt"), "w") as f:
            f.write(f"{url}\n")
            
        downloaded = downloader.run(cfg, source="manual")
        if not downloaded:
            LOG.warning(f"Berhenti: Video {url} gagal didownload.")
            sys.exit(0)
            
        clips = auto_clipper.run(cfg)
        if not clips:
            LOG.warning(f"Berhenti: Gagal menghasilkan klip AI untuk {url}.")
            sys.exit(0)
            
        branding.run(cfg)
        LOG.info(f"Manual processing for {url} complete!")
        sys.exit(0)

    if args.mode == "test_subtitle":
        LOG.info("=== STARTING SUBTITLE STYLE TEST ===")
        import glob, shutil
        from core.utils import storage_paths, run_cmd, find_ffmpeg
        import copy
        paths = storage_paths(cfg)
        ffmpeg = find_ffmpeg(cfg, "ffmpeg")
        downloads = glob.glob(os.path.join(paths["downloads"], "*.mp4"))
        if not downloads:
            LOG.error("No downloaded videos found in storage/downloads for testing.")
            sys.exit(1)
            
        source_video = downloads[0]
        base_clip = os.path.join(paths["output"], "base_test_clip.mp4")
        
        LOG.info(f"Extracting 10-second test clip from {os.path.basename(source_video)}")
        cmd = [ffmpeg, "-y", "-i", source_video, "-ss", "00:00:30", "-t", "10", "-c", "copy", base_clip]
        run_cmd(cmd, capture=True)
        
        styles = ["hormozi", "mrbeast", "mrbeast_karaoke", "neon", "karaoke"]
        for style in styles:
            LOG.info(f"--- Rendering Test Style: {style.upper()} ---")
            test_cfg = copy.deepcopy(cfg)
            test_cfg["subtitle_style"] = style
            test_cfg["watermark_text"] = f"STYLE {style.upper()}"
            
            style_clip = os.path.join(paths["clips"], f"test_subtitle_{style}.mp4")
            shutil.copy(base_clip, style_clip)
            
            branding.run(test_cfg)
            
        if os.path.exists(base_clip):
            os.remove(base_clip)
        LOG.info("Test complete! Check storage/output/ for the test_subtitle_*.mp4 files.")
        sys.exit(0)

    LOG.info(f"Mode: {args.mode}")

    if args.mode == "scrape":
        trending_scraper.run(cfg)
    elif args.mode == "download":
        if args.dry_run:
            LOG.info("DRY RUN: Skipping download.")
        else:
            downloader.run(cfg, source="queue", approve_first=args.approve_first)
    elif args.mode == "clip":
        if args.dry_run:
            LOG.info("DRY RUN: Skipping clip generation.")
        else:
            auto_clipper.run(cfg)
    elif args.mode == "brand":
        if args.dry_run:
            LOG.info("DRY RUN: Skipping branding.")
        else:
            branding.run(cfg)
    elif args.mode == "upload":
        if args.dry_run:
            LOG.info("DRY RUN: Skipping upload.")
        else:
            upload_scheduler.run(cfg)
    elif args.mode == "all":
        if args.dry_run:
            LOG.info("=== DRY RUN SIMULATION START ===")
            queued = trending_scraper.run(cfg)
            if queued:
                for q in queued:
                    LOG.info(f"DRY RUN: [Scraper] Memilih sumber: {q.get('source_channel')} - {q.get('title')}")
                
                num_clips = cfg.get("content_rules", {}).get("max_clips_per_source", 2)
                total_clips = len(queued) * num_clips
                LOG.info(f"DRY RUN: [Clipper] Akan memotong maksimal {num_clips} klip per video (Total ~{total_clips} klip).")
                LOG.info(f"DRY RUN: [Branding] Akan merender video vertikal dan membuat custom thumbnail (warna bervariasi).")
                LOG.info(f"DRY RUN: [Upload] Akan dijadwalkan 1 video per hari pada pukul {cfg.get('upload_schedule', {}).get('upload_time', '19:00')} WIB.")
            else:
                LOG.info("DRY RUN: Tidak ada video baru di queue.")
            LOG.info("=== DRY RUN SIMULATION END ===")
        else:
            trending_scraper.run(cfg)
            downloaded = downloader.run(cfg, source="queue")
            if downloaded:
                clips = auto_clipper.run(cfg)
                if clips:
                    branding.run(cfg)
                    upload_scheduler.run(cfg)

    LOG.info("Done.")


if __name__ == "__main__":
    main()
