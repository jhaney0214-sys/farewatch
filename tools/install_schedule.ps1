<#
    Register a Windows Scheduled Task that refreshes Farewatch every morning.

    A tool that only works when you remember to open it mostly does not work.
    This runs the refresh in the background so the report is already current
    when you double-click Farewatch.cmd.

    Install:    powershell -ExecutionPolicy Bypass -File tools\install_schedule.ps1
    Change time: -At "07:30"
    Remove:     powershell -ExecutionPolicy Bypass -File tools\install_schedule.ps1 -Remove
#>

param(
    [string]$At = "07:00",
    [string]$TaskName = "Farewatch daily refresh",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Output "Removed scheduled task: $TaskName"
    } else {
        Write-Output "No scheduled task named '$TaskName' to remove."
    }
    return
}

$python = (Get-Command python -ErrorAction SilentlyContinue).Source
if (-not $python) {
    throw "python was not found on PATH. Install Python or run fw.py manually."
}

# --refresh so the run ignores the 30-minute feed cache; no --open, because a
# browser window appearing on its own at 7am is not a feature.
$action = New-ScheduledTaskAction -Execute $python `
    -Argument "fw.py run --refresh --quiet" -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At $At

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Description "Refresh Farewatch travel deal rankings." | Out-Null

Write-Output "Registered '$TaskName' - runs daily at $At."
Write-Output "Working directory: $root"
Write-Output "Remove it with: powershell -ExecutionPolicy Bypass -File tools\install_schedule.ps1 -Remove"
