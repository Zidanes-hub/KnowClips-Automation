@echo off
REM ============================================================
REM KnowClips Automation - Windows Task Scheduler Setup
REM This script runs the pipeline when laptop starts
REM ============================================================

REM Change to project directory
cd /d D:\knowclips-automation

REM Activate virtual environment if using one (optional)
REM call .venv\Scripts\activate

REM Run the full pipeline (scrape + download + clip + brand + upload)
REM Or run specific modes: scrape, download, clip, brand, upload, all
python main.py --mode all

REM Keep console open on error for debugging
if errorlevel 1 (
    echo.
    echo Pipeline failed. Press any key to exit...
    pause >nul
)

exit /b 0