"""Shared helpers: config, logging, JSON, ffmpeg discovery, paths."""
import os
import sys
import json
import shutil
import logging
import subprocess

try:
    import yaml
except ImportError:
    print("PyYAML not installed. Run: python -m pip install -r requirements.txt")
    sys.exit(1)


def load_config(path="config.yaml"):
    """Load flat YAML config into a dict."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def storage_paths(cfg):
    """Return a dict of resolved storage subdirectories, creating them."""
    base = cfg.get("storage_dir") or os.path.join(os.getcwd(), "storage")
    paths = {
        "base": base,
        "downloads": os.path.join(base, "downloads"),
        "clips": os.path.join(base, "clips"),
        "output": os.path.join(base, "output"),
    }
    for p in paths.values():
        os.makedirs(p, exist_ok=True)
    return paths


def find_ffmpeg(cfg, tool="ffmpeg"):
    """Return a usable ffmpeg/ffprobe path (config value, else PATH)."""
    key = "ffmpeg_path" if tool == "ffmpeg" else "ffprobe_path"
    configured = (cfg.get(key) or "").strip()
    if configured and os.path.exists(configured):
        return configured
    found = shutil.which(tool)
    if found:
        return found
    return None  # caller decides whether this is fatal


def setup_logger(name="knowclips"):
    """Return a configured console logger (idempotent)."""
    # Force UTF-8 on the console so emoji / non-ASCII titles never crash logging
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    logger = logging.getLogger(name)
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    )
    logger.addHandler(handler)
    logger.propagate = False
    return logger


def read_json(path, default=None):
    """Load JSON file, returning `default` if missing/corrupt."""
    if not os.path.exists(path):
        return default if default is not None else {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return default if default is not None else {}


def write_json(path, data):
    """Write data to a JSON file (pretty, UTF-8)."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def run_cmd(cmd, capture=True, cwd=None):
    """Run a subprocess (list of args). Returns CompletedProcess."""
    return subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=cwd,
    )
