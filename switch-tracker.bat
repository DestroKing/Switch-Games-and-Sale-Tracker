@echo off
cd /d "%~dp0"
where bun >nul 2>nul
if errorlevel 1 goto setup
if not exist node_modules goto setup
goto menu

:setup
echo First run - setting things up. This takes a few minutes.
echo.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0setup.ps1"
if errorlevel 1 (
  echo.
  echo Setup did not finish. Read the message above.
  pause
  exit /b 1
)

:menu
set "PATH=%USERPROFILE%\.bun\bin;%PATH%"
bun run src/menu.ts
if errorlevel 1 pause
