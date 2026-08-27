param(
  [string]$TaskName = 'AR-local laptop backup',
  [Parameter(Mandatory = $true)][string]$Target,
  [Parameter(Mandatory = $true)][string]$RecoveryImage,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$CandidateCodeSha,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ProtectedCodeSha,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$PlanGitCommit,
  [string]$Operator = $env:USERNAME,
  [string]$PythonPath = (Get-Command python -ErrorAction Stop).Source
)

$ErrorActionPreference = 'Stop'
$repo = $PSScriptRoot
$script = Join-Path $repo 'laptop_backup_scheduled.py'
$runner = Join-Path $repo 'run_laptop_backup_task.ps1'
if ((git -C $repo status --porcelain) -or ((git -C $repo rev-parse HEAD).Trim() -ne $CandidateCodeSha)) {
  throw 'Task source must be a clean checkout at the exact candidate SHA.'
}

$arguments = @(
  '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
  '-File', ('"{0}"' -f $runner),
  '-PythonPath', ('"{0}"' -f $PythonPath),
  '-ScriptPath', ('"{0}"' -f $script),
  '-Target', ('"{0}"' -f (Resolve-Path -LiteralPath $Target).Path),
  '-RecoveryImage', ('"{0}"' -f (Resolve-Path -LiteralPath $RecoveryImage).Path),
  '-CandidateCodeSha', $CandidateCodeSha,
  '-ProtectedCodeSha', $ProtectedCodeSha,
  '-PlanGitCommit', $PlanGitCommit,
  '-Operator', ('"{0}"' -f $Operator)
) -join ' '

& $PythonPath $script --target $Target --recovery-image $RecoveryImage `
  --candidate-code-sha $CandidateCodeSha --protected-code-sha $ProtectedCodeSha `
  --plan-git-commit $PlanGitCommit --operator $Operator --check-only
if ($LASTEXITCODE -ne 0) { throw 'Manual backup and restore gate is not current; task was not registered.' }

$daily = New-ScheduledTaskTrigger -Daily -At '05:00'
$startup = New-ScheduledTaskTrigger -AtStartup
$startup.Delay = 'PT5M'
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -Argument $arguments -WorkingDirectory $repo
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 6) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 30) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
  -LogonType S4U -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger @($daily, $startup) -Settings $settings -Principal $principal `
  -Description 'Pulls and independently verifies AR-local Pi backup at 05:00 and at startup only when stale.'
try {
  Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force -ErrorAction Stop | Out-Null
} catch {
  throw "Scheduled task registration failed; the existing task was not accepted as updated: $($_.Exception.Message)"
}

$registered = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$registeredActions = @($registered.Actions)
$registeredTriggers = @($registered.Triggers)
$expectedExecutable = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$expectedPrincipalSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$dailyTrigger = @($registeredTriggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskDailyTrigger' })
$startupTrigger = @($registeredTriggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger' })
$mismatches = @()
if ($registeredActions.Count -ne 1) { $mismatches += 'action count' }
if ($registeredActions.Count -eq 1 -and $registeredActions[0].Execute -ne $expectedExecutable) { $mismatches += 'executable' }
if ($registeredActions.Count -eq 1 -and $registeredActions[0].Arguments -ne $arguments) { $mismatches += 'arguments' }
if ($registeredActions.Count -eq 1 -and $registeredActions[0].WorkingDirectory -ne $repo) { $mismatches += 'working directory' }
$registeredPrincipalSid = ([System.Security.Principal.NTAccount]$registered.Principal.UserId).Translate(
  [System.Security.Principal.SecurityIdentifier]
).Value
if ($registeredPrincipalSid -ne $expectedPrincipalSid) { $mismatches += 'principal identity' }
if ($registered.Principal.LogonType.ToString() -ne 'S4U') { $mismatches += 'logon type' }
if ($registered.Principal.RunLevel.ToString() -ne 'Limited') { $mismatches += 'run level' }
if (-not $registered.Settings.Enabled) { $mismatches += 'enabled state' }
if ($registered.Settings.MultipleInstances.ToString() -ne 'IgnoreNew') { $mismatches += 'overlap policy' }
if ($registered.Settings.RestartCount -ne 3) { $mismatches += 'retry count' }
if ($registered.Settings.RestartInterval -ne 'PT30M') { $mismatches += 'retry interval' }
if ($registered.Settings.ExecutionTimeLimit -ne 'PT6H') { $mismatches += 'runtime limit' }
if (-not $registered.Settings.StartWhenAvailable) { $mismatches += 'start-when-available' }
if ($dailyTrigger.Count -ne 1 -or ([datetimeoffset]$dailyTrigger[0].StartBoundary).TimeOfDay -ne [timespan]::FromHours(5)) { $mismatches += 'daily trigger' }
if ($startupTrigger.Count -ne 1 -or $startupTrigger[0].Delay -ne 'PT5M') { $mismatches += 'startup trigger' }
if ($mismatches.Count -gt 0) {
  throw "Scheduled task read-back verification failed: $($mismatches -join ', ')."
}

[pscustomobject]@{
  task_name = $registered.TaskName
  state = $registered.State.ToString()
  candidate_code_sha = $CandidateCodeSha
  daily_time = '05:00 Australia/Hobart laptop local time'
  startup_delay = 'PT5M'
  stale_action = 'verified latest observation: NO_WRITE; otherwise backup-latest'
} | ConvertTo-Json
