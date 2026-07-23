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
        choices=["scrape", "download", "manual", "clip", "brand", "upload", "all"],
        required=True,
        help="Action mode to run",
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
    args = parser.parse_args()

    cfg = load_config(args.config)

    if args.mode == "manual":
        # Interactive bypass for a single URL
        url = input("Enter YouTube URL to process immediately: ").strip()
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

    LOG.info(f"Mode: {args.mode}")

    if args.mode == "scrape":
        trending_scraper.run(cfg)
    elif args.mode == "download":
        downloader.run(cfg, source="queue", approve_first=args.approve_first)
    elif args.mode == "clip":
        auto_clipper.run(cfg)
    elif args.mode == "brand":
        branding.run(cfg)
    elif args.mode == "upload":
        upload_scheduler.run(cfg)
    elif args.mode == "all":
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
