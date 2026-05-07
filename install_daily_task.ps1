param(
  [string]$TaskName = "AustralianRates-Local-CDR-Ingest",
  # Local wall time for Task Scheduler (drifts across DST vs fixed UTC). Prefer -RunAtUtc from start_here.py option 5.
  [string]$At = "20:00",
  [string]$ExtraArgs = "--workers 8",
  [switch]$RunAtUtc,
  # 24h UTC clock HH:mm used only when -RunAtUtc (DST-safe daily trigger).
  [string]$UtcAt = "20:00"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

$PythonExe = $null
$PyPrefixArgs = ""
if (Get-Command python -ErrorAction SilentlyContinue) {
  $PythonExe = (Get-Command python).Source
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
  $PythonExe = (Get-Command py).Source
  $PyPrefixArgs = "-3 "
} else {
  throw "Neither python nor py launcher found on PATH."
}

$Daily = Join-Path $ScriptDir "cdr_daily.py"
$Argument = if ($PyPrefixArgs) { "${PyPrefixArgs}`"$Daily`" $ExtraArgs" } else { "`"$Daily`" $ExtraArgs" }

if ($RunAtUtc) {
  $parts = $UtcAt -split ':'
  if ($parts.Length -lt 2) {
    throw "UtcAt must be HH:mm (UTC, 24h), got: $UtcAt"
  }
  $uh = [int]$parts[0]
  $um = [int]$parts[1]
  $startBoundary = "2000-01-01T{0:D2}:{1:D2}:00Z" -f $uh, $um

  $escapedCmd = [System.Security.SecurityElement]::Escape($PythonExe)
  $escapedArg = [System.Security.SecurityElement]::Escape($Argument)
  $escapedWd = [System.Security.SecurityElement]::Escape($ScriptDir)

  $xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>Runs Australian Rates local manual CDR ingest daily at $UtcAt UTC (DST-stable).</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>$startBoundary</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>true</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT8H</ExecutionTimeLimit>
    <Priority>7</Priority>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>$escapedCmd</Command>
      <Arguments>$escapedArg</Arguments>
      <WorkingDirectory>$escapedWd</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"@

  Register-ScheduledTask -TaskName $TaskName -Xml $xml -Force | Out-Null
  Write-Host "Registered $TaskName daily at $UtcAt UTC (DST-stable) using $Daily"
  return
}

$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument $Argument -WorkingDirectory $ScriptDir
$Trigger = New-ScheduledTaskTrigger -Daily -At $At
$Settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 8)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Runs Australian Rates local manual CDR ingest once per day." -Force | Out-Null
Write-Host "Registered $TaskName at local wall time $At using $Daily"
