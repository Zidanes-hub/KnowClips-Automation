import os
from PIL import ImageFont

def fmt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"

def generate_ass(segments, ass_path, font_path, style="hormozi"):
    play_res_x = 1080
    play_res_y = 1920
    margin_lr = 100
    margin_v = 450
    max_line_width = play_res_x - (margin_lr * 2)
    
    styles_cfg = {
        "hormozi": {
            "font": "Montserrat Black", 
            "size": 75,
            "PrimaryColour": "&H00FFFFFF",
            "OutlineColour": "&H00000000",
            "BackColour": "&H80000000",
            "Bold": 1,
            "BorderStyle": 1,
            "Outline": 4,
            "Shadow": 2
        },
        "mrbeast": {
            "font": "Impact", 
            "size": 95,
            "PrimaryColour": "&H00FFFFFF",
            "OutlineColour": "&H00000000",
            "BackColour": "&H00000000",
            "Bold": 0,
            "BorderStyle": 1,
            "Outline": 8,
            "Shadow": 8
        },
        "neon": {
            "font": "Segoe UI", 
            "size": 85,
            "PrimaryColour": "&H00FFFFFF",
            "OutlineColour": "&H00FF00FF",
            "BackColour": "&H00000000",
            "Bold": 1,
            "BorderStyle": 1,
            "Outline": 6,
            "Shadow": 0
        },
        "karaoke": {
            "font": "Montserrat Black", 
            "size": 75,
            "PrimaryColour": "&H00FFFFFF",
            "SecondaryColour": "&H0000FFFF", # Karaoke active color (Yellow)
            "OutlineColour": "&H00000000",
            "BackColour": "&H80000000",
            "Bold": 1,
            "BorderStyle": 1,
            "Outline": 4,
            "Shadow": 2
        }
    }
    
    cfg = styles_cfg.get(style.lower(), styles_cfg["hormozi"])
    font_name = cfg["font"]
    font_size = cfg["size"]

    # Header definition
    header = (
        f"[Script Info]\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        f"WrapStyle: 1\n"
        f"ScriptType: v4.00+\n"
        f"ScaledBorderAndShadow: yes\n\n"
        f"[V4+ Styles]\n"
        f"Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{font_size},{cfg.get('PrimaryColour', '&H00FFFFFF')},{cfg.get('SecondaryColour', '&H00FFFFFF')},{cfg['OutlineColour']},{cfg['BackColour']},{cfg['Bold']},0,0,0,100,100,0,0,{cfg['BorderStyle']},{cfg['Outline']},{cfg['Shadow']},2,{margin_lr},{margin_lr},{margin_v},1\n\n"
        f"[Events]\n"
        f"Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    try:
        if font_name == "Montserrat Black" and font_path and os.path.exists(font_path):
            pil_font = ImageFont.truetype(font_path, font_size)
        else:
            sys_font_map = {
                "Impact": "impact.ttf",
                "Segoe UI": "seguibl.ttf"
            }
            font_file = sys_font_map.get(font_name, "arialbd.ttf")
            pil_font = ImageFont.truetype(font_file, font_size)
    except Exception:
        pil_font = ImageFont.load_default()

    def get_word_width(word):
        if hasattr(pil_font, "getlength"):
            return int(pil_font.getlength(word))
        elif hasattr(pil_font, "getbbox"):
            return pil_font.getbbox(word)[2]
        return len(word) * (font_size // 2)

    space_width = get_word_width(" ")

    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(header)

        for seg in segments:
            # Handle faster-whisper segment object or dict
            seg_s = getattr(seg, 'start', None)
            if seg_s is None:
                seg_s = seg["start"]
                seg_e = seg["end"]
                words = seg.get("words", [])
            else:
                seg_e = seg.end
                words = seg.words

            if not words:
                continue

            lines = []
            current_line = []
            current_w = 0
            
            for w_obj in words:
                if isinstance(w_obj, dict):
                    text = w_obj["word"].strip()
                    w_s = w_obj["start"]
                    w_e = w_obj["end"]
                else:
                    text = w_obj.word.strip()
                    w_s = w_obj.start
                    w_e = w_obj.end
                    
                if not text:
                    continue
                    
                if style == "mrbeast":
                    text = text.upper()
                    
                w_len = get_word_width(text)
                
                if current_line and (current_w + space_width + w_len > max_line_width):
                    lines.append({"words": current_line, "width": current_w})
                    current_line = []
                    current_w = 0
                
                x_offset = current_w if not current_line else current_w + space_width
                current_line.append({
                    "text": text,
                    "w": w_len,
                    "x_offset": x_offset,
                    "start": w_s,
                    "end": w_e
                })
                current_w = x_offset + w_len

            if current_line:
                lines.append({"words": current_line, "width": current_w})

            line_spacing = font_size + 15
            total_stack_h = (len(lines) - 1) * line_spacing
            current_y = play_res_y - margin_v - total_stack_h

            if style == "karaoke":
                for line in lines:
                    line_y = current_y
                    t_line_start = line["words"][0]["start"]
                    t_line_end = line["words"][-1]["end"]
                    
                    event_text = ""
                    for i, w_data in enumerate(line["words"]):
                        duration_cs = int((w_data["end"] - w_data["start"]) * 100)
                        space = " " if i > 0 else ""
                        event_text += f"{space}{{\\k{duration_cs}}}{w_data['text']}"
                    
                    pos_tag = f"\\pos({int(play_res_x/2)},{int(line_y)})"
                    # Yellow fill over white text
                    event_text = f"{{\\an2{pos_tag}\\1c&HFFFFFF&\\2c&H00FFFF&\\K10}}{event_text}"
                    f.write(f"Dialogue: 0,{fmt_time(t_line_start)},{fmt_time(t_line_end)},Default,,0,0,0,,{event_text}\n")
                    current_y += line_spacing
                continue

            for line in lines:
                start_x = (play_res_x - line["width"]) / 2
                line_y = current_y

                for i, w_data in enumerate(line["words"]):
                    word_x = start_x + w_data["x_offset"] + (w_data["w"] / 2)
                    
                    t_start_ms = int(max(0, w_data["start"] - seg_s) * 1000)
                    t_end_ms = int(max(0, w_data["end"] - seg_s) * 1000)
                    t_pop_ms = t_start_ms + 80
                    t_settle_ms = t_start_ms + 150
                    
                    pos_tag = f"\\pos({int(word_x)},{int(line_y)})"
                    
                    if style == "hormozi":
                        init_scale = 70
                        overshoot = 120
                        target_scale = 100
                        anim_tag = (
                            f"\\alpha&HFF&\\fscx{init_scale}\\fscy{init_scale}"
                            f"\\t({t_start_ms},{t_start_ms},\\alpha&H00&)"
                            f"\\t({t_start_ms},{t_pop_ms},\\fscx{overshoot}\\fscy{overshoot}\\c&H00FFFF&)"
                            f"\\t({t_pop_ms},{t_settle_ms},\\fscx{target_scale}\\fscy{target_scale})"
                            f"\\t({t_end_ms},{t_end_ms},\\c&HFFFFFF&)"
                        )
                    elif style == "mrbeast":
                        colors = ["&HFFFF00&", "&HFF00FF&", "&H00FFFF&"]
                        c = colors[i % len(colors)]
                        init_scale = 50
                        overshoot = 140
                        target_scale = 100
                        anim_tag = (
                            f"\\alpha&HFF&\\fscx{init_scale}\\fscy{init_scale}"
                            f"\\t({t_start_ms},{t_start_ms},\\alpha&H00&\\c{c})"
                            f"\\t({t_start_ms},{t_pop_ms},\\fscx{overshoot}\\fscy{overshoot})"
                            f"\\t({t_pop_ms},{t_settle_ms},\\fscx{target_scale}\\fscy{target_scale})"
                            f"\\t({t_end_ms},{t_end_ms},\\c&HFFFFFF&)"
                        )
                    elif style == "neon":
                        anim_tag = (
                            f"\\alpha&HFF&"
                            f"\\t({t_start_ms},{t_start_ms},\\alpha&H00&\\3c&H00FF00&\\blur5)"
                            f"\\t({t_end_ms},{t_end_ms},\\3c&HFF00FF&\\blur0)"
                        )
                    else:
                        anim_tag = ""
                        
                    event_text = f"{{\\an2{pos_tag}{anim_tag}}}{w_data['text']}"
                    
                    f.write(f"Dialogue: 0,{fmt_time(seg_s)},{fmt_time(seg_e)},Default,,0,0,0,,{event_text}\n")

                current_y += line_spacing

    return True
