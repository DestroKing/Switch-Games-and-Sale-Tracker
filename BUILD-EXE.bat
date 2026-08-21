@echo off
REM ===================================================================
REM  Builds the standalone app folder, so it runs on a PC with nothing
REM  installed - no Python, no uv, no downloads.
REM
REM  Output: dist\switch-tracker\  (copy the WHOLE folder to the other PC,
REM  then double-click switch-tracker.exe inside it)
REM
REM  Run START.bat at least once before this.
REM ===================================================================
cd /d "%~dp0"
title Switch Tracker - build

if not exist ".setup-complete" (
  echo.
  echo   Run START.bat first - the build needs the packages it installs.
  echo.
  pause
  exit /b 1
)

echo.
echo   Building. This takes a few minutes and produces a large folder ^(~900 MB^).
echo.
powershell -ExecutionPolicy Bypass -NoProfile -Command ^
  "$env:PATH='%USERPROFILE%\.local\bin;'+$env:PATH; uv run pyinstaller switch_tracker.spec --noconfirm"
if errorlevel 1 (
  echo.
  echo   Build failed. The message above says why.
  pause
  exit /b 1
)

echo.
echo   Done. The app is in:  dist\switch-tracker\
echo   Copy that whole folder anywhere and run switch-tracker.exe inside it.
echo.
pause
