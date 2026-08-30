param(
  [Parameter(Mandatory = $true)][string]$PythonPath,
  [Parameter(Mandatory = $true)][string]$ScriptPath,
  [Parameter(Mandatory = $true)][string]$Target,
  [Parameter(Mandatory = $true)][string]$RecoveryImage,
  [Parameter(Mandatory = $true)][string]$CandidateCodeSha,
  [Parameter(Mandatory = $true)][string]$ProtectedCodeSha,
  [Parameter(Mandatory = $true)][string]$PlanGitCommit,
  [Parameter(Mandatory = $true)][string]$Operator
)

$ErrorActionPreference = 'Stop'
$expectedConfigSha256 = '__AR_CONFIG_SHA256__'
$code = 1
function Get-ArManagedSha256 {
  param([Parameter(Mandatory = $true)][string]$Path)
  $stream = [IO.File]::OpenRead($Path)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try {
    ([BitConverter]::ToString($algorithm.ComputeHash($stream)) -replace '-', '').ToLowerInvariant()
  } finally {
    $algorithm.Dispose()
    $stream.Dispose()
  }
}
function Assert-ArManagedNoReparsePath {
  param([Parameter(Mandatory = $true)][string]$Path)
  $full = [IO.Path]::GetFullPath($Path)
  $current = [IO.Path]::GetPathRoot($full)
  foreach ($part in $full.Substring($current.Length).Split(@([IO.Path]::DirectorySeparatorChar), [StringSplitOptions]::RemoveEmptyEntries)) {
    $current = Join-Path $current $part
    if (Test-Path -LiteralPath $current) {
      $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Managed dispatcher path traverses a reparse point: $current"
      }
    }
  }
  $full
}
try {
  $controlRoot = Join-Path ([IO.Path]::GetFullPath($Target)) 'dispatcher-control'
  $configPath = Join-Path $controlRoot 'runner-config.json'
  if (-not (Test-Path -LiteralPath $configPath -PathType Leaf)) { throw 'Managed dispatcher configuration is absent.' }
  $configHash = Get-ArManagedSha256 $configPath
  if ($configHash -cne $expectedConfigSha256) { throw 'Managed dispatcher configuration hash mismatch.' }
  $config = Get-Content -LiteralPath $configPath -Raw -ErrorAction Stop | ConvertFrom-Json
  $expectedFields = @(
    'atomic_module_sha256', 'control_root', 'dispatcher_sha256', 'implementation_commit',
    'implementation_root', 'python_path', 'python_sha256', 'schema_version'
  )
  $actualFields = @($config.PSObject.Properties.Name | Sort-Object)
  if (@(Compare-Object $expectedFields $actualFields).Count -ne 0 -or $config.schema_version -ne 1) {
    throw 'Managed dispatcher configuration schema is invalid.'
  }
  if ([IO.Path]::GetFullPath([string]$config.control_root) -cne [IO.Path]::GetFullPath($controlRoot)) {
    throw 'Managed dispatcher control root mismatch.'
  }
  $implementationRoot = Assert-ArManagedNoReparsePath ([string]$config.implementation_root)
  $dispatcherPath = Join-Path $implementationRoot 'laptop_backup_dispatcher.py'
  $atomicPath = Join-Path $implementationRoot 'laptop_backup_atomic.py'
  Assert-ArManagedNoReparsePath $controlRoot | Out-Null
  Assert-ArManagedNoReparsePath ([string]$config.python_path) | Out-Null
  foreach ($path in @($implementationRoot, $dispatcherPath, $atomicPath, [string]$config.python_path)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Managed dispatcher dependency is absent: $path" }
  }
  $head = (git -C $implementationRoot rev-parse HEAD).Trim()
  $dirty = git -C $implementationRoot status --porcelain=v1
  git -C $implementationRoot symbolic-ref -q HEAD 2>$null | Out-Null
  $symbolicExit = $LASTEXITCODE
  if ($head -cne [string]$config.implementation_commit -or $dirty -or $symbolicExit -ne 1) {
    throw 'Managed dispatcher implementation checkout is not exact, clean and detached.'
  }
  if ((Get-ArManagedSha256 $dispatcherPath) -cne [string]$config.dispatcher_sha256 -or
      (Get-ArManagedSha256 $atomicPath) -cne [string]$config.atomic_module_sha256 -or
      (Get-ArManagedSha256 ([string]$config.python_path)) -cne [string]$config.python_sha256) {
    throw 'Managed dispatcher dependency hash mismatch.'
  }
  $mode = if ([string]::IsNullOrEmpty($env:AR_LOCAL_BACKUP_DISPATCHER_MODE)) {
    'run'
  } elseif ($env:AR_LOCAL_BACKUP_DISPATCHER_MODE -ceq 'probe') {
    'probe'
  } else {
    throw 'Managed dispatcher mode is invalid.'
  }
  & ([string]$config.python_path) $dispatcherPath $mode --control-root $controlRoot
  if ($null -eq $LASTEXITCODE) { throw 'Managed dispatcher did not return an exit code.' }
  $code = [int]$LASTEXITCODE
} catch {
  $code = 1
}
if ($code -ne 0) {
  $message = "AR-local laptop backup dispatcher failed (exit $code). Check dispatcher activation evidence."
  try { & "$env:SystemRoot\System32\msg.exe" $env:USERNAME $message 2>$null } catch { }
}
exit $code
