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
if ((git -C $repo status --porcelain) -or ((git -C $repo rev-parse HEAD).Trim() -ne $CandidateCodeSha)) {
  throw 'Task source must be a clean checkout at the exact candidate SHA.'
}

$arguments = @(
  ('"{0}"' -f $script),
  '--target', ('"{0}"' -f (Resolve-Path -LiteralPath $Target).Path),
  '--recovery-image', ('"{0}"' -f (Resolve-Path -LiteralPath $RecoveryImage).Path),
  '--candidate-code-sha', $CandidateCodeSha,
  '--protected-code-sha', $ProtectedCodeSha,
  '--plan-git-commit', $PlanGitCommit,
  '--operator', ('"{0}"' -f $Operator)
) -join ' '

& $PythonPath $script --target $Target --recovery-image $RecoveryImage `
  --candidate-code-sha $CandidateCodeSha --protected-code-sha $ProtectedCodeSha `
  --plan-git-commit $PlanGitCommit --operator $Operator --check-only
if ($LASTEXITCODE -ne 0) { throw 'Manual backup and restore gate is not current; task was not registered.' }

$daily = New-ScheduledTaskTrigger -Daily -At '05:00'
$startup = New-ScheduledTaskTrigger -AtStartup
$startup.Delay = 'PT5M'
$action = New-ScheduledTaskAction -Execute $PythonPath -Argument $arguments -WorkingDirectory $repo
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
  -ExecutionTimeLimit (New-TimeSpan -Hours 6) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId ([System.Security.Principal.WindowsIdentity]::GetCurrent().Name) `
  -LogonType S4U -RunLevel Limited
$task = New-ScheduledTask -Action $action -Trigger @($daily, $startup) -Settings $settings -Principal $principal `
  -Description 'Pulls and independently verifies AR-local Pi backup at 05:00 and at startup only when stale.'
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null

$registered = Get-ScheduledTask -TaskName $TaskName
[pscustomobject]@{
  task_name = $registered.TaskName
  state = $registered.State.ToString()
  candidate_code_sha = $CandidateCodeSha
  daily_time = '05:00 Australia/Hobart laptop local time'
  startup_delay = 'PT5M'
  stale_action = 'verified latest observation: NO_WRITE; otherwise backup-latest'
} | ConvertTo-Json
