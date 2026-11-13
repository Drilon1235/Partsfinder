@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
if not exist backend\.venv\Scripts\python.exe (
  echo Run setup_windows.bat first.
  pause
  exit /b 1
)
echo Checking, running tests, generating and importing test data...
backend\.venv\Scripts\python.exe backend\run_checks.py --testdata --import --eval
echo.
echo The full result is in backend\check_log.txt
pause
