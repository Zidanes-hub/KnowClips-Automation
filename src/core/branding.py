"""Branding: add a 'KnowClips' text watermark and burn Whisper subtitles.

Pipeline per clip:
1. Whisper transcribes audio -> a temp .srt with a SIMPLE name.
2. ffmpeg (run with cwd = clips dir) burns subtitles + draws the watermark,
   writing the result to output/.

Notes on Windows robustness:
- The `subtitles=` filter chokes on paths containing spaces / [] / drive colon,
  so we write the .srt under a simple name (__sub.srt) and run ffmpeg from that
  directory, referencing it by bare filename.
- `drawtext` needs an explicit `fontfile` because this ffmpeg build has no
  Fontconfig default config; we point it at a Windows system font.
"""
import os
import glob
from core.utils import load_config, setup_logger, storage_paths, find_ffmpeg, run_cmd

LOG = setup_logger("branding")

_WHISPER = None
_TMP_ASS = "__sub.ass"  # simple name used inside the clips dir


def _find_font(cfg):
    """Return the path to the downloaded Montserrat Black font."""
    font_dir = os.path.join(cfg.get("storage_dir", "storage"), "fonts")
    p = os.path.join(font_dir, "Montserrat-Black.ttf")
    if os.path.exists(p):
        return p
    return None


def _font_for_filter(path):
    """Escape a Windows font path for use inside an ffmpeg filter value."""
    # C:\Windows\Fonts\arialbd.ttf -> C\:/Windows/Fonts/arialbd.ttf
    return path.replace("\\", "/").replace(":", "\\:")


def _load_whisper(model_name):
    global _WHISPER
    if _WHISPER is not None:
        return _WHISPER
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        LOG.error("faster-whisper not installed. Run: pip install faster-whisper")
        return None
    LOG.info(f"Loading Faster-Whisper model '{model_name}' (first run downloads weights)...")
    
    # Use CPU by default for broader compatibility, int8 for speed
    # Use CPU explicitly to prevent CUDA hang on Windows initialization
    _WHISPER = WhisperModel(model_name, device="cpu", compute_type="int8")
    return _WHISPER


def _fmt_ts(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def transcribe_to_ass(model, video, ass_path, font_path, style="hormozi"):
    """Transcribe audio with word-level timestamps and write an .ass file."""
    try:
        segments, info = model.transcribe(video, word_timestamps=True)
        # faster-whisper returns a generator, consume it to get all segments
        segs = list(segments)
    except Exception as e:
        LOG.error(f"Whisper failed on {os.path.basename(video)}: {e}")
        return False
    if not segs:
        return False
        
    try:
        from core.ass_maker import generate_ass
        generate_ass(segs, ass_path, font_path, style=style)
    except Exception as e:
        LOG.error(f"Failed to generate ASS subtitles: {e}")
        return False
    return True


def brand_clip(video, out_path, work_dir, has_ass, watermark, font_path, ffmpeg):
    """Burn animated ASS subtitles (if any) + watermark."""
    filters = ["scale='iw*max(1080/iw,1920/ih)':'ih*max(1080/iw,1920/ih)',crop=1080:1920"]
    if has_ass:
        # Use fontsdir to let FFmpeg find the font from storage/fonts
        font_dir = os.path.dirname(font_path) if font_path else ""
        if font_dir:
            font_dir_escaped = font_dir.replace("\\", "/").replace(":", "\\:")
            filters.append(f"ass={_TMP_ASS}:fontsdir='{font_dir_escaped}'")
        else:
            filters.append(f"ass={_TMP_ASS}")
            
    dt = (f"drawtext=text='{watermark}':fontcolor=white@0.9:fontsize=42:"
          "x=w-tw-30:y=30:box=1:boxcolor=black@0.35:boxborderw=8")
    if font_path:
        dt = f"drawtext=fontfile='{_font_for_filter(font_path)}':" + dt[len("drawtext="):]
    filters.append(dt)
    vf = ",".join(filters)

    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", video,
           "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "copy", out_path]
    LOG.info(f"Branding -> {os.path.basename(out_path)}")
    r = run_cmd(cmd, capture=True, cwd=work_dir)
    if r.returncode != 0:
        LOG.error(f"ffmpeg branding failed: {(r.stderr or '')[:300]}")
        return False
    return True


def auto_thumbnail(video, out_path, work_dir, title, font_path, ffmpeg, clip_index=1):
    """Generate a custom thumbnail with text hook from the 5th second."""
    import re
    # Ambil 4 kata pertama dari judul sebagai hook
    words = title.split()[:4]
    hook_text = " ".join(words).upper()
    hook_text = re.sub(r'[\'"]', '', hook_text) # bersihkan tanda kutip
    
    # Resolusi 1280x720 (Thumbnail YouTube standar)
    # Gunakan font Bebas Neue, Anton, atau fallback ke Impact
    font = font_path if font_path else "C\\:/Windows/Fonts/impact.ttf"
    
    # Variasi warna teks berdasarkan clip_index
    text_color = "white" if clip_index == 1 else "#FFD700"
    
    # Filter FFmpeg: scale/crop ke 1280x720, lalu drawtext besar di tengah-bawah
    vf = (
        "scale=1280:720:force_original_aspect_ratio=increase,"
        "crop=1280:720,"
        f"drawtext=fontfile='{_font_for_filter(font)}':text='{hook_text}':"
        f"fontsize=120:fontcolor={text_color}:borderw=8:bordercolor=black:"
        "x=(w-text_w)/2:y=h-text_h-100:shadowcolor=black:shadowx=5:shadowy=5"
    )
    
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", 
           "-ss", "00:00:05", "-i", video, "-vframes", "1", 
           "-vf", vf, "-q:v", "2", out_path]
           
    r = run_cmd(cmd, capture=True, cwd=work_dir)
    if r.returncode != 0:
        LOG.error(f"ffmpeg auto_thumbnail failed: {(r.stderr or '')[:300]}")
        return False
    LOG.info(f"Auto Thumbnail -> {os.path.basename(out_path)}")
    return True



def run(cfg):
    paths = storage_paths(cfg)
    ffmpeg = find_ffmpeg(cfg, "ffmpeg")
    if not ffmpeg:
        LOG.error("ffmpeg not found. Install ffmpeg or set ffmpeg_path in config.yaml.")
        return []

    # Whisper shells out to `ffmpeg` via PATH to load audio; make sure it's there.
    ff_dir = os.path.dirname(ffmpeg)
    if ff_dir and ff_dir not in os.environ.get("PATH", ""):
        os.environ["PATH"] = ff_dir + os.pathsep + os.environ.get("PATH", "")

    clips = glob.glob(os.path.join(paths["clips"], "*.mp4"))
    if not clips:
        LOG.info(f"No clips to brand in {paths['clips']}")
        return []

    enable_subtitles = cfg.get("enable_subtitles", False)
    
    model = None
    if enable_subtitles:
        model = _load_whisper(cfg.get("whisper_model", "tiny"))
        
    watermark = cfg.get("watermark_text", "KnowClips")
    subtitle_style = cfg.get("subtitle_style", "hormozi")
    font_path = _find_font(cfg)
    if not font_path:
        LOG.warning("Montserrat-Black font not found in storage/fonts. Ensure it is downloaded.")

    work_dir = paths["clips"]
    tmp_ass = os.path.join(work_dir, _TMP_ASS)

    made = []
    for clip in clips:
        stem = os.path.splitext(os.path.basename(clip))[0]
        out_path = os.path.join(paths["output"], stem + "_branded.mp4")
        if os.path.exists(out_path):
            LOG.info(f"Skip {stem} - Sudah ada file _branded.mp4 di output.")
            continue
            
        has_ass = False
        if model is not None:
            has_ass = transcribe_to_ass(model, clip, tmp_ass, font_path, style=subtitle_style)
            
        if brand_clip(clip, out_path, work_dir, has_ass, watermark, font_path, ffmpeg):
            made.append(out_path)
            
            # Generate Auto Thumbnail
            # Buat direktori thumbnails jika belum ada
            thumb_dir = os.path.join(cfg.get("storage_dir", "storage"), "thumbnails")
            os.makedirs(thumb_dir, exist_ok=True)
            thumb_path = os.path.join(thumb_dir, stem + "_thumbnail.jpg")
            
            # Cari judul dari metadata json jika ada
            meta_path = os.path.join(work_dir, f"{stem}_metadata.json")
            title = stem
            clip_index = 1
            if os.path.exists(meta_path):
                import json
                try:
                    with open(meta_path, 'r', encoding='utf-8') as f:
                        meta = json.load(f)
                        title = meta.get("title", stem)
                        clip_index = meta.get("clip_index", 1)
                except Exception:
                    pass
            
            auto_thumbnail(out_path, thumb_path, work_dir, title, None, ffmpeg, clip_index) # Use Impact natively

            # Auto-cleanup: hapus klip mentah agar tidak menumpuk dan diulang
            try:
                os.remove(clip)
            except Exception as e:
                LOG.warning(f"Gagal menghapus klip mentah {clip}: {e}")
                
        if os.path.exists(tmp_ass):
            os.remove(tmp_ass)

    LOG.info(f"Branded {len(made)} clip(s) into {paths['output']}")
    return made


def main():
    cfg = load_config()
    run(cfg)


if __name__ == "__main__":
    main()
