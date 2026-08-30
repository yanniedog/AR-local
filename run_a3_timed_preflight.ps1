param(
  [Parameter(Mandatory=$true)][ValidateSet('0025','0055')][string]$Phase,
  [Parameter(Mandatory=$true)][string]$EvidenceRoot,
  [Parameter(Mandatory=$true)][string]$ScriptSha256,
  [Parameter(Mandatory=$true)][string]$PlanDocumentId,
  [Parameter(Mandatory=$true)][string]$PlanVersion,
  [Parameter(Mandatory=$true)][string]$PlanGitCommit,
  [Parameter(Mandatory=$true)][string]$PlanSha256,
  [Parameter(Mandatory=$true)][string]$PlanNormalizedSha256,
  [Parameter(Mandatory=$true)][string]$AuthorityCommit,
  [Parameter(Mandatory=$true)][string]$AuthorityHandoffSha256,
  [Parameter(Mandatory=$true)][string]$CandidateCodeSha,
  [Parameter(Mandatory=$true)][string]$ProtectedCodeSha,
  [Parameter(Mandatory=$true)][string]$Operator
)

$ErrorActionPreference='Stop'
Import-Module Microsoft.PowerShell.Utility -ErrorAction Stop

function Assert-NoReparsePath([string]$Path,[bool]$AllowMissingLeaf=$false) {
  $full=[IO.Path]::GetFullPath($Path)
  $volume=[IO.Path]::GetPathRoot($full)
  $current=$volume
  $parts=$full.Substring($volume.Length) -split '[\\/]'
  for($index=0;$index -lt $parts.Count;$index++) {
    if([string]::IsNullOrEmpty($parts[$index])) { continue }
    $current=Join-Path $current $parts[$index]
    if(Test-Path -LiteralPath $current) {
      $item=Get-Item -LiteralPath $current -Force -ErrorAction Stop
      if(($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Controlled path traverses a reparse point: $current"
      }
    } elseif(-not($AllowMissingLeaf -and $index -eq ($parts.Count-1))) {
      throw "Controlled path component is missing: $current"
    }
  }
  return $full
}

function Write-NewBytes([string]$Path,[byte[]]$Bytes) {
  [void](Assert-NoReparsePath $Path $true)
  $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {$stream.Write($Bytes,0,$Bytes.Length);$stream.Flush($true)} finally {$stream.Dispose()}
}

function Write-NewText([string]$Path,[string]$Text) {
  Write-NewBytes $Path ([Text.UTF8Encoding]::new($false).GetBytes($Text))
}

function File-Evidence([string]$Root,[string]$Path) {
  $resolved=Assert-NoReparsePath $Path $false
  if(-not $resolved.StartsWith($Root+[IO.Path]::DirectorySeparatorChar,[StringComparison]::OrdinalIgnoreCase)) {
    throw "Evidence path escaped root: $Path"
  }
  $item=Get-Item -LiteralPath $resolved -ErrorAction Stop
  [ordered]@{
    path=$resolved.Substring($Root.Length+1).Replace([IO.Path]::DirectorySeparatorChar,[char]'/')
    bytes=[int64]$item.Length
    sha256=(Get-FileHash -LiteralPath $resolved -Algorithm SHA256).Hash.ToLowerInvariant()
  }
}

foreach($sha in @($ScriptSha256,$PlanSha256,$PlanNormalizedSha256,$AuthorityHandoffSha256)) {
  if($sha -cnotmatch '^[0-9a-f]{64}$') { throw 'Controlled SHA-256 identity is invalid.' }
}
foreach($commit in @($PlanGitCommit,$AuthorityCommit,$CandidateCodeSha,$ProtectedCodeSha)) {
  if($commit -cnotmatch '^[0-9a-f]{40}$') { throw 'Controlled Git commit identity is invalid.' }
}
if($PlanDocumentId -cne 'ARL-OPS-001' -or [string]::IsNullOrWhiteSpace($PlanVersion) -or
   [string]::IsNullOrWhiteSpace($Operator)) {
  throw 'Controlled execution identity is incomplete.'
}

$root=Assert-NoReparsePath $EvidenceRoot $false
if(-not(Test-Path -LiteralPath $root -PathType Container)) { throw 'Evidence root is missing.' }
$scriptPath=Join-Path $root 'timed-preflight.ps1'
if((Assert-NoReparsePath $scriptPath $false) -cne [IO.Path]::GetFullPath($scriptPath)) { throw 'Timed preflight path resolution failed.' }
if((Get-FileHash -LiteralPath $scriptPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $ScriptSha256) {
  throw 'Timed preflight source is unauthenticated.'
}
$wrapperSource=Assert-NoReparsePath $PSCommandPath $false
$wrapperCopy=Join-Path $root 'run_a3_timed_preflight.ps1'
$wrapperDigest=(Get-FileHash -LiteralPath $wrapperSource -Algorithm SHA256).Hash.ToLowerInvariant()
if(Test-Path -LiteralPath $wrapperCopy) {
  [void](Assert-NoReparsePath $wrapperCopy $false)
  if((Get-FileHash -LiteralPath $wrapperCopy -Algorithm SHA256).Hash.ToLowerInvariant() -cne $wrapperDigest) {
    throw 'Immutable preflight wrapper evidence changed.'
  }
} else {
  Write-NewBytes $wrapperCopy ([IO.File]::ReadAllBytes($wrapperSource))
}
$stdoutPath=Join-Path $root "$Phase-stdout.txt"
$stderrPath=Join-Path $root "$Phase-stderr.txt"
$recordPath=Join-Path $root "$Phase-execution.json"
foreach($path in @($stdoutPath,$stderrPath,$recordPath)) {
  if(Test-Path -LiteralPath $path) { throw "Controlled phase output already exists: $path" }
}
$effectiveCommand=('"{0}" -Phase "{1}" -EvidenceRoot "{2}" -ScriptSha256 "{3}" -PlanDocumentId "{4}" -PlanVersion "{5}" -PlanGitCommit "{6}" -PlanSha256 "{7}" -PlanNormalizedSha256 "{8}" -AuthorityCommit "{9}" -AuthorityHandoffSha256 "{10}" -CandidateCodeSha "{11}" -ProtectedCodeSha "{12}" -Operator "{13}"' -f $PSCommandPath,$Phase,$root,$ScriptSha256,$PlanDocumentId,$PlanVersion,$PlanGitCommit,$PlanSha256,$PlanNormalizedSha256,$AuthorityCommit,$AuthorityHandoffSha256,$CandidateCodeSha,$ProtectedCodeSha,$Operator)

$started=[DateTimeOffset]::Now.ToString('o')
$result='FAIL';$errorText=$null;$stdout='';$stderr=''
try {
  $engine=[PowerShell]::Create()
  try {
    [void]$engine.AddCommand('Import-Module').AddParameter('Name',[string[]]@('Microsoft.PowerShell.Utility','ScheduledTasks','CimCmdlets')).AddParameter('ErrorAction','Stop')
    [void]$engine.Invoke()
    if($engine.HadErrors) { throw 'Required PowerShell modules could not be loaded in the controlled runspace.' }
    $engine.Commands.Clear();$engine.Streams.Error.Clear()
    [void]$engine.AddCommand($scriptPath).AddParameter('Phase',$Phase).AddParameter('EvidenceRoot',$root)
    $output=$engine.Invoke()
    $stdout=($output|ForEach-Object{$_|Out-String -Width 4096}) -join ''
    $stderr=($engine.Streams.Error|ForEach-Object{$_|Out-String -Width 4096}) -join ''
    if($engine.HadErrors) { throw 'Timed preflight returned one or more PowerShell errors.' }
  } finally {
    if($engine) {$engine.Dispose()}
  }
  $manifestPath=Join-Path $root "$Phase-hashes.json"
  $manifest=Get-Content -LiteralPath $manifestPath -Raw -ErrorAction Stop|ConvertFrom-Json
  if($manifest.result -cne 'PASS' -or $manifest.script_sha256 -cne $ScriptSha256) {
    throw 'Timed preflight manifest did not record authenticated PASS.'
  }
  $result='PASS'
} catch {
  $errorText=$_.Exception.Message
  if([string]::IsNullOrWhiteSpace($stderr)) {$stderr=($_|Out-String -Width 4096)}
} finally {
  Write-NewText $stdoutPath $stdout
  Write-NewText $stderrPath $stderr
  $paths=@($stdoutPath,$stderrPath)
  foreach($name in @("$Phase-local.json","$Phase-pi.txt","$Phase-values.json","$Phase-hashes.json")) {
    $candidate=Join-Path $root $name
    if(Test-Path -LiteralPath $candidate -PathType Leaf) {$paths+=$candidate}
  }
  $evidence=@($paths|ForEach-Object{File-Evidence $root $_})
  $record=[ordered]@{
    schema_version=1
    plan_document_id=$PlanDocumentId
    plan_version=$PlanVersion
    plan_git_commit=$PlanGitCommit
    plan_sha256=$PlanSha256
    plan_normalized_sha256=$PlanNormalizedSha256
    authority_commit=$AuthorityCommit
    authority_handoff_sha256=$AuthorityHandoffSha256
    candidate_code_sha=$CandidateCodeSha
    protected_code_sha=$ProtectedCodeSha
    operator=$Operator
    phase=$Phase
    wrapper_sha256=$wrapperDigest
    preflight_script_sha256=$ScriptSha256
    timestamps=[ordered]@{started_at=$started;completed_at=[DateTimeOffset]::Now.ToString('o')}
    exact_commands=@($effectiveCommand)
    evidence=$evidence
    result=$result
    error=$errorText
    deviations=@()
    deviation_authorization=$null
  }
  Write-NewText $recordPath (($record|ConvertTo-Json -Depth 10 -Compress)+"`n")
}
if($result -cne 'PASS') { throw "Timed preflight failed; immutable evidence: $recordPath" }
Get-Content -LiteralPath $recordPath -Raw
