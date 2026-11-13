@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist backend\.venv\Scripts\python.exe (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
echo Building and importing the engineering demo library, then evaluating...
backend\.venv\Scripts\python.exe scripts\engineering\setup_engineering.py %*
echo.
echo The full result is in backend\engineering_log.txt
pause
