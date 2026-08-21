# Switch Tracker - one-shot installer.
#
# Safe to run again at any time: every step checks before it acts, so a
# half-finished install is fixed by simply running it a second time.
#
# Needs no administrator rights. Everything installs into your own user
# folder; nothing is written to Program Files or the registry.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($n, $text) { Write-Host "`n  [$n/5] $text" -ForegroundColor Cyan }
function Ok($text)       { Write-Host "        $text" -ForegroundColor Green }
function Info($text)     { Write-Host "        $text" -ForegroundColor DarkGray }
function Die($text) {
    Write-Host "`n  PROBLEM: $text`n" -ForegroundColor Red
    exit 1
}

Write-Host "`n  Switch Tracker setup" -ForegroundColor White
Write-Host "  ------------------------------------------------"
Info "Downloads about 1 GB. A slow connection may take 15 minutes."

# --- 1. uv -----------------------------------------------------------------
# uv is the Python installer/package manager. It also installs Python itself,
# which is why nothing here asks you to install Python separately.
Step 1 "Python tooling (uv)"
$uv = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uv) {
    # The per-user location uv installs into, in case it is there but not yet
    # on PATH for this window (happens right after a previous install).
    $candidate = "$env:USERPROFILE\.local\bin\uv.exe"
    if (Test-Path $candidate) {
        $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
        $uv = Get-Command uv -ErrorAction SilentlyContinue
    }
}
if (-not $uv) {
    Info "not found - installing it"
    try {
        Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression
    } catch {
        Die "Could not download uv. Check your internet connection, then run this again.`n           ($($_.Exception.Message))"
    }
    $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
        Die "uv installed but is not on PATH. Close this window, open a new one, and try again."
    }
    Ok "installed"
} else {
    Ok "already installed ($(uv --version))"
}

# --- 2. Python -------------------------------------------------------------
Step 2 "Python 3.12"
uv python install 3.12
if ($LASTEXITCODE -ne 0) { Die "Could not install Python 3.12." }
Ok "ready"

# --- 3. Packages -----------------------------------------------------------
Step 3 "Application packages"
uv sync
if ($LASTEXITCODE -ne 0) { Die "Could not install the application's packages." }
Ok "installed"

# --- 4. Browser ------------------------------------------------------------
# Several shops (Amazon, Flipkart and others) have no product feed to read,
# so the app drives a real browser to see their pages. This is that browser.
# It runs invisibly - you will not see windows opening.
Step 4 "Browser engine (about 500 MB - the slow part)"
uv run playwright install chromium
if ($LASTEXITCODE -ne 0) { Die "Could not download the browser engine. Check your connection and run this again." }
Ok "downloaded"

# --- 5. Verify -------------------------------------------------------------
# Proves the four things that break silently: secure connections, page
# templates, the web server, and the browser engine. Better to fail here
# with a clear message than halfway through collecting prices.
Step 5 "Checking everything works"
uv run python -m switch_tracker spike
if ($LASTEXITCODE -ne 0) { Die "The check above failed. Send that output along when asking for help." }

New-Item -ItemType File -Path ".setup-complete" -Force | Out-Null
Write-Host "`n  Setup complete." -ForegroundColor Green
Write-Host "  From now on, double-clicking START.bat goes straight to the app.`n"
