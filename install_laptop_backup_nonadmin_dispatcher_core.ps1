function Get-ArSha256 {
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

function Write-ArUtf8NoBom {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Text
  )
  [IO.File]::WriteAllText($Path, $Text, [Text.UTF8Encoding]::new($false))
}

function New-ArLfRemoteScript {
  param([Parameter(Mandatory = $true)][string[]]$Lines)
  $text = ($Lines -join "`n") + "`n"
  if ($text.Contains("`r")) { throw 'Remote script contains a carriage return.' }
  $text
}

function Assert-ArNoReparsePath {
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

function New-ArManagedRunnerText {
  param(
    [Parameter(Mandatory = $true)][string]$TemplatePath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ConfigSha256
  )
  $token = '__AR_CONFIG_SHA256__'
  $template = [IO.File]::ReadAllText($TemplatePath)
  if (($template.Split(@($token), [StringSplitOptions]::None).Count - 1) -ne 1) {
    throw 'Managed runner template does not contain exactly one configuration token.'
  }
  $template.Replace($token, $ConfigSha256)
}

function Install-ArManagedRunnerAtomic {
  param(
    [Parameter(Mandatory = $true)][string]$RunnerPath,
    [Parameter(Mandatory = $true)][string]$RunnerText,
    [Parameter(Mandatory = $true)][string]$BackupPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedOldSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedNewSha256
  )
  if ((Get-ArSha256 $RunnerPath) -cne $ExpectedOldSha256) { throw 'Legacy runner hash changed before replacement.' }
  if (Test-Path -LiteralPath $BackupPath) { throw 'Runner rollback artifact already exists.' }
  $temporary = Join-Path (Split-Path -Parent $RunnerPath) ('.ar-runner-' + [guid]::NewGuid().ToString('N') + '.tmp')
  try {
    Write-ArUtf8NoBom -Path $temporary -Text $RunnerText
    if ((Get-ArSha256 $temporary) -cne $ExpectedNewSha256) { throw 'Generated runner hash is invalid.' }
    [IO.File]::Replace($temporary, $RunnerPath, $BackupPath, $true)
    if ((Get-ArSha256 $RunnerPath) -cne $ExpectedNewSha256 -or
        (Get-ArSha256 $BackupPath) -cne $ExpectedOldSha256) {
      throw 'Atomic runner replacement did not preserve both authenticated versions.'
    }
  } finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
  }
}

function Restore-ArManagedRunnerAtomic {
  param(
    [Parameter(Mandatory = $true)][string]$RunnerPath,
    [Parameter(Mandatory = $true)][string]$BackupPath,
    [Parameter(Mandatory = $true)][string]$FailedRunnerPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedOldSha256
  )
  if ((Get-ArSha256 $BackupPath) -cne $ExpectedOldSha256) { throw 'Runner rollback artifact is not authentic.' }
  if (Test-Path -LiteralPath $FailedRunnerPath) { throw 'Failed-runner evidence path already exists.' }
  $temporary = Join-Path (Split-Path -Parent $RunnerPath) ('.ar-runner-rollback-' + [guid]::NewGuid().ToString('N') + '.tmp')
  try {
    [IO.File]::WriteAllBytes($temporary, [IO.File]::ReadAllBytes($BackupPath))
    [IO.File]::Replace($temporary, $RunnerPath, $FailedRunnerPath, $true)
    if ((Get-ArSha256 $RunnerPath) -cne $ExpectedOldSha256) { throw 'Legacy runner rollback hash is invalid.' }
  } finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
  }
}
