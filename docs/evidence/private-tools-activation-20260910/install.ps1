# D-023 exact ordinary-user action transition. Does not start a backup.
$ErrorActionPreference='Stop'
$root='C:\code\backups\AR-local-user-session\private-tools-20260910-v5'
$deploymentPath=Join-Path $root 'private-tools-deployment.json'
$deploymentSha='9751b0441d9eec953b19de5f148018afdd76b99effcb8c60bb8449a79e63e314'
$intent=Join-Path $root 'D-023-activation-intent.json'
if((Get-FileHash -LiteralPath $intent).Hash.ToLowerInvariant() -cne '02c3b5838e8fbfcfa63596aab7013b027469043d33fda4806710dc455dc88236'){throw 'Activation intent changed.'}
if((Get-FileHash -LiteralPath $deploymentPath).Hash.ToLowerInvariant() -cne $deploymentSha){throw 'Deployment identity changed.'}
$d=Get-Content -LiteralPath $deploymentPath -Raw | ConvertFrom-Json
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator) -or $identity.User.Value -cne $d.operator_sid){throw 'Ordinary operator identity required.'}
$new=Get-Content -LiteralPath $d.new_config -Raw | ConvertFrom-Json
$old=Get-Content -LiteralPath $d.old_config -Raw | ConvertFrom-Json
$helper=Join-Path $new.receiver 'laptop_backup_user_update.ps1'
if((Get-FileHash -LiteralPath $helper).Hash.ToLowerInvariant() -cne $d.transition_helper_sha256){throw 'Task helper changed.'}
. $helper
$execute=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$oldArguments='-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -ConfigPath "{1}" -ConfigSha256 {2}' -f (Join-Path $old.receiver 'run_laptop_backup_user_session.ps1'),$d.old_config,$d.old_sha256
$newArguments='-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -DeploymentPath "{1}" -DeploymentSha256 {2}' -f (Join-Path $new.receiver 'laptop_backup_private_git.ps1'),$deploymentPath,$deploymentSha
$verify={
  $raw=& $d.python_path -B (Join-Path $new.receiver 'laptop_backup_user_update.py') `
    --old-config $d.old_config --old-sha256 $d.old_sha256 --config $d.new_config `
    --config-sha256 $d.new_sha256 --tool-contract $d.tool_contract --tool-contract-sha256 $d.tool_contract_sha256
  if($LASTEXITCODE -ne 0){throw 'Exact predecessor/package verification failed.'}
  if((($raw -join "`n") | ConvertFrom-Json).result -cne 'PASS'){throw 'Predecessor verification did not pass.'}
  $raw
}
Invoke-UserBackupTaskUpdate -Execute $execute -OldArguments $oldArguments -NewArguments $newArguments `
  -OldReceiver $old.receiver -NewReceiver $new.receiver -EvidenceDirectory (Join-Path $root 'task-update') `
  -Verify $verify -OperatorName $identity.Name -OperatorSid $identity.User.Value
Get-Content -LiteralPath (Join-Path $root 'task-update\installation.json')
