# Task-only transaction; the entrypoint supplies verified immutable configurations.
function Write-UserUpdateEvidence([string]$Path, [string]$Text) {
  $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
  try {
    # Task Scheduler exports an XML declaration naming UTF-16. Preserve it with
    # matching bytes and BOM so saved evidence is independently parseable.
    $encoding=[Text.UTF8Encoding]::new($false)
    if($Path.EndsWith('.xml',[StringComparison]::OrdinalIgnoreCase)){$encoding=[Text.UnicodeEncoding]::new($false,$true)}
    $bytes=$encoding.GetPreamble()+$encoding.GetBytes($Text)
    $stream.Write($bytes,0,$bytes.Length)
  } finally { $stream.Dispose() }
}

function Invoke-UserBackupTaskUpdate {
  param([string]$Execute, [string]$OldArguments, [string]$NewArguments,
        [string]$OldReceiver, [string]$NewReceiver, [string]$EvidenceDirectory,
        [scriptblock]$Verify, [string]$OperatorName, [string]$OperatorSid)
  $taskName='AR-local user-session backup'
  $existing=Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
  if($existing.State.ToString() -cne 'Ready' -or $existing.Actions.Count -ne 1){throw 'User backup task is not idle and ready.'}
  $oldAction=$existing.Actions[0]
  if($existing.Principal.LogonType.ToString() -cne 'Interactive' -or $existing.Principal.RunLevel.ToString() -cne 'Limited' -or
     $existing.Principal.UserId -notin @($OperatorName,$OperatorSid,($OperatorName -split '\\')[-1])){throw 'Task principal differs from the ordinary user.'}
  if($oldAction.Execute -ine $Execute -or $oldAction.Arguments -cne $OldArguments -or
     ($oldAction.WorkingDirectory -and $oldAction.WorkingDirectory -cne $OldReceiver)){throw 'Existing task action differs from the verified receiver.'}
  $before=Export-ScheduledTask -TaskName $taskName
  New-Item -ItemType Directory -Path $EvidenceDirectory -ErrorAction Stop | Out-Null
  Write-UserUpdateEvidence (Join-Path $EvidenceDirectory 'task-before.xml') $before
  $verification=& $Verify
  Write-UserUpdateEvidence (Join-Path $EvidenceDirectory 'predecessor-verification.json') ($verification -join "`n")
  $action=New-ScheduledTaskAction -Execute $Execute -Argument $NewArguments -WorkingDirectory $NewReceiver
  # No task changes if a natural trigger or another operator raced the preflight.
  if((Get-ScheduledTask -TaskName $taskName).State.ToString() -cne 'Ready' -or
     (Export-ScheduledTask -TaskName $taskName) -cne $before){throw 'Task changed during update verification.'}
  try {
    Set-ScheduledTask -TaskName $taskName -Action $action -ErrorAction Stop | Out-Null
    $after=Export-ScheduledTask -TaskName $taskName
    [xml]$oldXml=$before
    [xml]$newXml=$after
    foreach($section in @('Triggers','Principals','Settings')) {
      $oldSection=$oldXml.DocumentElement.SelectSingleNode("*[local-name()='$section']")
      $newSection=$newXml.DocumentElement.SelectSingleNode("*[local-name()='$section']")
      if(-not $oldSection -or -not $newSection -or $oldSection.OuterXml -cne $newSection.OuterXml){throw "Task $section changed."}
    }
    $actual=Get-ScheduledTask -TaskName $taskName
    if($actual.Actions.Count -ne 1 -or $actual.Actions[0].Execute -ine $Execute -or
       $actual.Actions[0].Arguments -cne $NewArguments -or $actual.Actions[0].WorkingDirectory -cne $NewReceiver){throw 'Task action readback mismatch.'}
    Write-UserUpdateEvidence (Join-Path $EvidenceDirectory 'task-after.xml') $after
    Write-UserUpdateEvidence (Join-Path $EvidenceDirectory 'installation.json') (
      [ordered]@{result='PASS';elevated=$false;task=$taskName;completed_at_utc=[DateTime]::UtcNow.ToString('o');
        old_receiver=$OldReceiver;new_receiver=$NewReceiver;settings_preserved=$true;trigger='NO_BACKUP_STARTED'} | ConvertTo-Json)
  } catch {
    $originalError=$_.Exception.Message
    $rollback='PASS'
    try {
      Set-ScheduledTask -TaskName $taskName -Action $existing.Actions -ErrorAction Stop | Out-Null
      [xml]$rolled=Export-ScheduledTask -TaskName $taskName
      [xml]$original=$before
      foreach($section in @('Actions','Triggers','Principals','Settings')) {
        $rolledSection=$rolled.DocumentElement.SelectSingleNode("*[local-name()='$section']")
        $originalSection=$original.DocumentElement.SelectSingleNode("*[local-name()='$section']")
        if(-not $rolledSection -or -not $originalSection -or $rolledSection.OuterXml -cne $originalSection.OuterXml){throw "Rollback $section mismatch."}
      }
    } catch { $rollback='FAIL: '+$_.Exception.Message }
    Write-UserUpdateEvidence (Join-Path $EvidenceDirectory 'installation-failed.json') (
      [ordered]@{result='FAIL';error=$originalError;rollback=$rollback;completed_at_utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json)
    throw "User task update failed: $originalError; rollback: $rollback"
  }
}
