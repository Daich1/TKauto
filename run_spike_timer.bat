@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist "dist\SpikeTimer.exe" (
    start "" "dist\SpikeTimer.exe"
    exit /b
)
if exist "SpikeTimer.exe" (
    start "" "SpikeTimer.exe"
    exit /b
)
python -m pip install -r requirements.txt -q
python spike_timer.py
pause
