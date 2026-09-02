function Write-ArTrustedResult {
  param([string]$Result, [string]$ErrorText, [hashtable]$Detail)
  $path = Join-Path $script:executionRoot 'bootstrap-result.json'
  $files = @()
  foreach ($file in @(Get-ChildItem -LiteralPath $script:executionRoot -File -Recurse | Where-Object {
    [IO.Path]::GetFullPath($_.FullName) -cne [IO.Path]::GetFullPath($path)
  } | Sort-Object FullName)) {
    $files += [ordered]@{ path = $file.FullName; sha256 = Get-ArTrustedSha256 $file.FullName; size = $file.Length }
  }
  $record = [ordered]@{
    schema_version = 1; plan_document_id = 'ARL-OPS-001'; plan_version = '1.5'; plan_git_commit = $PlanGitCommit
    plan_sha256 = $PlanSha256; plan_raw_sha256 = $PlanRawSha256; authority_commit = $AuthorityCommit; handoff_sha256 = $HandoffSha256
    candidate_code_sha = $CandidateCodeSha; protected_code_sha = $ProtectedCodeSha
    operator = $Operator; operator_sid = $OperatorSid; package_sha256 = $PackageSha256; task_name = $TaskName
    pre_execution_manifest_sha256 = $PreExecutionManifestSha256
    started_at = $script:startedAt; completed_at = [DateTimeOffset]::UtcNow.ToString('o')
    exact_commands = @($script:exactCommand); result = $Result; error = $ErrorText; evidence = $Detail
    evidence_files = $files
    deviations = @($script:authorizedDeviations)
    deviation_authorization = $script:deviationAuthorization
  }
  $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($record | ConvertTo-Json -Depth 10 -Compress) + "`n")
  $stream = [IO.File]::Open($path,[IO.FileMode]::Create,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {
    $stream.Write($bytes,0,$bytes.Length)
    $stream.Flush($true)
  } finally {
    $stream.Dispose()
  }
  $path
}

function Read-ArTrustedPreExecutionManifest {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256
  )
  $stream = [IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try {
    $actual = ([BitConverter]::ToString($algorithm.ComputeHash($stream)) -replace '-','').ToLowerInvariant()
    if ($actual -cne $ExpectedSha256) { throw 'Pre-execution manifest hash mismatch.' }
    $stream.Position = 0
    $reader = New-Object IO.StreamReader($stream,[Text.UTF8Encoding]::new($false),$true,4096,$true)
    try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
  } finally { $algorithm.Dispose(); $stream.Dispose() }
  $value = $text | ConvertFrom-Json
  if ($null -eq $value -or $value -is [Array]) { throw 'Pre-execution manifest is not one object.' }
  $value
}

function Assert-ArTrustedPreExecutionManifest {
  param(
    [Parameter(Mandatory = $true)]$Manifest,
    [Parameter(Mandatory = $true)][Collections.Specialized.OrderedDictionary]$Expected,
    [string[]]$RequiredEvidencePaths = @(),
    [switch]$RequireFresh
  )
  $required = @($Expected.Keys | ForEach-Object { [string]$_ }) + @(
    'created_at','expires_at','exact_commands','command_self_hash_placeholder',
    'evidence_files','result','deviations'
  )
  $actual = @($Manifest.PSObject.Properties.Name)
  if ((Compare-Object ($required | Sort-Object) ($actual | Sort-Object))) { throw 'Pre-execution manifest fields are not exact.' }
  foreach ($key in $Expected.Keys) {
    $value = $Manifest.$key
    if ($Expected[$key] -is [int] -or $Expected[$key] -is [long]) {
      if ($null -eq $value -or ($value -isnot [int] -and $value -isnot [long]) -or [long]$value -ne [long]$Expected[$key]) {
        throw "Pre-execution manifest identity or type differs: $key"
      }
    } elseif ($value -isnot [string] -or $value -cne [string]$Expected[$key]) {
      throw "Pre-execution manifest identity or type differs: $key"
    }
  }
  if ($Manifest.result -cne 'PASS' -or @($Manifest.deviations).Count -ne 0) {
    throw 'Pre-execution manifest result or deviations are invalid.'
  }
  if ($Manifest.command_self_hash_placeholder -cne '<SELF_SHA256>' -or
      @($Manifest.exact_commands).Count -ne 2 -or
      $Manifest.exact_commands[0] -cne 'MARKED_ARL_D012_PREPARE_AND_PREFLIGHT_PS1_C20260902T160000') {
    throw 'Pre-execution manifest command evidence is invalid.'
  }
  $template = [string]$Manifest.exact_commands[1]
  if ([regex]::Matches($template,[regex]::Escape('<SELF_SHA256>')).Count -ne 1) {
    throw 'Pre-execution installer command template has an invalid self-hash boundary.'
  }
  $seenEvidence = @{}
  foreach ($record in @($Manifest.evidence_files)) {
    $fields = @($record.PSObject.Properties.Name)
    if ((Compare-Object @('bytes','path','sha256') ($fields | Sort-Object)) -or
        $record.path -isnot [string] -or $record.sha256 -isnot [string] -or
        ($record.bytes -isnot [int] -and $record.bytes -isnot [long])) {
      throw 'Pre-execution evidence record is malformed.'
    }
    $path = [IO.Path]::GetFullPath([string]$record.path)
    if ($seenEvidence.ContainsKey($path)) { throw 'Pre-execution evidence path is duplicated.' }
    $seenEvidence[$path] = $true
    Assert-ArTrustedPlainPath $path | Out-Null
    $item = Get-Item -LiteralPath $path -Force -ErrorAction Stop
    if ($item.PSIsContainer -or [long]$item.Length -ne [long]$record.bytes -or
        (Get-ArTrustedSha256 $path) -cne [string]$record.sha256) {
      throw "Pre-execution evidence differs: $path"
    }
  }
  foreach ($requiredPath in $RequiredEvidencePaths) {
    $full = [IO.Path]::GetFullPath($requiredPath)
    if (-not $seenEvidence.ContainsKey($full)) { throw "Required pre-execution evidence is absent: $full" }
  }
  try {
    $created = [DateTimeOffset]::ParseExact([string]$Manifest.created_at,'o',[Globalization.CultureInfo]::InvariantCulture)
    $expires = [DateTimeOffset]::ParseExact([string]$Manifest.expires_at,'o',[Globalization.CultureInfo]::InvariantCulture)
  } catch { throw 'Pre-execution manifest timestamps are invalid.' }
  $now = [DateTimeOffset]::UtcNow
  if ($created.Offset -ne [TimeSpan]::Zero -or $expires.Offset -ne [TimeSpan]::Zero -or $expires -le $created) {
    throw 'Pre-execution manifest timestamps are structurally invalid.'
  }
  if ($RequireFresh -and ($created -gt $now.AddMinutes(5) -or $now -ge $expires)) {
    throw 'Pre-execution manifest is expired or outside allowed clock skew.'
  }
}

function Assert-ArTrustedInstallerCommandEvidence {
  param(
    [Parameter(Mandatory = $true)]$Manifest,
    [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ManifestSha256,
    [Parameter(Mandatory = $true)][string]$ActualProcessCommand
  )
  $template = [string]$Manifest.exact_commands[1]
  if ([regex]::Matches($template,[regex]::Escape('<SELF_SHA256>')).Count -ne 1) {
    throw 'Pre-execution installer command template has an invalid self-hash boundary.'
  }
  $expectedEncoded = [Convert]::ToBase64String(
    [Text.Encoding]::Unicode.GetBytes($template.Replace('<SELF_SHA256>',$ManifestSha256))
  )
  $hostPath = [IO.Path]::GetFullPath((Join-Path $PSHOME 'powershell.exe'))
  $escapedHost = [regex]::Escape($hostPath)
  $pattern = ('^\s*(?:"' + $escapedHost + '"|' + $escapedHost + ')' +
    '\s+-NoProfile\s+-NonInteractive\s+-ExecutionPolicy\s+Bypass' +
    '\s+-EncodedCommand\s+([A-Za-z0-9+/]+={0,2})\s*$')
  $match = [regex]::Match($ActualProcessCommand,$pattern,[Text.RegularExpressions.RegexOptions]::IgnoreCase)
  if (-not $match.Success -or $match.Groups[1].Value -cne $expectedEncoded) {
    throw 'Elevated process does not match the authenticated installer command.'
  }
}

function Assert-ArTrustedAuthorityMain {
  param(
    [Parameter(Mandatory = $true)][string]$GitPath,
    [Parameter(Mandatory = $true)][string]$Phase
  )
  $output = @(& $GitPath -c credential.interactive=never -c http.lowSpeedLimit=1 -c http.lowSpeedTime=20 `
    ls-remote 'https://github.com/yanniedog/AR-local.git' refs/heads/main 2>&1)
  $text = ($output | Out-String).Trim()
  if ($LASTEXITCODE -ne 0) { throw "Canonical main lookup failed during ${Phase}: $text" }
  $fields = @($text -split '\s+')
  if ($fields.Count -ne 2 -or $fields[0] -cne $AuthorityCommit -or $fields[1] -cne 'refs/heads/main') {
    throw "Canonical main advanced during $Phase."
  }
  [ordered]@{ phase=$Phase; authority_commit=$fields[0]; reference=$fields[1] }
}
