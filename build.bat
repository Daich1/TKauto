@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/3] Installing build packages...
python -m pip install pyinstaller -q
python -m pip install -r requirements.txt -q

echo [2/3] Building executable...
pyinstaller --onefile --windowed --name "SpikeTimer" spike_timer.py

echo [3/3] Done. Check dist\SpikeTimer.exe
pause
