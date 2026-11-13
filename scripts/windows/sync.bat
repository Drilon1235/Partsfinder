@echo off
rem Keep a company library in step with a folder or share (new, changed and removed files).
rem   sync.bat "\\nas\cad" acme
rem For every night: Windows Task Scheduler -> Create Basic Task -> Daily -> Start a program:
rem   program  C:\path\to\Partsfinder\scripts\windows\sync.bat   arguments  "\\nas\cad" acme
rem Rules (.partsfinderignore, .partsfinderaccess) and safety: docs\10_COMPANY_LIBRARIES.md
rem The log of the last run is in backend\sync_log.txt.
setlocal
if "%~2"=="" (
  echo Usage: sync.bat FOLDER COMPANY
  exit /b 2
)
cd /d "%~dp0..\..\backend"
set PYTHONUTF8=1
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set TRANSFORMERS_VERBOSITY=error
set HF_HUB_DISABLE_PROGRESS_BARS=1
if not exist .venv\Scripts\python.exe (
  echo Run scripts\windows\setup_windows.bat first.
  exit /b 1
)
.venv\Scripts\python.exe -m partsfinder.ingest "%~1" --company %2 --sync > sync_log.txt 2>&1
set RESULT=%ERRORLEVEL%
type sync_log.txt
exit /b %RESULT%
