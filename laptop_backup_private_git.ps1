param(
  [Parameter(Mandatory=$true)][string]$DeploymentPath,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$DeploymentSha256,
  [ValidateSet('run','probe','check')][string]$Mode='run'
)
$ErrorActionPreference='Stop'
$identity=[Security.Principal.WindowsIdentity]::GetCurrent()
$principal=[Security.Principal.WindowsPrincipal]::new($identity)
if($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Elevation prohibited.'}
function Assert-PrivateGitHash([string]$Path,[string]$Sha) {
  if($Sha -cnotmatch '^[0-9a-f]{64}$' -or
     (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $Sha){throw 'Private Git deployment file changed.'}
}
Assert-PrivateGitHash $DeploymentPath $DeploymentSha256
$deployment=Get-Content -LiteralPath $DeploymentPath -Raw | ConvertFrom-Json
if($deployment.schema -cne 'ARL-PRIVATE-GIT-V1' -or $identity.User.Value -cne $deployment.operator_sid){throw 'Private Git deployment identity changed.'}
Assert-PrivateGitHash $PSCommandPath $deployment.wrapper_sha256
Assert-PrivateGitHash $deployment.python_path $deployment.python_sha256
Assert-PrivateGitHash $deployment.verifier_path $deployment.verifier_sha256
Assert-PrivateGitHash $deployment.launcher_path $deployment.launcher_sha256
$logRoot=Join-Path (Split-Path -Parent $DeploymentPath) 'guard-executions'
New-Item -ItemType Directory -Path $logRoot -Force | Out-Null
$recordPath=Join-Path $logRoot (([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))+'-'+[guid]::NewGuid().ToString('N')+'.json')
$record=[ordered]@{started_at_utc=[DateTime]::UtcNow.ToString('o');mode=$Mode;
  deployment_sha256=$DeploymentSha256;authority=$deployment.decision_id;elevated=$false;result='FAIL'}
$previousPath=$env:PATH
$code=1
try {
  $verification=& $deployment.python_path -I -S -B $deployment.verifier_path verify `
  --old-config $deployment.old_config --old-sha256 $deployment.old_sha256 `
  --new-config $deployment.new_config --new-sha256 $deployment.new_sha256 `
  --archive $deployment.archive --package-sha256 $deployment.package_sha256 `
  --package-root $deployment.package_root --ssh-archive $deployment.ssh_archive `
  --ssh-sha256 $deployment.ssh_sha256 --ssh-root $deployment.ssh_root
if($LASTEXITCODE -ne 0){throw 'Private Git dependency verification failed.'}
$verified=($verification -join "`n") | ConvertFrom-Json
if($verified.result -cne 'PASS'){throw 'Private Git dependency verification did not pass.'}
$config=Get-Content -LiteralPath $deployment.new_config -Raw | ConvertFrom-Json
if($deployment.launcher_path -cne (Join-Path $config.receiver 'run_laptop_backup_user_session.ps1')){throw 'Launcher is outside receiver.'}
# Bind every unqualified Git subprocess in the unchanged receiver to the
# authenticated private package. Never edit machine/user PATH or Program Files.
  $record.dependency_verification=$verified
  $env:PATH=(Split-Path -Parent $config.git_path)+';'+$previousPath
  & $deployment.launcher_path -ConfigPath $deployment.new_config -ConfigSha256 $deployment.new_sha256 -Mode $Mode
  $code=$LASTEXITCODE
  if($code -eq 0){$record.result='PASS'}
} catch {
  $record.error=$_.Exception.Message
  throw
} finally {
  $env:PATH=$previousPath
  $record.exit_code=$code
  $record.completed_at_utc=[DateTime]::UtcNow.ToString('o')
  $bytes=[Text.UTF8Encoding]::new($false).GetBytes(($record | ConvertTo-Json -Depth 6))
  $stream=[IO.File]::Open($recordPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::Read)
  try {$stream.Write($bytes,0,$bytes.Length)} finally {$stream.Dispose()}
}
exit $code
