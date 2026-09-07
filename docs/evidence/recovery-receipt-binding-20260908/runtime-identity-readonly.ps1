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
$script=@'
import pathlib, sys
sys.path.insert(0, sys.argv[1])
import laptop_backup_user_session as user
config = user.load_config(pathlib.Path(sys.argv[1]).parent / user.CONFIG_NAME,
                         '4b7a812f01c4f3f027bcb5298f2a5aa5c53a7f9e345504fd78b80da53ea34bbf')
user.verify_release(config)
assert config['candidate_sha'] == 'cbf920eceedcfd5cc19bd75d86351ddbc7b39e2e'
assert config['protected_sha'] == '2607ed681d5d3c1da66f9c3c0109cff524e02338'
print('receiver_binding=PASS')
'@
$receiver=& $python -B -c $script $source
if($LASTEXITCODE -ne 0 -or $receiver -cne 'receiver_binding=PASS'){throw 'Receiver identity check failed.'}
$production=& ssh -o BatchMode=yes -o ConnectTimeout=15 ar-local-pi5-lan 'git -C /srv/ar-local/AR-local rev-parse HEAD'
if($LASTEXITCODE -ne 0 -or $production -cne '2607ed681d5d3c1da66f9c3c0109cff524e02338'){throw 'Production identity changed.'}
$dirty=& ssh -o BatchMode=yes -o ConnectTimeout=15 ar-local-pi5-lan 'git -C /srv/ar-local/AR-local status --porcelain'
if($LASTEXITCODE -ne 0 -or $dirty){throw 'Production cleanliness check failed.'}
[ordered]@{runtime_binding='PASS';checked_at_hobart=(Get-Date -Format o);
  task_last_run=$info.LastRunTime.ToString('o');task_next_run=$info.NextRunTime.ToString('o');
  task_definition_unchanged=$true;production_sha=$production;production_clean=$true;
  receiver_sha='cbf920eceedcfd5cc19bd75d86351ddbc7b39e2e';
  config_sha256='4b7a812f01c4f3f027bcb5298f2a5aa5c53a7f9e345504fd78b80da53ea34bbf';
  natural_trigger='UNVERIFIED';physical_recovery='BLOCKED';read_only=$true} | ConvertTo-Json
