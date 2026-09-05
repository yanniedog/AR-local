param(
  [Parameter(Mandatory=$true)][string]$ConfigPath,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ConfigSha256,
  [string]$TaskName = 'AR-local user-session backup'
)
$ErrorActionPreference='Stop'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
  throw 'Run this installer as the ordinary user; elevation is prohibited.'
}
if($TaskName -cne 'AR-local user-session backup'){throw 'Task name is not the user-session backup task.'}
if((Get-FileHash -LiteralPath $ConfigPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ConfigSha256){throw 'Config hash changed.'}
$config=Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if($config.schema -cne 'ARL-USER-SESSION-BACKUP-V1' -or $config.operator_sid -cne $identity.User.Value){throw 'Config identity mismatch.'}
$runner=Join-Path $config.receiver 'laptop_backup_user_session.py'
& $config.python_path -B $runner probe --config $ConfigPath --config-sha256 $ConfigSha256
if($LASTEXITCODE -ne 0){throw 'Ordinary-user release probe failed.'}
$existing=Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if($existing){throw 'User task already exists; inspect its definition before an explicit update.'}
$launcher=Join-Path $config.receiver 'run_laptop_backup_user_session.ps1'
$powershell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$arguments='-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -ConfigPath "{1}" -ConfigSha256 {2}' -f $launcher,$ConfigPath,$ConfigSha256
$action=New-ScheduledTaskAction -Execute $powershell -Argument $arguments -WorkingDirectory $config.receiver
$daily=New-ScheduledTaskTrigger -Daily -At '06:00'
$logon=New-ScheduledTaskTrigger -AtLogOn -User $identity.Name
$logon.Delay='PT10M'
$limited=New-ScheduledTaskPrincipal -UserId $identity.Name -LogonType Interactive -RunLevel Limited
$settings=New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 6) -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -Hidden
$task=New-ScheduledTask -Action $action -Trigger @($daily,$logon) -Principal $limited -Settings $settings -Description 'Ordinary-user AR-local backup. Runs only in the signed-in session; no elevation, stored password or legacy catalog writes.'
Register-ScheduledTask -TaskName $TaskName -InputObject $task -ErrorAction Stop | Out-Null
$actual=Get-ScheduledTask -TaskName $TaskName
if($actual.Principal.LogonType.ToString() -cne 'Interactive' -or $actual.Principal.RunLevel.ToString() -cne 'Limited' -or $actual.Actions.Execute -cne $powershell -or $actual.Actions.Arguments -cne $arguments){
  Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
  throw 'User-session task readback mismatch; new task removed.'
}
[ordered]@{task=$TaskName;state=$actual.State.ToString();logon_type=$actual.Principal.LogonType.ToString();run_level=$actual.Principal.RunLevel.ToString();daily='06:00';logon_delay='PT10M';requires_uac=$false;requires_signed_in_session=$true} | ConvertTo-Json
