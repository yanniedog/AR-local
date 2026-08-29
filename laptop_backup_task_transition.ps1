param(
  [Parameter(Mandatory = $true)][ValidateSet('Snapshot', 'Disable', 'Install', 'Restore')][string]$Action,
  [string]$TaskName = 'AR-local laptop backup',
  [string]$Receiver,
  [string]$Target,
  [string]$RecoveryImage,
  [ValidatePattern('^[0-9a-f]{40}$')][string]$CandidateCodeSha,
  [ValidatePattern('^[0-9a-f]{40}$')][string]$ProtectedCodeSha,
  [ValidatePattern('^[0-9a-f]{40}$')][string]$PlanGitCommit,
  [string]$Operator,
  [string]$PythonPath,
  [string]$OldTaskXmlPath,
  [string]$TransitionId
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'laptop_backup_task_transition_core.ps1')

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) { throw 'Task transition requires an elevated Windows process.' }
$identity = ([Security.Principal.WindowsIdentity]::GetCurrent().Name).ToLowerInvariant()
if ($identity -ne 'yanniedog\jkoka') { throw "Unexpected task-transition identity: $identity" }

Invoke-ArTransitionTaskAction -Action $Action -TaskName $TaskName -Receiver $Receiver `
  -Target $Target -RecoveryImage $RecoveryImage -CandidateCodeSha $CandidateCodeSha `
  -ProtectedCodeSha $ProtectedCodeSha -PlanGitCommit $PlanGitCommit -Operator $Operator `
  -PythonPath $PythonPath -OldTaskXmlPath $OldTaskXmlPath -TransitionId $TransitionId |
  ConvertTo-Json -Depth 9 -Compress
