function Get-ArSha256 {
  param([Parameter(Mandatory = $true)][string]$Path)
  (Get-FileHash -LiteralPath $Path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
}

function Get-ArTaskXmlBytes {
  param([Parameter(Mandatory = $true)][string]$TaskName)
  $xml = Export-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  [byte[]](0xff, 0xfe) + [Text.Encoding]::Unicode.GetBytes($xml)
}

function Get-ArTaskSddl {
  param([Parameter(Mandatory = $true)][string]$TaskName)
  $service = New-Object -ComObject 'Schedule.Service'
  $service.Connect()
  $service.GetFolder('\').GetTask("\$TaskName").GetSecurityDescriptor(7)
}

function Get-ArTextSha256 {
  param([Parameter(Mandatory = $true)][string]$Text)
  $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
  [Convert]::ToHexString([Security.Cryptography.SHA256]::HashData($bytes)).ToLowerInvariant()
}

function Get-ArDispatcherTaskArguments {
  param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$ControlRoot
  )
  @(
    '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
    '-File', ('"{0}"' -f (Join-Path $InstallRoot 'run_laptop_backup_dispatcher.ps1')),
    '-PythonPath', ('"{0}"' -f $PythonPath),
    '-DispatcherPath', ('"{0}"' -f (Join-Path $InstallRoot 'laptop_backup_dispatcher.py')),
    '-ControlRoot', ('"{0}"' -f $ControlRoot)
  ) -join ' '
}

function Assert-ArDispatcherTask {
  param(
    [Parameter(Mandatory = $true)][string]$TaskName,
    [Parameter(Mandatory = $true)][string]$ExpectedArguments,
    [Parameter(Mandatory = $true)][string]$ExpectedWorkingDirectory,
    [Parameter(Mandatory = $true)][string]$ExpectedPrincipalSid,
    [Parameter(Mandatory = $true)][bool]$ExpectedEnabled,
    [scriptblock]$ResolvePrincipalSid = {
      param($UserId)
      ([Security.Principal.NTAccount]$UserId).Translate(
        [Security.Principal.SecurityIdentifier]
      ).Value
    }
  )
  $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $actions = @($task.Actions)
  $triggers = @($task.Triggers)
  $daily = @($triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskDailyTrigger' })
  $boot = @($triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger' })
  $actualSid = & $ResolvePrincipalSid $task.Principal.UserId
  $expectedExe = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
  $mismatch = @()
  if ($actions.Count -ne 1) { $mismatch += 'action count' }
  elseif ($actions[0].Execute -ne $expectedExe -or
          $actions[0].Arguments -ne $ExpectedArguments -or
          $actions[0].WorkingDirectory -ne $ExpectedWorkingDirectory) { $mismatch += 'action' }
  if ($actualSid -ne $ExpectedPrincipalSid -or
      $task.Principal.LogonType.ToString() -ne 'S4U' -or
      $task.Principal.RunLevel.ToString() -ne 'Limited') { $mismatch += 'principal' }
  if ([bool]$task.Settings.Enabled -ne $ExpectedEnabled -or
      $task.Settings.MultipleInstances.ToString() -ne 'IgnoreNew' -or
      $task.Settings.RestartCount -ne 3 -or
      $task.Settings.RestartInterval -ne 'PT30M' -or
      $task.Settings.ExecutionTimeLimit -ne 'PT6H' -or
      -not $task.Settings.StartWhenAvailable) { $mismatch += 'settings' }
  if ($daily.Count -ne 1 -or ([datetimeoffset]$daily[0].StartBoundary).TimeOfDay -ne [timespan]::FromHours(5)) {
    $mismatch += 'daily trigger'
  }
  if ($boot.Count -ne 1 -or $boot[0].Delay -ne 'PT5M') { $mismatch += 'boot trigger' }
  if ($mismatch.Count -gt 0) { throw "Dispatcher task verification failed: $($mismatch -join ', ')." }
  $task
}

function Install-ArProtectedDispatcherFiles {
  param(
    [Parameter(Mandatory = $true)][string]$SourceRoot,
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$OperatorSid,
    [Parameter(Mandatory = $true)][hashtable]$ExpectedHashes
  )
  if (Test-Path -LiteralPath $InstallRoot) { throw 'Dispatcher install root already exists but is not accepted.' }
  New-Item -ItemType Directory -Path $InstallRoot -ErrorAction Stop | Out-Null
  foreach ($name in $ExpectedHashes.Keys) {
    $source = Join-Path $SourceRoot $name
    if ((Get-ArSha256 $source) -cne $ExpectedHashes[$name]) { throw "Dispatcher source hash mismatch: $name" }
    Copy-Item -LiteralPath $source -Destination (Join-Path $InstallRoot $name) -ErrorAction Stop
  }
  & "$env:SystemRoot\System32\icacls.exe" $InstallRoot '/inheritance:r' '/grant:r' `
    '*S-1-5-18:(OI)(CI)(F)' '*S-1-5-32-544:(OI)(CI)(F)' "*$OperatorSid`:(OI)(CI)(RX)" '/T' '/C' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Failed to apply protected dispatcher ACL.' }
  foreach ($name in $ExpectedHashes.Keys) {
    if ((Get-ArSha256 (Join-Path $InstallRoot $name)) -cne $ExpectedHashes[$name]) {
      throw "Installed dispatcher hash mismatch: $name"
    }
  }
  Assert-ArProtectedDispatcherAcl -InstallRoot $InstallRoot -OperatorSid $OperatorSid
}

function Assert-ArProtectedDispatcherAcl {
  param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$OperatorSid
  )
  $dangerous = [Security.AccessControl.FileSystemRights]::Write -bor
    [Security.AccessControl.FileSystemRights]::Delete -bor
    [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor
    [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
    [Security.AccessControl.FileSystemRights]::TakeOwnership
  foreach ($path in @($InstallRoot) + @(Get-ChildItem -LiteralPath $InstallRoot -File | ForEach-Object FullName)) {
    $acl = Get-Acl -LiteralPath $path -ErrorAction Stop
    if (-not $acl.AreAccessRulesProtected) { throw "Dispatcher ACL inheritance remains enabled: $path" }
    foreach ($rule in $acl.Access) {
      $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
      if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
          $sid -eq $OperatorSid -and ($rule.FileSystemRights -band $dangerous)) {
        throw "Operator retains dispatcher write or ownership rights: $path"
      }
    }
  }
}

function New-ArDispatcherTaskDefinition {
  param(
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$Arguments,
    [Parameter(Mandatory = $true)][string]$Operator
  )
  $daily = New-ScheduledTaskTrigger -Daily -At '05:00'
  $startup = New-ScheduledTaskTrigger -AtStartup
  $startup.Delay = 'PT5M'
  $action = New-ScheduledTaskAction `
    -Execute "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" `
    -Argument $Arguments -WorkingDirectory $InstallRoot
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6) -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries
  $settings.Enabled = $false
  $principal = New-ScheduledTaskPrincipal -UserId $Operator -LogonType S4U -RunLevel Limited
  New-ScheduledTask -Action $action -Trigger @($daily, $startup) -Settings $settings `
    -Principal $principal -Description 'Runs the fixed non-elevated AR-local laptop-backup dispatcher.'
}

function Restore-ArPriorTask {
  param(
    [Parameter(Mandatory = $true)][string]$TaskName,
    [Parameter(Mandatory = $true)][string]$TaskXml,
    [Parameter(Mandatory = $true)][string]$TaskSddl
  )
  Register-ScheduledTask -TaskName $TaskName -Xml $TaskXml -Force -ErrorAction Stop | Out-Null
  $service = New-Object -ComObject 'Schedule.Service'
  $service.Connect()
  $service.GetFolder('\').GetTask("\$TaskName").SetSecurityDescriptor($TaskSddl, 0)
  Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
}
