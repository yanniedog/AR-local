param(
  [Parameter(Mandatory=$true)][string]$ConfigPath,
  [Parameter(Mandatory=$true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ConfigSha256,
  [ValidateSet('run','probe','check')][string]$Mode='run'
)
$ErrorActionPreference='Stop'
$principal=[Security.Principal.WindowsPrincipal]::new([Security.Principal.WindowsIdentity]::GetCurrent())
if($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){throw 'Elevation prohibited.'}
if((Get-FileHash -LiteralPath $ConfigPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ConfigSha256){throw 'User backup config drift.'}
$config=Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
if((Get-FileHash -LiteralPath $config.python_path -Algorithm SHA256).Hash.ToLowerInvariant() -cne $config.python_sha256){throw 'User backup Python drift.'}
$logs=Join-Path (Split-Path -Parent $ConfigPath) 'logs'
New-Item -ItemType Directory -Path $logs -Force | Out-Null
$log=Join-Path $logs (([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ'))+'-'+[guid]::NewGuid().ToString('N')+'.log')
$errorLog=$log+'.stderr'
$runner=Join-Path $config.receiver 'laptop_backup_user_session.py'
$arguments='-B "{0}" {1} --config "{2}" --config-sha256 {3}' -f $runner,$Mode,$ConfigPath,$ConfigSha256
$process=Start-Process -FilePath $config.python_path -ArgumentList $arguments -WindowStyle Hidden -Wait -PassThru -RedirectStandardOutput $log -RedirectStandardError $errorLog
exit $process.ExitCode
