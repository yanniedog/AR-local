$ErrorActionPreference = 'Stop'
. (Join-Path (Join-Path $PSScriptRoot '..') 'install_laptop_backup_task_core.ps1')

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
$registrationTask = [pscustomobject]@{ Settings = [pscustomobject]@{ Enabled = $true } }
try {
  $registrationOutput += Invoke-ArLaptopBackupTaskRegistration -TaskName 'test task' -Task $registrationTask
} catch {
  if ($_.Exception.Message -notmatch 'Scheduled task registration failed.*Access is denied') { throw }
  $registrationFailed = $true
}
if (-not $registrationFailed) { throw 'Registration denial did not fail closed.' }
if ($registrationOutput.Count -ne 0) { throw 'Registration denial emitted success output.' }
if ($registrationTask.Settings.Enabled) { throw 'Task was not disabled before registration.' }

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
  -ExpectedPrincipalSid 'S-1-test' -ExpectedEnabled $true -ResolvePrincipalSid $resolvePrincipalSid

$registered.Actions[0].Arguments = '-wrong'
$readBackFailed = $false
try {
  Assert-ArLaptopBackupTaskDefinition -Registered $registered -ExpectedExecutable 'pwsh.exe' `
    -ExpectedArguments '-expected' -ExpectedWorkingDirectory 'C:\receiver' `
    -ExpectedPrincipalSid 'S-1-test' -ExpectedEnabled $true -ResolvePrincipalSid $resolvePrincipalSid
} catch {
  if ($_.Exception.Message -notmatch 'read-back verification failed: arguments') { throw }
  $readBackFailed = $true
}
if (-not $readBackFailed) { throw 'Mismatched read-back did not fail closed.' }

$disableCalled = $false
$activationFailed = $false
try {
  Enable-ArLaptopBackupTaskAfterVerification -TaskName 'test task' `
    -EnableTask { param($Name) } `
    -GetTask { param($Name) $registered } `
    -VerifyEnabledTask { param($Task) throw 'simulated enabled read-back mismatch' } `
    -DisableTask { param($Name) $script:disableCalled = $true }
} catch {
  if ($_.Exception.Message -notmatch 'activation/read-back failed; the task was disabled') { throw }
  $activationFailed = $true
}
if (-not $activationFailed) { throw 'Activation mismatch did not fail closed.' }
if (-not $disableCalled) { throw 'Activation mismatch did not disable the task.' }
