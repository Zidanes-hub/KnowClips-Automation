@echo off
echo ======================================================
echo    KNOWCLIPS AUTOMATION - MANUAL YOUTUBE DOWNLOAD
echo ======================================================
echo.
set /p "yt_url=Masukkan Link YouTube: "
if "%yt_url%"=="" (
    echo Link tidak boleh kosong!
    pause
    exit /b
)

echo.
echo Memproses video... Mohon tunggu (proses Download, Clip, dan Brand)...
echo.
cd /d "%~dp0\.."
python main.py --mode manual --url "%yt_url%"
echo.
echo Proses selesai! Silakan periksa folder storage\output
pause
