# Builds standalone .exe files that don't need Bun installed.
#
#     powershell -ExecutionPolicy Bypass -File .\build-exe.ps1
#
# Produces dist\switch-tracker.exe (collector + dashboard, no Bun required).
#
# READ THIS BEFORE RELYING ON IT
# ------------------------------
# `bun build --compile` bakes the runtime and your code into one binary. That
# works cleanly for everything here EXCEPT Playwright.
#
# Playwright isn't a normal library - it ships a separate driver process and
# resolves a Chromium binary from disk at runtime. Neither survives being
# packed into a single executable. So there are two honest options:
#
#   1. Full build (default). Compiles everything and ships a browsers\ folder
#      next to the exe. Result is a ~400 MB folder, not a single file, and the
#      Playwright parts may still need PLAYWRIGHT_BROWSERS_PATH set correctly.
#
#   2. -NoBrowser. Compiles a much smaller exe (~60 MB, single file) that runs
#      the twelve HTTP stores and the dashboard, and skips the four browser
#      stores. If you mostly care about the Indian importers, this is the one
#      that actually behaves like a normal Windows program.
#
# I have not been able to execute either path, so treat the first run as a test.

param([switch]$NoBrowser)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command bun -ErrorAction SilentlyContinue)) {
    Write-Host "Run setup.ps1 first - building needs Bun even though the output won't." -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path dist | Out-Null

Write-Host "Compiling..." -ForegroundColor Cyan

$args = @(
    "build", "src/launch.ts",
    "--compile",
    "--target=bun-windows-x64",
    "--outfile", "dist/switch-tracker.exe"
)

# The HTML is read from disk at runtime by default; embed it so the exe is
# self-contained on that front at least.
if ($NoBrowser) {
    # Excluding Playwright removes ~200 MB of driver and avoids the packing
    # problem entirely. The browser adapter degrades to a clear error.
    $args += @("--external", "playwright")
    $env:TRACKER_NO_BROWSER = "1"
}

& bun @args
if ($LASTEXITCODE -ne 0) {
    Write-Host "`nCompile failed." -ForegroundColor Red
    Write-Host "If the error mentions playwright, retry with:  .\build-exe.ps1 -NoBrowser"
    exit 1
}

Copy-Item src/web/index.html dist/ -Force

if (-not $NoBrowser) {
    Write-Host "Copying Chromium (~300 MB)..." -ForegroundColor Cyan
    $cache = "$env:USERPROFILE\AppData\Local\ms-playwright"
    if (Test-Path $cache) {
        Copy-Item $cache dist\browsers -Recurse -Force
        # The exe must be told where the browser went.
        @'
@echo off
set PLAYWRIGHT_BROWSERS_PATH=%~dp0browsers
"%~dp0switch-tracker.exe" %*
'@ | Set-Content dist\switch-tracker.bat -Encoding ASCII
        Write-Host "  Ship the whole dist\ folder. Users run switch-tracker.bat." -ForegroundColor Yellow
    } else {
        Write-Host "  Chromium cache not found - run 'bunx playwright install chromium' first." -ForegroundColor Yellow
    }
}

$size = "{0:N0} MB" -f ((Get-ChildItem dist -Recurse | Measure-Object Length -Sum).Sum / 1MB)
Write-Host "`nBuilt dist\ ($size)" -ForegroundColor Green
