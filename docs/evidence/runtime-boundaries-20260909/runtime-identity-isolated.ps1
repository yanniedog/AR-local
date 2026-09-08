param([Parameter(Mandatory=$true)][string]$RuntimeSourceSha256)
# Recorded September 8 operator environment; evidence, not an installation default.
$ErrorActionPreference='Stop'
$baseline='C:\code\backups\AR-local-user-session\lan-recovery-20260908\task-terminal.xml'
if((Get-FileHash -LiteralPath $baseline).Hash.ToLowerInvariant() -cne '5faa91ad9967a10821605af50360c4d9d556aee6bf7388bc414945b86a850b6b'){throw 'Task baseline changed.'}
[xml]$before=Get-Content -LiteralPath $baseline -Raw
[xml]$current=Export-ScheduledTask -TaskName 'AR-local user-session backup'
foreach($section in @('Actions','Triggers','Principals','Settings')) {
  $a=$before.DocumentElement.SelectSingleNode("*[local-name()='$section']")
  $b=$current.DocumentElement.SelectSingleNode("*[local-name()='$section']")
  if(-not $a -or -not $b -or $a.OuterXml -cne $b.OuterXml){throw "Task $section changed."}
}
$task=Get-ScheduledTask -TaskName 'AR-local user-session backup'
$info=Get-ScheduledTaskInfo -TaskName $task.TaskName
if($task.State.ToString() -cne 'Ready' -or $info.LastTaskResult -ne 0){throw 'Task is not Ready with exit zero.'}
$source='C:\code\backups\AR-local-user-session\source-lan-fallback-20260908\source'
$python='C:\Users\jkoka\.pyenv\pyenv-win\versions\3.10.9\python.exe'
if((Get-FileHash -LiteralPath $python).Hash.ToLowerInvariant() -cne '53e910971cbb20c3223cc44c696254ccfba9595dc4be8e16f56f6c954fff831f'){throw 'Pinned Python executable changed.'}
$runtimeSource=Join-Path $PSScriptRoot '../../../laptop_recovery_runtime.py'
if((Get-FileHash -LiteralPath $runtimeSource).Hash.ToLowerInvariant() -cne $RuntimeSourceSha256){throw 'Runtime reader source changed.'}
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Runtime check requires an ordinary token.'}
if($identity.User.Value -cne 'S-1-5-21-689213601-40760280-3596424081-1001'){throw 'Operator SID changed.'}
$raw=& $python -I -S -B $runtimeSource --config (Join-Path (Split-Path $source) 'user-session-backup.json') --config-sha256 '4b7a812f01c4f3f027bcb5298f2a5aa5c53a7f9e345504fd78b80da53ea34bbf' --receiver-sha 'cbf920eceedcfd5cc19bd75d86351ddbc7b39e2e' --production-sha '2607ed681d5d3c1da66f9c3c0109cff524e02338'
if($LASTEXITCODE -ne 0){
  # Return the structured failure to the capture driver before it marks FAIL.
  Write-Output ($raw -join "`n")
  return
}
$verified=($raw -join "`n") | ConvertFrom-Json
if($verified.runtime_binding -cne 'PASS' -or -not $verified.production_clean -or -not $verified.known_hosts_unchanged){throw 'Runtime identity check failed.'}
$production=$verified.production_sha
[ordered]@{runtime_binding='PASS';checked_at_hobart=(Get-Date -Format o);
  task_last_run=$info.LastRunTime.ToString('o');task_next_run=$info.NextRunTime.ToString('o');
  task_definition_unchanged=$true;production_sha=$production;production_clean=$true;
  receiver_sha='cbf920eceedcfd5cc19bd75d86351ddbc7b39e2e';
  config_sha256='4b7a812f01c4f3f027bcb5298f2a5aa5c53a7f9e345504fd78b80da53ea34bbf';
  natural_trigger='UNVERIFIED';physical_recovery='BLOCKED';read_only=$true;
  known_hosts_unchanged=$verified.known_hosts_unchanged;exact_commands=$verified.exact_commands;receiver_code_executed=$false;runtime_source_sha256=$RuntimeSourceSha256;operator_sid=$identity.User.Value} | ConvertTo-Json -Depth 6
