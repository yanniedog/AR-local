# Create-once runtime evidence capture. Hash this driver before invoking it.
param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
$helper=Join-Path $PSScriptRoot 'runtime-identity-current.ps1'
$source=Join-Path $PSScriptRoot '../../../laptop_recovery_runtime.py'
$helperHash='c44439d95fb8bf1358b44994e93a08473a85b53a3b0e8eab05192aad9c9b8726'
$sourceHash='2c8b264af5f6f0dc52026f7d5e03e8c2aec8ec63f30f57f848c8f59e8841c1a7'
if((Get-FileHash -LiteralPath $helper).Hash.ToLowerInvariant() -cne $helperHash){throw 'Helper bytes changed before execution.'}
if((Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant() -cne $sourceHash){throw 'Runtime source changed before execution.'}
$guard=Join-Path $PSScriptRoot 'capture-paths.ps1'
$guardHash='288145e7ae3b957506c647592760d898dca7770d142fa7b9b74478328cf57955'
if((Get-FileHash -LiteralPath $guard).Hash.ToLowerInvariant() -cne $guardHash){throw 'Capture path guard changed.'}
. $guard
$out=[IO.Path]::GetFullPath($OutputDirectory)
$allowed=[IO.Path]::GetFullPath($PSScriptRoot)+[IO.Path]::DirectorySeparatorChar
if(-not $out.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)){throw 'Output is outside this evidence folder.'}
AssertEvidenceParents $out
if(Test-Path -LiteralPath $out){throw 'Refusing to replace existing execution evidence.'}
$null=New-Item -ItemType Directory -Path $out -ErrorAction Stop
$started=Get-Date -Format o
$result='FAIL'
$errorText=$null
$rows=@()
try {
  $rows=@(& $helper -RuntimeSourceSha256 $sourceHash)
  $text=($rows -join "`n")+"`n"
  $parsed=$text | ConvertFrom-Json
  if($parsed.runtime_binding -cne 'PASS'){throw 'Runtime helper did not pass.'}
  if((Get-FileHash -LiteralPath $helper).Hash.ToLowerInvariant() -cne $helperHash){throw 'Helper changed during execution.'}
  if((Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant() -cne $sourceHash){throw 'Runtime source changed during execution.'}
  $result='PASS'
} catch {
  $errorText=$_.Exception.Message
  $text=($rows -join "`n")+"`n"
}
$utf8=[Text.UTF8Encoding]::new($false)
function WriteNewBytes([string]$Path,[byte[]]$Bytes) {
  $stream=[IO.File]::Open($Path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {$stream.Write($Bytes,0,$Bytes.Length);$stream.Flush($true)} finally {$stream.Dispose()}
}
$stdout=Join-Path $out 'stdout.json'
WriteNewBytes $stdout ($utf8.GetBytes($text))
$record=[ordered]@{
  result=$result;started_at=$started;completed_at=(Get-Date -Format o);error=$errorText;
  source_commit='cc4219308532081bdc8bea8aeedbf01121f0dca3';
  helper_sha256=$helperHash;runtime_source_sha256=$sourceHash;capture_path_guard_sha256=$guardHash;
  driver_sha256=(Get-FileHash -LiteralPath $PSCommandPath).Hash.ToLowerInvariant();
  driver_path=$PSCommandPath;output_directory=$out;
  exact_helper_command=('& '+$helper+' -RuntimeSourceSha256 '+$sourceHash);
  capture_encoding='PowerShell output objects joined with LF plus final LF, encoded UTF-8 without BOM';
  stdout_sha256=(Get-FileHash -LiteralPath $stdout).Hash.ToLowerInvariant();
  physical_recovery='BLOCKED';natural_trigger='UNVERIFIED'
}
WriteNewBytes (Join-Path $out 'capture.json') ($utf8.GetBytes(($record|ConvertTo-Json -Depth 5)+"`n"))
$record|ConvertTo-Json -Depth 5
if($result -cne 'PASS'){throw 'Runtime check failed; original failure evidence retained.'}
