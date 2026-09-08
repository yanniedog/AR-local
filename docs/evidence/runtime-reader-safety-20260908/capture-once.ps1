# Create-once runtime evidence capture. Hash this driver before invoking it.
param([Parameter(Mandatory=$true)][string]$OutputDirectory)
$ErrorActionPreference='Stop'
$helper=Join-Path $PSScriptRoot 'runtime-identity-isolated.ps1'
$source=Join-Path $PSScriptRoot '../../../laptop_recovery_runtime.py'
$helperHash='6fcf4d195e5b68caa969349af6b8f081605c794ad2dbfba2e435d23ddb0c9243'
$sourceHash='36e95ee5322c2485ad978bf5ca608072a4a149c535f6a08b4e953d7d4f649f67'
if((Get-FileHash -LiteralPath $helper).Hash.ToLowerInvariant() -cne $helperHash){throw 'Helper bytes changed before execution.'}
if((Get-FileHash -LiteralPath $source).Hash.ToLowerInvariant() -cne $sourceHash){throw 'Runtime source changed before execution.'}
$out=[IO.Path]::GetFullPath($OutputDirectory)
$allowed=[IO.Path]::GetFullPath($PSScriptRoot)+[IO.Path]::DirectorySeparatorChar
if(-not $out.StartsWith($allowed,[StringComparison]::OrdinalIgnoreCase)){throw 'Output is outside this evidence folder.'}
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
  source_commit='e4e0ba2c96b4598541ed5d07203a269112688ea1';
  helper_sha256=$helperHash;runtime_source_sha256=$sourceHash;
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
