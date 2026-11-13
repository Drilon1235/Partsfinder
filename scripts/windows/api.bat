@echo off
cd /d "%~dp0..\..\backend"
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set TRANSFORMERS_VERBOSITY=error
set HF_HUB_DISABLE_PROGRESS_BARS=1
if not exist .venv\Scripts\python.exe (
  echo Run scripts\windows\setup_windows.bat first.
  pause
  exit /b 1
)
start "" /b cmd /c "timeout /t 12 >nul & start http://127.0.0.1:8000/docs"
.venv\Scripts\python.exe -m partsfinder.api %*
pause
