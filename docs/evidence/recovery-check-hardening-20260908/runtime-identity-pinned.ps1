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
$script=@'
import json, os, pathlib, subprocess, sys
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
import laptop_backup_user_session as user
expected = '4b7a812f01c4f3f027bcb5298f2a5aa5c53a7f9e345504fd78b80da53ea34bbf'
config = user.load_config(pathlib.Path(sys.argv[1]).parent / user.CONFIG_NAME, expected)
user.verify_release(config)
assert config['candidate_sha'] == 'cbf920eceedcfd5cc19bd75d86351ddbc7b39e2e'
assert config['protected_sha'] == '2607ed681d5d3c1da66f9c3c0109cff524e02338'
os.environ['AR_USER_BACKUP_CONFIG_SHA256'] = expected
from laptop_backup_transport import ssh_command
pins = user.transport_contract()
args = SimpleNamespace(**pins, host=config['lan_fallback_ipv4'],
                       ssh_identity=pins['ssh_identity_path'],
                       ssh_known_hosts=pins['ssh_known_hosts_path'])
known_hosts = pathlib.Path(pins['ssh_known_hosts_path'])
before = (user.digest(known_hosts), known_hosts.stat().st_mtime_ns)
commands = []
def remote(*command):
    argv = ssh_command(args, *command)
    commands.append(argv)
    return subprocess.run(argv, capture_output=True, text=True, check=True, timeout=30).stdout.strip()
production = remote('git', '-C', '/srv/ar-local/AR-local', 'rev-parse', 'HEAD')
dirty = remote('git', '-C', '/srv/ar-local/AR-local', 'status', '--porcelain')
assert production == config['protected_sha'] and not dirty
assert before == (user.digest(known_hosts), known_hosts.stat().st_mtime_ns)
print(json.dumps({'receiver_binding':'PASS','production_sha':production,
                  'production_clean':True,'known_hosts_unchanged':True,'ssh_argv':commands}))
'@
$raw=& $python -B -c $script $source
if($LASTEXITCODE -ne 0){throw 'Pinned receiver/SSH identity check failed.'}
$verified=($raw -join "`n") | ConvertFrom-Json
if($verified.receiver_binding -cne 'PASS' -or -not $verified.production_clean -or -not $verified.known_hosts_unchanged){throw 'Pinned runtime identity check failed.'}
$production=$verified.production_sha
[ordered]@{runtime_binding='PASS';checked_at_hobart=(Get-Date -Format o);
  task_last_run=$info.LastRunTime.ToString('o');task_next_run=$info.NextRunTime.ToString('o');
  task_definition_unchanged=$true;production_sha=$production;production_clean=$true;
  receiver_sha='cbf920eceedcfd5cc19bd75d86351ddbc7b39e2e';
  config_sha256='4b7a812f01c4f3f027bcb5298f2a5aa5c53a7f9e345504fd78b80da53ea34bbf';
  natural_trigger='UNVERIFIED';physical_recovery='BLOCKED';read_only=$true;
  known_hosts_unchanged=$verified.known_hosts_unchanged;ssh_argv=$verified.ssh_argv} | ConvertTo-Json -Depth 6
