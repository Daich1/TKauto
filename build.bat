@echo off
cd /d "%~dp0"

echo [1/3] ビルド用パッケージをインストール...
pip install pyinstaller -q
pip install -r requirements.txt -q

echo [2/3] 実行ファイルをビルド中...
pyinstaller --onefile --windowed --name "SpikeTimer" spike_timer.py

echo [3/3] 完了
echo.
echo dist\SpikeTimer.exe が生成されました
echo exeと同じフォルダでconfig.jsonが自動作成されます（F12でキャリブレーション）
pause
