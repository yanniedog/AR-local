param(
  [string]$TaskName = 'AR-local laptop backup',
  [Parameter(Mandatory = $true)][string]$PackagePath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$PackageSha256,
  [Parameter(Mandatory = $true)][string]$InstallRoot,
  [Parameter(Mandatory = $true)][string]$Target,
  [Parameter(Mandatory = $true)][string]$ControlRoot,
  [Parameter(Mandatory = $true)][string]$RecoveryImage,
  [Parameter(Mandatory = $true)][string]$EvidenceRoot,
  [Parameter(Mandatory = $true)][string]$Principal,
  [Parameter(Mandatory = $true)][string]$Operator,
  [Parameter(Mandatory = $true)][string]$OperatorSid,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$CandidateCodeSha,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$AuthorityCommit,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ProtectedCodeSha,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$PlanGitCommit,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$PlanSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$HandoffSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedOldTaskXmlSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedOldTaskSddlSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedOldTaskSddlSemanticSha256,
  [Parameter(Mandatory = $true)][int]$ExpectedOldTaskLastResult,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$InstallerSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$CoreSha256,
  [Parameter(Mandatory = $true)][string]$PreExecutionManifestPath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$PreExecutionManifestSha256,
  [string]$PiHost = 'ar-local-pi5-lan'
)

$ErrorActionPreference = 'Stop'
$corePath = Join-Path $PSScriptRoot 'install_laptop_backup_trusted_dispatcher_core.ps1'
if ((Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $InstallerSha256) {
  throw 'Trusted installer implementation hash mismatch.'
}
$coreStream = [IO.File]::Open($corePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
$coreAlgorithm = [Security.Cryptography.SHA256]::Create()
try {
  $coreActual = ([BitConverter]::ToString($coreAlgorithm.ComputeHash($coreStream)) -replace '-','').ToLowerInvariant()
  if ($coreActual -cne $CoreSha256) { throw 'Trusted installer core hash mismatch.' }
  $coreStream.Position = 0
  $reader = New-Object IO.StreamReader($coreStream,[Text.UTF8Encoding]::new($false),$true,4096,$true)
  try { $coreText = $reader.ReadToEnd() } finally { $reader.Dispose() }
  . ([ScriptBlock]::Create($coreText))
} finally {
  $coreAlgorithm.Dispose()
  $coreStream.Dispose()
}

function Write-ArTrustedResult {
  param([string]$Result, [string]$ErrorText, [hashtable]$Detail)
  $files = @()
  foreach ($file in @(Get-ChildItem -LiteralPath $script:executionRoot -File -Recurse | Sort-Object FullName)) {
    $files += [ordered]@{ path = $file.FullName; sha256 = Get-ArTrustedSha256 $file.FullName; size = $file.Length }
  }
  $record = [ordered]@{
    schema_version = 1; plan_document_id = 'ARL-OPS-001'; plan_version = '1.5'; plan_git_commit = $PlanGitCommit
    plan_sha256 = $PlanSha256; authority_commit = $AuthorityCommit; handoff_sha256 = $HandoffSha256
    candidate_code_sha = $CandidateCodeSha; protected_code_sha = $ProtectedCodeSha
    operator = $Operator; operator_sid = $OperatorSid; package_sha256 = $PackageSha256; task_name = $TaskName
    pre_execution_manifest_sha256 = $PreExecutionManifestSha256
    started_at = $script:startedAt; completed_at = [DateTimeOffset]::UtcNow.ToString('o')
    exact_commands = @($script:exactCommand); result = $Result; error = $ErrorText; evidence = $Detail
    evidence_files = $files
    deviations = @(); deviation_authorization = $null
  }
  $path = Join-Path $script:executionRoot 'bootstrap-result.json'
  [IO.File]::WriteAllText($path, (($record | ConvertTo-Json -Depth 10 -Compress) + "`n"), [Text.UTF8Encoding]::new($false))
  $path
}

function Write-ArMutationIntent {
  param([Parameter(Mandatory = $true)][string]$Action, [Parameter(Mandatory = $true)][string]$TargetPath)
  $entry = [ordered]@{ at = [DateTimeOffset]::UtcNow.ToString('o'); action = $Action; target = $TargetPath }
  [IO.File]::AppendAllText(
    (Join-Path $script:executionRoot 'mutation-journal.jsonl'),
    (($entry | ConvertTo-Json -Compress) + "`n"),
    [Text.UTF8Encoding]::new($false)
  )
}

function Assert-ArExactInstalledBootstrap {
  $launcher = Join-Path $InstallRoot 'launcher.exe'
  if ((Get-ArTrustedSha256 $PackagePath) -cne $PackageSha256) { throw 'Already-installed package input changed.' }
  Assert-ArTrustedPackageManifest -Root $InstallRoot -InstallRoot $InstallRoot -CandidateCodeSha $CandidateCodeSha `
    -AuthorityCommit $AuthorityCommit -OperatorSid $OperatorSid -ControlRoot $ControlRoot | Out-Null
  Assert-ArTrustedRootAcl -Root $InstallRoot
  Assert-ArTrustedChildConfiguration -Root $InstallRoot -ControlRoot $ControlRoot | Out-Null
  Assert-ArTrustedTask -TaskName $TaskName -LauncherPath $launcher -InstallRoot $InstallRoot -OperatorSid $OperatorSid -Enabled $true | Out-Null
  Assert-ArTrustedTaskSddl -Sddl (Get-ArTrustedTaskSddl $TaskName)
  if ((Test-Path -LiteralPath (Join-Path $InstallRoot 'finalize.enabled')) -or (Test-Path -LiteralPath (Join-Path $InstallRoot 'probe.enabled'))) {
    throw 'Already-installed protected root retains a probe marker.'
  }
  $pointer = Get-Content -LiteralPath (Join-Path $ControlRoot 'active-runner.json') -Raw -ErrorAction Stop | ConvertFrom-Json
  $manifestHash = Get-ArTrustedSha256 (Join-Path $InstallRoot 'dispatcher-manifest.json')
  if ([string]$pointer.manifest_sha256 -cne $manifestHash) { throw 'Active dispatcher pointer differs from the installed manifest.' }
  $installedManifest = Get-Content -LiteralPath (Join-Path $InstallRoot 'dispatcher-manifest.json') -Raw | ConvertFrom-Json
  $receiptName = '{0:d8}-{1}-pass.json' -f [int]$installedManifest.sequence,[string]$installedManifest.activation_id
  $receipt = Get-Content -LiteralPath (Join-Path (Join-Path $ControlRoot 'activation-receipts') $receiptName) -Raw -ErrorAction Stop | ConvertFrom-Json
  if ($receipt.status -cne 'PASS' -or [string]$receipt.manifest_sha256 -cne $manifestHash) { throw 'Installed dispatcher lacks its terminal PASS receipt.' }
  $prior = @(Get-ChildItem -LiteralPath $EvidenceRoot -Filter bootstrap-result.json -File -Recurse | Where-Object { $_.DirectoryName -ne $script:executionRoot } | ForEach-Object {
    try { Get-Content -LiteralPath $_.FullName -Raw | ConvertFrom-Json } catch { $null }
  } | Where-Object { $_.result -ceq 'PASS' -and $_.package_sha256 -ceq $PackageSha256 -and $_.candidate_code_sha -ceq $CandidateCodeSha -and $_.authority_commit -ceq $AuthorityCommit })
  if ($prior.Count -lt 1) { throw 'Protected evidence has no matching prior bootstrap PASS.' }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -or $identity.User.Value -cne $OperatorSid) { throw 'Trusted bootstrap requires the authorised elevated operator.' }
$local = [DateTimeOffset]::Now
if ($local.TimeOfDay -lt [TimeSpan]::FromHours(3.5) -or $local.TimeOfDay -ge [TimeSpan]::FromHours(22)) { throw 'Trusted bootstrap is outside the D-006 daylight window.' }
if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw 'Trusted package is absent.' }
if (-not (Test-Path -LiteralPath $PreExecutionManifestPath -PathType Leaf)) { throw 'Pre-execution manifest is absent.' }
foreach ($path in @($Target,$ControlRoot)) { if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw "Required directory is absent: $path" } }
foreach ($path in @($PackagePath,$PreExecutionManifestPath,$Target,$ControlRoot,$RecoveryImage,([IO.Path]::GetDirectoryName($InstallRoot)),([IO.Path]::GetDirectoryName($EvidenceRoot)))) { Assert-ArTrustedPlainPath $path | Out-Null }
$expectedControl = Join-Path ([IO.Path]::GetFullPath($Target)) 'dispatcher-control'
if ([IO.Path]::GetFullPath($ControlRoot) -cne [IO.Path]::GetFullPath($expectedControl)) { throw 'ControlRoot must be exactly Target\dispatcher-control.' }
$programFilesRoot = [IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\') + '\'
$installFull = [IO.Path]::GetFullPath($InstallRoot)
if (-not $installFull.StartsWith($programFilesRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'InstallRoot must be below Program Files.' }
$evidenceFull = [IO.Path]::GetFullPath($EvidenceRoot)
if (-not $evidenceFull.StartsWith($programFilesRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'EvidenceRoot must be below Program Files.' }
$identitySuffix = $CandidateCodeSha + '-' + $AuthorityCommit
$expectedInstall = [IO.Path]::GetFullPath((Join-Path $env:ProgramFiles ('AR-local-backup-trusted-' + $identitySuffix)))
$expectedEvidence = [IO.Path]::GetFullPath((Join-Path $env:ProgramFiles ('AR-local-backup-evidence-' + $identitySuffix)))
if ($installFull -cne $expectedInstall) { throw 'InstallRoot is not exactly content-addressed by candidate and authority.' }
if ($evidenceFull -cne $expectedEvidence) { throw 'EvidenceRoot is not exactly content-addressed by candidate and authority.' }
if ([IO.Path]::GetFullPath([IO.Path]::GetDirectoryName($installFull)) -cne [IO.Path]::GetFullPath($env:ProgramFiles) -or
    [IO.Path]::GetFullPath([IO.Path]::GetDirectoryName($evidenceFull)) -cne [IO.Path]::GetFullPath($env:ProgramFiles)) {
  throw 'InstallRoot and EvidenceRoot must be direct children of the protected Program Files directory.'
}
$preExecution = Read-ArTrustedPreExecutionManifest -Path $PreExecutionManifestPath -ExpectedSha256 $PreExecutionManifestSha256
$expectedPreExecution = [ordered]@{
  schema_version = 1; plan_document_id = 'ARL-OPS-001'; plan_version = '1.5'; task_name = $TaskName
  package_path = [IO.Path]::GetFullPath($PackagePath); package_sha256 = $PackageSha256
  install_root = $installFull; target = [IO.Path]::GetFullPath($Target); control_root = [IO.Path]::GetFullPath($ControlRoot)
  recovery_image = [IO.Path]::GetFullPath($RecoveryImage)
  evidence_root = $evidenceFull; principal = $Principal; operator = $Operator; operator_sid = $OperatorSid
  candidate_code_sha = $CandidateCodeSha; authority_commit = $AuthorityCommit; protected_code_sha = $ProtectedCodeSha
  plan_git_commit = $PlanGitCommit; plan_sha256 = $PlanSha256; handoff_sha256 = $HandoffSha256
  expected_old_task_xml_sha256 = $ExpectedOldTaskXmlSha256; expected_old_task_sddl_sha256 = $ExpectedOldTaskSddlSha256
  expected_old_task_sddl_semantic_sha256 = $ExpectedOldTaskSddlSemanticSha256
  expected_old_task_last_result = $ExpectedOldTaskLastResult; installer_sha256 = $InstallerSha256; core_sha256 = $CoreSha256
  pi_host = $PiHost
}
Assert-ArTrustedPreExecutionManifest -Manifest $preExecution -Expected $expectedPreExecution
if ((Get-PSDrive -Name ([IO.Path]::GetPathRoot($Target).Substring(0,1))).Free -lt 50GB) { throw 'Laptop free space is below 50 GiB.' }
$active = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine -match 'laptop_backup_(scheduled|dispatcher)|laptop_pull_backup' })
if ($active.Count) { throw 'A laptop backup or dispatcher process is already active.' }
$residue = @()
foreach ($path in @((Join-Path $Target 'catalog\.receiver.lock'),(Join-Path $ControlRoot 'transition.lease'))) {
  if (Test-Path -LiteralPath $path) { $residue += $path }
}
$residue += @(Get-ChildItem -LiteralPath $Target -Recurse -Force -ErrorAction Stop | Where-Object {
  $_.Name -like '*.partial' -or $_.Name -like '.partial-*' -or $_.Name -like '*.partial-*'
} | ForEach-Object { $_.FullName })
if ($residue.Count) { throw 'Backup lock, transition lease, or partial residue exists.' }

$ssh = "$env:SystemRoot\System32\OpenSSH\ssh.exe"
$piLines = @('set -eu','cd /srv/ar-local/AR-local',('test "$(git rev-parse HEAD)" = ''{0}''' -f $ProtectedCodeSha),'test -z "$(git status --porcelain=v1)"','! systemctl is-active --quiet ar-local-daily.service','test ! -e /srv/ar-local/data/state/daily-ingest.lock','curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest >/dev/null','echo AR_PI_PREFLIGHT_PASS')
$piScript = ($piLines -join "`n") + "`n"
$piResult = Invoke-ArTrustedSshScript -SshPath $ssh -HostName $PiHost -Script $piScript
$piOutput = @($piResult.Stdout.TrimEnd() -split "`n")
if ($piResult.ExitCode -ne 0 -or $piOutput[-1] -cne 'AR_PI_PREFLIGHT_PASS') { throw 'Pi trusted-bootstrap preflight failed.' }

$script:startedAt = [DateTimeOffset]::UtcNow.ToString('o')
$script:exactCommand = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").CommandLine
if (-not (Test-Path -LiteralPath $EvidenceRoot)) {
  try {
    New-Item -ItemType Directory -Path $EvidenceRoot -ErrorAction Stop | Out-Null
    Set-ArTrustedRootAcl -Root $EvidenceRoot -OperatorSid $OperatorSid
    Assert-ArTrustedRootAcl -Root $EvidenceRoot
  } catch {
    if (Test-Path -LiteralPath $EvidenceRoot) { Remove-Item -LiteralPath $EvidenceRoot -Recurse -Force -ErrorAction SilentlyContinue }
    throw
  }
} else {
  Assert-ArTrustedRootAcl -Root $EvidenceRoot
}
$executionId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N')
$script:executionRoot = Join-Path $EvidenceRoot $executionId
New-Item -ItemType Directory -Path $script:executionRoot -ErrorAction Stop | Out-Null
Set-ArTrustedRootAcl -Root $script:executionRoot -OperatorSid $OperatorSid
Assert-ArTrustedRootAcl -Root $script:executionRoot
[IO.File]::WriteAllText((Join-Path $script:executionRoot 'pi-preflight.txt'), (($piOutput -join "`n") + "`n"), [Text.UTF8Encoding]::new($false))
$preservedPreExecution = Join-Path $script:executionRoot 'pre-execution-manifest.json'
Copy-Item -LiteralPath $PreExecutionManifestPath -Destination $preservedPreExecution -ErrorAction Stop
if ((Get-ArTrustedSha256 $preservedPreExecution) -cne $PreExecutionManifestSha256) { throw 'Preserved pre-execution manifest changed.' }

if (Test-Path -LiteralPath $InstallRoot) {
  try {
    Assert-ArExactInstalledBootstrap
    $already = Write-ArTrustedResult -Result 'PASS' -ErrorText $null -Detail @{ mode='ALREADY_INSTALLED'; install_root=$InstallRoot }
    Get-Content -LiteralPath $already -Raw
    exit 0
  } catch {
    Write-ArTrustedResult -Result 'BLOCKED' -ErrorText $_.Exception.Message -Detail @{ mode='ALREADY_INSTALLED_REJECTED' } | Out-Null
    throw
  }
}

# Exact installed-state recovery is intentionally available after the short
# bootstrap authorization expires.  A new installation, however, requires the
# same manifest to be fresh immediately before any staging or task mutation.
Assert-ArTrustedPreExecutionManifest -Manifest $preExecution -Expected $expectedPreExecution -RequireFresh

try {
  $oldTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $oldInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
  if ($oldTask.State.ToString() -ne 'Ready' -or -not $oldTask.Settings.Enabled -or $oldInfo.LastTaskResult -ne $ExpectedOldTaskLastResult -or
      $oldTask.Principal.LogonType.ToString() -ne 'S4U' -or $oldTask.Principal.RunLevel.ToString() -ne 'Limited') {
    throw 'Existing production task state differs from the authorised prestate.'
  }
  $oldXml = Export-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $oldXmlPath = Join-Path $script:executionRoot 'pre-bootstrap-task.xml'
  [IO.File]::WriteAllBytes($oldXmlPath, (Get-ArTrustedTaskXmlBytes $TaskName))
  $oldSddl = Get-ArTrustedTaskSddl $TaskName
  [IO.File]::WriteAllText((Join-Path $script:executionRoot 'pre-bootstrap-task.sddl'), $oldSddl, [Text.UTF8Encoding]::new($false))
  if ((Get-ArTrustedSha256 $oldXmlPath) -cne $ExpectedOldTaskXmlSha256 -or
      (Get-ArTrustedTextSha256 $oldSddl) -cne $ExpectedOldTaskSddlSha256 -or
      (Get-ArTrustedSddlSemanticSha256 $oldSddl) -cne $ExpectedOldTaskSddlSemanticSha256) {
    throw 'Existing task is not the authorised prestate.'
  }
} catch {
  Write-ArTrustedResult -Result 'BLOCKED' -ErrorText $_.Exception.Message -Detail @{ mode='PRESTATE_REJECTED' } | Out-Null
  throw
}

$staging = $InstallRoot + '.staging-' + [guid]::NewGuid().ToString('N')
$probeName = 'AR-local trusted dispatcher probe ' + [guid]::NewGuid().ToString('N')
$controlPrestate = Join-Path $script:executionRoot 'dispatcher-control-prestate'
$controlSddl = (Get-Acl -LiteralPath $ControlRoot -ErrorAction Stop).Sddl
$controlSddlSemanticSha256 = Get-ArTrustedSddlBinarySha256 $controlSddl
[IO.File]::WriteAllText((Join-Path $script:executionRoot 'pre-bootstrap-control.sddl'), $controlSddl, [Text.UTF8Encoding]::new($false))
$mutated = $false; $probeRegistered = $false; $installed = $false; $controlChanged = $false
try {
  # Authenticate and publish the new protected bytes before the first task or
  # control mutation.  Package drift, expiry, or authority-main drift therefore
  # stops with the production task untouched.
  Write-ArMutationIntent -Action 'CREATE_PACKAGE_STAGING' -TargetPath $staging
  New-Item -ItemType Directory -Path $staging -ErrorAction Stop | Out-Null
  Set-ArTrustedRootAcl -Root $staging -OperatorSid $OperatorSid
  Assert-ArTrustedRootAcl -Root $staging
  Expand-ArAuthenticatedPackage -PackagePath $PackagePath -ExpectedSha256 $PackageSha256 -Destination $staging
  Assert-ArTrustedPackageManifest -Root $staging -InstallRoot $InstallRoot -CandidateCodeSha $CandidateCodeSha `
    -AuthorityCommit $AuthorityCommit -OperatorSid $OperatorSid -ControlRoot $ControlRoot | Out-Null
  Set-ArTrustedRootAcl -Root $staging -OperatorSid $OperatorSid
  Assert-ArTrustedRootAcl -Root $staging
  Write-ArMutationIntent -Action 'PUBLISH_PROTECTED_ROOT' -TargetPath $InstallRoot
  Move-Item -LiteralPath $staging -Destination $InstallRoot -ErrorAction Stop
  $installed = $true
  Assert-ArTrustedRootAcl -Root $InstallRoot
  $launcher = Join-Path $InstallRoot 'launcher.exe'
  $manifest = Join-Path $InstallRoot 'dispatcher-manifest.json'
  $python = Join-Path $InstallRoot 'python\python.exe'
  $dispatcher = Join-Path $InstallRoot 'laptop_backup_dispatcher.py'
  $dispatcherManifest = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
  if ($dispatcherManifest.plan_document_id -cne 'ARL-OPS-001' -or $dispatcherManifest.plan_version -cne '1.5' -or
      $dispatcherManifest.plan_git_commit -cne $PlanGitCommit -or $dispatcherManifest.plan_sha256 -cne $PlanSha256 -or
      $dispatcherManifest.authority_commit -cne $AuthorityCommit -or $dispatcherManifest.handoff_sha256 -cne $HandoffSha256 -or
      $dispatcherManifest.candidate_code_sha -cne $CandidateCodeSha -or $dispatcherManifest.protected_code_sha -cne $ProtectedCodeSha -or
      $dispatcherManifest.operator -cne $Operator -or $dispatcherManifest.operator_sid -cne $OperatorSid -or
      [IO.Path]::GetFullPath([string]$dispatcherManifest.receiver) -cne (Join-Path $InstallRoot 'receiver') -or
      [IO.Path]::GetFullPath([string]$dispatcherManifest.authority_repo) -cne (Join-Path $InstallRoot 'authority') -or
      [IO.Path]::GetFullPath([string]$dispatcherManifest.python_path) -cne $python -or
      [IO.Path]::GetFullPath([string]$dispatcherManifest.allowed_receiver_root) -cne [IO.Path]::GetFullPath($InstallRoot) -or
      [IO.Path]::GetFullPath([string]$dispatcherManifest.target) -cne [IO.Path]::GetFullPath($Target) -or
      [IO.Path]::GetFullPath([string]$dispatcherManifest.allowed_target_root) -cne [IO.Path]::GetFullPath($Target) -or
      [IO.Path]::GetFullPath([string]$dispatcherManifest.recovery_image) -cne [IO.Path]::GetFullPath($RecoveryImage) -or
      [IO.Path]::GetFullPath([string]$dispatcherManifest.allowed_recovery_root) -cne [IO.Path]::GetFullPath([IO.Path]::GetDirectoryName($RecoveryImage))) {
    throw 'Protected dispatcher manifest does not match the authorised bootstrap identity.'
  }
  $trustedConfig = Assert-ArTrustedChildConfiguration -Root $InstallRoot -ControlRoot $ControlRoot
  $toolPaths = @($trustedConfig.git_path,$trustedConfig.ssh_path,$trustedConfig.scp_path,$trustedConfig.whoami_path)
  $env:PATH = (($toolPaths | ForEach-Object { [IO.Path]::GetDirectoryName([string]$_) } | Select-Object -Unique) -join ';')
  $env:GIT_CONFIG_COUNT = '2'; $env:GIT_CONFIG_KEY_0 = 'safe.directory'; $env:GIT_CONFIG_VALUE_0 = [string]$trustedConfig.receiver_path
  $env:GIT_CONFIG_KEY_1 = 'safe.directory'; $env:GIT_CONFIG_VALUE_1 = [string]$trustedConfig.authority_path; $env:GIT_CONFIG_GLOBAL = 'NUL'
  $env:AR_TRUSTED_ROOT = $InstallRoot; $env:GIT_OPTIONAL_LOCKS = '0'; $env:PYTHONNOUSERSITE = '1'; $env:PYTHONDONTWRITEBYTECODE = '1'
  & $python -B -s -E $dispatcher validate --control-root $ControlRoot --manifest $manifest
  if ($LASTEXITCODE -ne 0) { throw 'Protected dispatcher pre-mutation validation failed.' }

  Copy-Item -LiteralPath $ControlRoot -Destination $controlPrestate -Recurse -ErrorAction Stop
  Write-ArMutationIntent -Action 'DISABLE_PRODUCTION_TASK' -TargetPath $TaskName
  $mutated = $true
  Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
  $disabled = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $activeAfterDisable = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine -match 'laptop_backup_(scheduled|dispatcher)|laptop_pull_backup' })
  if ($disabled.State.ToString() -ne 'Disabled' -or $disabled.Settings.Enabled -or $activeAfterDisable.Count) { throw 'Production task did not become safely quiescent.' }
  $controlChanged = $true
  Write-ArMutationIntent -Action 'ACTIVATE_DISPATCHER_MANIFEST' -TargetPath $ControlRoot
  & $python -B -s -E $dispatcher activate --control-root $ControlRoot --manifest $manifest --defer-proof
  if ($LASTEXITCODE -ne 0) { throw 'Protected dispatcher activation failed.' }

  $definition = New-ArTrustedTaskDefinition -LauncherPath $launcher -InstallRoot $InstallRoot -Principal $Principal -Enabled $false
  Write-ArMutationIntent -Action 'REGISTER_DISABLED_PRODUCTION_TASK' -TargetPath $TaskName
  Register-ScheduledTask -TaskName $TaskName -InputObject $definition -Force -ErrorAction Stop | Out-Null
  $installedTaskSddl = Set-ArTrustedTaskSddl -TaskName $TaskName -OperatorSid $OperatorSid
  Assert-ArTrustedTask -TaskName $TaskName -LauncherPath $launcher -InstallRoot $InstallRoot -OperatorSid $OperatorSid -Enabled $false | Out-Null

  $probeMarker = Join-Path $InstallRoot 'finalize.enabled'
  $probeOutput = Join-Path $ControlRoot 'bootstrap-finalize.json'
  if (Test-Path -LiteralPath $probeOutput) { throw 'Semantic-finalization output already exists.' }
  [IO.File]::WriteAllBytes($probeMarker, [Text.Encoding]::ASCII.GetBytes('FINALIZE'))
  Set-ArTrustedRootAcl -Root $InstallRoot -OperatorSid $OperatorSid
  $probeSettings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  $probeDefinition = New-ScheduledTask -Action (New-ScheduledTaskAction -Execute $launcher -WorkingDirectory $InstallRoot) -Settings $probeSettings `
    -Principal (New-ScheduledTaskPrincipal -UserId $Principal -LogonType S4U -RunLevel Limited) -Description 'Disposable protected-token validation only.'
  Write-ArMutationIntent -Action 'REGISTER_DISPOSABLE_PROBE' -TargetPath $probeName
  Register-ScheduledTask -TaskName $probeName -InputObject $probeDefinition -Force -ErrorAction Stop | Out-Null
  $probeRegistered = $true
  $probeSddl = Set-ArTrustedTaskSddl -TaskName $probeName -OperatorSid $OperatorSid
  Assert-ArTrustedProbeTask -TaskName $probeName -LauncherPath $launcher -InstallRoot $InstallRoot -OperatorSid $OperatorSid | Out-Null
  if ((Get-ArTrustedTaskSddl $probeName) -cne $probeSddl) { throw 'Disposable probe SDDL changed before execution.' }
  Write-ArMutationIntent -Action 'START_DISPOSABLE_PROBE_ONLY' -TargetPath $probeName
  Start-ScheduledTask -TaskName $probeName -ErrorAction Stop
  $deadline = [DateTimeOffset]::Now.AddMinutes(2)
  do { Start-Sleep -Seconds 1; $probeTask = Get-ScheduledTask -TaskName $probeName; $probeInfo = Get-ScheduledTaskInfo -TaskName $probeName } while ($probeTask.State.ToString() -eq 'Running' -and [DateTimeOffset]::Now -lt $deadline)
  if ($probeTask.State.ToString() -eq 'Running' -or $probeInfo.LastTaskResult -ne 0) { throw 'Disposable protected-token probe failed.' }
  $probe = Get-Content -LiteralPath $probeOutput -Raw -ErrorAction Stop | ConvertFrom-Json
  if ($probe.ok -ne $true -or $probe.result -cne 'PASS' -or $probe.is_admin -ne $false -or
      [string]$probe.operator_sid -cne $OperatorSid -or [string]$probe.candidate_code_sha -cne $CandidateCodeSha) {
    throw 'Protected semantic-finalization result is invalid.'
  }
  Copy-Item -LiteralPath $probeOutput -Destination (Join-Path $script:executionRoot 'semantic-finalization.json') -ErrorAction Stop
  Write-ArMutationIntent -Action 'REMOVE_DISPOSABLE_PROBE' -TargetPath $probeName
  Unregister-ScheduledTask -TaskName $probeName -Confirm:$false -ErrorAction Stop; $probeRegistered = $false
  Write-ArMutationIntent -Action 'REMOVE_PROBE_MARKER' -TargetPath $probeMarker
  Remove-Item -LiteralPath $probeMarker -Force -ErrorAction Stop
  Write-ArMutationIntent -Action 'REMOVE_SEMANTIC_OUTPUT' -TargetPath $probeOutput
  Remove-Item -LiteralPath $probeOutput -Force -ErrorAction Stop
  Assert-ArTrustedRootAcl -Root $InstallRoot

  Write-ArMutationIntent -Action 'ENABLE_PRODUCTION_TASK_WITHOUT_START' -TargetPath $TaskName
  Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
  Assert-ArTrustedTask -TaskName $TaskName -LauncherPath $launcher -InstallRoot $InstallRoot -OperatorSid $OperatorSid -Enabled $true | Out-Null
  $installedXml = Join-Path $script:executionRoot 'installed-task.xml'
  [IO.File]::WriteAllBytes($installedXml, (Get-ArTrustedTaskXmlBytes $TaskName))
  $installedSddl = Get-ArTrustedTaskSddl $TaskName
  if ($installedSddl -cne $installedTaskSddl) { throw 'Installed task SDDL changed after activation.' }
  [IO.File]::WriteAllText((Join-Path $script:executionRoot 'installed-task.sddl'), $installedSddl, [Text.UTF8Encoding]::new($false))
  $result = Write-ArTrustedResult -Result 'PASS' -ErrorText $null -Detail @{
    install_root = $InstallRoot; installed_task_xml_sha256 = Get-ArTrustedSha256 $installedXml
    installed_task_sddl_sha256 = Get-ArTrustedTextSha256 $installedSddl; probe_last_result = $probeInfo.LastTaskResult
  }
  Get-Content -LiteralPath $result -Raw
} catch {
  $failure = $_.Exception.Message
  $rollbackErrors = New-Object Collections.Generic.List[string]
  if ($probeRegistered) {
    try { Write-ArMutationIntent -Action 'ROLLBACK_REMOVE_PROBE' -TargetPath $probeName; Unregister-ScheduledTask -TaskName $probeName -Confirm:$false -ErrorAction Stop }
    catch { $rollbackErrors.Add("probe cleanup: $($_.Exception.Message)") }
  }
  if ($controlChanged) {
    try {
      Write-ArMutationIntent -Action 'ROLLBACK_RESTORE_CONTROL' -TargetPath $ControlRoot
      Restore-ArTrustedControlRootAtomic -ControlRoot $ControlRoot -Prestate $controlPrestate `
        -EvidenceRoot $script:executionRoot -OperatorSid $OperatorSid -ControlSddl $controlSddl `
        -ExpectedControlSddlSha256 $controlSddlSemanticSha256
    } catch { $rollbackErrors.Add("control restore: $($_.Exception.Message)") }
  }
  if ($mutated) {
    try {
      Write-ArMutationIntent -Action 'ROLLBACK_RESTORE_PRODUCTION_TASK' -TargetPath $TaskName
      Restore-ArTrustedPriorTask -TaskName $TaskName -TaskXml $oldXml -TaskSddl $oldSddl
      $restoredXml = Join-Path $script:executionRoot 'rollback-task.xml'
      [IO.File]::WriteAllBytes($restoredXml, (Get-ArTrustedTaskXmlBytes $TaskName))
      $restoredSddl = Get-ArTrustedTaskSddl $TaskName
      $restoredSddlPath = Join-Path $script:executionRoot 'rollback-task.sddl'
      [IO.File]::WriteAllText($restoredSddlPath, $restoredSddl, [Text.UTF8Encoding]::new($false))
      if ((Get-ArTrustedSha256 $restoredXml) -cne $ExpectedOldTaskXmlSha256 -or
          (Get-ArTrustedSddlSemanticSha256 $restoredSddl) -cne $ExpectedOldTaskSddlSemanticSha256) {
        throw 'Rollback task differs semantically from authenticated prestate.'
      }
      $restoredTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
      if ($restoredTask.State.ToString() -ne 'Ready' -or -not $restoredTask.Settings.Enabled) { throw 'Rollback did not restore a Ready enabled task.' }
    } catch { $rollbackErrors.Add("task restore: $($_.Exception.Message)") }
  }
  foreach ($path in @($staging,$InstallRoot)) {
    if (Test-Path -LiteralPath $path) {
      try {
        $destination = Join-Path $script:executionRoot ('failed-protected-root-' + [guid]::NewGuid().ToString('N'))
        Write-ArMutationIntent -Action 'ROLLBACK_QUARANTINE_NEW_ROOT' -TargetPath $path
        Move-Item -LiteralPath $path -Destination $destination -ErrorAction Stop
        Set-ArTrustedRootAcl -Root $destination -OperatorSid $OperatorSid
        Assert-ArTrustedRootAcl -Root $destination
      } catch { $rollbackErrors.Add("root quarantine $path`: $($_.Exception.Message)") }
    }
  }
  $outcome = if ($rollbackErrors.Count -eq 0) { 'ROLLED_BACK' } else { 'FAIL' }
  $message = if ($rollbackErrors.Count -eq 0) { $failure } else { "$failure; rollback failures: $($rollbackErrors -join '; ')" }
  Write-ArTrustedResult -Result $outcome -ErrorText $message -Detail @{} | Out-Null
  throw $message
}
