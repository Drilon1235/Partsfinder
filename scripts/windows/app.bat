@echo off
cd /d "%~dp0..\..\app"
title Partsfinder

where npm >nul 2>nul
if errorlevel 1 (
  if exist "%ProgramFiles%\nodejs\npm.cmd" (
    set "PATH=%ProgramFiles%\nodejs;%PATH%"
  ) else (
    echo Node.js not found: installing via winget. Click Yes if Windows asks for permission.
    winget install -e --id OpenJS.NodeJS.LTS --accept-package-agreements --accept-source-agreements
    set "PATH=%ProgramFiles%\nodejs;%PATH%"
  )
)
where npm >nul 2>nul
if errorlevel 1 (
  echo Node.js could not be installed. Install Node.js LTS from https://nodejs.org and start this again.
  pause
  exit /b 1
)

if not exist node_modules\electron\dist\electron.exe (
  echo First time: installing Electron, about 100 MB...
  call npm install --no-audit --no-fund
  if errorlevel 1 (
    echo npm install failed. See the message above.
    pause
    exit /b 1
  )
)

echo The app is starting. This window may stay open; it closes by itself when you close the app.
call npm start
