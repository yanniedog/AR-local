param([Parameter(Mandatory = $true)][string]$ConfigPath)

$ErrorActionPreference = 'Stop'
$code = 1
function Get-ArTrustedSha256 {
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
function Assert-ArTrustedPlainPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  $full = [IO.Path]::GetFullPath($Path)
  $current = [IO.Path]::GetPathRoot($full)
  foreach ($part in $full.Substring($current.Length).Split(@([IO.Path]::DirectorySeparatorChar), [StringSplitOptions]::RemoveEmptyEntries)) {
    $current = Join-Path $current $part
    if (Test-Path -LiteralPath $current) {
      $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Trusted child path traverses a reparse point: $current"
      }
    }
  }
  $full
}
try {
  $configFull = Assert-ArTrustedPlainPath $ConfigPath
  $config = Get-Content -LiteralPath $configFull -Raw -ErrorAction Stop | ConvertFrom-Json
  $fields = @('control_root', 'dispatcher_path', 'dispatcher_sha256', 'python_path', 'python_sha256', 'schema_version')
  if ($config.schema_version -ne 1 -or
      @(Compare-Object $fields @($config.PSObject.Properties.Name | Sort-Object)).Count -ne 0) {
    throw 'Trusted child configuration schema is invalid.'
  }
  $python = Assert-ArTrustedPlainPath ([string]$config.python_path)
  $dispatcher = Assert-ArTrustedPlainPath ([string]$config.dispatcher_path)
  $control = Assert-ArTrustedPlainPath ([string]$config.control_root)
  if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
      -not (Test-Path -LiteralPath $dispatcher -PathType Leaf) -or
      -not (Test-Path -LiteralPath $control -PathType Container)) {
    throw 'Trusted child dependency is absent.'
  }
  if ((Get-ArTrustedSha256 $python) -cne [string]$config.python_sha256 -or
      (Get-ArTrustedSha256 $dispatcher) -cne [string]$config.dispatcher_sha256) {
    throw 'Trusted child dependency hash mismatch.'
  }
  & $python $dispatcher run --control-root $control
  if ($null -eq $LASTEXITCODE) { throw 'Dispatcher returned no exit code.' }
  $code = [int]$LASTEXITCODE
} catch {
  [Console]::Error.WriteLine($_.Exception.Message)
  $code = 1
}
exit $code
