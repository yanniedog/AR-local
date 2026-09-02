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
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$PlanRawSha256,
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
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$SshBoundarySha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$EvidenceBoundarySha256,
  [Parameter(Mandatory = $true)][string]$PreExecutionManifestPath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$PreExecutionManifestSha256,
  [Parameter(Mandatory = $true)][string]$SshIdentityPath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$SshIdentitySha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$SshExecutableSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$')][string]$PiHost,
  [ValidateSet('pi')][string]$PiUser = 'pi',
  [ValidateRange(22,22)][int]$PiPort = 22
)
$ErrorActionPreference = 'Stop'
$script:authorizedDeviations = @()
$script:deviationAuthorization = $null
$script:bootstrapGate = $null
$script:bootstrapGateName = 'Global\ARLocalTrustedBootstrapGate'
$script:trustedSshConfig = $null
$script:trustedSshEndpoint = $null
$sshContractArguments = @{ HostName=$PiHost; UserName=$PiUser; Port=$PiPort; SshSha256=$SshExecutableSha256; IdentitySha256=$SshIdentitySha256 }
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
$sshBoundaryPath = Join-Path $PSScriptRoot 'install_laptop_backup_trusted_dispatcher_ssh.ps1'
. (Read-ArTrustedScriptBlock -Path $sshBoundaryPath -ExpectedSha256 $SshBoundarySha256)
$evidenceBoundaryPath = Join-Path $PSScriptRoot 'install_laptop_backup_trusted_dispatcher_evidence.ps1'
. (Read-ArTrustedScriptBlock -Path $evidenceBoundaryPath -ExpectedSha256 $EvidenceBoundarySha256)

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
  if ($null -eq $script:trustedSshConfig -or $null -eq $script:trustedSshEndpoint) { throw 'Protected SSH configuration is not authenticated.' }
  $config = $script:trustedSshConfig
  $lines = @(
    'set -eu','cd /srv/ar-local/AR-local',
    ('test "$(git rev-parse HEAD)" = ''{0}''' -f $ProtectedCodeSha),
    'test -z "$(git status --porcelain=v1)"',
    '! systemctl is-active --quiet ar-local-daily.service',
    'test ! -e /srv/ar-local/data/state/daily-ingest.lock',
    'curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest >/dev/null',
    'echo AR_PI_PREFLIGHT_PASS'
  )
  $result = Invoke-ArTrustedSshScript -SshPath ([string]$config.ssh_path) -HostName $script:trustedSshEndpoint -LogicalHost ([string]$config.ssh_logical_host) `
    -UserName ([string]$config.ssh_user) -Port ([int]$config.ssh_port) -IdentityPath ([string]$config.ssh_identity_path) `
    -KnownHostsPath ([string]$config.ssh_known_hosts_path) -Script (($lines -join "`n") + "`n")
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
  Assert-ArTrustedSshConfiguration -Config $trustedConfig @sshContractArguments
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
  Assert-ArTrustedPlainPath $Path | Out-Null
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

function Prepare-ArTrustedBootstrapPublication {
  $fixedResult = Join-Path $InstallRoot 'bootstrap-result.json'
  $pendingResult = $fixedResult + '.pending'
  $readyMarker = Join-Path $InstallRoot 'bootstrap.ready'
  $pendingReady = $readyMarker + '.pending'
  if ((Test-Path -LiteralPath $fixedResult) -and (Test-Path -LiteralPath $pendingResult)) {
    throw 'Durable bootstrap result and its pending sibling both exist.'
  }
  if (-not (Test-Path -LiteralPath $fixedResult) -and (Test-Path -LiteralPath $pendingResult)) {
    try {
      Assert-ArTrustedBootstrapResultIdentity -Path $pendingResult | Out-Null
      Write-ArMutationIntent -Action 'RECOVER_DURABLE_BOOTSTRAP_RESULT' -TargetPath $fixedResult
      Move-ArTrustedFileWriteThrough -Source $pendingResult -Destination $fixedResult
    } catch {
      $recovered = Join-Path $script:executionRoot ('incomplete-bootstrap-result-' + [guid]::NewGuid().ToString('N') + '.json')
      Write-ArMutationIntent -Action 'QUARANTINE_INCOMPLETE_BOOTSTRAP_RESULT' -TargetPath $pendingResult
      Move-Item -LiteralPath $pendingResult -Destination $recovered -ErrorAction Stop
      Set-ArTrustedRootAcl -Root $script:executionRoot -OperatorSid $OperatorSid
    }
  }
  if (Test-Path -LiteralPath $fixedResult) {
    Assert-ArTrustedBootstrapResultIdentity -Path $fixedResult | Out-Null
  }
  if ((Test-Path -LiteralPath $readyMarker) -and -not (Test-Path -LiteralPath $fixedResult -PathType Leaf)) {
    throw 'Protected bootstrap readiness exists without its durable PASS result.'
  }
  if ((Test-Path -LiteralPath $readyMarker) -and (Test-Path -LiteralPath $pendingReady)) {
    throw 'Bootstrap readiness and its pending sibling both exist.'
  }
  if (Test-Path -LiteralPath $fixedResult) {
    $expectedReady = "AR_LOCAL_TRUSTED_BOOTSTRAP_READY_V2`n$(Get-ArTrustedSha256 $fixedResult)`n"
    if (-not (Test-Path -LiteralPath $readyMarker) -and (Test-Path -LiteralPath $pendingReady)) {
      Assert-ArTrustedPlainPath $pendingReady | Out-Null
      if ([IO.File]::ReadAllText($pendingReady,[Text.Encoding]::ASCII) -ceq $expectedReady) {
        Write-ArMutationIntent -Action 'RECOVER_TERMINAL_BOOTSTRAP_READINESS' -TargetPath $readyMarker
        Move-ArTrustedFileWriteThrough -Source $pendingReady -Destination $readyMarker
      } else {
        $recovered = Join-Path $script:executionRoot ('incomplete-bootstrap-readiness-' + [guid]::NewGuid().ToString('N'))
        Write-ArMutationIntent -Action 'QUARANTINE_INCOMPLETE_BOOTSTRAP_READINESS' -TargetPath $pendingReady
        Move-Item -LiteralPath $pendingReady -Destination $recovered -ErrorAction Stop
        Set-ArTrustedRootAcl -Root $script:executionRoot -OperatorSid $OperatorSid
      }
    }
    if (Test-Path -LiteralPath $readyMarker) {
      Assert-ArTrustedPlainPath $readyMarker | Out-Null
      if ([IO.File]::ReadAllText($readyMarker,[Text.Encoding]::ASCII) -cne $expectedReady) {
        throw 'Installed bootstrap readiness marker or durable-result binding is invalid.'
      }
    }
  } elseif (Test-Path -LiteralPath $pendingReady) {
    throw 'Pending bootstrap readiness exists without a durable PASS result.'
  }
  if (-not (Test-Path -LiteralPath $fixedResult)) {
    Write-ArMutationIntent -Action 'PUBLISH_DURABLE_BOOTSTRAP_RESULT' -TargetPath $fixedResult
  }
  if (-not (Test-Path -LiteralPath $readyMarker)) {
    Write-ArMutationIntent -Action 'PUBLISH_TERMINAL_BOOTSTRAP_READINESS' -TargetPath $readyMarker
  }
  Set-ArTrustedRootAcl -Root $InstallRoot -OperatorSid $OperatorSid
  Assert-ArTrustedRootAcl -Root $InstallRoot -OperatorSid $OperatorSid
}

function Publish-ArTrustedBootstrapReadiness {
  param([Parameter(Mandatory = $true)][string]$ResultPath)
  Assert-ArTrustedBootstrapResultIdentity -Path $ResultPath | Out-Null
  $fixedResult = Join-Path $InstallRoot 'bootstrap-result.json'
  $pendingResult = $fixedResult + '.pending'
  $readyMarker = Join-Path $InstallRoot 'bootstrap.ready'
  $pendingReady = $readyMarker + '.pending'
  if ((Test-Path -LiteralPath $readyMarker) -and -not (Test-Path -LiteralPath $fixedResult -PathType Leaf)) {
    throw 'Protected bootstrap readiness exists without its durable PASS result.'
  }
  if (-not (Test-Path -LiteralPath $fixedResult)) {
    $source = [IO.File]::Open($ResultPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $destination = [IO.File]::Open($pendingResult,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {
      $source.CopyTo($destination)
      $destination.Flush($true)
    } finally {
      $destination.Dispose()
      $source.Dispose()
    }
    Move-ArTrustedFileWriteThrough -Source $pendingResult -Destination $fixedResult
  }
  Assert-ArTrustedBootstrapResultIdentity -Path $fixedResult | Out-Null
  if (Test-Path -LiteralPath $pendingResult) { throw 'Pending bootstrap result remains after publication.' }
  $fixedResultSha256 = Get-ArTrustedSha256 $fixedResult
  $expectedReady = "AR_LOCAL_TRUSTED_BOOTSTRAP_READY_V2`n$fixedResultSha256`n"
  if (-not (Test-Path -LiteralPath $readyMarker)) {
    $readyStream = [IO.File]::Open($pendingReady,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {
      $readyBytes = [Text.Encoding]::ASCII.GetBytes($expectedReady)
      $readyStream.Write($readyBytes,0,$readyBytes.Length)
      $readyStream.Flush($true)
    } finally {
      $readyStream.Dispose()
    }
    Move-ArTrustedFileWriteThrough -Source $pendingReady -Destination $readyMarker
  }
  if (Test-Path -LiteralPath $pendingReady) { throw 'Pending bootstrap readiness remains after publication.' }
  Assert-ArTrustedPlainPath $readyMarker | Out-Null
  if ([IO.File]::ReadAllText($readyMarker,[Text.Encoding]::ASCII) -cne $expectedReady) {
    throw 'Installed bootstrap readiness marker or durable-result binding is invalid.'
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
    -AllowedRuntimeFiles @('ssh\id','bootstrap.ready','bootstrap.ready.pending','bootstrap-result.json','bootstrap-result.json.pending','installed-task-sddl-semantic.sha256') | Out-Null
  Set-ArTrustedDeviationAuthorization -Root $InstallRoot
  Assert-ArTrustedRootAcl -Root $InstallRoot -OperatorSid $OperatorSid
  $trustedConfig = Assert-ArTrustedChildConfiguration -Root $InstallRoot -ControlRoot $ControlRoot
  Assert-ArTrustedSshConfiguration -Config $trustedConfig @sshContractArguments
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

function Get-ArTrustedPriorTaskState {
  param([Parameter(Mandatory = $true)][string]$EvidencePrefix)
  $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $info = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
  if ($task.State.ToString() -notin @('Ready','Disabled') -or
      $task.Principal.LogonType.ToString() -ne 'S4U' -or $task.Principal.RunLevel.ToString() -ne 'Limited') {
    throw 'Existing production task cannot be authenticated for bootstrap recovery.'
  }
  $xml = Export-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $xmlPath = Join-Path $script:executionRoot ($EvidencePrefix + '-task.xml')
  [IO.File]::WriteAllBytes($xmlPath, (Get-ArTrustedTaskXmlBytes $TaskName))
  $sddl = Get-ArTrustedTaskSddl $TaskName
  $sddlPath = Join-Path $script:executionRoot ($EvidencePrefix + '-task.sddl')
  [IO.File]::WriteAllText($sddlPath, $sddl, [Text.UTF8Encoding]::new($false))
  [pscustomobject]@{
    task=$task; info=$info; xml=$xml; sddl=$sddl; xml_path=$xmlPath; sddl_path=$sddlPath
    matches_authorized_prestate=(
      (Get-ArTrustedSha256 $xmlPath) -ceq $ExpectedOldTaskXmlSha256 -and
      (Get-ArTrustedTextSha256 $sddl) -ceq $ExpectedOldTaskSddlSha256 -and
      (Get-ArTrustedSddlSemanticSha256 $sddl) -ceq $ExpectedOldTaskSddlSemanticSha256 -and
      $task.State.ToString() -ceq 'Ready' -and $task.Settings.Enabled -and
      $info.LastTaskResult -eq $ExpectedOldTaskLastResult
    )
  }
}

function Read-ArTrustedInterruptedBootstrap {
  $markerPath = Join-Path $InstallRoot 'bootstrap.installing.json'
  if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) { return $null }
  Assert-ArTrustedPlainPath $markerPath | Out-Null
  $marker = Get-Content -LiteralPath $markerPath -Raw -ErrorAction Stop | ConvertFrom-Json
  $fields = @(
    'authority_commit','candidate_code_sha','control_root','control_sddl_semantic_sha256','evidence_execution_id',
    'expected_old_task_sddl_semantic_sha256','expected_old_task_sddl_sha256','expected_old_task_xml_sha256',
    'handoff_sha256','install_root','operator_sid','package_sha256','plan_git_commit','plan_sha256',
    'pre_execution_manifest_sha256','schema_version'
  )
  if (@(Compare-Object $fields @($marker.PSObject.Properties.Name | Sort-Object)).Count -ne 0 -or
      $marker.schema_version -ne 1 -or [string]$marker.authority_commit -cne $AuthorityCommit -or
      [string]$marker.candidate_code_sha -cne $CandidateCodeSha -or [string]$marker.handoff_sha256 -cne $HandoffSha256 -or
      [string]$marker.operator_sid -cne $OperatorSid -or [string]$marker.package_sha256 -cne $PackageSha256 -or
      [string]$marker.plan_git_commit -cne $PlanGitCommit -or [string]$marker.plan_sha256 -cne $PlanSha256 -or
      [string]$marker.pre_execution_manifest_sha256 -cne $PreExecutionManifestSha256 -or
      [string]$marker.expected_old_task_xml_sha256 -cne $ExpectedOldTaskXmlSha256 -or
      [string]$marker.expected_old_task_sddl_sha256 -cne $ExpectedOldTaskSddlSha256 -or
      [string]$marker.expected_old_task_sddl_semantic_sha256 -cne $ExpectedOldTaskSddlSemanticSha256 -or
      [IO.Path]::GetFullPath([string]$marker.install_root) -cne [IO.Path]::GetFullPath($InstallRoot) -or
      [IO.Path]::GetFullPath([string]$marker.control_root) -cne [IO.Path]::GetFullPath($ControlRoot) -or
      [string]$marker.evidence_execution_id -notmatch '^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{32}$' -or
      [string]$marker.control_sddl_semantic_sha256 -notmatch '^[0-9a-f]{64}$') {
    throw 'Interrupted-bootstrap recovery marker identity is invalid.'
  }
  $priorRoot = Join-Path $EvidenceRoot ([string]$marker.evidence_execution_id)
  if (-not (Test-Path -LiteralPath $priorRoot -PathType Container) -or
      [IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($priorRoot)) -cne [IO.Path]::GetFullPath($EvidenceRoot)) {
    throw 'Interrupted-bootstrap evidence root is invalid.'
  }
  Assert-ArTrustedRootAcl -Root $priorRoot -OperatorSid $OperatorSid
  $priorManifest = Join-Path $priorRoot 'pre-execution-manifest.json'
  $priorTaskXml = Join-Path $priorRoot 'pre-bootstrap-task.xml'
  $priorTaskSddl = Join-Path $priorRoot 'pre-bootstrap-task.sddl'
  $priorControlSddl = Join-Path $priorRoot 'pre-bootstrap-control.sddl'
  $journalPath = Join-Path $priorRoot 'mutation-journal.jsonl'
  foreach ($path in @($priorManifest,$priorTaskXml,$priorTaskSddl,$priorControlSddl,$journalPath)) {
    Assert-ArTrustedPlainPath $path | Out-Null
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Interrupted-bootstrap evidence is absent: $path" }
  }
  if ((Get-ArTrustedSha256 $priorManifest) -cne $PreExecutionManifestSha256 -or
      (Get-ArTrustedSha256 $priorTaskXml) -cne $ExpectedOldTaskXmlSha256 -or
      (Get-ArTrustedTextSha256 ([IO.File]::ReadAllText($priorTaskSddl))) -cne $ExpectedOldTaskSddlSha256 -or
      (Get-ArTrustedSddlSemanticSha256 ([IO.File]::ReadAllText($priorTaskSddl))) -cne $ExpectedOldTaskSddlSemanticSha256 -or
      (Get-ArTrustedSddlBinarySha256 ([IO.File]::ReadAllText($priorControlSddl))) -cne [string]$marker.control_sddl_semantic_sha256) {
    throw 'Interrupted-bootstrap recovery evidence hashes are invalid.'
  }
  $journal = @([IO.File]::ReadAllLines($journalPath,[Text.UTF8Encoding]::new($false)) | Where-Object { $_ } | ForEach-Object { $_ | ConvertFrom-Json })
  $published = @($journal | Where-Object { $_.action -ceq 'PUBLISH_PROTECTED_ROOT' -and [IO.Path]::GetFullPath([string]$_.target) -ceq [IO.Path]::GetFullPath($InstallRoot) })
  if ($published.Count -ne 1) { throw 'Interrupted-bootstrap journal lacks one authenticated root publication.' }
  [pscustomobject]@{
    marker=$marker; marker_path=$markerPath; prior_root=$priorRoot; task_xml=$priorTaskXml; task_sddl=$priorTaskSddl
    control_sddl=$priorControlSddl; control_prestate=(Join-Path $priorRoot 'dispatcher-control-prestate')
    journal=$journal
  }
}

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -or $identity.User.Value -cne $OperatorSid) { throw 'Trusted bootstrap requires the authorised elevated operator.' }
$hobart = [TimeZoneInfo]::FindSystemTimeZoneById('Tasmania Standard Time')
$local = [TimeZoneInfo]::ConvertTime([DateTimeOffset]::UtcNow,$hobart)
if ($local.TimeOfDay -lt [TimeSpan]::FromHours(3.5) -or $local.TimeOfDay -ge [TimeSpan]::FromHours(22)) { throw 'Trusted bootstrap is outside the D-006 daylight window.' }
if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw 'Trusted package is absent.' }
if (-not (Test-Path -LiteralPath $PreExecutionManifestPath -PathType Leaf)) { throw 'Pre-execution manifest is absent.' }
if (-not (Test-Path -LiteralPath $SshIdentityPath -PathType Leaf)) { throw 'SSH identity source is absent.' }
foreach ($path in @($Target,$ControlRoot)) { if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw "Required directory is absent: $path" } }
foreach ($path in @($PackagePath,$PreExecutionManifestPath,$SshIdentityPath,$Target,$ControlRoot,$RecoveryImage,([IO.Path]::GetDirectoryName($InstallRoot)),([IO.Path]::GetDirectoryName($EvidenceRoot)))) { Assert-ArTrustedPlainPath $path | Out-Null }
$sshExecutable = "$env:SystemRoot\System32\OpenSSH\ssh.exe"
Assert-ArTrustedSystemSshExecutable -Path $sshExecutable -ExpectedSha256 $SshExecutableSha256
$expectedControl = Join-Path ([IO.Path]::GetFullPath($Target)) 'dispatcher-control'
if ([IO.Path]::GetFullPath($ControlRoot) -cne [IO.Path]::GetFullPath($expectedControl)) { throw 'ControlRoot must be exactly Target\dispatcher-control.' }
$programFilesRoot = [IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\') + '\'
$installFull = [IO.Path]::GetFullPath($InstallRoot)
if (-not $installFull.StartsWith($programFilesRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'InstallRoot must be below Program Files.' }
$evidenceFull = [IO.Path]::GetFullPath($EvidenceRoot)
if (-not $evidenceFull.StartsWith($programFilesRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'EvidenceRoot must be below Program Files.' }
$identitySourceFull = [IO.Path]::GetFullPath($SshIdentityPath)
foreach ($sensitiveRoot in @($installFull,$evidenceFull)) {
  if ($identitySourceFull -eq $sensitiveRoot -or $identitySourceFull.StartsWith($sensitiveRoot.TrimEnd('\') + '\',[StringComparison]::OrdinalIgnoreCase)) { throw 'SSH identity source must remain outside install and evidence roots.' }
}
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
  protected_code_sha=$ProtectedCodeSha; plan_git_commit=$PlanGitCommit; plan_sha256=$PlanSha256; plan_raw_sha256=$PlanRawSha256; handoff_sha256=$HandoffSha256
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
  installer_sha256=$InstallerSha256; core_sha256=$CoreSha256; ssh_boundary_sha256=$SshBoundarySha256; evidence_boundary_sha256=$EvidenceBoundarySha256
  # A manifest cannot contain its own SHA-256. D-012 therefore binds every
  # non-self invocation value here, while the separately authorized outer UAC
  # command supplies the exact manifest SHA-256 that Read-ArTrusted... verifies
  # under one locked stream and Write-ArTrustedResult preserves.
  pre_execution_manifest_path=[IO.Path]::GetFullPath($PreExecutionManifestPath); pre_execution_manifest_sha256='<SELF_SHA256>'
  pi_host=$PiHost; pi_user=$PiUser; pi_port=$PiPort
  ssh_identity_path=[IO.Path]::GetFullPath($SshIdentityPath); ssh_identity_sha256=$SshIdentitySha256; ssh_executable_sha256=$SshExecutableSha256
}
$invocationContractSha256 = Get-ArTrustedInvocationContractSha256 $invocationParameters
$preExecution = Read-ArTrustedPreExecutionManifest -Path $PreExecutionManifestPath -ExpectedSha256 $PreExecutionManifestSha256
$expectedPreExecution = [ordered]@{
  schema_version = 1; plan_document_id = 'ARL-OPS-001'; plan_version = '1.5'; document_commit = $PlanGitCommit; task_name = $TaskName
  package_path = [IO.Path]::GetFullPath($PackagePath); package_sha256 = $PackageSha256
  install_root = $installFull; target = [IO.Path]::GetFullPath($Target); control_root = [IO.Path]::GetFullPath($ControlRoot)
  recovery_image = [IO.Path]::GetFullPath($RecoveryImage)
  evidence_root = $evidenceFull; principal = $Principal; operator = $Operator; operator_sid = $OperatorSid
  candidate_code_sha = $CandidateCodeSha; authority_commit = $AuthorityCommit; protected_code_sha = $ProtectedCodeSha
  plan_git_commit = $PlanGitCommit; plan_sha256 = $PlanSha256; plan_raw_sha256 = $PlanRawSha256; handoff_sha256 = $HandoffSha256
  expected_old_task_xml_sha256 = $ExpectedOldTaskXmlSha256; expected_old_task_sddl_sha256 = $ExpectedOldTaskSddlSha256
  expected_old_task_sddl_semantic_sha256 = $ExpectedOldTaskSddlSemanticSha256
  expected_old_task_last_result = $ExpectedOldTaskLastResult; installer_sha256 = $InstallerSha256; core_sha256 = $CoreSha256
  ssh_boundary_sha256 = $SshBoundarySha256; evidence_boundary_sha256 = $EvidenceBoundarySha256
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
  pi_host = $PiHost; pi_user = $PiUser; pi_port = $PiPort
  ssh_identity_path = [IO.Path]::GetFullPath($SshIdentityPath); ssh_identity_sha256 = $SshIdentitySha256; ssh_executable_sha256 = $SshExecutableSha256
}
$requiredPreExecutionEvidence = @($PackagePath,$PSCommandPath,$corePath,$sshBoundaryPath,$evidenceBoundaryPath,$SshIdentityPath)
Assert-ArTrustedPreExecutionManifest -Manifest $preExecution -Expected $expectedPreExecution `
  -RequiredEvidencePaths $requiredPreExecutionEvidence
$actualBootstrapCommand = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").CommandLine
Assert-ArTrustedInstallerCommandEvidence -Manifest $preExecution -ManifestSha256 $PreExecutionManifestSha256 `
  -ActualProcessCommand $actualBootstrapCommand
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
[IO.File]::WriteAllText(
  (Join-Path $script:executionRoot 'pre-execution-observed.json'),
  (([ordered]@{
    invocation_contract_sha256=$invocationContractSha256; free_bytes=$freeBytes
    active_process_count=$active.Count; residue_count=$residue.Count; pi_status='PENDING_AUTHENTICATED_PROTECTED_PACKAGE'
    task_expected_last_result=$ExpectedOldTaskLastResult; catalog=$catalogBaseline
    rollback_procedure='RESTORE_TASK_CONTROL_AND_QUARANTINE_V1'
  } | ConvertTo-Json -Depth 8 -Compress) + "`n"),
  [Text.UTF8Encoding]::new($false)
)
$preservedPreExecution = Join-Path $script:executionRoot 'pre-execution-manifest.json'
Copy-Item -LiteralPath $PreExecutionManifestPath -Destination $preservedPreExecution -ErrorAction Stop
if ((Get-ArTrustedSha256 $preservedPreExecution) -cne $PreExecutionManifestSha256) { throw 'Preserved pre-execution manifest changed.' }
Enter-ArTrustedBootstrapGate
try {
  Remove-ArTrustedOrphanedSshInputs -OperatorSid $OperatorSid
  Assert-ArTrustedShortQuarantineState -OperatorSid $OperatorSid | Out-Null

if (Test-Path -LiteralPath $InstallRoot) {
  try {
    $interrupted = Read-ArTrustedInterruptedBootstrap
    if ($null -eq $interrupted) {
      $installedState = Assert-ArExactInstalledBootstrap
      $alreadyQuiescence = Assert-ArTrustedBackupQuiescence -RequireReadyTask
      Prepare-ArTrustedBootstrapPublication
      $already = Write-ArTrustedResult -Result 'PASS' -ErrorText $null -Detail @{
        mode='ALREADY_INSTALLED'; install_root=$InstallRoot; bootstrap_gate_held=$true
        terminal_quiescence=$alreadyQuiescence; recovered_incomplete_readiness=(-not $installedState.readiness_present)
      }
      Publish-ArTrustedBootstrapReadiness -ResultPath $already | Out-Null
      Get-Content -LiteralPath $already -Raw
      exit 0
    }

    Assert-ArTrustedPackageManifest -Root $InstallRoot -InstallRoot $InstallRoot -CandidateCodeSha $CandidateCodeSha `
      -AuthorityCommit $AuthorityCommit -OperatorSid $OperatorSid -ControlRoot $ControlRoot `
      -AllowedRuntimeFiles @('ssh\id','bootstrap.installing.json','installed-task-sddl-semantic.sha256','finalize.enabled') | Out-Null
    Set-ArTrustedDeviationAuthorization -Root $InstallRoot
    Assert-ArTrustedRootAcl -Root $InstallRoot -OperatorSid $OperatorSid
    $probes = @(Get-ScheduledTask -ErrorAction Stop | Where-Object { $_.TaskName -like 'AR-local trusted dispatcher probe *' })
    foreach ($probe in $probes) {
      Assert-ArTrustedProbeTask -TaskName $probe.TaskName -LauncherPath (Join-Path $InstallRoot 'launcher.exe') `
        -InstallRoot $InstallRoot -OperatorSid $OperatorSid | Out-Null
      if ($probe.State.ToString() -eq 'Running') {
        Write-ArMutationIntent -Action 'RECOVERY_STOP_INTERRUPTED_PROBE' -TargetPath $probe.TaskName
        Stop-ScheduledTask -TaskName $probe.TaskName -ErrorAction Stop
      }
      $probeDeadline = [DateTimeOffset]::Now.AddSeconds(30)
      do {
        Start-Sleep -Milliseconds 250
        $probeState = Get-ScheduledTask -TaskName $probe.TaskName -ErrorAction Stop
      } while ($probeState.State.ToString() -eq 'Running' -and [DateTimeOffset]::Now -lt $probeDeadline)
      if ($probeState.State.ToString() -eq 'Running') { throw 'Interrupted disposable probe did not stop.' }
      Write-ArMutationIntent -Action 'RECOVERY_REMOVE_INTERRUPTED_PROBE' -TargetPath $probe.TaskName
      Unregister-ScheduledTask -TaskName $probe.TaskName -Confirm:$false -ErrorAction Stop
    }
    $helpers = @(Get-CimInstance Win32_Process | Where-Object {
      $_.ProcessId -ne $PID -and $_.CommandLine -and
      $_.CommandLine -match 'laptop_backup_(scheduled|dispatcher|trusted_child)|laptop_pull_backup|run_laptop_backup|AR-local-backup-trusted-.*launcher\.exe'
    })
    if ($helpers.Count) { throw 'Interrupted-bootstrap helper process remains active.' }

    $journalActions = @($interrupted.journal | ForEach-Object { [string]$_.action })
    $controlMutationRecorded = @($journalActions | Where-Object {
      $_ -in @('ACTIVATE_DISPATCHER_MANIFEST','REGISTER_DISABLED_PRODUCTION_TASK','REGISTER_DISPOSABLE_PROBE',
        'START_DISPOSABLE_PROBE_ONLY','ENABLE_PRODUCTION_TASK_WITHOUT_START')
    }).Count -gt 0
    if ($controlMutationRecorded) {
      if (-not (Test-Path -LiteralPath $interrupted.control_prestate -PathType Container)) {
        throw 'Interrupted-bootstrap control mutation lacks protected prestate.'
      }
      $priorControlSddl = [IO.File]::ReadAllText($interrupted.control_sddl)
      Write-ArMutationIntent -Action 'RECOVERY_RESTORE_CONTROL_PRESTATE' -TargetPath $ControlRoot
      Restore-ArTrustedControlRootAtomic -ControlRoot $ControlRoot -Prestate $interrupted.control_prestate `
        -EvidenceRoot $script:executionRoot -OperatorSid $OperatorSid -ControlSddl $priorControlSddl `
        -ExpectedControlSddlSha256 ([string]$interrupted.marker.control_sddl_semantic_sha256)
    }

    $currentTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
    if ($currentTask.State.ToString() -eq 'Running') {
      Write-ArMutationIntent -Action 'RECOVERY_STOP_INTERRUPTED_PRODUCTION_TASK' -TargetPath $TaskName
      Stop-ScheduledTask -TaskName $TaskName -ErrorAction Stop
      $taskDeadline = [DateTimeOffset]::Now.AddSeconds(30)
      do {
        Start-Sleep -Milliseconds 250
        $currentTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
      } while ($currentTask.State.ToString() -eq 'Running' -and [DateTimeOffset]::Now -lt $taskDeadline)
      if ($currentTask.State.ToString() -eq 'Running') { throw 'Interrupted production task did not stop.' }
    }
    $observedPrior = Get-ArTrustedPriorTaskState -EvidencePrefix 'interrupted-recovery-observed'
    if (-not $observedPrior.matches_authorized_prestate) {
      Write-ArMutationIntent -Action 'RECOVERY_RESTORE_PRODUCTION_TASK_PRESTATE' -TargetPath $TaskName
      Restore-ArTrustedPriorTask -TaskName $TaskName `
        -TaskXml (Get-Content -LiteralPath $interrupted.task_xml -Raw -ErrorAction Stop) `
        -TaskSddl ([IO.File]::ReadAllText($interrupted.task_sddl))
    }
    $restoredPrior = Get-ArTrustedPriorTaskState -EvidencePrefix 'interrupted-recovery-restored'
    if (-not $restoredPrior.matches_authorized_prestate) { throw 'Interrupted-bootstrap task prestate was not restored exactly.' }
    Assert-ArTrustedCatalogBaseline @catalogArguments | Out-Null
    Write-ArMutationIntent -Action 'RECOVERY_QUARANTINE_INTERRUPTED_ROOT' -TargetPath $InstallRoot
    $quarantine = Move-ArTrustedFailedRootToQuarantine -Path $InstallRoot -OperatorSid $OperatorSid
    [IO.File]::WriteAllText(
      (Join-Path $script:executionRoot 'interrupted-recovery.json'),
      (([ordered]@{
        result='PASS'; prior_execution_root=$interrupted.prior_root
        quarantined_root=$quarantine.quarantine_path; quarantine_record=$quarantine.record_path
        bootstrap_gate_held=$true
      } | ConvertTo-Json -Compress) + "`n"),
      [Text.UTF8Encoding]::new($false)
    )
  } catch {
    Write-ArTrustedResult -Result 'BLOCKED' -ErrorText $_.Exception.Message -Detail @{ mode='INSTALLED_OR_INTERRUPTED_RECOVERY_REJECTED' } | Out-Null
    throw
  }
}

# Exact installed-state recovery is intentionally available after the short
# bootstrap authorization expires.  A new installation, however, requires the
# same manifest to be fresh immediately before any staging or task mutation.
Assert-ArTrustedPreExecutionManifest -Manifest $preExecution -Expected $expectedPreExecution `
  -RequiredEvidencePaths $requiredPreExecutionEvidence -RequireFresh
Assert-ArTrustedInstallerCommandEvidence -Manifest $preExecution -ManifestSha256 $PreExecutionManifestSha256 `
  -ActualProcessCommand $actualBootstrapCommand

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

$staging = Join-Path $env:ProgramFiles ('ARLBS-' + [guid]::NewGuid().ToString('N'))
Assert-ArTrustedPlainPath $staging | Out-Null
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
  Install-ArTrustedSshIdentity -SourcePath $SshIdentityPath -ExpectedSha256 $SshIdentitySha256 `
    -DestinationPath (Join-Path $staging 'ssh\id') -OperatorSid $OperatorSid
  Set-ArTrustedDeviationAuthorization -Root $staging
  $stagingConfig = Assert-ArTrustedChildConfiguration -Root $staging -ControlRoot $ControlRoot
  $authorityPrepublication = Assert-ArTrustedAuthorityMain -GitPath ([string]$stagingConfig.git_path) -Phase 'protected-package prepublication'
  [IO.File]::WriteAllText(
    (Join-Path $script:executionRoot 'authority-prepublication.json'),
    (($authorityPrepublication | ConvertTo-Json -Compress) + "`n"),
    [Text.UTF8Encoding]::new($false)
  )
  $installingMarker = Join-Path $staging 'bootstrap.installing.json'
  $installingRecord = [ordered]@{
    schema_version=1; plan_git_commit=$PlanGitCommit; plan_sha256=$PlanSha256; authority_commit=$AuthorityCommit
    handoff_sha256=$HandoffSha256; candidate_code_sha=$CandidateCodeSha; package_sha256=$PackageSha256
    operator_sid=$OperatorSid; install_root=[IO.Path]::GetFullPath($InstallRoot); control_root=[IO.Path]::GetFullPath($ControlRoot)
    evidence_execution_id=$executionId; pre_execution_manifest_sha256=$PreExecutionManifestSha256
    expected_old_task_xml_sha256=$ExpectedOldTaskXmlSha256; expected_old_task_sddl_sha256=$ExpectedOldTaskSddlSha256
    expected_old_task_sddl_semantic_sha256=$ExpectedOldTaskSddlSemanticSha256
    control_sddl_semantic_sha256=$controlSddlSemanticSha256
  }
  $installingBytes = [Text.UTF8Encoding]::new($false).GetBytes(($installingRecord | ConvertTo-Json -Compress) + "`n")
  $installingStream = [IO.File]::Open($installingMarker,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {
    $installingStream.Write($installingBytes,0,$installingBytes.Length)
    $installingStream.Flush($true)
  } finally {
    $installingStream.Dispose()
  }
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
  Assert-ArTrustedSshConfiguration -Config $trustedConfig @sshContractArguments
  $toolPaths = @($trustedConfig.git_path,$trustedConfig.ssh_path,$trustedConfig.scp_path,$trustedConfig.whoami_path)
  $env:PATH = (($toolPaths | ForEach-Object { [IO.Path]::GetDirectoryName([string]$_) } | Select-Object -Unique) -join ';')
  $env:GIT_CONFIG_COUNT = '2'; $env:GIT_CONFIG_KEY_0 = 'safe.directory'; $env:GIT_CONFIG_VALUE_0 = [string]$trustedConfig.receiver_path
  $env:GIT_CONFIG_KEY_1 = 'safe.directory'; $env:GIT_CONFIG_VALUE_1 = [string]$trustedConfig.authority_path; $env:GIT_CONFIG_GLOBAL = 'NUL'
  $env:AR_TRUSTED_ROOT = $InstallRoot; $env:GIT_OPTIONAL_LOCKS = '0'; $env:PYTHONNOUSERSITE = '1'; $env:PYTHONDONTWRITEBYTECODE = '1'
  & $python -B -s -E $dispatcher validate --control-root $ControlRoot --manifest $manifest
  if ($LASTEXITCODE -ne 0) { throw 'Protected dispatcher pre-mutation validation failed.' }

  $piPreflight = Invoke-ArTrustedPiIdleCheck -Phase 'protected-package preflight'
  [IO.File]::WriteAllText(
    (Join-Path $script:executionRoot 'pi-preflight.json'),
    (($piPreflight | ConvertTo-Json -Depth 5 -Compress) + "`n"),
    [Text.UTF8Encoding]::new($false)
  )
  $piPremutation = Invoke-ArTrustedPiIdleCheck -Phase 'immediate pre-mutation'
  [IO.File]::WriteAllText(
    (Join-Path $script:executionRoot 'pi-immediate-pre-mutation.json'),
    (($piPremutation | ConvertTo-Json -Depth 5 -Compress) + "`n"),
    [Text.UTF8Encoding]::new($false)
  )
  $authorityPremutation = Assert-ArTrustedAuthorityMain -GitPath ([string]$trustedConfig.git_path) -Phase 'immediate pre-mutation'
  [IO.File]::WriteAllText(
    (Join-Path $script:executionRoot 'authority-immediate-pre-mutation.json'),
    (($authorityPremutation | ConvertTo-Json -Compress) + "`n"),
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
      $probe.token_elevation -ne $false -or $probe.token_elevation_type -notin @('Default','Limited') -or
      $probe.token_has_restrictions -ne $true -or [int]$probe.integrity_rid -gt 8192 -or
      $probe.ssh_preflight -cne 'PASS' -or
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
  $publishedInstallingMarker = Join-Path $InstallRoot 'bootstrap.installing.json'
  Write-ArMutationIntent -Action 'REMOVE_INTERRUPTED_RECOVERY_MARKER' -TargetPath $publishedInstallingMarker
  Remove-Item -LiteralPath $publishedInstallingMarker -Force -ErrorAction Stop
  Set-ArTrustedRootAcl -Root $InstallRoot -OperatorSid $OperatorSid
  $terminalQuiescence = Assert-ArTrustedBackupQuiescence -RequireReadyTask
  $terminalQuiescence['bootstrap_gate_held'] = $true
  [IO.File]::WriteAllText((Join-Path $script:executionRoot 'terminal-quiescence.json'), (($terminalQuiescence | ConvertTo-Json -Depth 5 -Compress) + "`n"), [Text.UTF8Encoding]::new($false))
  Prepare-ArTrustedBootstrapPublication
  $result = Write-ArTrustedResult -Result 'PASS' -ErrorText $null -Detail @{
    install_root = $InstallRoot; installed_task_xml_sha256 = Get-ArTrustedSha256 $installedXml
    installed_task_sddl_sha256 = Get-ArTrustedTextSha256 $installedSddl; probe_last_result = $probeInfo.LastTaskResult
    bootstrap_gate_held = $true; installed_task_sddl_semantic_sha256 = Get-ArTrustedSddlSemanticSha256 $installedSddl
  }
  Publish-ArTrustedBootstrapReadiness -ResultPath $result | Out-Null
  Get-Content -LiteralPath $result -Raw
} catch {
  $failure = $_.Exception.Message
  try { Write-ArTrustedFailureObserved -Message $failure | Out-Null } catch {}
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
        Write-ArMutationIntent -Action 'ROLLBACK_QUARANTINE_NEW_ROOT' -TargetPath $path
        Move-ArTrustedFailedRootToQuarantine -Path $path -OperatorSid $OperatorSid | Out-Null
      } catch { $rollbackErrors.Add("root quarantine $path`: $($_.Exception.Message)") }
    }
  }
  try { Assert-ArTrustedCatalogBaseline @catalogArguments | Out-Null }
  catch { $rollbackErrors.Add("catalog baseline: $($_.Exception.Message)") }
  $outcome = if ($rollbackErrors.Count -eq 0) { 'ROLLED_BACK' } else { 'FAIL' }
  $message = if ($rollbackErrors.Count -eq 0) { $failure } else { "$failure; rollback failures: $($rollbackErrors -join '; ')" }
  Write-ArTrustedResult -Result $outcome -ErrorText $message -Detail @{} | Out-Null
  throw $message
}
} finally {
  Exit-ArTrustedBootstrapGate
}
