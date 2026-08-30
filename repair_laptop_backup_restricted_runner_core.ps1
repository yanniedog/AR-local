function Install-ArManagedFileAtomic {
  param(
    [Parameter(Mandatory = $true)][string]$DestinationPath,
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$BackupPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedOldSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedNewSha256
  )
  if ((Get-ArSha256 $DestinationPath) -cne $ExpectedOldSha256 -or
      (Get-ArSha256 $SourcePath) -cne $ExpectedNewSha256) {
    throw 'Managed atomic replacement input hash mismatch.'
  }
  if (Test-Path -LiteralPath $BackupPath) { throw 'Managed rollback artifact already exists.' }
  $temporary = Join-Path (Split-Path -Parent $DestinationPath) ('.ar-managed-' + [guid]::NewGuid().ToString('N') + '.tmp')
  try {
    [IO.File]::WriteAllBytes($temporary, [IO.File]::ReadAllBytes($SourcePath))
    if ((Get-ArSha256 $temporary) -cne $ExpectedNewSha256) { throw 'Managed temporary file hash mismatch.' }
    [IO.File]::Replace($temporary, $DestinationPath, $BackupPath, $true)
    if ((Get-ArSha256 $DestinationPath) -cne $ExpectedNewSha256 -or
        (Get-ArSha256 $BackupPath) -cne $ExpectedOldSha256) {
      throw 'Managed atomic replacement verification failed.'
    }
  } finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
  }
}

function Restore-ArManagedFileAtomic {
  param(
    [Parameter(Mandatory = $true)][string]$DestinationPath,
    [Parameter(Mandatory = $true)][string]$BackupPath,
    [Parameter(Mandatory = $true)][string]$FailedPath,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedOldSha256,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedFailedSha256
  )
  if ((Get-ArSha256 $BackupPath) -cne $ExpectedOldSha256 -or
      (Get-ArSha256 $DestinationPath) -cne $ExpectedFailedSha256) {
    throw 'Managed rollback input hash mismatch.'
  }
  if (Test-Path -LiteralPath $FailedPath) { throw 'Managed failed-version evidence already exists.' }
  $temporary = Join-Path (Split-Path -Parent $DestinationPath) ('.ar-rollback-' + [guid]::NewGuid().ToString('N') + '.tmp')
  try {
    [IO.File]::WriteAllBytes($temporary, [IO.File]::ReadAllBytes($BackupPath))
    [IO.File]::Replace($temporary, $DestinationPath, $FailedPath, $true)
    if ((Get-ArSha256 $DestinationPath) -cne $ExpectedOldSha256 -or
        (Get-ArSha256 $FailedPath) -cne $ExpectedFailedSha256) {
      throw 'Managed rollback verification failed.'
    }
  } finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
  }
}
