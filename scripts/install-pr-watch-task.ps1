# Register Windows Scheduled Task for AR-local PR watch autopilot (at logon, restart on failure).
#Requires -RunAsAdministrator
param(
    [string]$RepoRoot = (Split-Path $PSScriptRoot -Parent),
    [string]$TaskName = 'AR-local-PR-Watch-Autopilot',
    [string]$UserId = $env:USERNAME
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path $RepoRoot).Path
$hostScript = Join-Path $RepoRoot 'scripts\ar-local-pr-watch-autopilot.ps1'
if (-not (Test-Path $hostScript)) {
    throw "Missing host script: $hostScript"
}

$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$hostScript`" -RepoRoot `"$RepoRoot`"" `
    -WorkingDirectory $RepoRoot

$trigger = New-ScheduledTaskTrigger -AtLogOn -User $UserId
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Registered scheduled task: $TaskName"
Write-Host "  Repo: $RepoRoot"
Write-Host "  Host: $hostScript"
Write-Host "  Logs: $RepoRoot\.ar-pr-watch\autopilot.log"
Write-Host ""
Write-Host "Start now:  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "Stop:       Stop-ScheduledTask -TaskName '$TaskName'"
Write-Host "Remove:     Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
Write-Host ""
Write-Host "Prerequisites: gh auth login, optional Cursor CLI (agent) or CURSOR_API_KEY + @cursor/sdk"
Write-Host "Probe:        cd `"$RepoRoot`"; npm run pr:watch:autopilot -- --probe-cursor"
