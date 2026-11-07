@echo off
cd /d "%~dp0"
where python >nul 2>nul || (echo [ERROR] Python not found. Please install Python 3.10+ from https://www.python.org & pause & exit /b 1)
if not exist .venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv .venv || (pause & exit /b 1)
)
echo Installing / updating packages ^(latest yt-dlp^)...
.venv\Scripts\python.exe -m pip install -q -U --disable-pip-version-check -r requirements.txt
start "" http://127.0.0.1:8765
.venv\Scripts\python.exe server.py
pause
