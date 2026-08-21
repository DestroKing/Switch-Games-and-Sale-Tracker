@echo off
REM ===================================================================
REM  Runs the BUILT app's self-check and keeps the window open so you
REM  can actually read the result.
REM
REM  Double-clicking switch-tracker.exe directly will always flash and
REM  vanish: Windows closes the console the moment the program ends.
REM  That is a property of the console, not a sign of failure.
REM ===================================================================
cd /d "%~dp0"
title Switch Tracker - self check

if not exist "dist\switch-tracker\switch-tracker.exe" (
  echo.
  echo   No built app found at dist\switch-tracker\switch-tracker.exe
  echo   Run BUILD-EXE.bat first.
  echo.
  pause
  exit /b 1
)

echo.
echo   Running the built app's self-check...
echo.
"dist\switch-tracker\switch-tracker.exe" spike
echo.
echo   ---------------------------------------------------------------
echo   Exit code: %ERRORLEVEL%
echo   Copy everything above this line if you need to report a problem.
echo   ---------------------------------------------------------------
echo.
pause
