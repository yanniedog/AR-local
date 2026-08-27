$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot '..\install_laptop_backup_task_core.ps1')

function Register-ScheduledTask {
  [CmdletBinding()]
  param(
    [string]$TaskName,
    [object]$InputObject,
    [switch]$Force
  )
  Write-Error 'Access is denied.'
}

$registrationOutput = @()
$registrationFailed = $false
try {
  $registrationOutput += Invoke-ArLaptopBackupTaskRegistration -TaskName 'test task' -Task ([pscustomobject]@{})
} catch {
  if ($_.Exception.Message -notmatch 'Scheduled task registration failed.*Access is denied') { throw }
  $registrationFailed = $true
}
if (-not $registrationFailed) { throw 'Registration denial did not fail closed.' }
if ($registrationOutput.Count -ne 0) { throw 'Registration denial emitted success output.' }

$registered = [pscustomobject]@{
  Actions = @([pscustomobject]@{
    Execute = 'pwsh.exe'
    Arguments = '-expected'
    WorkingDirectory = 'C:\receiver'
  })
  Principal = [pscustomobject]@{
    UserId = 'operator'
    LogonType = 'S4U'
    RunLevel = 'Limited'
  }
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
      StartBoundary = '2026-08-27T05:00:00+10:00'
    },
    [pscustomobject]@{
      CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskBootTrigger' }
      Delay = 'PT5M'
    }
  )
}
$resolvePrincipalSid = { param($UserId) 'S-1-test' }

Assert-ArLaptopBackupTaskDefinition -Registered $registered -ExpectedExecutable 'pwsh.exe' `
  -ExpectedArguments '-expected' -ExpectedWorkingDirectory 'C:\receiver' `
  -ExpectedPrincipalSid 'S-1-test' -ResolvePrincipalSid $resolvePrincipalSid

$registered.Actions[0].Arguments = '-wrong'
$readBackFailed = $false
try {
  Assert-ArLaptopBackupTaskDefinition -Registered $registered -ExpectedExecutable 'pwsh.exe' `
    -ExpectedArguments '-expected' -ExpectedWorkingDirectory 'C:\receiver' `
    -ExpectedPrincipalSid 'S-1-test' -ResolvePrincipalSid $resolvePrincipalSid
} catch {
  if ($_.Exception.Message -notmatch 'read-back verification failed: arguments') { throw }
  $readBackFailed = $true
}
if (-not $readBackFailed) { throw 'Mismatched read-back did not fail closed.' }
