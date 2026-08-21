# Registers a Windows scheduled task that runs a collection twice a day.
#
#     powershell -ExecutionPolicy Bypass -File .\schedule-task.ps1
#
# Remove it later with:
#     Unregister-ScheduledTask -TaskName "switch-tracker" -Confirm:$false

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$taskName = "switch-tracker"
$bun = "$env:USERPROFILE\.bun\bin\bun.exe"
if (-not (Test-Path $bun)) { $bun = (Get-Command bun).Source }

# cmd wraps it so stdout can be redirected to a log - the scheduler gives you
# only an exit code otherwise, and a store failing silently is exactly the
# thing worth being able to read afterwards.
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"`"$bun`" run collect >> `"$PSScriptRoot\collect.log`" 2>&1`"" `
    -WorkingDirectory $PSScriptRoot

$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At 7:30am),
    (New-ScheduledTaskTrigger -Daily -At 9:30pm)
)

# StartWhenAvailable catches up a run missed because the machine was asleep,
# which on a desktop PC is most of them.
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $triggers `
    -Settings $settings `
    -Description "Collect Nintendo Switch cartridge prices" `
    -Force | Out-Null

Write-Host "Scheduled '$taskName' for 07:30 and 21:30 daily." -ForegroundColor Green
Write-Host "  Log:       $PSScriptRoot\collect.log"
Write-Host "  Run now:   Start-ScheduledTask -TaskName $taskName"
Write-Host "  Remove:    Unregister-ScheduledTask -TaskName $taskName -Confirm:`$false"
