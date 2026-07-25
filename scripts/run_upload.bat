@echo off
echo ======================================================
echo    KNOWCLIPS AUTOMATION - UPLOAD TO YOUTUBE
echo ======================================================
echo.
echo Jika ini adalah pertama kalinya Anda melakukan upload,
echo Browser internet Anda akan terbuka secara otomatis.
echo Silakan login menggunakan akun YouTube Anda dan berikan izin akses.
echo.
cd /d "%~dp0\.."
python main.py --mode upload
echo.
pause
