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
echo AI evaluation with the real Claude (needs ANTHROPIC_API_KEY in backend\.env, about 5-10 s per question)...
.venv\Scripts\python.exe eval_ai.py %*
echo.
echo The full result is in backend\ai_log.txt
pause
