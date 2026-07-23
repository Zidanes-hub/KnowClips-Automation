"""Modul untuk menganalisis transkrip menggunakan Gemini API."""
import os
import json
import logging
import warnings
from google import genai

LOG = logging.getLogger("gemini")

CLIENT = None

def init_gemini(api_key):
    global CLIENT
    if not api_key:
        return False
    CLIENT = genai.Client(api_key=api_key)
    return True

def find_best_cut(vtt_text, min_dur=45, max_dur=59):
    """
    Mengirimkan potongan transkrip VTT ke Gemini untuk mencari 
    awal dan akhir kalimat yang paling sempurna dan viral.
    """
    prompt = f"""Anda adalah editor YouTube Shorts profesional.
Di bawah ini adalah potongan transkrip VTT dari sebuah video. 
Tugas Anda adalah memilih SATU blok percakapan yang berpotensi paling viral/menarik.

ATURAN WAJIB:
1. Harus diawali tepat di AWAL sebuah kalimat/konteks (tidak terpotong di tengah kata).
2. Harus diakhiri tepat di AKHIR kalimat (titik/tanda seru/tanya).
3. Selisih antara end_time dan start_time HARUS antara {min_dur} hingga {max_dur} detik.
4. Jangan halusinasi timestamp! Gunakan persis angka timestamp yang ada di dalam teks VTT di bawah.
5. Berikan sebuah "title" (judul) yang sangat catchy, spesifik, dan memancing rasa penasaran (clickbait positif) maksimal 50 karakter!

Kembalikan HANYA format JSON valid tanpa format markdown (```json), contoh:
{{
  "start_time": 123.450,
  "end_time": 175.000,
  "reason": "Alasan mengapa ini viral",
  "title": "Alasan Utama Kenapa Amerika Pecah!"
}}

Transkrip VTT:
{vtt_text}
"""
    try:
        response = CLIENT.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        # Bersihkan format jika model mengembalikan markdown
        text = response.text.replace("```json", "").replace("```", "").strip()
        data = json.loads(text)
        
        # Validasi ringan
        start = float(data.get("start_time", 0))
        end = float(data.get("end_time", 0))
        dur = end - start
        
        
        if start > 0 and end > start and dur >= (min_dur - 5):
            title = data.get("title", "Klip Viral Rahasia")
            LOG.info(f"Gemini Cut: {start}s to {end}s ({dur:.1f}s) - {data.get('reason')}")
            return start, end, title
        else:
            LOG.error(f"Gemini membalas durasi tidak wajar: {dur}s")
            return None, None, None
            
    except Exception as e:
        LOG.error(f"Gemini API Error: {e}")
        return None, None, None
