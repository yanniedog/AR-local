param(
  [string]$TaskName = 'AR-local laptop backup',
  [Parameter(Mandatory = $true)][string]$ImplementationRoot,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ImplementationCommit,
  [Parameter(Mandatory = $true)][string]$RunnerTemplatePath,
  [Parameter(Mandatory = $true)][string]$RunnerConfigPath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RunnerConfigSha256,
  [Parameter(Mandatory = $true)][string]$LegacyRunnerPath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedLegacyRunnerSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedManagedRunnerSha256,
  [Parameter(Mandatory = $true)][string]$LegacyPythonPath,
  [Parameter(Mandatory = $true)][string]$LegacyScriptPath,
  [Parameter(Mandatory = $true)][string]$Target,
  [Parameter(Mandatory = $true)][string]$RecoveryImage,
  [Parameter(Mandatory = $true)][string]$ControlRoot,
  [Parameter(Mandatory = $true)][string]$ManifestPath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ManifestSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$CandidateCodeSha,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ProtectedCodeSha,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ScheduledPlanGitCommit,
  [Parameter(Mandatory = $true)][string]$Operator,
  [Parameter(Mandatory = $true)][string]$Principal,
  [Parameter(Mandatory = $true)][string]$OperatorSid,
  [Parameter(Mandatory = $true)][string]$PythonPath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedTaskXmlSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedTaskSddlSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$DispatcherSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$AtomicModuleSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$InstallerSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$SharedCoreSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$NonAdminCoreSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RunnerTemplateSha256,
  [Parameter(Mandatory = $true)][string]$EvidenceRoot,
  [string]$PiHost = 'ar-local-pi5-lan'
)

$ErrorActionPreference = 'Stop'
$sharedCore = Join-Path $PSScriptRoot 'install_laptop_backup_dispatcher_core.ps1'
$nonAdminCore = Join-Path $PSScriptRoot 'install_laptop_backup_nonadmin_dispatcher_core.ps1'
if ((Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $InstallerSha256 -or
    (Get-FileHash -LiteralPath $sharedCore -Algorithm SHA256).Hash.ToLowerInvariant() -cne $SharedCoreSha256 -or
    (Get-FileHash -LiteralPath $nonAdminCore -Algorithm SHA256).Hash.ToLowerInvariant() -cne $NonAdminCoreSha256) {
  throw 'Non-administrator dispatcher installer implementation hash mismatch.'
}
. $sharedCore
. $nonAdminCore

function Write-ArNonAdminResult {
  param([string]$Result, [string]$ErrorText, [hashtable]$Evidence)
  $payload = [ordered]@{
    schema_version = 1
    plan_document_id = 'ARL-OPS-001'
    plan_version = '1.5'
    plan_git_commit = $script:manifest.plan_git_commit
    plan_sha256 = $script:manifest.plan_sha256
    authority_commit = $script:manifest.authority_commit
    handoff_sha256 = $script:manifest.handoff_sha256
    candidate_code_sha = $CandidateCodeSha
    protected_code_sha = $ProtectedCodeSha
    scheduled_plan_git_commit = $ScheduledPlanGitCommit
    operator = $Operator
    task_name = $TaskName
    implementation_commit = $ImplementationCommit
    manifest_sha256 = $ManifestSha256
    runner_config_sha256 = $RunnerConfigSha256
    managed_runner_sha256 = $ExpectedManagedRunnerSha256
    timestamps = [ordered]@{ started_at = $script:startedAt; completed_at = [DateTimeOffset]::UtcNow.ToString('o') }
    exact_commands = @($script:exactCommand, $script:piCommandIdentity)
    result = $Result
    error = $ErrorText
    evidence = $Evidence
    evidence_files = @(
      Get-ChildItem -LiteralPath $script:executionRoot -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName | ForEach-Object {
          [ordered]@{ path = $_.FullName; sha256 = Get-ArSha256 $_.FullName; size = $_.Length }
        }
    )
    deviations = @('The existing operator-writable task runner is intentionally managed outside Git cleanliness under D-008.')
    deviation_authorization = 'HANDOFF-20260830T170600+1000-A3-NONADMIN-RUNNER-REDESIGN'
  }
  $path = Join-Path $script:executionRoot 'transition-result.json'
  Write-ArUtf8NoBom -Path $path -Text (($payload | ConvertTo-Json -Depth 12 -Compress) + "`n")
  $path
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if ($isAdmin) { throw 'D-008 transition must run without administrator elevation.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if ($identity.Name.ToLowerInvariant() -ne $Principal.ToLowerInvariant() -or $identity.User.Value -ne $OperatorSid) {
  throw 'Non-administrator transition identity is not the authorised operator.'
}
$local = [DateTimeOffset]::Now
if ($local.TimeOfDay -lt [TimeSpan]::FromHours(3.5) -or $local.TimeOfDay -ge [TimeSpan]::FromHours(22)) {
  throw 'Non-administrator transition is outside the D-006 daylight window.'
}

foreach ($path in @($ImplementationRoot, $Target, $ControlRoot, $EvidenceRoot)) {
  if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw "Required directory is missing: $path" }
}
$derivedControlRoot = Join-Path ([IO.Path]::GetFullPath($Target)) 'dispatcher-control'
if ([IO.Path]::GetFullPath($ControlRoot) -cne [IO.Path]::GetFullPath($derivedControlRoot)) {
  throw 'ControlRoot must be exactly Target\dispatcher-control.'
}
foreach ($path in @(
  $RunnerTemplatePath, $RunnerConfigPath, $LegacyRunnerPath, $LegacyPythonPath,
  $LegacyScriptPath, $ManifestPath, $PythonPath
)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file is missing: $path" }
}
foreach ($path in @(
  $ImplementationRoot, $RunnerTemplatePath, $RunnerConfigPath, $LegacyRunnerPath,
  $LegacyPythonPath, $LegacyScriptPath, $Target, $ControlRoot, $ManifestPath,
  $PythonPath, $EvidenceRoot
)) {
  Assert-ArNoReparsePath $path | Out-Null
}
if ((Get-ArSha256 $RunnerTemplatePath) -cne $RunnerTemplateSha256 -or
    (Get-ArSha256 $RunnerConfigPath) -cne $RunnerConfigSha256 -or
    (Get-ArSha256 $ManifestPath) -cne $ManifestSha256 -or
    (Get-ArSha256 $LegacyRunnerPath) -cne $ExpectedLegacyRunnerSha256) {
  throw 'Runner, configuration, manifest, or legacy input hash mismatch.'
}
$script:manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if ($script:manifest.plan_document_id -cne 'ARL-OPS-001' -or $script:manifest.plan_version -cne '1.5' -or
    $script:manifest.candidate_code_sha -cne $CandidateCodeSha -or
    $script:manifest.protected_code_sha -cne $ProtectedCodeSha -or
    $script:manifest.scheduled_plan_git_commit -cne $ScheduledPlanGitCommit -or
    $script:manifest.operator -cne $Operator -or $script:manifest.operator_sid -cne $OperatorSid) {
  throw 'Manifest identity does not match the transition inputs.'
}
if ((git -C $ImplementationRoot rev-parse HEAD).Trim() -cne $ImplementationCommit -or
    (git -C $ImplementationRoot status --porcelain=v1)) {
  throw 'Dispatcher implementation checkout is not clean at the exact commit.'
}
git -C $ImplementationRoot symbolic-ref -q HEAD 2>$null | Out-Null
if ($LASTEXITCODE -ne 1) { throw 'Dispatcher implementation checkout is not detached.' }
$dispatcherPath = Join-Path $ImplementationRoot 'laptop_backup_dispatcher.py'
$atomicPath = Join-Path $ImplementationRoot 'laptop_backup_atomic.py'
if ((Get-ArSha256 $dispatcherPath) -cne $DispatcherSha256 -or
    (Get-ArSha256 $atomicPath) -cne $AtomicModuleSha256 -or
    (Get-ArSha256 $PythonPath) -cne ((Get-Content -LiteralPath $RunnerConfigPath -Raw | ConvertFrom-Json).python_sha256)) {
  throw 'Dispatcher implementation or Python hash mismatch.'
}
$config = Get-Content -LiteralPath $RunnerConfigPath -Raw | ConvertFrom-Json
$expectedConfigFields = @(
  'atomic_module_sha256', 'control_root', 'dispatcher_sha256', 'implementation_commit',
  'implementation_root', 'python_path', 'python_sha256', 'schema_version'
)
if (@(Compare-Object $expectedConfigFields @($config.PSObject.Properties.Name | Sort-Object)).Count -ne 0 -or
    $config.schema_version -ne 1 -or
    [IO.Path]::GetFullPath([string]$config.control_root) -cne [IO.Path]::GetFullPath($ControlRoot) -or
    [IO.Path]::GetFullPath([string]$config.implementation_root) -cne [IO.Path]::GetFullPath($ImplementationRoot) -or
    [string]$config.implementation_commit -cne $ImplementationCommit -or
    [string]$config.dispatcher_sha256 -cne $DispatcherSha256 -or
    [string]$config.atomic_module_sha256 -cne $AtomicModuleSha256 -or
    [IO.Path]::GetFullPath([string]$config.python_path) -cne [IO.Path]::GetFullPath($PythonPath)) {
  throw 'Runner configuration is not exactly bound to the transition inputs.'
}
$runnerText = New-ArManagedRunnerText -TemplatePath $RunnerTemplatePath -ConfigSha256 $RunnerConfigSha256
$runnerBytes = [Text.UTF8Encoding]::new($false).GetBytes($runnerText)
$algorithm = [Security.Cryptography.SHA256]::Create()
try { $generatedRunnerHash = ([BitConverter]::ToString($algorithm.ComputeHash($runnerBytes)) -replace '-', '').ToLowerInvariant() } finally { $algorithm.Dispose() }
if ($generatedRunnerHash -cne $ExpectedManagedRunnerSha256) { throw 'Managed runner generation does not match the accepted digest.' }

$free = (Get-PSDrive -Name ([IO.Path]::GetPathRoot($Target).Substring(0, 1))).Free
if ($free -lt 50GB) { throw 'Laptop free space is below 50 GiB.' }
$activeProcesses = @(Get-CimInstance Win32_Process | Where-Object {
  $_.ProcessId -ne $PID -and $_.CommandLine -and
  $_.CommandLine -match 'laptop_backup_(scheduled|dispatcher)|laptop_pull_backup'
})
if ($activeProcesses.Count -gt 0) { throw 'A laptop backup or dispatcher process is already active.' }
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
if ($task.State.ToString() -ne 'Ready' -or -not $task.Settings.Enabled -or $taskInfo.LastTaskResult -ne 0 -or
    $task.Principal.LogonType.ToString() -ne 'S4U' -or $task.Principal.RunLevel.ToString() -ne 'Limited') {
  throw 'Existing task is not Ready, enabled, successful and S4U/Limited.'
}
$taskXmlBytes = Get-ArTaskXmlBytes -TaskName $TaskName
$algorithm = [Security.Cryptography.SHA256]::Create()
try { $taskXmlHash = ([BitConverter]::ToString($algorithm.ComputeHash($taskXmlBytes)) -replace '-', '').ToLowerInvariant() } finally { $algorithm.Dispose() }
$taskSddlHash = Get-ArTextSha256 (Get-ArTaskSddl -TaskName $TaskName)
if ($taskXmlHash -cne $ExpectedTaskXmlSha256 -or $taskSddlHash -cne $ExpectedTaskSddlSha256) {
  throw 'Existing task XML or SDDL is not the accepted recovered artifact.'
}
if (@($task.Actions).Count -ne 1 -or [IO.Path]::GetFullPath($task.Actions[0].WorkingDirectory) -cne [IO.Path]::GetFullPath((Split-Path -Parent $LegacyRunnerPath)) -or
    $task.Actions[0].Arguments -notlike "*-File `"$LegacyRunnerPath`"*") {
  throw 'Existing task does not execute the authenticated legacy runner.'
}

$piCheck = New-ArLfRemoteScript -Lines @(
  'set -eu',
  'cd /srv/ar-local/AR-local',
  ('test "$(git rev-parse HEAD)" = ''{0}''' -f $ProtectedCodeSha),
  'test -z "$(git status --porcelain=v1)"',
  '! systemctl is-active --quiet ar-local-daily.service',
  'test ! -e /srv/ar-local/data/state/daily-ingest.lock',
  'curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest >/dev/null',
  'echo AR_PI_PREFLIGHT_PASS'
)
$piAlgorithm = [Security.Cryptography.SHA256]::Create()
try {
  $piCheckSha = ([BitConverter]::ToString($piAlgorithm.ComputeHash([Text.UTF8Encoding]::new($false).GetBytes($piCheck))) -replace '-', '').ToLowerInvariant()
} finally {
  $piAlgorithm.Dispose()
}
$script:piCommandIdentity = "ssh $PiHost LF-SHA256=$piCheckSha"
$piOutput = @(& ssh -o BatchMode=yes -o ConnectTimeout=10 $PiHost $piCheck 2>&1)
if ($LASTEXITCODE -ne 0 -or $piOutput[-1] -cne 'AR_PI_PREFLIGHT_PASS') { throw 'Pi non-administrator transition preflight failed.' }

$script:startedAt = [DateTimeOffset]::UtcNow.ToString('o')
$script:exactCommand = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").CommandLine
$executionId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N')
$script:executionRoot = Join-Path (Join-Path $EvidenceRoot 'executions') $executionId
New-Item -ItemType Directory -Path $script:executionRoot -ErrorAction Stop | Out-Null
[IO.File]::WriteAllBytes((Join-Path $script:executionRoot 'pre-task.xml'), $taskXmlBytes)
Write-ArUtf8NoBom -Path (Join-Path $script:executionRoot 'pre-task.sddl') -Text (Get-ArTaskSddl -TaskName $TaskName)
Write-ArUtf8NoBom -Path (Join-Path $script:executionRoot 'pi-preflight.txt') -Text (($piOutput -join "`n") + "`n")
$backupRunner = Join-Path $script:executionRoot 'legacy-runner.ps1'
$failedRunner = Join-Path $script:executionRoot 'failed-managed-runner.ps1'
$installedConfig = Join-Path $ControlRoot 'runner-config.json'
$runnerReplaced = $false
$controlChanged = $false

try {
  $unexpected = @(Get-ChildItem -LiteralPath $ControlRoot -Force)
  if ($unexpected.Count -ne 0) { throw 'Dispatcher control root is not empty before initial D-008 transition.' }
  $controlChanged = $true
  $activationLog = Join-Path $script:executionRoot 'manifest-activation.txt'
  & $PythonPath $dispatcherPath activate --control-root $ControlRoot --manifest $ManifestPath *> $activationLog
  $activationExit = $LASTEXITCODE
  if ($activationExit -ne 0) { throw "Initial non-administrator manifest activation failed with exit $activationExit." }
  if (Test-Path -LiteralPath $installedConfig) { throw 'Runner configuration unexpectedly exists after activation.' }
  $configTemporary = Join-Path $ControlRoot ('.runner-config-' + [guid]::NewGuid().ToString('N') + '.tmp')
  [IO.File]::WriteAllBytes($configTemporary, [IO.File]::ReadAllBytes($RunnerConfigPath))
  [IO.File]::Move($configTemporary, $installedConfig)
  if ((Get-ArSha256 $installedConfig) -cne $RunnerConfigSha256) { throw 'Installed runner configuration hash mismatch.' }
  Install-ArManagedRunnerAtomic -RunnerPath $LegacyRunnerPath -RunnerText $runnerText `
    -BackupPath $backupRunner -ExpectedOldSha256 $ExpectedLegacyRunnerSha256 `
    -ExpectedNewSha256 $ExpectedManagedRunnerSha256
  $runnerReplaced = $true
  $taskImmediatelyBeforeProbe = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $backupImmediatelyBeforeProbe = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -and
    $_.CommandLine -match 'laptop_backup_(scheduled|dispatcher)|laptop_pull_backup'
  })
  if ($taskImmediatelyBeforeProbe.State.ToString() -ne 'Ready' -or $backupImmediatelyBeforeProbe.Count -ne 0) {
    throw 'Task or backup process changed during atomic runner transition.'
  }
  $probeLog = Join-Path $script:executionRoot 'installed-runner-probe.txt'
  $priorMode = $env:AR_LOCAL_BACKUP_DISPATCHER_MODE
  try {
    $env:AR_LOCAL_BACKUP_DISPATCHER_MODE = 'probe'
    & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive `
      -ExecutionPolicy Bypass -File $LegacyRunnerPath -PythonPath $LegacyPythonPath `
      -ScriptPath $LegacyScriptPath -Target $Target -RecoveryImage $RecoveryImage `
      -CandidateCodeSha $CandidateCodeSha -ProtectedCodeSha $ProtectedCodeSha `
      -PlanGitCommit $ScheduledPlanGitCommit -Operator $Operator *> $probeLog
    $probeExit = $LASTEXITCODE
  } finally {
    $env:AR_LOCAL_BACKUP_DISPATCHER_MODE = $priorMode
  }
  if ($probeExit -ne 0) { throw "Installed managed runner probe failed with exit $probeExit." }
  $probe = Get-Content -LiteralPath $probeLog -Raw | ConvertFrom-Json
  if ($probe.ok -ne $true -or $probe.result -cne 'PASS' -or $probe.mode -cne 'PROBE' -or
      $probe.is_admin -ne $false -or $probe.operator_sid -cne $OperatorSid -or
      $probe.candidate_code_sha -cne $CandidateCodeSha -or $probe.manifest_sha256 -cne $ManifestSha256) {
    throw 'Installed managed runner probe identity is invalid.'
  }
  $taskAfter = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $xmlAfter = Get-ArTaskXmlBytes -TaskName $TaskName
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try { $xmlAfterHash = ([BitConverter]::ToString($algorithm.ComputeHash($xmlAfter)) -replace '-', '').ToLowerInvariant() } finally { $algorithm.Dispose() }
  $sddlAfterHash = Get-ArTextSha256 (Get-ArTaskSddl -TaskName $TaskName)
  if ($xmlAfterHash -cne $ExpectedTaskXmlSha256 -or $sddlAfterHash -cne $ExpectedTaskSddlSha256 -or
      $taskAfter.State.ToString() -ne 'Ready' -or -not $taskAfter.Settings.Enabled) {
    throw 'Task definition or state changed during the non-administrator transition.'
  }
  [IO.File]::WriteAllBytes((Join-Path $script:executionRoot 'post-task.xml'), $xmlAfter)
  Write-ArUtf8NoBom -Path (Join-Path $script:executionRoot 'post-task.sddl') -Text (Get-ArTaskSddl -TaskName $TaskName)
  $resultPath = Write-ArNonAdminResult -Result 'PASS' -ErrorText $null -Evidence @{
    free_bytes = $free
    pi_output = $piOutput
    legacy_runner_sha256 = $ExpectedLegacyRunnerSha256
    managed_runner_sha256 = $ExpectedManagedRunnerSha256
    task_xml_sha256 = $ExpectedTaskXmlSha256
    task_sddl_sha256 = $ExpectedTaskSddlSha256
    probe_sha256 = Get-ArSha256 $probeLog
    control_root = $ControlRoot
  }
  Get-Content -LiteralPath $resultPath -Raw
} catch {
  $failure = $_.Exception.Message
  $rollbackError = $null
  try {
    if ($runnerReplaced) {
      Restore-ArManagedRunnerAtomic -RunnerPath $LegacyRunnerPath -BackupPath $backupRunner `
        -FailedRunnerPath $failedRunner -ExpectedOldSha256 $ExpectedLegacyRunnerSha256
    }
    if ($controlChanged) {
      $rollbackRoot = Join-Path $script:executionRoot 'dispatcher-control-rollback'
      New-Item -ItemType Directory -Path $rollbackRoot -ErrorAction Stop | Out-Null
      foreach ($item in @(Get-ChildItem -LiteralPath $ControlRoot -Force)) {
        Move-Item -LiteralPath $item.FullName -Destination $rollbackRoot -ErrorAction Stop
      }
    }
  } catch {
    $rollbackError = $_.Exception.Message
  }
  $result = if ($null -eq $rollbackError) { 'ROLLED_BACK' } else { 'FAIL' }
  $errorText = if ($null -eq $rollbackError) { $failure } else { "$failure; rollback failed: $rollbackError" }
  $resultPath = Write-ArNonAdminResult -Result $result -ErrorText $errorText -Evidence @{
    runner_restored = ($runnerReplaced -and (Get-ArSha256 $LegacyRunnerPath) -ceq $ExpectedLegacyRunnerSha256)
    control_root_empty = (@(Get-ChildItem -LiteralPath $ControlRoot -Force).Count -eq 0)
  }
  Get-Content -LiteralPath $resultPath -Raw
  throw $errorText
}
