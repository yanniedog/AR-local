$ErrorActionPreference = 'Stop'
. (Join-Path (Join-Path $PSScriptRoot '..') 'install_laptop_backup_trusted_dispatcher_core.ps1')

$script:task = [pscustomobject]@{
  Actions = @([pscustomobject]@{ Execute='C:\Program Files\AR-local\trusted\launcher.exe'; Arguments=$null; WorkingDirectory='C:\Program Files\AR-local\trusted' })
  Principal = [pscustomobject]@{ UserId='operator'; LogonType='S4U'; RunLevel='Limited' }
  Settings = [pscustomobject]@{ Enabled=$true; MultipleInstances='IgnoreNew'; RestartCount=3; RestartInterval='PT30M'; ExecutionTimeLimit='PT6H'; StartWhenAvailable=$true }
  Triggers = @(
    [pscustomobject]@{ CimClass=[pscustomobject]@{ CimClassName='MSFT_TaskDailyTrigger' }; StartBoundary='2026-08-31T05:00:00+10:00' },
    [pscustomobject]@{ CimClass=[pscustomobject]@{ CimClassName='MSFT_TaskBootTrigger' }; Delay='PT5M' }
  )
}
function Get-ScheduledTask { param([string]$TaskName) $script:task }
$resolve = { param($UserId) 'S-1-test' }
Assert-ArTrustedTask -TaskName test -LauncherPath 'C:\Program Files\AR-local\trusted\launcher.exe' `
  -InstallRoot 'C:\Program Files\AR-local\trusted' -OperatorSid 'S-1-test' -Enabled $true -ResolvePrincipalSid $resolve | Out-Null
$script:task.Actions[0].Execute = 'powershell.exe'
$failed = $false
try {
  Assert-ArTrustedTask -TaskName test -LauncherPath 'C:\Program Files\AR-local\trusted\launcher.exe' `
    -InstallRoot 'C:\Program Files\AR-local\trusted' -OperatorSid 'S-1-test' -Enabled $true -ResolvePrincipalSid $resolve | Out-Null
} catch { if ($_.Exception.Message -notmatch 'action') { throw }; $failed = $true }
if (-not $failed) { throw 'PowerShell production action was accepted.' }

$remote = "set -eu`nexit 0`n"
if ($remote.Contains("`r")) { throw 'Test remote script unexpectedly contains CR.' }
$core = Get-Content -LiteralPath (Join-Path (Join-Path $PSScriptRoot '..') 'install_laptop_backup_trusted_dispatcher_core.ps1') -Raw
if ($core -notmatch "HostName\.Length -gt 253" -or $core -notmatch "HostName\.Contains\('\.\.'\)") {
  throw 'Strict SSH hostname validation is absent.'
}
$explicitSddl = 'D:P(A;;FR;;;SY)'
$inheritedSddl = 'D:P(A;ID;FR;;;SY)'
if ((Get-ArTrustedSddlSemanticSha256 $explicitSddl) -ceq (Get-ArTrustedSddlSemanticSha256 $inheritedSddl)) {
  throw 'Semantic SDDL digest discarded ACE inheritance provenance.'
}
$manifestPath = Join-Path $env:TEMP ('ar-preexecution-' + [guid]::NewGuid().ToString('N') + '.json')
try {
  $expected = [ordered]@{ schema_version=1; candidate_code_sha=('a' * 40) }
  $manifest = [ordered]@{
    schema_version=1; candidate_code_sha=('a' * 40)
    created_at=[DateTimeOffset]::UtcNow.AddMinutes(-1).ToString('o')
    expires_at=[DateTimeOffset]::UtcNow.AddMinutes(10).ToString('o')
  }
  [IO.File]::WriteAllText($manifestPath,(($manifest|ConvertTo-Json -Compress)+"`n"),[Text.UTF8Encoding]::new($false))
  $manifestHash = Get-ArTrustedSha256 $manifestPath
  $loaded = Read-ArTrustedPreExecutionManifest -Path $manifestPath -ExpectedSha256 $manifestHash
  Assert-ArTrustedPreExecutionManifest -Manifest $loaded -Expected $expected
  $loaded.candidate_code_sha = 'b' * 40
  $rejected = $false
  try { Assert-ArTrustedPreExecutionManifest -Manifest $loaded -Expected $expected } catch { $rejected = $true }
  if (-not $rejected) { throw 'Pre-execution identity drift was accepted.' }
  $loaded.candidate_code_sha = 'a' * 40
  $loaded.schema_version = $null
  $rejected = $false
  try { Assert-ArTrustedPreExecutionManifest -Manifest $loaded -Expected $expected } catch { $rejected = $true }
  if (-not $rejected) { throw 'Null pre-execution integer field was accepted.' }
  $loaded.schema_version = 1
  $loaded.created_at = [DateTimeOffset]::UtcNow.AddMinutes(10).ToString('o')
  $loaded.expires_at = [DateTimeOffset]::UtcNow.AddMinutes(20).ToString('o')
  $rejected = $false
  try { Assert-ArTrustedPreExecutionManifest -Manifest $loaded -Expected $expected -RequireFresh } catch { $rejected = $true }
  if (-not $rejected) { throw 'Future pre-execution creation time was accepted.' }
} finally { Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if ($isAdmin) {
  $rollbackRoot = Join-Path $env:TEMP ('ar-control-rollback-' + [guid]::NewGuid().ToString('N'))
  $controlRoot = Join-Path $rollbackRoot 'control'
  $prestateRoot = Join-Path $rollbackRoot 'prestate'
  $evidenceRoot = Join-Path $rollbackRoot 'evidence'
  New-Item -ItemType Directory -Path $controlRoot,$prestateRoot,$evidenceRoot -Force | Out-Null
  [IO.File]::WriteAllText((Join-Path $controlRoot 'old.txt'),'old',[Text.UTF8Encoding]::new($false))
  [IO.File]::WriteAllText((Join-Path $prestateRoot 'new.txt'),'new',[Text.UTF8Encoding]::new($false))
  $controlSddl = (Get-Acl -LiteralPath $controlRoot).Sddl
  $operatorSid = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  $failedAsExpected = $false
  try {
    Restore-ArTrustedControlRootAtomic -ControlRoot $controlRoot -Prestate $prestateRoot -EvidenceRoot $evidenceRoot `
      -OperatorSid $operatorSid -ControlSddl $controlSddl -ExpectedControlSddlSha256 ('0' * 64)
  } catch { $failedAsExpected = $true }
  if (-not $failedAsExpected -or -not (Test-Path -LiteralPath (Join-Path $evidenceRoot 'failed-dispatcher-control'))) {
    throw 'Control rollback failure did not preserve the displaced tree.'
  }
  Remove-Item -LiteralPath $rollbackRoot -Recurse -Force -ErrorAction SilentlyContinue

  Remove-Item Function:\Get-ScheduledTask -ErrorAction SilentlyContinue
  $name = 'AR-local trusted rollback contract ' + [guid]::NewGuid().ToString('N')
  try {
    $principal = New-ScheduledTaskPrincipal -UserId ([Security.Principal.WindowsIdentity]::GetCurrent().Name) -LogonType S4U -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
    $original = New-ScheduledTask -Action (New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument '/c exit 0') `
      -Settings $settings -Principal $principal -Description 'Trusted rollback round-trip contract.'
    Register-ScheduledTask -TaskName $name -InputObject $original -Force | Out-Null
    $xml = Export-ScheduledTask -TaskName $name
    $xmlBytes = Get-ArTrustedTaskXmlBytes $name
    $sddl = Get-ArTrustedTaskSddl $name
    $sddlSemantic = Get-ArTrustedSddlSemanticSha256 $sddl
    $replacement = New-ScheduledTask -Action (New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\whoami.exe") `
      -Settings $settings -Principal $principal
    Register-ScheduledTask -TaskName $name -InputObject $replacement -Force | Out-Null
    Restore-ArTrustedPriorTask -TaskName $name -TaskXml $xml -TaskSddl $sddl
    if ((Get-ArTrustedSddlSemanticSha256 (Get-ArTrustedTaskSddl $name)) -cne $sddlSemantic -or
        (Get-ArTrustedTextSha256 ([Text.Encoding]::Unicode.GetString((Get-ArTrustedTaskXmlBytes $name), 2, (Get-ArTrustedTaskXmlBytes $name).Length - 2))) -cne
        (Get-ArTrustedTextSha256 ([Text.Encoding]::Unicode.GetString($xmlBytes, 2, $xmlBytes.Length - 2)))) {
      throw 'Task Scheduler did not round-trip the authenticated task definition semantically.'
    }
  } finally {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
  }
}
