@echo off
cd /d "%~dp0..\.."
echo Partsfinder - installation
echo This installs Python 3.12 (if missing) and all packages. This can take 10 minutes.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\setup_windows.ps1"
echo.
echo Done. The result is also in backend\setup_log.txt
pause
