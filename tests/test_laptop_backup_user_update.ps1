param([string]$CorePath,[string]$TestRoot)
$ErrorActionPreference='Stop'
. $CorePath
function Get-ScheduledTask {
  $script:gets++
  $state='Ready'
  if($script:fault -ceq 'race' -and $script:gets -gt 1){$state='Running'}
  $argsValue=$script:action.Arguments
  if($script:fault -ceq 'old-action' -and $script:sets -eq 0){$argsValue='unexpected'}
  [pscustomobject]@{State=$state;Actions=@([pscustomobject]@{Execute='powershell';Arguments=$argsValue;WorkingDirectory=$script:action.WorkingDirectory});
    Principal=[pscustomobject]@{LogonType='Interactive';RunLevel='Limited';UserId='operator'}}
}
function Export-ScheduledTask {
  $settings='same'
  if($script:action.Arguments -ceq 'new' -and $script:fault -in @('readback','rollback')){$settings='changed'}
  '<?xml version="1.0" encoding="UTF-16"?><Task><Actions><Command>'+ $script:action.Arguments +'</Command></Actions><Triggers><Daily>same</Daily></Triggers><Principals><User>same</User></Principals><Settings><Value>'+ $settings +'</Value></Settings></Task>'
}
function New-ScheduledTaskAction {
  param($Execute,$Argument,$WorkingDirectory)
  if($script:fault -ceq 'action'){throw 'injected action construction failure'}
  [pscustomobject]@{Execute=$Execute;Arguments=$Argument;WorkingDirectory=$WorkingDirectory}
}
function Set-ScheduledTask {
  param($TaskName,$Action)
  $script:sets++
  if($script:fault -ceq 'rollback' -and $script:sets -eq 2){throw 'injected rollback failure'}
  $script:action=@($Action)[0]
}
foreach($case in @('success','old-action','probe','action','race','readback','rollback')) {
  $script:fault=$case
  $script:sets=0
  $script:gets=0
  $script:action=[pscustomobject]@{Execute='powershell';Arguments='old';WorkingDirectory='old-root'}
  $evidence=Join-Path $TestRoot $case
  $failed=$false
  try {
    Invoke-UserBackupTaskUpdate -Execute 'powershell' -OldArguments 'old' -NewArguments 'new' -OldReceiver 'old-root' -NewReceiver 'new-root' -EvidenceDirectory $evidence -OperatorName 'operator' -OperatorSid 'sid' -Verify {
      if($script:fault -ceq 'probe'){throw 'invalid predecessor'}
      '{"result":"PASS"}'
    }
  } catch { $failed=$true }
  if($case -ceq 'success') {
    if($failed -or $script:sets -ne 1 -or $script:action.Arguments -cne 'new'){throw 'Successful update failed'}
    $receipt=Get-Content (Join-Path $evidence 'installation.json') -Raw | ConvertFrom-Json
    if($receipt.result -cne 'PASS' -or $receipt.elevated){throw 'Invalid success receipt'}
    foreach($name in @('task-before.xml','task-after.xml')) {
      $xml=[xml]::new()
      $xml.Load((Join-Path $evidence $name))
      if(-not $xml.Task.Actions){throw 'Task XML evidence cannot be read independently'}
    }
  } else {
    if(-not $failed){throw "Expected failure: $case"}
    if($case -in @('old-action','probe','action','race') -and $script:sets -ne 0){throw 'Preflight failure mutated task'}
    if($case -in @('probe','action','race')) {
      $receipt=Get-Content (Join-Path $evidence 'installation-failed.json') -Raw | ConvertFrom-Json
      if($receipt.result -cne 'FAIL' -or $receipt.mutation_attempted -or $receipt.rollback -cne 'NOT_NEEDED'){throw 'Pre-mutation failure not terminalized correctly'}
    }
    if($case -in @('readback','rollback')) {
      $receipt=Get-Content (Join-Path $evidence 'installation-failed.json') -Raw | ConvertFrom-Json
      if($script:sets -ne 2 -or $receipt.result -cne 'FAIL'){throw 'Missing rollback attempt'}
      if($case -ceq 'readback' -and ($script:action.Arguments -cne 'old' -or $receipt.rollback -cne 'PASS')){throw 'Rollback failed'}
      if($case -ceq 'rollback' -and $receipt.rollback -notlike 'FAIL:*'){throw 'Rollback failure hidden'}
    }
  }
}
'PASS: update, preflight rejection, readback rollback and rollback failure evidence'
