# Starts the app. Called by START.bat; you should not need to run it yourself.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    $env:PATH = "$env:USERPROFILE\.local\bin;$env:PATH"
}

# Default action: serve the dashboard. Pass a subcommand (spike, collect,
# probe, fx) to do something else instead.
$command = if ($args.Count -gt 0) { $args } else { @("serve") }

# Queue the browser BEFORE starting the server: `uv run` blocks until the
# server stops, so anything after it would never run.
if ($command[0] -eq "serve") {
    Start-Job -ScriptBlock {
        Start-Sleep -Seconds 4
        Start-Process "http://127.0.0.1:4173"
    } | Out-Null
}

uv run python -m switch_tracker @command
exit $LASTEXITCODE
