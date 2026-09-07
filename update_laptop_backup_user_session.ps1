param(
  [Parameter(Mandatory=$true)][string]$OldConfigPath,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$OldConfigSha256,
  [Parameter(Mandatory=$true)][string]$ConfigPath,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ConfigSha256,
  [Parameter(Mandatory=$true)][string]$EvidenceDirectory
)
$ErrorActionPreference='Stop'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Elevation prohibited.'}
if(Test-Path -LiteralPath $EvidenceDirectory){throw 'Update evidence directory must be new.'}
foreach($entry in @(@($OldConfigPath,$OldConfigSha256),@($ConfigPath,$ConfigSha256))) {
  if((Get-FileHash -LiteralPath $entry[0] -Algorithm SHA256).Hash.ToLowerInvariant() -cne $entry[1]){throw 'Config digest changed.'}
}
$old=Get-Content -LiteralPath $OldConfigPath -Raw | ConvertFrom-Json
$config=Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if($config.operator_sid -cne $identity.User.Value){throw 'Config operator changed.'}
if((Get-FileHash -LiteralPath $config.python_path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $config.python_sha256){throw 'Python digest changed.'}
$verify={
  & $config.python_path -B (Join-Path $PSScriptRoot 'laptop_backup_user_update.py') --old-config $OldConfigPath --old-sha256 $OldConfigSha256 --config $ConfigPath --config-sha256 $ConfigSha256
  if($LASTEXITCODE -ne 0){throw 'Read-only receiver ancestry verification failed.'}
}
# Validate before sourcing helper code or reading Task Scheduler.
& $verify | Out-Null
. (Join-Path $PSScriptRoot 'laptop_backup_user_update.ps1')
$template='-NoProfile -NonInteractive -WindowStyle Hidden -File "{0}" -ConfigPath "{1}" -ConfigSha256 {2}'
$oldArguments=$template -f (Join-Path $old.receiver 'run_laptop_backup_user_session.ps1'),$OldConfigPath,$OldConfigSha256
$newArguments=$template -f (Join-Path $config.receiver 'run_laptop_backup_user_session.ps1'),$ConfigPath,$ConfigSha256
$powershell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
Invoke-UserBackupTaskUpdate -Execute $powershell -OldArguments $oldArguments -NewArguments $newArguments -OldReceiver $old.receiver -NewReceiver $config.receiver -EvidenceDirectory $EvidenceDirectory -Verify $verify -OperatorName $identity.Name -OperatorSid $identity.User.Value
Get-Content -LiteralPath (Join-Path $EvidenceDirectory 'installation.json') -Raw
