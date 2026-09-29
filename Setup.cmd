@echo off
setlocal
cd /d "%~dp0"
title HTU Campus Network Setup

powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\Install-All.ps1"
set "exitCode=%ERRORLEVEL%"

if not "%exitCode%"=="0" (
  echo.
  echo Setup failed. Review the error above and run this file again.
  pause
)

endlocal & exit /b %exitCode%
