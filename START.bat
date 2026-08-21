@echo off
REM ===================================================================
REM  Switch Tracker - double-click this file. That is the whole thing.
REM
REM  First run installs everything (a few minutes, ~1 GB of downloads).
REM  Every run after that just starts the app.
REM
REM  If Windows says "this file came from another computer": close this,
REM  right-click the file, choose Properties, tick Unblock, click OK.
REM ===================================================================
cd /d "%~dp0"
title Switch Tracker

REM A marker file, not a guess about what is installed - re-running setup
REM when it is already done costs minutes for no reason.
if not exist ".setup-complete" goto setup
if not exist ".venv" goto setup
goto run

:setup
echo.
echo   First run - setting things up. This takes a few minutes.
echo   You can leave it alone; it will tell you when it is done.
echo.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0setup.ps1"
if errorlevel 1 (
  echo.
  echo   Setup did not finish. The message above says why.
  echo.
  pause
  exit /b 1
)

:run
echo.
echo   Starting Switch Tracker. Your browser will open in a few seconds.
echo   Close this window to stop it.
echo.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0run.ps1" %*
if errorlevel 1 pause
