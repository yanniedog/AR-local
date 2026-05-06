param(
  [string]$TaskName = "AustralianRates-Local-CDR-Ingest",
  # Local wall time for Task Scheduler. For 20:00 UTC, use start_here.py (option 5) so the time is TZ-adjusted.
  [string]$At = "20:00",
  [string]$ExtraArgs = "--workers 8"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Python = (Get-Command python).Source
$Daily = Join-Path $ScriptDir "cdr_daily.py"
$Argument = "`"$Daily`" $ExtraArgs"

$Action = New-ScheduledTaskAction -Execute $Python -Argument $Argument -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 8)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Runs Australian Rates local manual CDR ingest once per day." -Force | Out-Null
Write-Host "Registered $TaskName at $At using $Daily"
