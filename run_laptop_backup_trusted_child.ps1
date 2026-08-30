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
function Assert-ArTrustedWriteDenied {
  param([Parameter(Mandatory = $true)][string]$Path)
  $stream = $null
  try {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
  } catch [UnauthorizedAccessException] {
    return
  } finally {
    if ($null -ne $stream) { $stream.Dispose() }
  }
  throw "Restricted child can modify trusted executable bytes: $Path"
}
function Assert-ArTrustedWithinRoot {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Label
  )
  $prefix = $Root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
  if (-not $Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "$Label is outside the administrator-protected launcher root."
  }
}
try {
  $configFull = Assert-ArTrustedPlainPath $ConfigPath
  $config = Get-Content -LiteralPath $configFull -Raw -ErrorAction Stop | ConvertFrom-Json
  $fields = @(
    'atomic_path', 'atomic_sha256', 'control_root', 'dispatcher_path', 'dispatcher_sha256',
    'git_path', 'git_sha256', 'python_path', 'python_sha256', 'schema_version',
    'scp_path', 'scp_sha256', 'ssh_path', 'ssh_sha256', 'whoami_path', 'whoami_sha256'
  )
  if ($config.schema_version -ne 2 -or
      @(Compare-Object $fields @($config.PSObject.Properties.Name | Sort-Object)).Count -ne 0) {
    throw 'Trusted child configuration schema is invalid.'
  }
  $trustedRoot = Assert-ArTrustedPlainPath $PSScriptRoot
  $python = Assert-ArTrustedPlainPath ([string]$config.python_path)
  $dispatcher = Assert-ArTrustedPlainPath ([string]$config.dispatcher_path)
  $atomic = Assert-ArTrustedPlainPath ([string]$config.atomic_path)
  $control = Assert-ArTrustedPlainPath ([string]$config.control_root)
  Assert-ArTrustedWithinRoot $python $trustedRoot 'Python interpreter'
  Assert-ArTrustedWithinRoot $dispatcher $trustedRoot 'Dispatcher'
  Assert-ArTrustedWithinRoot $atomic $trustedRoot 'Dispatcher atomic module'
  if ($atomic -cne (Join-Path ([IO.Path]::GetDirectoryName($dispatcher)) 'laptop_backup_atomic.py')) {
    throw 'Dispatcher atomic module path is not exact.'
  }
  if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
      -not (Test-Path -LiteralPath $dispatcher -PathType Leaf) -or
      -not (Test-Path -LiteralPath $atomic -PathType Leaf) -or
      -not (Test-Path -LiteralPath $control -PathType Container)) {
    throw 'Trusted child dependency is absent.'
  }
  if ((Get-ArTrustedSha256 $python) -cne [string]$config.python_sha256 -or
      (Get-ArTrustedSha256 $dispatcher) -cne [string]$config.dispatcher_sha256 -or
      (Get-ArTrustedSha256 $atomic) -cne [string]$config.atomic_sha256) {
    throw 'Trusted child dependency hash mismatch.'
  }
  foreach ($path in @($python, $dispatcher, $atomic)) { Assert-ArTrustedWriteDenied $path }

  $system = [Environment]::GetFolderPath([Environment+SpecialFolder]::System)
  $programRoots = @(
    [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles),
    [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)
  ) | Where-Object { -not [String]::IsNullOrWhiteSpace($_) }
  $tools = @(
    @{ Name = 'git.exe'; Path = Assert-ArTrustedPlainPath ([string]$config.git_path); Hash = [string]$config.git_sha256; Root = $programRoots },
    @{ Name = 'ssh.exe'; Path = Assert-ArTrustedPlainPath ([string]$config.ssh_path); Hash = [string]$config.ssh_sha256; Root = @($system) },
    @{ Name = 'scp.exe'; Path = Assert-ArTrustedPlainPath ([string]$config.scp_path); Hash = [string]$config.scp_sha256; Root = @($system) },
    @{ Name = 'whoami.exe'; Path = Assert-ArTrustedPlainPath ([string]$config.whoami_path); Hash = [string]$config.whoami_sha256; Root = @($system) }
  )
  foreach ($tool in $tools) {
    if ([IO.Path]::GetFileName($tool.Path) -ine $tool.Name -or -not (Test-Path -LiteralPath $tool.Path -PathType Leaf)) {
      throw "Trusted system tool is absent or misnamed: $($tool.Name)"
    }
    $allowed = $false
    foreach ($root in $tool.Root) {
      $prefix = ([IO.Path]::GetFullPath($root)).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
      if ($tool.Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { $allowed = $true }
    }
    if (-not $allowed -or (Get-ArTrustedSha256 $tool.Path) -cne $tool.Hash) {
      throw "Trusted system tool path or hash is invalid: $($tool.Name)"
    }
    Assert-ArTrustedWriteDenied $tool.Path
  }
  $env:PATH = (($tools | ForEach-Object { [IO.Path]::GetDirectoryName($_.Path) } | Select-Object -Unique) -join ';')
  $env:AR_TRUSTED_ROOT = $trustedRoot
  $env:PYTHONNOUSERSITE = '1'
  $env:PYTHONDONTWRITEBYTECODE = '1'
  & $python -s -E $dispatcher run --control-root $control
  if ($null -eq $LASTEXITCODE) { throw 'Dispatcher returned no exit code.' }
  $code = [int]$LASTEXITCODE
} catch {
  [Console]::Error.WriteLine($_.Exception.Message)
  $code = 1
}
exit $code
