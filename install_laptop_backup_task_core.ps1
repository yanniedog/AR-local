function Invoke-ArLaptopBackupTaskRegistration {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string]$TaskName,
    [Parameter(Mandatory = $true)][object]$Task,
    [scriptblock]$RegisterTask = {
      param($Name, $InputTask)
      Register-ScheduledTask -TaskName $Name -InputObject $InputTask -Force -ErrorAction Stop | Out-Null
    }
  )

  $Task.Settings.Enabled = $false
  try {
    & $RegisterTask $TaskName $Task
  } catch {
    throw "Scheduled task registration failed; the existing task was not accepted as updated: $($_.Exception.Message)"
  }
}

function Assert-ArLaptopBackupTaskDefinition {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][object]$Registered,
    [Parameter(Mandatory = $true)][string]$ExpectedExecutable,
    [Parameter(Mandatory = $true)][string]$ExpectedArguments,
    [Parameter(Mandatory = $true)][string]$ExpectedWorkingDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedPrincipalSid,
    [Parameter(Mandatory = $true)][bool]$ExpectedEnabled,
    [scriptblock]$ResolvePrincipalSid = {
      param($UserId)
      ([System.Security.Principal.NTAccount]$UserId).Translate(
        [System.Security.Principal.SecurityIdentifier]
      ).Value
    }
  )

  $registeredActions = @($Registered.Actions)
  $registeredTriggers = @($Registered.Triggers)
  $dailyTrigger = @($registeredTriggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskDailyTrigger' })
  $startupTrigger = @($registeredTriggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger' })
  $mismatches = @()
  if ($registeredActions.Count -ne 1) { $mismatches += 'action count' }
  if ($registeredActions.Count -eq 1 -and $registeredActions[0].Execute -ne $ExpectedExecutable) { $mismatches += 'executable' }
  if ($registeredActions.Count -eq 1 -and $registeredActions[0].Arguments -ne $ExpectedArguments) { $mismatches += 'arguments' }
  if ($registeredActions.Count -eq 1 -and $registeredActions[0].WorkingDirectory -ne $ExpectedWorkingDirectory) { $mismatches += 'working directory' }
  $registeredPrincipalSid = & $ResolvePrincipalSid $Registered.Principal.UserId
  if ($registeredPrincipalSid -ne $ExpectedPrincipalSid) { $mismatches += 'principal identity' }
  if ($Registered.Principal.LogonType.ToString() -ne 'S4U') { $mismatches += 'logon type' }
  if ($Registered.Principal.RunLevel.ToString() -ne 'Limited') { $mismatches += 'run level' }
  if ([bool]$Registered.Settings.Enabled -ne $ExpectedEnabled) { $mismatches += 'enabled state' }
  if ($Registered.Settings.MultipleInstances.ToString() -ne 'IgnoreNew') { $mismatches += 'overlap policy' }
  if ($Registered.Settings.RestartCount -ne 3) { $mismatches += 'retry count' }
  if ($Registered.Settings.RestartInterval -ne 'PT30M') { $mismatches += 'retry interval' }
  if ($Registered.Settings.ExecutionTimeLimit -ne 'PT6H') { $mismatches += 'runtime limit' }
  if (-not $Registered.Settings.StartWhenAvailable) { $mismatches += 'start-when-available' }
  if ($dailyTrigger.Count -ne 1 -or ([datetimeoffset]$dailyTrigger[0].StartBoundary).TimeOfDay -ne [timespan]::FromHours(5)) { $mismatches += 'daily trigger' }
  if ($startupTrigger.Count -ne 1 -or $startupTrigger[0].Delay -ne 'PT5M') { $mismatches += 'startup trigger' }
  if ($mismatches.Count -gt 0) {
    throw "Scheduled task read-back verification failed: $($mismatches -join ', ')."
  }
}

function Enable-ArLaptopBackupTaskAfterVerification {
  [CmdletBinding()]
  param(
    [Parameter(Mandatory = $true)][string]$TaskName,
    [Parameter(Mandatory = $true)][scriptblock]$VerifyEnabledTask,
    [scriptblock]$EnableTask = {
      param($Name)
      Enable-ScheduledTask -TaskName $Name -ErrorAction Stop | Out-Null
    },
    [scriptblock]$GetTask = {
      param($Name)
      Get-ScheduledTask -TaskName $Name -ErrorAction Stop
    },
    [scriptblock]$DisableTask = {
      param($Name)
      Disable-ScheduledTask -TaskName $Name -ErrorAction Stop | Out-Null
    }
  )

  try {
    & $EnableTask $TaskName
    $enabledTask = & $GetTask $TaskName
    & $VerifyEnabledTask $enabledTask
    return $enabledTask
  } catch {
    $activationError = $_.Exception.Message
    try {
      & $DisableTask $TaskName
    } catch {
      throw "Scheduled task activation/read-back failed ($activationError), and disabling it also failed: $($_.Exception.Message)"
    }
    throw "Scheduled task activation/read-back failed; the task was disabled: $activationError"
  }
}
