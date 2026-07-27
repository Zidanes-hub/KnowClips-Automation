import subprocess
ffmpeg = 'C:\\Users\\MyBook Hype\\AppData\\Local\\Microsoft\\WinGet\\Packages\\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\\ffmpeg-8.1.2-full_build\\bin\\ffmpeg.exe'
video = r'D:\knowclips-automation\storage\output\Kenapa Indonesia SUSAH Maju! Jawaban Tak Terduga!_clip01_branded.mp4'
out_path = r'D:\knowclips-automation\storage\output\test_thumb.jpg'

vf = (
    "scale=1280:720:force_original_aspect_ratio=increase,"
    "crop=1280:720,"
    "drawtext=fontfile='C\\:/Windows/Fonts/impact.ttf':text='KENAPA INDONESIA SUSAH MAJU':"
    "fontsize=120:fontcolor=yellow:borderw=8:bordercolor=black:"
    "x=(w-text_w)/2:y=h-text_h-100:shadowcolor=black:shadowx=5:shadowy=5"
)

cmd = [ffmpeg, '-y', '-i', video, '-ss', '00:00:05', '-vframes', '1', '-vf', vf, '-q:v', '2', out_path]
r = subprocess.run(cmd, capture_output=True, text=True)
print('RC:', r.returncode)
print('STDERR:', r.stderr)
