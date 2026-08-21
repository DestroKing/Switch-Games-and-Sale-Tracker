# switch-tracker setup - Windows 10 / 11
#
# Run from the project folder:
#     powershell -ExecutionPolicy Bypass -File .\setup.ps1
#
# Safe to re-run. Every step checks before it acts.

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Step($n, $msg) { Write-Host "`n[$n/5] $msg" -ForegroundColor Cyan }
function Ok($msg)       { Write-Host "      OK  $msg" -ForegroundColor Green }
function Warn($msg)     { Write-Host "      !   $msg" -ForegroundColor Yellow }
function Die($msg)      { Write-Host "`nSTOP: $msg" -ForegroundColor Red; exit 1 }

# PowerShell 5.1 (what Windows 10 ships) can default to TLS 1.0, which makes
# every download below fail with an unhelpful "could not create SSL/TLS
# secure channel". Force 1.2.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ------------------------------------------------------------- 1. Windows
Step 1 "Checking Windows version"
$build = [int](Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion").CurrentBuild
if ($build -lt 17763) {
    Die "Bun needs Windows 10 version 1809 (build 17763) or later. This machine is build $build.`n      Windows Update will fix it, or use the Docker route in the README."
}
Ok "build $build"

# ----------------------------------------------------------------- 2. CPU
# The standard Bun x64 binary requires AVX2. Without it Bun installs happily
# and then dies with "Illegal Instruction" on first run, which looks like a
# broken project rather than a CPU mismatch. Detect it now instead.
Step 2 "Checking CPU instruction support"
$avx2 = $false
try {
    Add-Type -TypeDefinition @"
using System.Runtime.Intrinsics.X86;
public static class CpuCheck { public static bool Avx2() { return Avx2.IsSupported; } }
"@ -ErrorAction Stop
    $avx2 = [CpuCheck]::Avx2()
} catch {
    # .NET Framework 4.x has no System.Runtime.Intrinsics. Fall back to the
    # CPU name, which is coarse but catches genuinely old hardware.
    $cpu = (Get-CimInstance Win32_Processor | Select-Object -First 1).Name
    $avx2 = $cpu -notmatch "Core.*(2 Duo|i[357]-[23]\d{2})|Pentium|Celeron|Athlon|Phenom"
    Warn "could not query directly; inferred from: $cpu"
}

if ($avx2) {
    Ok "AVX2 available (standard Bun build)"
} else {
    Warn "no AVX2 detected - will install Bun's baseline build"
    $env:BUN_BASELINE = "1"
}

# ----------------------------------------------------------------- 3. Bun
Step 3 "Installing Bun"
if (Get-Command bun -ErrorAction SilentlyContinue) {
    Ok "already installed ($(bun --version))"
} else {
    try {
        if ($env:BUN_BASELINE -eq "1") {
            # The installer accepts a version argument; -Baseline selects the
            # SSE4.2 build for pre-Haswell CPUs.
            & ([scriptblock]::Create((Invoke-RestMethod "https://bun.sh/install.ps1"))) -Baseline
        } else {
            Invoke-RestMethod "https://bun.sh/install.ps1" | Invoke-Expression
        }
    } catch {
        Die "Bun install failed: $($_.Exception.Message)`n      Try manually: powershell -c ""irm bun.sh/install.ps1 | iex"""
    }
    # The installer sets PATH for future sessions, not this one.
    $env:Path = "$env:USERPROFILE\.bun\bin;$env:Path"
    $script:NeedsReload = $true
    Ok "installed ($(bun --version))"
}

# Prove the binary actually runs on this CPU before going further.
try {
    $null = bun --revision 2>&1
} catch {
    Die "Bun installed but won't run on this CPU.`n      Reinstall the baseline build: powershell -c ""irm bun.sh/install.ps1|iex"" -Baseline"
}

# ------------------------------------------------------- 4. deps + browser
Step 4 "Dependencies and Chromium (~300 MB, one time)"
bun install
Ok "packages installed"
bunx playwright install chromium
Ok "Chromium ready"
# Note: 'playwright install-deps' is Linux-only. Windows needs nothing extra.

# -------------------------------------------------------------- 5. verify
Step 5 "Checking it runs"
bun --version | Out-Null
Ok "ready"

Write-Host "`nSetup complete. Opening the menu..." -ForegroundColor Green
Start-Sleep -Seconds 1
