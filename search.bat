@echo off
cd /d "%~dp0backend"
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set TRANSFORMERS_VERBOSITY=error
set HF_HUB_DISABLE_PROGRESS_BARS=1
if not exist .venv\Scripts\python.exe (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
echo Loading the AI model, please wait...
.venv\Scripts\python.exe -m partsfinder.search_cli
