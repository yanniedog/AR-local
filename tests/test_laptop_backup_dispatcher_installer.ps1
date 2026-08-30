$ErrorActionPreference = 'Stop'
. (Join-Path (Join-Path $PSScriptRoot '..') 'install_laptop_backup_dispatcher_core.ps1')

$script:registered = [pscustomobject]@{
  Actions = @([pscustomobject]@{
    Execute = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
    Arguments = '-expected'
    WorkingDirectory = 'C:\Program Files\AR-local Backup Dispatcher'
  })
  Principal = [pscustomobject]@{ UserId = 'operator'; LogonType = 'S4U'; RunLevel = 'Limited' }
  Settings = [pscustomobject]@{
    Enabled = $true
    MultipleInstances = 'IgnoreNew'
    RestartCount = 3
    RestartInterval = 'PT30M'
    ExecutionTimeLimit = 'PT6H'
    StartWhenAvailable = $true
  }
  Triggers = @(
    [pscustomobject]@{
      CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskDailyTrigger' }
      StartBoundary = '2026-08-30T05:00:00+10:00'
    },
    [pscustomobject]@{
      CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskBootTrigger' }
      Delay = 'PT5M'
    }
  )
}

function Get-ScheduledTask { param([string]$TaskName) $script:registered }
$resolve = { param($UserId) 'S-1-test' }

Assert-ArDispatcherTask -TaskName 'test' -ExpectedArguments '-expected' `
  -ExpectedWorkingDirectory 'C:\Program Files\AR-local Backup Dispatcher' `
  -ExpectedPrincipalSid 'S-1-test' -ExpectedEnabled $true -ResolvePrincipalSid $resolve | Out-Null

$script:registered.Actions[0].Arguments = '-wrong'
$failed = $false
try {
  Assert-ArDispatcherTask -TaskName 'test' -ExpectedArguments '-expected' `
    -ExpectedWorkingDirectory 'C:\Program Files\AR-local Backup Dispatcher' `
    -ExpectedPrincipalSid 'S-1-test' -ExpectedEnabled $true -ResolvePrincipalSid $resolve | Out-Null
} catch {
  if ($_.Exception.Message -notmatch 'verification failed: action') { throw }
  $failed = $true
}
if (-not $failed) { throw 'Mismatched dispatcher action did not fail closed.' }

$arguments = Get-ArDispatcherTaskArguments `
  -InstallRoot 'C:\Program Files\AR-local Backup Dispatcher' `
  -PythonPath 'C:\Python\python.exe' -ControlRoot 'C:\backup\dispatcher-control'
if ($arguments -notmatch 'run_laptop_backup_dispatcher\.ps1' -or
    $arguments -notmatch 'laptop_backup_dispatcher\.py' -or
    $arguments -notmatch 'dispatcher-control') {
  throw 'Fixed dispatcher task arguments are incomplete.'
}
