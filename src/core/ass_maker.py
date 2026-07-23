import os
from PIL import ImageFont

def fmt_time(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int(round((seconds - int(seconds)) * 100))
    return f"{h:01d}:{m:02d}:{s:02d}.{cs:02d}"

def generate_ass(segments, ass_path, font_path, font_name="Montserrat Black"):
    play_res_x = 1080
    play_res_y = 1920
    font_size = 75
    margin_lr = 100
    margin_v = 450
    max_line_width = play_res_x - (margin_lr * 2)
    
    header = (
        f"[Script Info]\n"
        f"PlayResX: {play_res_x}\n"
        f"PlayResY: {play_res_y}\n"
        f"WrapStyle: 1\n"
        f"ScriptType: v4.00+\n"
        f"ScaledBorderAndShadow: yes\n\n"
        f"[V4+ Styles]\n"
        f"Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{font_size},&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,0,0,1,4,2,2,{margin_lr},{margin_lr},{margin_v},1\n\n"
        f"[Events]\n"
        f"Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    try:
        pil_font = ImageFont.truetype(font_path, font_size)
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
            seg_s = seg["start"]
            seg_e = seg["end"]
            
            # Use segment words if available (word_timestamps=True), otherwise simulate it
            words = seg.get("words", [])
            if not words:
                continue

            lines = []
            current_line = []
            current_w = 0
            
            for w_dict in words:
                text = w_dict["word"].strip()
                if not text:
                    continue
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
                    "start": w_dict["start"],
                    "end": w_dict["end"]
                })
                current_w = x_offset + w_len

            if current_line:
                lines.append({"words": current_line, "width": current_w})

            line_spacing = font_size + 15
            total_stack_h = (len(lines) - 1) * line_spacing
            current_y = play_res_y - margin_v - total_stack_h

            for line in lines:
                start_x = (play_res_x - line["width"]) / 2
                line_y = current_y

                for w_data in line["words"]:
                    word_x = start_x + w_data["x_offset"] + (w_data["w"] / 2)
                    
                    t_start_ms = int(max(0, w_data["start"] - seg_s) * 1000)
                    t_end_ms = int(max(0, w_data["end"] - seg_s) * 1000)
                    t_pop_ms = t_start_ms + 80
                    t_settle_ms = t_start_ms + 150
                    
                    # Highlight color (Yellow: &H0000FFFF)
                    # Note: ASS colors are BGR: Blue=00, Green=FF, Red=FF -> &H00FFFF&
                    pos_tag = f"\\pos({int(word_x)},{int(line_y)})"
                    
                    # Bounce Pop + Color change
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
                    
                    event_text = f"{{\\an2{pos_tag}{anim_tag}}}{w_data['text']}"
                    
                    # Write the event
                    f.write(f"Dialogue: 0,{fmt_time(seg_s)},{fmt_time(seg_e)},Default,,0,0,0,,{event_text}\n")

                current_y += line_spacing

    return True
