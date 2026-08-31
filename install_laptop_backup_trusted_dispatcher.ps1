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
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedCatalogSha256,
  [Parameter(Mandatory = $true)][long]$ExpectedCatalogSize,
  [Parameter(Mandatory = $true)][int]$ExpectedCatalogFinalSequence,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedCatalogFinalEntrySha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedLatestVerifiedSha256,
  [Parameter(Mandatory = $true)][long]$ExpectedLatestVerifiedSize,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedAcceptedCatalogEntrySha256,
  [Parameter(Mandatory = $true)][string]$ExpectedAcceptedReceiptRelativePath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedAcceptedReceiptSha256,
  [Parameter(Mandatory = $true)][long]$ExpectedAcceptedReceiptSize,
  [Parameter(Mandatory = $true)][string]$ExpectedAcceptedObservationId,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedAcceptedArchiveSha256,
  [Parameter(Mandatory = $true)][long]$ExpectedAcceptedArchiveSize,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$InstallerSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$CoreSha256,
  [Parameter(Mandatory = $true)][string]$PreExecutionManifestPath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$PreExecutionManifestSha256,
  [string]$PiHost = 'ar-local-pi5-lan'
)

$ErrorActionPreference = 'Stop'
$script:authorizedDeviations = @()
$script:deviationAuthorization = $null
$script:bootstrapGate = $null
$script:bootstrapGateName = 'Global\ARLocalTrustedBootstrapGate'
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
    deviations = @($script:authorizedDeviations)
    deviation_authorization = $script:deviationAuthorization
  }
  $path = Join-Path $script:executionRoot 'bootstrap-result.json'
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

function Write-ArMutationIntent {
  param([Parameter(Mandatory = $true)][string]$Action, [Parameter(Mandatory = $true)][string]$TargetPath)
  $entry = [ordered]@{ at = [DateTimeOffset]::UtcNow.ToString('o'); action = $Action; target = $TargetPath }
  [IO.File]::AppendAllText(
    (Join-Path $script:executionRoot 'mutation-journal.jsonl'),
    (($entry | ConvertTo-Json -Compress) + "`n"),
    [Text.UTF8Encoding]::new($false)
  )
}

function Enter-ArTrustedBootstrapGate {
  if ($null -ne $script:bootstrapGate) { throw 'Trusted bootstrap gate is already held by this process.' }
  $createdNew = $false
  $gate = [Threading.Mutex]::new($true, $script:bootstrapGateName, [ref]$createdNew)
  if (-not $createdNew) {
    $gate.Dispose()
    throw 'Another trusted bootstrap gate already exists.'
  }
  $script:bootstrapGate = $gate
  Write-ArMutationIntent -Action 'ACQUIRE_GLOBAL_BOOTSTRAP_GATE' -TargetPath $script:bootstrapGateName
}

function Exit-ArTrustedBootstrapGate {
  if ($null -eq $script:bootstrapGate) { return }
  try {
    $script:bootstrapGate.ReleaseMutex()
  } finally {
    $script:bootstrapGate.Dispose()
    $script:bootstrapGate = $null
  }
}

function Assert-ArTrustedBackupQuiescence {
  param([switch]$RequireReadyTask)
  $processes = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -and
    $_.CommandLine -match 'laptop_backup_(scheduled|dispatcher|trusted_child)|laptop_pull_backup|run_laptop_backup|AR-local-backup-trusted-.*launcher\.exe'
  })
  $items = @((Join-Path $Target 'catalog\.receiver.lock'),(Join-Path $ControlRoot 'transition.lease')) | Where-Object { Test-Path -LiteralPath $_ }
  $items += @(Get-ChildItem -LiteralPath $Target -Recurse -Force -ErrorAction Stop | Where-Object {
    $_.Name -like '*.partial' -or $_.Name -like '.partial-*' -or $_.Name -like '*.partial-*'
  } | ForEach-Object { $_.FullName })
  if ($processes.Count -or $items.Count) { throw 'Backup process, lock, transition lease, or partial residue exists.' }
  if ($RequireReadyTask) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ($task.State.ToString() -ne 'Ready' -or -not $task.Settings.Enabled) { throw 'Production task is not terminally Ready and enabled.' }
  }
  [ordered]@{ active_process_count=$processes.Count; residue_count=$items.Count; task_ready=[bool]$RequireReadyTask }
}

function Invoke-ArTrustedPiIdleCheck {
  param([Parameter(Mandatory = $true)][string]$Phase)
  $ssh = "$env:SystemRoot\System32\OpenSSH\ssh.exe"
  $lines = @(
    'set -eu','cd /srv/ar-local/AR-local',
    ('test "$(git rev-parse HEAD)" = ''{0}''' -f $ProtectedCodeSha),
    'test -z "$(git status --porcelain=v1)"',
    '! systemctl is-active --quiet ar-local-daily.service',
    'test ! -e /srv/ar-local/data/state/daily-ingest.lock',
    'curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest >/dev/null',
    'echo AR_PI_PREFLIGHT_PASS'
  )
  $result = Invoke-ArTrustedSshScript -SshPath $ssh -HostName $PiHost -Script (($lines -join "`n") + "`n")
  $output = @($result.Stdout.TrimEnd() -split "`n")
  if ($result.ExitCode -ne 0 -or $output[-1] -cne 'AR_PI_PREFLIGHT_PASS') {
    throw "Pi trusted-bootstrap $Phase check failed."
  }
  [ordered]@{ phase=$Phase; exit_code=$result.ExitCode; output=$output }
}

function Stop-ArTrustedProbeAndAwait {
  $task = Get-ScheduledTask -TaskName $probeName -ErrorAction Stop
  if ($task.State.ToString() -eq 'Running') {
    Write-ArMutationIntent -Action 'ROLLBACK_STOP_RUNNING_PROBE' -TargetPath $probeName
    Stop-ScheduledTask -TaskName $probeName -ErrorAction Stop
  }
  $deadline = [DateTimeOffset]::Now.AddSeconds(30)
  do {
    Start-Sleep -Milliseconds 250
    $task = Get-ScheduledTask -TaskName $probeName -ErrorAction Stop
  } while ($task.State.ToString() -eq 'Running' -and [DateTimeOffset]::Now -lt $deadline)
  if ($task.State.ToString() -eq 'Running') { throw 'Disposable probe remained Running after stop.' }
  $helpers = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -and
    $_.CommandLine -match 'laptop_backup_(dispatcher|trusted_child)|run_laptop_backup|AR-local-backup-trusted-.*launcher\.exe'
  })
  if ($helpers.Count) { throw 'Disposable probe helper remained after stop.' }
}

function Invoke-ArTrustedActiveControlValidation {
  $trustedConfig = Assert-ArTrustedChildConfiguration -Root $InstallRoot -ControlRoot $ControlRoot
  $toolPaths = @($trustedConfig.git_path,$trustedConfig.ssh_path,$trustedConfig.scp_path,$trustedConfig.whoami_path)
  $env:PATH = (($toolPaths | ForEach-Object { [IO.Path]::GetDirectoryName([string]$_) } | Select-Object -Unique) -join ';')
  $env:GIT_CONFIG_COUNT = '2'; $env:GIT_CONFIG_KEY_0 = 'safe.directory'; $env:GIT_CONFIG_VALUE_0 = [string]$trustedConfig.receiver_path
  $env:GIT_CONFIG_KEY_1 = 'safe.directory'; $env:GIT_CONFIG_VALUE_1 = [string]$trustedConfig.authority_path; $env:GIT_CONFIG_GLOBAL = 'NUL'
  $env:AR_TRUSTED_ROOT = $InstallRoot; $env:GIT_OPTIONAL_LOCKS = '0'; $env:PYTHONNOUSERSITE = '1'; $env:PYTHONDONTWRITEBYTECODE = '1'
  $python = Join-Path $InstallRoot 'python\python.exe'
  $dispatcher = Join-Path $InstallRoot 'laptop_backup_dispatcher.py'
  $lines = @(& $python -B -s -E $dispatcher verify-active --control-root $ControlRoot 2>&1 | ForEach-Object { [string]$_ })
  if ($LASTEXITCODE -ne 0 -or $lines.Count -lt 1) { throw "Protected active-control validation failed: $($lines -join ' ')" }
  $value = $lines[-1] | ConvertFrom-Json
  $expectedManifestSha256 = Get-ArTrustedSha256 (Join-Path $InstallRoot 'dispatcher-manifest.json')
  if ($value.ok -ne $true -or $value.result -cne 'PASS' -or $value.mode -cne 'VERIFY_ACTIVE' -or
      [string]$value.candidate_code_sha -cne $CandidateCodeSha -or
      [string]$value.manifest_sha256 -cne $expectedManifestSha256) { throw 'Protected active-control result is invalid.' }
  $value
}

function Set-ArTrustedDeviationAuthorization {
  param([Parameter(Mandatory = $true)][string]$Root)
  $handoffPath = Join-Path $Root 'authority\docs\PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'
  if (-not (Test-Path -LiteralPath $handoffPath -PathType Leaf) -or (Get-ArTrustedSha256 $handoffPath) -cne $HandoffSha256) {
    throw 'Protected authority handoff does not match the authenticated digest.'
  }
  $handoffText = [IO.File]::ReadAllText($handoffPath,[Text.UTF8Encoding]::new($false))
  foreach ($decision in @('D-011','D-012')) {
    $heading = '(?m)^### Append-only deviation decision ' + [char]96 + [regex]::Escape($decision) + [char]96
    if ($handoffText -notmatch $heading) {
      throw "Protected authority handoff does not authorize $decision."
    }
  }
  $script:authorizedDeviations = @('D-011','D-012')
  $script:deviationAuthorization = [ordered]@{ authority_commit=$AuthorityCommit; handoff_sha256=$HandoffSha256 }
}

function Assert-ArTrustedBootstrapResultIdentity {
  param([Parameter(Mandatory = $true)][string]$Path)
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw 'Protected bootstrap result is absent.' }
  $value = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop | ConvertFrom-Json
  if ($value.schema_version -ne 1 -or $value.result -cne 'PASS' -or $null -ne $value.error -or
      $value.plan_document_id -cne 'ARL-OPS-001' -or
      $value.plan_version -cne '1.5' -or $value.plan_git_commit -cne $PlanGitCommit -or
      $value.plan_sha256 -cne $PlanSha256 -or $value.authority_commit -cne $AuthorityCommit -or
      $value.handoff_sha256 -cne $HandoffSha256 -or $value.candidate_code_sha -cne $CandidateCodeSha -or
      $value.protected_code_sha -cne $ProtectedCodeSha -or $value.operator_sid -cne $OperatorSid -or
      $value.package_sha256 -cne $PackageSha256 -or $value.task_name -cne $TaskName) {
    throw 'Protected bootstrap result identity is invalid.'
  }
  $value
}

function Publish-ArTrustedBootstrapReadiness {
  param([Parameter(Mandatory = $true)][string]$ResultPath)
  Assert-ArTrustedBootstrapResultIdentity -Path $ResultPath | Out-Null
  $fixedResult = Join-Path $InstallRoot 'bootstrap-result.json'
  $readyMarker = Join-Path $InstallRoot 'bootstrap.ready'
  if ((Test-Path -LiteralPath $readyMarker) -and -not (Test-Path -LiteralPath $fixedResult -PathType Leaf)) {
    throw 'Protected bootstrap readiness exists without its durable PASS result.'
  }
  if (-not (Test-Path -LiteralPath $fixedResult)) {
    Write-ArMutationIntent -Action 'PUBLISH_DURABLE_BOOTSTRAP_RESULT' -TargetPath $fixedResult
    $source = [IO.File]::Open($ResultPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $destination = [IO.File]::Open($fixedResult,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {
      $source.CopyTo($destination)
      $destination.Flush($true)
    } finally {
      $destination.Dispose()
      $source.Dispose()
    }
  }
  Assert-ArTrustedBootstrapResultIdentity -Path $fixedResult | Out-Null
  if (-not (Test-Path -LiteralPath $readyMarker)) {
    Write-ArMutationIntent -Action 'PUBLISH_TERMINAL_BOOTSTRAP_READINESS' -TargetPath $readyMarker
    $readyStream = [IO.File]::Open($readyMarker,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {
      $readyBytes = [Text.Encoding]::ASCII.GetBytes("AR_LOCAL_TRUSTED_BOOTSTRAP_READY_V1`n")
      $readyStream.Write($readyBytes,0,$readyBytes.Length)
      $readyStream.Flush($true)
    } finally {
      $readyStream.Dispose()
    }
  }
  if ([IO.File]::ReadAllText($readyMarker,[Text.Encoding]::ASCII) -cne "AR_LOCAL_TRUSTED_BOOTSTRAP_READY_V1`n") {
    throw 'Installed bootstrap readiness marker is invalid.'
  }
  Set-ArTrustedRootAcl -Root $InstallRoot -OperatorSid $OperatorSid
  Assert-ArTrustedRootAcl -Root $InstallRoot -OperatorSid $OperatorSid
  [ordered]@{
    bootstrap_result_sha256 = Get-ArTrustedSha256 $fixedResult
    bootstrap_ready_sha256 = Get-ArTrustedSha256 $readyMarker
  }
}

function Assert-ArExactInstalledBootstrap {
  $launcher = Join-Path $InstallRoot 'launcher.exe'
  if ((Get-ArTrustedSha256 $PackagePath) -cne $PackageSha256) { throw 'Already-installed package input changed.' }
  Assert-ArTrustedPackageManifest -Root $InstallRoot -InstallRoot $InstallRoot -CandidateCodeSha $CandidateCodeSha `
    -AuthorityCommit $AuthorityCommit -OperatorSid $OperatorSid -ControlRoot $ControlRoot `
    -AllowedRuntimeFiles @('bootstrap.ready','bootstrap-result.json','installed-task-sddl-semantic.sha256') | Out-Null
  Set-ArTrustedDeviationAuthorization -Root $InstallRoot
  Assert-ArTrustedRootAcl -Root $InstallRoot -OperatorSid $OperatorSid
  Assert-ArTrustedChildConfiguration -Root $InstallRoot -ControlRoot $ControlRoot | Out-Null
  Assert-ArTrustedTask -TaskName $TaskName -LauncherPath $launcher -InstallRoot $InstallRoot -OperatorSid $OperatorSid -Enabled $true | Out-Null
  $taskSddl = Get-ArTrustedTaskSddl $TaskName
  Assert-ArTrustedTaskSddl -Sddl $taskSddl
  $taskSddlSeal = Join-Path $InstallRoot 'installed-task-sddl-semantic.sha256'
  $sealedTaskSddl = (Get-Content -LiteralPath $taskSddlSeal -Raw -ErrorAction Stop).Trim()
  if ($sealedTaskSddl -notmatch '^[0-9a-f]{64}$' -or
      (Get-ArTrustedSddlSemanticSha256 $taskSddl) -cne $sealedTaskSddl) {
    throw 'Installed task SDDL differs from its protected semantic seal.'
  }
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
  $activeValidation = Invoke-ArTrustedActiveControlValidation
  [IO.File]::WriteAllText((Join-Path $script:executionRoot 'active-control-validation.json'), (($activeValidation | ConvertTo-Json -Depth 8 -Compress) + "`n"), [Text.UTF8Encoding]::new($false))
  [ordered]@{
    durable_result_present = Test-Path -LiteralPath (Join-Path $InstallRoot 'bootstrap-result.json') -PathType Leaf
    readiness_present = Test-Path -LiteralPath (Join-Path $InstallRoot 'bootstrap.ready') -PathType Leaf
  }
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
$invocationParameters = [ordered]@{
  task_name=$TaskName; package_path=[IO.Path]::GetFullPath($PackagePath); package_sha256=$PackageSha256
  install_root=$installFull; target=[IO.Path]::GetFullPath($Target); control_root=[IO.Path]::GetFullPath($ControlRoot)
  recovery_image=[IO.Path]::GetFullPath($RecoveryImage); evidence_root=$evidenceFull; principal=$Principal
  operator=$Operator; operator_sid=$OperatorSid; candidate_code_sha=$CandidateCodeSha; authority_commit=$AuthorityCommit
  protected_code_sha=$ProtectedCodeSha; plan_git_commit=$PlanGitCommit; plan_sha256=$PlanSha256; handoff_sha256=$HandoffSha256
  expected_old_task_xml_sha256=$ExpectedOldTaskXmlSha256; expected_old_task_sddl_sha256=$ExpectedOldTaskSddlSha256
  expected_old_task_sddl_semantic_sha256=$ExpectedOldTaskSddlSemanticSha256; expected_old_task_last_result=$ExpectedOldTaskLastResult
  expected_catalog_sha256=$ExpectedCatalogSha256; expected_catalog_size=$ExpectedCatalogSize
  expected_catalog_final_sequence=$ExpectedCatalogFinalSequence; expected_catalog_final_entry_sha256=$ExpectedCatalogFinalEntrySha256
  expected_latest_verified_sha256=$ExpectedLatestVerifiedSha256; expected_latest_verified_size=$ExpectedLatestVerifiedSize
  expected_accepted_catalog_entry_sha256=$ExpectedAcceptedCatalogEntrySha256
  expected_accepted_receipt_relative_path=$ExpectedAcceptedReceiptRelativePath
  expected_accepted_receipt_sha256=$ExpectedAcceptedReceiptSha256; expected_accepted_receipt_size=$ExpectedAcceptedReceiptSize
  expected_accepted_observation_id=$ExpectedAcceptedObservationId; expected_accepted_archive_sha256=$ExpectedAcceptedArchiveSha256
  expected_accepted_archive_size=$ExpectedAcceptedArchiveSize
  installer_sha256=$InstallerSha256; core_sha256=$CoreSha256
  # A manifest cannot contain its own SHA-256. D-012 therefore binds every
  # non-self invocation value here, while the separately authorized outer UAC
  # command supplies the exact manifest SHA-256 that Read-ArTrusted... verifies
  # under one locked stream and Write-ArTrustedResult preserves.
  pre_execution_manifest_path=[IO.Path]::GetFullPath($PreExecutionManifestPath); pre_execution_manifest_sha256='<SELF_SHA256>'
  pi_host=$PiHost
}
$invocationContractSha256 = Get-ArTrustedInvocationContractSha256 $invocationParameters
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
  expected_catalog_sha256 = $ExpectedCatalogSha256; expected_catalog_size = $ExpectedCatalogSize
  expected_catalog_final_sequence = $ExpectedCatalogFinalSequence; expected_catalog_final_entry_sha256 = $ExpectedCatalogFinalEntrySha256
  expected_latest_verified_sha256 = $ExpectedLatestVerifiedSha256; expected_latest_verified_size = $ExpectedLatestVerifiedSize
  expected_accepted_catalog_entry_sha256 = $ExpectedAcceptedCatalogEntrySha256
  expected_accepted_receipt_relative_path = $ExpectedAcceptedReceiptRelativePath
  expected_accepted_receipt_sha256 = $ExpectedAcceptedReceiptSha256; expected_accepted_receipt_size = $ExpectedAcceptedReceiptSize
  expected_accepted_observation_id = $ExpectedAcceptedObservationId; expected_accepted_archive_sha256 = $ExpectedAcceptedArchiveSha256
  expected_accepted_archive_size = $ExpectedAcceptedArchiveSize
  invocation_contract_schema = 1; invocation_host_path = [IO.Path]::GetFullPath((Join-Path $PSHOME 'powershell.exe'))
  invocation_script_path = [IO.Path]::GetFullPath($PSCommandPath); invocation_contract_sha256 = $invocationContractSha256
  rollback_procedure = 'RESTORE_TASK_CONTROL_AND_QUARANTINE_V1'; preflight_min_free_bytes = [long]50GB
  preflight_expected_active_process_count = 0; preflight_expected_residue_count = 0; preflight_expected_pi_status = 'AR_PI_PREFLIGHT_PASS'
  pi_host = $PiHost
}
Assert-ArTrustedPreExecutionManifest -Manifest $preExecution -Expected $expectedPreExecution
$catalogArguments = @{
  Target=$Target; ExpectedCatalogSha256=$ExpectedCatalogSha256; ExpectedCatalogSize=$ExpectedCatalogSize
  ExpectedCatalogFinalSequence=$ExpectedCatalogFinalSequence; ExpectedCatalogFinalEntrySha256=$ExpectedCatalogFinalEntrySha256
  ExpectedLatestVerifiedSha256=$ExpectedLatestVerifiedSha256; ExpectedLatestVerifiedSize=$ExpectedLatestVerifiedSize
  ExpectedAcceptedCatalogEntrySha256=$ExpectedAcceptedCatalogEntrySha256
  ExpectedAcceptedReceiptRelativePath=$ExpectedAcceptedReceiptRelativePath; ExpectedAcceptedReceiptSha256=$ExpectedAcceptedReceiptSha256
  ExpectedAcceptedReceiptSize=$ExpectedAcceptedReceiptSize; ExpectedAcceptedObservationId=$ExpectedAcceptedObservationId
  ExpectedAcceptedArchiveSha256=$ExpectedAcceptedArchiveSha256; ExpectedAcceptedArchiveSize=$ExpectedAcceptedArchiveSize
}
$catalogBaseline = Assert-ArTrustedCatalogBaseline @catalogArguments
$freeBytes = [long](Get-PSDrive -Name ([IO.Path]::GetPathRoot($Target).Substring(0,1))).Free
if ($freeBytes -lt 50GB) { throw 'Laptop free space is below 50 GiB.' }
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

$piPreflight = Invoke-ArTrustedPiIdleCheck -Phase 'initial preflight'
$piOutput = @($piPreflight.output)

$script:startedAt = [DateTimeOffset]::UtcNow.ToString('o')
$script:exactCommand = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").CommandLine
if (-not (Test-Path -LiteralPath $EvidenceRoot)) {
  try {
    New-Item -ItemType Directory -Path $EvidenceRoot -ErrorAction Stop | Out-Null
    Set-ArTrustedRootAcl -Root $EvidenceRoot -OperatorSid $OperatorSid
    Assert-ArTrustedRootAcl -Root $EvidenceRoot -OperatorSid $OperatorSid
  } catch {
    if (Test-Path -LiteralPath $EvidenceRoot) { Remove-Item -LiteralPath $EvidenceRoot -Recurse -Force -ErrorAction SilentlyContinue }
    throw
  }
} else {
  Assert-ArTrustedRootAcl -Root $EvidenceRoot -OperatorSid $OperatorSid
}
$executionId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N')
$script:executionRoot = Join-Path $EvidenceRoot $executionId
New-Item -ItemType Directory -Path $script:executionRoot -ErrorAction Stop | Out-Null
Set-ArTrustedRootAcl -Root $script:executionRoot -OperatorSid $OperatorSid
Assert-ArTrustedRootAcl -Root $script:executionRoot -OperatorSid $OperatorSid
[IO.File]::WriteAllText((Join-Path $script:executionRoot 'pi-preflight.txt'), (($piOutput -join "`n") + "`n"), [Text.UTF8Encoding]::new($false))
[IO.File]::WriteAllText(
  (Join-Path $script:executionRoot 'pre-execution-observed.json'),
  (([ordered]@{
    invocation_contract_sha256=$invocationContractSha256; free_bytes=$freeBytes
    active_process_count=$active.Count; residue_count=$residue.Count; pi_status=$piOutput[-1]
    task_expected_last_result=$ExpectedOldTaskLastResult; catalog=$catalogBaseline
    rollback_procedure='RESTORE_TASK_CONTROL_AND_QUARANTINE_V1'
  } | ConvertTo-Json -Depth 8 -Compress) + "`n"),
  [Text.UTF8Encoding]::new($false)
)
$preservedPreExecution = Join-Path $script:executionRoot 'pre-execution-manifest.json'
Copy-Item -LiteralPath $PreExecutionManifestPath -Destination $preservedPreExecution -ErrorAction Stop
if ((Get-ArTrustedSha256 $preservedPreExecution) -cne $PreExecutionManifestSha256) { throw 'Preserved pre-execution manifest changed.' }

if (Test-Path -LiteralPath $InstallRoot) {
  Enter-ArTrustedBootstrapGate
  try {
    $installedState = Assert-ArExactInstalledBootstrap
    $alreadyQuiescence = Assert-ArTrustedBackupQuiescence -RequireReadyTask
    $already = Write-ArTrustedResult -Result 'PASS' -ErrorText $null -Detail @{
      mode='ALREADY_INSTALLED'; install_root=$InstallRoot; bootstrap_gate_held=$true
      terminal_quiescence=$alreadyQuiescence; recovered_incomplete_readiness=(-not $installedState.readiness_present)
    }
    Publish-ArTrustedBootstrapReadiness -ResultPath $already | Out-Null
    Get-Content -LiteralPath $already -Raw
    exit 0
  } catch {
    Write-ArTrustedResult -Result 'BLOCKED' -ErrorText $_.Exception.Message -Detail @{ mode='ALREADY_INSTALLED_REJECTED' } | Out-Null
    throw
  } finally {
    Exit-ArTrustedBootstrapGate
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
  Assert-ArTrustedRootAcl -Root $staging -OperatorSid $OperatorSid
  Expand-ArAuthenticatedPackage -PackagePath $PackagePath -ExpectedSha256 $PackageSha256 -Destination $staging
  Assert-ArTrustedPackageManifest -Root $staging -InstallRoot $InstallRoot -CandidateCodeSha $CandidateCodeSha `
    -AuthorityCommit $AuthorityCommit -OperatorSid $OperatorSid -ControlRoot $ControlRoot | Out-Null
  Set-ArTrustedDeviationAuthorization -Root $staging
  Set-ArTrustedRootAcl -Root $staging -OperatorSid $OperatorSid
  Assert-ArTrustedRootAcl -Root $staging -OperatorSid $OperatorSid
  Write-ArMutationIntent -Action 'PUBLISH_PROTECTED_ROOT' -TargetPath $InstallRoot
  Move-Item -LiteralPath $staging -Destination $InstallRoot -ErrorAction Stop
  $installed = $true
  Assert-ArTrustedRootAcl -Root $InstallRoot -OperatorSid $OperatorSid
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

  $piPremutation = Invoke-ArTrustedPiIdleCheck -Phase 'immediate pre-mutation'
  [IO.File]::WriteAllText(
    (Join-Path $script:executionRoot 'pi-immediate-pre-mutation.json'),
    (($piPremutation | ConvertTo-Json -Depth 5 -Compress) + "`n"),
    [Text.UTF8Encoding]::new($false)
  )

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
  $taskSddlSeal = Join-Path $InstallRoot 'installed-task-sddl-semantic.sha256'
  $sealStream = [IO.File]::Open($taskSddlSeal,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {
    $sealBytes = [Text.Encoding]::ASCII.GetBytes((Get-ArTrustedSddlSemanticSha256 $installedTaskSddl) + "`n")
    $sealStream.Write($sealBytes,0,$sealBytes.Length)
    $sealStream.Flush($true)
  } finally {
    $sealStream.Dispose()
  }
  Set-ArTrustedRootAcl -Root $InstallRoot -OperatorSid $OperatorSid
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
  Assert-ArTrustedRootAcl -Root $InstallRoot -OperatorSid $OperatorSid

  Enter-ArTrustedBootstrapGate
  Write-ArMutationIntent -Action 'ENABLE_PRODUCTION_TASK_WITHOUT_START' -TargetPath $TaskName
  Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
  Assert-ArTrustedTask -TaskName $TaskName -LauncherPath $launcher -InstallRoot $InstallRoot -OperatorSid $OperatorSid -Enabled $true | Out-Null
  $installedXml = Join-Path $script:executionRoot 'installed-task.xml'
  [IO.File]::WriteAllBytes($installedXml, (Get-ArTrustedTaskXmlBytes $TaskName))
  $installedSddl = Get-ArTrustedTaskSddl $TaskName
  if ($installedSddl -cne $installedTaskSddl) { throw 'Installed task SDDL changed after activation.' }
  [IO.File]::WriteAllText((Join-Path $script:executionRoot 'installed-task.sddl'), $installedSddl, [Text.UTF8Encoding]::new($false))
  $activeValidation = Invoke-ArTrustedActiveControlValidation
  [IO.File]::WriteAllText((Join-Path $script:executionRoot 'active-control-validation.json'), (($activeValidation | ConvertTo-Json -Depth 8 -Compress) + "`n"), [Text.UTF8Encoding]::new($false))
  $catalogAfter = Assert-ArTrustedCatalogBaseline @catalogArguments
  [IO.File]::WriteAllText((Join-Path $script:executionRoot 'post-bootstrap-catalog.json'), (($catalogAfter | ConvertTo-Json -Depth 8 -Compress) + "`n"), [Text.UTF8Encoding]::new($false))
  $terminalQuiescence = Assert-ArTrustedBackupQuiescence -RequireReadyTask
  $terminalQuiescence['bootstrap_gate_held'] = $true
  [IO.File]::WriteAllText((Join-Path $script:executionRoot 'terminal-quiescence.json'), (($terminalQuiescence | ConvertTo-Json -Depth 5 -Compress) + "`n"), [Text.UTF8Encoding]::new($false))
  $result = Write-ArTrustedResult -Result 'PASS' -ErrorText $null -Detail @{
    install_root = $InstallRoot; installed_task_xml_sha256 = Get-ArTrustedSha256 $installedXml
    installed_task_sddl_sha256 = Get-ArTrustedTextSha256 $installedSddl; probe_last_result = $probeInfo.LastTaskResult
    bootstrap_gate_held = $true; installed_task_sddl_semantic_sha256 = Get-ArTrustedSddlSemanticSha256 $installedSddl
  }
  Publish-ArTrustedBootstrapReadiness -ResultPath $result | Out-Null
  Get-Content -LiteralPath $result -Raw
} catch {
  $failure = $_.Exception.Message
  $rollbackErrors = New-Object Collections.Generic.List[string]
  $rollbackMayMutate = $true
  if ($probeRegistered) {
    try {
      Stop-ArTrustedProbeAndAwait
      Write-ArMutationIntent -Action 'ROLLBACK_REMOVE_PROBE' -TargetPath $probeName
      Unregister-ScheduledTask -TaskName $probeName -Confirm:$false -ErrorAction Stop
      $probeRegistered = $false
    } catch {
      $rollbackErrors.Add("probe cleanup: $($_.Exception.Message)")
      $rollbackMayMutate = $false
      $rollbackErrors.Add('task/control/root rollback withheld because probe quiescence was not proven')
    }
  }
  if ($rollbackMayMutate -and $controlChanged) {
    try {
      Write-ArMutationIntent -Action 'ROLLBACK_RESTORE_CONTROL' -TargetPath $ControlRoot
      Restore-ArTrustedControlRootAtomic -ControlRoot $ControlRoot -Prestate $controlPrestate `
        -EvidenceRoot $script:executionRoot -OperatorSid $OperatorSid -ControlSddl $controlSddl `
        -ExpectedControlSddlSha256 $controlSddlSemanticSha256
    } catch { $rollbackErrors.Add("control restore: $($_.Exception.Message)") }
  }
  if ($rollbackMayMutate -and $mutated) {
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
  foreach ($path in $(if ($rollbackMayMutate) { @($staging,$InstallRoot) } else { @() })) {
    if (Test-Path -LiteralPath $path) {
      try {
        $destination = Join-Path $script:executionRoot ('failed-protected-root-' + [guid]::NewGuid().ToString('N'))
        Write-ArMutationIntent -Action 'ROLLBACK_QUARANTINE_NEW_ROOT' -TargetPath $path
        Move-Item -LiteralPath $path -Destination $destination -ErrorAction Stop
        Set-ArTrustedRootAcl -Root $destination -OperatorSid $OperatorSid
        Assert-ArTrustedRootAcl -Root $destination -OperatorSid $OperatorSid
      } catch { $rollbackErrors.Add("root quarantine $path`: $($_.Exception.Message)") }
    }
  }
  try { Assert-ArTrustedCatalogBaseline @catalogArguments | Out-Null }
  catch { $rollbackErrors.Add("catalog baseline: $($_.Exception.Message)") }
  $outcome = if ($rollbackErrors.Count -eq 0) { 'ROLLED_BACK' } else { 'FAIL' }
  $message = if ($rollbackErrors.Count -eq 0) { $failure } else { "$failure; rollback failures: $($rollbackErrors -join '; ')" }
  Write-ArTrustedResult -Result $outcome -ErrorText $message -Detail @{} | Out-Null
  throw $message
} finally {
  Exit-ArTrustedBootstrapGate
}
