function Get-ArTransitionTaskSnapshot {
  param([Parameter(Mandatory = $true)][string]$Name)

  $task = Get-ScheduledTask -TaskName $Name -ErrorAction Stop
  $info = Get-ScheduledTaskInfo -TaskName $Name -ErrorAction Stop
  $xml = Export-ScheduledTask -TaskName $Name -ErrorAction Stop
  $actions = @($task.Actions | ForEach-Object {
    [ordered]@{
      execute = [string]$_.Execute
      arguments = [string]$_.Arguments
      working_directory = [string]$_.WorkingDirectory
    }
  })
  $triggers = @($task.Triggers | ForEach-Object {
    $class = $_.CimClass.CimClassName
    if ($class -eq 'MSFT_TaskDailyTrigger') {
      [ordered]@{ kind = 'daily'; at = ([datetimeoffset]$_.StartBoundary).TimeOfDay.ToString(); delay = '' }
    } elseif ($class -eq 'MSFT_TaskBootTrigger') {
      [ordered]@{ kind = 'boot'; at = ''; delay = [string]$_.Delay }
    } else {
      [ordered]@{ kind = $class; at = [string]$_.StartBoundary; delay = [string]$_.Delay }
    }
  })
  $receiverSha = ''
  if ($actions.Count -eq 1 -and $actions[0].arguments -match '(?i)-CandidateCodeSha\s+([0-9a-f]{40})') {
    $receiverSha = $Matches[1].ToLowerInvariant()
  }
  $xmlBytes = [byte[]](0xff, 0xfe) + [Text.Encoding]::Unicode.GetBytes($xml)
  [ordered]@{
    state = $task.State.ToString()
    enabled = [bool]$task.Settings.Enabled
    last_task_result = [int64]$info.LastTaskResult
    next_run_time = $info.NextRunTime.ToString('o')
    actions = $actions
    triggers = $triggers
    principal = [ordered]@{
      user_id = ([string]$task.Principal.UserId).ToLowerInvariant()
      logon_type = $task.Principal.LogonType.ToString()
      run_level = $task.Principal.RunLevel.ToString()
    }
    settings = [ordered]@{
      enabled = [bool]$task.Settings.Enabled
      multiple_instances = $task.Settings.MultipleInstances.ToString()
      restart_count = [int]$task.Settings.RestartCount
      restart_interval = [string]$task.Settings.RestartInterval
      execution_time_limit = [string]$task.Settings.ExecutionTimeLimit
      start_when_available = [bool]$task.Settings.StartWhenAvailable
    }
    receiver_sha = $receiverSha
    xml_base64 = [Convert]::ToBase64String($xmlBytes)
  }
}

function Invoke-ArTransitionTaskAction {
  param(
    [Parameter(Mandatory = $true)][ValidateSet('Snapshot', 'Disable', 'Install', 'RestoreDisabled', 'Enable')][string]$Action,
    [Parameter(Mandatory = $true)][string]$TaskName,
    [string]$Receiver,
    [string]$Target,
    [string]$RecoveryImage,
    [string]$CandidateCodeSha,
    [string]$ProtectedCodeSha,
    [string]$PlanGitCommit,
    [string]$Operator,
    [string]$PythonPath,
    [string]$OldTaskXmlPath,
    [string]$TransitionId
  )

  switch ($Action) {
    'Snapshot' { return Get-ArTransitionTaskSnapshot -Name $TaskName }
    'Disable' {
      $before = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
      if ($before.State.ToString() -ne 'Ready') { throw "Task is not Ready before disable: $($before.State)" }
      Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
      $snapshot = Get-ArTransitionTaskSnapshot -Name $TaskName
      if ($snapshot.state -ne 'Disabled' -or $snapshot.enabled) { throw 'Task disable read-back failed.' }
      return $snapshot
    }
    'Install' {
      if ([string]::IsNullOrWhiteSpace($TransitionId)) { throw 'Install action lacks transition identity.' }
      foreach ($required in @($Receiver, $Target, $RecoveryImage, $CandidateCodeSha, $ProtectedCodeSha, $PlanGitCommit, $Operator, $PythonPath)) {
        if ([string]::IsNullOrWhiteSpace($required)) { throw 'Install action lacks a required exact argument.' }
      }
      $installer = Join-Path $Receiver 'install_laptop_backup_task.ps1'
      $output = & $installer -TaskName $TaskName -Target $Target -RecoveryImage $RecoveryImage `
        -CandidateCodeSha $CandidateCodeSha -ProtectedCodeSha $ProtectedCodeSha `
        -PlanGitCommit $PlanGitCommit -Operator $Operator -PythonPath $PythonPath `
        -TransitionId $TransitionId 2>&1
      if ($LASTEXITCODE -ne 0) { throw "Installer failed: $($output -join [Environment]::NewLine)" }
      return [ordered]@{
        task = Get-ArTransitionTaskSnapshot -Name $TaskName
        installer_stdout = ($output -join [Environment]::NewLine)
      }
    }
    'RestoreDisabled' {
      if ([string]::IsNullOrWhiteSpace($OldTaskXmlPath)) { throw 'Restore action lacks old task XML.' }
      [xml]$oldXml = Get-Content -LiteralPath $OldTaskXmlPath -Raw -ErrorAction Stop
      $oldXml.Task.Settings.Enabled = 'false'
      Register-ScheduledTask -TaskName $TaskName -Xml $oldXml.OuterXml -Force -ErrorAction Stop | Out-Null
      Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
      $snapshot = Get-ArTransitionTaskSnapshot -Name $TaskName
      if ($snapshot.state -ne 'Disabled' -or $snapshot.enabled) { throw 'Restored task disable read-back failed.' }
      return $snapshot
    }
    'Enable' {
      Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
      return Get-ArTransitionTaskSnapshot -Name $TaskName
    }
  }
}
