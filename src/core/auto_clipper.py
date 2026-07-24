"""Auto clipper: cut clips from source videos using YouTube Heatmap and VTT transcript
to find the most viral and perfectly cut sentences via Gemini AI.
"""
import os
import glob
import json
import re
import logging
import matplotlib.pyplot as plt
from core.utils import load_config, setup_logger, storage_paths, find_ffmpeg, run_cmd
from core.gemini_analyzer import init_gemini, find_best_cut

LOG = setup_logger("clipper")

def parse_vtt(vtt_path):
    """Parse VTT file into a list of dicts: [{'start': 0.0, 'end': 2.0, 'text': '...'}, ...]"""
    if not os.path.exists(vtt_path):
        return []
    
    with open(vtt_path, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = content.split('\n\n')
    parsed = []
    
    # Regex to match VTT timestamps: 00:00:00.000 --> 00:00:02.000
    ts_re = re.compile(r'(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})')
    
    def ts_to_sec(ts_str):
        h, m, s = ts_str.split(':')
        sec, ms = s.split('.')
        return int(h) * 3600 + int(m) * 60 + int(sec) + int(ms) / 1000.0

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2: continue
        
        ts_match = None
        text_lines = []
        for line in lines:
            if ts_re.search(line):
                ts_match = ts_re.search(line)
            elif not line.startswith('WEBVTT') and '-->' not in line and not line.isdigit():
                text_lines.append(line.strip())
        
        if ts_match and text_lines:
            start = ts_to_sec(ts_match.group(1))
            end = ts_to_sec(ts_match.group(2))
            text = " ".join(text_lines).strip()
            # Remove VTT tags like <c> or <00:00:01.000>
            text = re.sub(r'<[^>]+>', '', text)
            if text:
                parsed.append({"start": start, "end": end, "text": text})
                
    return parsed

def get_vtt_chunk(parsed_vtt, start_sec, end_sec):
    """Get VTT text block within a time range."""
    lines = []
    for item in parsed_vtt:
        if item['end'] >= start_sec and item['start'] <= end_sec:
            lines.append(f"[{item['start']:.3f} - {item['end']:.3f}] {item['text']}")
    return "\n".join(lines)

def plot_heatmap(heatmap, out_png):
    """Generate a visual graph of the heatmap."""
    if not heatmap: return
    x = [(h['start_time'] + h['end_time'])/2 for h in heatmap]
    y = [h['value'] for h in heatmap]
    
    plt.figure(figsize=(10, 4))
    plt.plot(x, y, color='purple', label='Heatmap (Most Replayed)')
    plt.fill_between(x, y, color='purple', alpha=0.3)
    plt.title('YouTube Most Replayed Heatmap')
    plt.xlabel('Time (seconds)')
    plt.ylabel('Replay Intensity')
    plt.grid(True, alpha=0.5)
    plt.tight_layout()
    plt.savefig(out_png)
    plt.close()

def find_heatmap_peaks(heatmap, num_peaks, min_dist=60):
    """Find top N peaks in the heatmap that are at least min_dist seconds apart."""
    sorted_hm = sorted(heatmap, key=lambda x: x['value'], reverse=True)
    peaks = []
    
    for h in sorted_hm:
        time_center = (h['start_time'] + h['end_time']) / 2
        # Check distance to existing peaks
        if all(abs(time_center - p) >= min_dist for p in peaks):
            peaks.append(time_center)
        if len(peaks) >= num_peaks:
            break
    return sorted(peaks)

def analyze_speech_density(parsed_vtt, duration, window_size=60, step=10):
    """
    Menghitung kepadatan kata (speech density) per sliding window.
    Mengembalikan data format Heatmap buatan sendiri: [{'start_time': t, 'value': density}]
    """
    density_data = []
    
    # Pre-calculate words and their timestamps
    words_data = []
    for block in parsed_vtt:
        words = block['text'].split()
        if not words: continue
        time_per_word = (block['end'] - block['start']) / len(words)
        for i in range(len(words)):
            words_data.append(block['start'] + (i * time_per_word))
            
    # Sliding window
    for t in range(0, int(duration) - window_size + 1, step):
        window_end = t + window_size
        # Hitung jumlah kata dalam window [t, window_end]
        word_count = sum(1 for w in words_data if t <= w < window_end)
        
        density_data.append({
            'start_time': float(t),
            'end_time': float(window_end),
            'value': float(word_count)
        })
        
    # Normalisasi agar max value = 1.0 (seperti heatmap YouTube)
    if density_data:
        max_val = max(d['value'] for d in density_data)
        if max_val > 0:
            for d in density_data:
                d['value'] = d['value'] / max_val
                
    return density_data

def cut_clip(video, out_path, start, end, ffmpeg):
    """Cut one clip and format it vertically (1080x1920)."""
    vf = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920"
    cmd = [ffmpeg, "-y", "-ss", f"{start:.2f}", "-to", f"{end:.2f}", "-i", video,
           "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", out_path]
    r = run_cmd(cmd, capture=True)
    if r.returncode != 0:
        LOG.error(f"ffmpeg cut failed: {(r.stderr or '')[:200]}")
        return False
    return True

def run(cfg):
    paths = storage_paths(cfg)
    ffmpeg = find_ffmpeg(cfg, "ffmpeg")
    if not ffmpeg:
        LOG.error("ffmpeg not found.")
        return []

    # Init Gemini API
    api_key = cfg.get("gemini_api_key", "")
    has_gemini = init_gemini(api_key)
    if not has_gemini:
        LOG.error("Gemini API Key tidak ditemukan di config.yaml. Clipper AI tidak bisa berjalan.")
        return []

    sources = []
    for ext in ("*.mp4", "*.mkv", "*.webm"):
        sources.extend(glob.glob(os.path.join(paths["downloads"], ext)))
        
    made = []
    
    for video in sources:
        stem = os.path.splitext(os.path.basename(video))[0]
        json_path = os.path.join(paths["downloads"], stem + ".info.json")
        
        # Load clipped state
        clipped_state_file = os.path.join(paths["clips"], "clipped_state.json")
        clipped_set = set()
        if os.path.exists(clipped_state_file):
            with open(clipped_state_file, "r") as f:
                clipped_set = set(json.load(f).get("clipped", []))
                
        if stem in clipped_set:
            LOG.info(f"Skip {stem} - Sudah dipotong (ada di clipped_state.json).")
            continue
        
        # Check for auto-sub VTT or manual sub VTT
        vtt_files = glob.glob(os.path.join(paths["downloads"], glob.escape(stem) + "*.vtt"))
        vtt_path = vtt_files[0] if vtt_files else None
        
        if not os.path.exists(json_path) or not vtt_path:
            LOG.warning(f"Skip {stem} - Tidak ada Heatmap JSON atau file VTT subtitle.")
            continue
            
        with open(json_path, 'r', encoding='utf-8') as f:
            info = json.load(f)
            
        original_url = info.get("webpage_url") or info.get("original_url") or info.get("channel_url") or ""
            
        heatmap = info.get('heatmap')
        num_clips = cfg.get("clips_per_video", 5)
        min_dur = cfg.get("clip_duration_min", 45)
        max_dur = cfg.get("clip_duration_max", 59)
        
        # Parse VTT
        parsed_vtt = parse_vtt(vtt_path)
        if not parsed_vtt:
            LOG.warning(f"Skip {stem} - File VTT kosong atau gagal di-parse.")
            continue
            
        LOG.info(f"Analyzing Data & Subtitles for: {stem}")
        
        peaks = []
        if heatmap:
            # Generate Plot
            plot_path = os.path.join(paths["clips"], f"{stem}_heatmap.png")
            plot_heatmap(heatmap, plot_path)
            LOG.info(f"Visual grafik Heatmap disimpan di: {plot_path}")
            
            peaks = find_heatmap_peaks(heatmap, num_peaks=num_clips, min_dist=120) # 2 mins apart
            LOG.info(f"Ditemukan {len(peaks)} puncak viral dari Heatmap: {[round(p,1) for p in peaks]}")
        else:
            LOG.info(f"Video tidak memiliki Heatmap YouTube. Membangun Analitik Kepadatan Teks (Speech Density) mandiri...")
            duration = parsed_vtt[-1]['end']
            custom_heatmap = analyze_speech_density(parsed_vtt, duration)
            
            # Generate Custom Plot
            plot_path = os.path.join(paths["clips"], f"{stem}_custom_analytics.png")
            plot_heatmap(custom_heatmap, plot_path)
            LOG.info(f"Visual grafik Speech Density (Analitik Mandiri) disimpan di: {plot_path}")
            
            peaks = find_heatmap_peaks(custom_heatmap, num_peaks=num_clips, min_dist=120)
            LOG.info(f"Ditemukan {len(peaks)} puncak viral dari Analitik Mandiri: {[round(p,1) for p in peaks]}")
        
        for idx, peak_time in enumerate(peaks, 1):
            LOG.info(f"  Menganalisis klip ke-{idx} di sekitar {peak_time:.1f}s dengan Gemini AI...")
            # Extract 2 minutes of context around the peak (1 min before, 1 min after)
            chunk = get_vtt_chunk(parsed_vtt, max(0, peak_time - 60), peak_time + 60)
            
            start_cut, end_cut, title = find_best_cut(chunk, min_dur, max_dur)
            
            if start_cut and end_cut:
                import re
                safe_title = re.sub(r'[\\/*?:"<>|]', "", title) if title else f"{stem} Part {idx}"
                clip_name = f"{safe_title}_clip{idx:02d}"
                out = os.path.join(paths["clips"], f"{clip_name}.mp4")
                meta_out = os.path.join(paths["clips"], f"{clip_name}_metadata.json")
                if cut_clip(video, out, start_cut, end_cut, ffmpeg):
                    LOG.info(f"  Berhasil memotong klip: {os.path.basename(out)}")
                    # Save metadata
                    meta_data = {
                        "title": title or f"{stem} Part {idx}",
                        "original_url": original_url,
                        "channel_url": original_url # Keep this for backward compatibility with old clips
                    }
                    with open(meta_out, 'w', encoding='utf-8') as mf:
                        json.dump(meta_data, mf, indent=2, ensure_ascii=False)
                        
                    made.append(out)
            else:
                LOG.warning(f"  Gemini gagal menemukan potongan sempurna untuk puncak {peak_time:.1f}s")
                
        # Save to state after finishing this video
        clipped_set.add(stem)
        with open(clipped_state_file, "w") as f:
            json.dump({"clipped": list(clipped_set)}, f)
            
    LOG.info(f"Auto Clipper selesai. Memotong total {len(made)} klip AI.")
    return made

if __name__ == "__main__":
    run(load_config())
