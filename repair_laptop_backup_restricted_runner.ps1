param(
  [string]$TaskName = 'AR-local laptop backup',
  [Parameter(Mandatory = $true)][string]$ImplementationRoot,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ImplementationCommit,
  [Parameter(Mandatory = $true)][string]$RunnerTemplatePath,
  [Parameter(Mandatory = $true)][string]$NewRunnerConfigPath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$NewRunnerConfigSha256,
  [Parameter(Mandatory = $true)][string]$ManagedRunnerPath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedOldRunnerSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedNewRunnerSha256,
  [Parameter(Mandatory = $true)][string]$LegacyPythonPath,
  [Parameter(Mandatory = $true)][string]$LegacyScriptPath,
  [Parameter(Mandatory = $true)][string]$Target,
  [Parameter(Mandatory = $true)][string]$RecoveryImage,
  [Parameter(Mandatory = $true)][string]$ControlRoot,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedOldConfigSha256,
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
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RestrictedLauncherSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$InstallerSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$SharedCoreSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$NonAdminCoreSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RepairCoreSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RunnerTemplateSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$FailedExecutionSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$AuthorityCommit,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$AuthorityHandoffSha256,
  [Parameter(Mandatory = $true)][string]$EvidenceRoot,
  [string]$PiHost = 'ar-local-pi5-lan'
)

$ErrorActionPreference = 'Stop'
$sharedCore = Join-Path $PSScriptRoot 'install_laptop_backup_dispatcher_core.ps1'
$nonAdminCore = Join-Path $PSScriptRoot 'install_laptop_backup_nonadmin_dispatcher_core.ps1'
$repairCore = Join-Path $PSScriptRoot 'repair_laptop_backup_restricted_runner_core.ps1'
if ((Get-FileHash $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $InstallerSha256 -or
    (Get-FileHash $sharedCore -Algorithm SHA256).Hash.ToLowerInvariant() -cne $SharedCoreSha256 -or
    (Get-FileHash $nonAdminCore -Algorithm SHA256).Hash.ToLowerInvariant() -cne $NonAdminCoreSha256 -or
    (Get-FileHash $repairCore -Algorithm SHA256).Hash.ToLowerInvariant() -cne $RepairCoreSha256) {
  throw 'Restricted-runner repair implementation hash mismatch.'
}
. $sharedCore
. $nonAdminCore
. $repairCore

function Write-ArRepairResult {
  param([string]$Result, [string]$ErrorText, [hashtable]$Details)
  $payload = [ordered]@{
    schema_version = 1
    plan_document_id = 'ARL-OPS-001'
    plan_version = '1.5'
    plan_git_commit = '9094a8e115958fcaf2cb36525736bd5e297e6b04'
    plan_sha256 = 'a512b7424de16dabf7d0b71db00539b4b0b653d1239749bceda6b27e05bd7ada'
    authority_commit = $AuthorityCommit
    handoff_sha256 = $AuthorityHandoffSha256
    candidate_code_sha = $CandidateCodeSha
    protected_code_sha = $ProtectedCodeSha
    scheduled_plan_git_commit = $ScheduledPlanGitCommit
    operator = $Operator
    task_name = $TaskName
    implementation_commit = $ImplementationCommit
    manifest_sha256 = $ManifestSha256
    runner_config_sha256 = $NewRunnerConfigSha256
    managed_runner_sha256 = $ExpectedNewRunnerSha256
    restricted_launcher_sha256 = $RestrictedLauncherSha256
    timestamps = [ordered]@{ started_at = $script:startedAt; completed_at = [DateTimeOffset]::UtcNow.ToString('o') }
    exact_commands = @($script:exactCommand, $script:piCommandIdentity)
    result = $Result
    error = $ErrorText
    details = $Details
    evidence_files = @(
      Get-ChildItem -LiteralPath $script:executionRoot -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object FullName | ForEach-Object {
          [ordered]@{ path = $_.FullName; sha256 = Get-ArSha256 $_.FullName; size = $_.Length }
        }
    )
    deviations = @('D-009 replaces D-008 direct dispatch with a SAFER normal-user child; Task Scheduler is unchanged.')
    deviation_authorization = 'HANDOFF-20260831T074200+1000-A3-NATURAL-BACKUP-FAIL-SAFER-REPAIR'
  }
  $path = Join-Path $script:executionRoot 'repair-result.json'
  Write-ArUtf8NoBom -Path $path -Text (($payload | ConvertTo-Json -Depth 12 -Compress) + "`n")
  $path
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if ($isAdmin) { throw 'D-009 repair must run without administrator elevation.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if ($identity.Name.ToLowerInvariant() -ne $Principal.ToLowerInvariant() -or $identity.User.Value -ne $OperatorSid) {
  throw 'Restricted-runner repair identity is not the authorised operator.'
}
$local = [DateTimeOffset]::Now
if ($local.TimeOfDay -lt [TimeSpan]::FromHours(3.5) -or $local.TimeOfDay -ge [TimeSpan]::FromHours(22)) {
  throw 'Restricted-runner repair is outside the D-006 daylight window.'
}

$paths = @($ImplementationRoot, $RunnerTemplatePath, $NewRunnerConfigPath, $ManagedRunnerPath,
  $LegacyPythonPath, $LegacyScriptPath, $Target, $RecoveryImage, $ControlRoot, $PythonPath, $EvidenceRoot)
foreach ($path in $paths) {
  if (-not (Test-Path -LiteralPath $path)) { throw "Required repair path is missing: $path" }
  Assert-ArNoReparsePath $path | Out-Null
}
if ([IO.Path]::GetFullPath($ControlRoot) -cne [IO.Path]::GetFullPath((Join-Path $Target 'dispatcher-control'))) {
  throw 'ControlRoot must be exactly Target\dispatcher-control.'
}
if ((git -C $ImplementationRoot rev-parse HEAD).Trim() -cne $ImplementationCommit -or
    (git -C $ImplementationRoot status --porcelain=v1)) {
  throw 'Repair implementation checkout is not exact and clean.'
}
git -C $ImplementationRoot symbolic-ref -q HEAD 2>$null | Out-Null
if ($LASTEXITCODE -ne 1) { throw 'Repair implementation checkout is not detached.' }

$dispatcherPath = Join-Path $ImplementationRoot 'laptop_backup_dispatcher.py'
$atomicPath = Join-Path $ImplementationRoot 'laptop_backup_atomic.py'
$restrictedPath = Join-Path $ImplementationRoot 'laptop_backup_restricted_process.py'
$configPath = Join-Path $ControlRoot 'runner-config.json'
$manifestPath = Join-Path (Join-Path $ControlRoot 'manifests') ($ManifestSha256 + '.json')
$pointerPath = Join-Path $ControlRoot 'active-runner.json'
$failedExecution = Get-ChildItem (Join-Path $ControlRoot 'dispatcher-executions') -File |
  Sort-Object LastWriteTimeUtc | Select-Object -Last 1
if ($null -eq $failedExecution -or (Get-ArSha256 $failedExecution.FullName) -cne $FailedExecutionSha256) {
  throw 'Natural dispatcher failure evidence is absent or drifted.'
}
if ((Get-ArSha256 $RunnerTemplatePath) -cne $RunnerTemplateSha256 -or
    (Get-ArSha256 $NewRunnerConfigPath) -cne $NewRunnerConfigSha256 -or
    (Get-ArSha256 $ManagedRunnerPath) -cne $ExpectedOldRunnerSha256 -or
    (Get-ArSha256 $configPath) -cne $ExpectedOldConfigSha256 -or
    (Get-ArSha256 $manifestPath) -cne $ManifestSha256 -or
    (Get-ArSha256 $dispatcherPath) -cne $DispatcherSha256 -or
    (Get-ArSha256 $atomicPath) -cne $AtomicModuleSha256 -or
    (Get-ArSha256 $restrictedPath) -cne $RestrictedLauncherSha256) {
  throw 'Restricted-runner repair input hash mismatch.'
}

$config = Get-Content $NewRunnerConfigPath -Raw | ConvertFrom-Json
$expectedFields = @('atomic_module_sha256', 'control_root', 'dispatcher_sha256', 'implementation_commit',
  'implementation_root', 'python_path', 'python_sha256', 'restricted_launcher_sha256', 'schema_version')
if (@(Compare-Object $expectedFields @($config.PSObject.Properties.Name | Sort-Object)).Count -ne 0 -or
    $config.schema_version -ne 2 -or [string]$config.implementation_commit -cne $ImplementationCommit -or
    [IO.Path]::GetFullPath([string]$config.implementation_root) -cne [IO.Path]::GetFullPath($ImplementationRoot) -or
    [IO.Path]::GetFullPath([string]$config.control_root) -cne [IO.Path]::GetFullPath($ControlRoot) -or
    [IO.Path]::GetFullPath([string]$config.python_path) -cne [IO.Path]::GetFullPath($PythonPath) -or
    [string]$config.python_sha256 -cne (Get-ArSha256 $PythonPath) -or
    [string]$config.dispatcher_sha256 -cne $DispatcherSha256 -or
    [string]$config.atomic_module_sha256 -cne $AtomicModuleSha256 -or
    [string]$config.restricted_launcher_sha256 -cne $RestrictedLauncherSha256) {
  throw 'New runner configuration is invalid.'
}
$runnerText = New-ArManagedRunnerText -TemplatePath $RunnerTemplatePath `
  -ConfigSha256 $NewRunnerConfigSha256 -RestrictedLauncherSha256 $RestrictedLauncherSha256
$runnerBytes = [Text.UTF8Encoding]::new($false).GetBytes($runnerText)
if ((Get-ArBytesSha256 $runnerBytes) -cne $ExpectedNewRunnerSha256) {
  throw 'Generated restricted runner hash mismatch.'
}

$manifest = Get-Content $manifestPath -Raw | ConvertFrom-Json
$pointer = Get-Content $pointerPath -Raw | ConvertFrom-Json
if ($pointer.manifest_sha256 -cne $ManifestSha256 -or $manifest.candidate_code_sha -cne $CandidateCodeSha -or
    $manifest.protected_code_sha -cne $ProtectedCodeSha -or
    $manifest.scheduled_plan_git_commit -cne $ScheduledPlanGitCommit -or
    $manifest.operator -cne $Operator -or $manifest.operator_sid -cne $OperatorSid) {
  throw 'Active dispatcher manifest identity drifted.'
}
$authorityHash = (& $PythonPath -c "import hashlib,subprocess,sys;print(hashlib.sha256(subprocess.check_output(['git','-C',sys.argv[1],'show',sys.argv[2]+':docs/PI_INGEST_PAYLOAD_RECOVERY_HANDOFF.md'])).hexdigest())" $ImplementationRoot $AuthorityCommit).Trim()
if ($LASTEXITCODE -ne 0 -or $authorityHash -cne $AuthorityHandoffSha256) {
  throw 'D-009 authority authentication failed.'
}

$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
$taskInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
if ($task.State.ToString() -ne 'Ready' -or -not $task.Settings.Enabled -or $taskInfo.LastTaskResult -ne 1 -or
    $task.Principal.LogonType.ToString() -ne 'S4U' -or $task.Principal.RunLevel.ToString() -ne 'Limited') {
  throw 'Natural-failure task state is not the accepted D-009 prestate.'
}
$taskXml = Get-ArTaskXmlBytes -TaskName $TaskName
$taskXmlHash = Get-ArBytesSha256 $taskXml
$taskSddlHash = Get-ArTextSha256 (Get-ArTaskSddl -TaskName $TaskName)
if ($taskXmlHash -cne $ExpectedTaskXmlSha256 -or $taskSddlHash -cne $ExpectedTaskSddlSha256) {
  throw 'Task XML or SDDL drifted before D-009 repair.'
}
$helpers = @(Get-CimInstance Win32_Process | Where-Object {
  $_.ProcessId -ne $PID -and $_.CommandLine -and
  $_.CommandLine -match 'laptop_backup_(scheduled|dispatcher|restricted_process)|laptop_pull_backup|run_laptop_backup_task'
})
if ($helpers.Count -ne 0 -or (Get-PSDrive C).Free -lt 50GB) {
  throw 'Helper or free-space gate failed before D-009 repair.'
}

$piCheck = New-ArLfRemoteScript -Lines @(
  'set -eu', 'cd /srv/ar-local/AR-local',
  ('test "$(git rev-parse HEAD)" = ''{0}''' -f $ProtectedCodeSha),
  'test -z "$(git status --porcelain=v1)"',
  '! systemctl is-active --quiet ar-local-daily.service',
  'test ! -e /srv/ar-local/data/state/daily-ingest.lock',
  'curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest >/dev/null',
  'echo AR_PI_D009_PREFLIGHT_PASS'
)
$script:piCommandIdentity = "ssh $PiHost LF-SHA256=$(Get-ArTextSha256 $piCheck)"
$piOutput = @(& ssh -o BatchMode=yes -o ConnectTimeout=10 $PiHost $piCheck 2>&1)
if ($LASTEXITCODE -ne 0 -or $piOutput[-1] -cne 'AR_PI_D009_PREFLIGHT_PASS') {
  throw 'Pi D-009 preflight failed.'
}

$script:startedAt = [DateTimeOffset]::UtcNow.ToString('o')
$script:exactCommand = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").CommandLine
$executionId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N')
$script:executionRoot = Join-Path (Join-Path $EvidenceRoot 'executions') $executionId
New-Item -ItemType Directory -Path $script:executionRoot | Out-Null
[IO.File]::WriteAllBytes((Join-Path $script:executionRoot 'pre-task.xml'), $taskXml)
Write-ArUtf8NoBom (Join-Path $script:executionRoot 'pre-task.sddl') (Get-ArTaskSddl -TaskName $TaskName)
Write-ArUtf8NoBom (Join-Path $script:executionRoot 'pi-preflight.txt') (($piOutput -join "`n") + "`n")
[IO.File]::WriteAllBytes((Join-Path $script:executionRoot 'new-runner-config.json'), [IO.File]::ReadAllBytes($NewRunnerConfigPath))
$evidenceRunner = Join-Path $script:executionRoot 'new-managed-runner.ps1'
[IO.File]::WriteAllBytes($evidenceRunner, $runnerBytes)
if ((Get-ArSha256 $evidenceRunner) -cne $ExpectedNewRunnerSha256) { throw 'Evidence runner hash mismatch.' }
$oldConfig = Join-Path $script:executionRoot 'old-runner-config.json'
$oldRunner = Join-Path $script:executionRoot 'old-managed-runner.ps1'
$failedConfig = Join-Path $script:executionRoot 'failed-new-runner-config.json'
$failedRunner = Join-Path $script:executionRoot 'failed-new-managed-runner.ps1'
$configReplaced = $false
$runnerReplaced = $false

try {
  Install-ArManagedFileAtomic -DestinationPath $configPath -SourcePath $NewRunnerConfigPath `
    -BackupPath $oldConfig -ExpectedOldSha256 $ExpectedOldConfigSha256 -ExpectedNewSha256 $NewRunnerConfigSha256
  $configReplaced = $true
  Install-ArManagedFileAtomic -DestinationPath $ManagedRunnerPath -SourcePath $evidenceRunner `
    -BackupPath $oldRunner -ExpectedOldSha256 $ExpectedOldRunnerSha256 -ExpectedNewSha256 $ExpectedNewRunnerSha256
  $runnerReplaced = $true
  for ($probeNumber = 1; $probeNumber -le 2; $probeNumber++) {
    if ((Get-ScheduledTask -TaskName $TaskName).State.ToString() -ne 'Ready') { throw 'Task started during repair.' }
    $probePath = Join-Path $script:executionRoot ("restricted-probe-$probeNumber.json")
    $priorMode = $env:AR_LOCAL_BACKUP_DISPATCHER_MODE
    try {
      $env:AR_LOCAL_BACKUP_DISPATCHER_MODE = 'probe'
      & "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive `
        -ExecutionPolicy Bypass -File $ManagedRunnerPath -PythonPath $LegacyPythonPath `
        -ScriptPath $LegacyScriptPath -Target $Target -RecoveryImage $RecoveryImage `
        -CandidateCodeSha $CandidateCodeSha -ProtectedCodeSha $ProtectedCodeSha `
        -PlanGitCommit $ScheduledPlanGitCommit -Operator $Operator *> $probePath
      $probeExit = $LASTEXITCODE
    } finally { $env:AR_LOCAL_BACKUP_DISPATCHER_MODE = $priorMode }
    if ($probeExit -ne 0) { throw "Restricted semantic probe $probeNumber failed with exit $probeExit." }
    $probe = Get-Content $probePath -Raw | ConvertFrom-Json
    if ($probe.ok -ne $true -or $probe.result -cne 'PASS' -or $probe.mode -cne 'PROBE' -or
        $probe.is_admin -ne $false -or $probe.operator_sid -cne $OperatorSid -or
        $probe.candidate_code_sha -cne $CandidateCodeSha -or $probe.manifest_sha256 -cne $ManifestSha256) {
      throw "Restricted semantic probe $probeNumber identity failed."
    }
  }
  $xmlAfter = Get-ArTaskXmlBytes -TaskName $TaskName
  $sddlAfter = Get-ArTextSha256 (Get-ArTaskSddl -TaskName $TaskName)
  if ((Get-ArBytesSha256 $xmlAfter) -cne $ExpectedTaskXmlSha256 -or $sddlAfter -cne $ExpectedTaskSddlSha256 -or
      (Get-ScheduledTask -TaskName $TaskName).State.ToString() -ne 'Ready') {
    throw 'Task state changed during D-009 repair.'
  }
  [IO.File]::WriteAllBytes((Join-Path $script:executionRoot 'post-task.xml'), $xmlAfter)
  $resultPath = Write-ArRepairResult -Result 'PASS' -ErrorText $null -Details @{
    task_xml_sha256 = $ExpectedTaskXmlSha256
    task_sddl_sha256 = $ExpectedTaskSddlSha256
    previous_runner_sha256 = $ExpectedOldRunnerSha256
    previous_config_sha256 = $ExpectedOldConfigSha256
    natural_failure_sha256 = $FailedExecutionSha256
    probes = 2
    task_triggered = $false
  }
  Get-Content $resultPath -Raw
} catch {
  $failure = $_.Exception.Message
  $rollbackError = $null
  try {
    if ($runnerReplaced) {
      Restore-ArManagedFileAtomic -DestinationPath $ManagedRunnerPath -BackupPath $oldRunner `
        -FailedPath $failedRunner -ExpectedOldSha256 $ExpectedOldRunnerSha256 -ExpectedFailedSha256 $ExpectedNewRunnerSha256
    }
    if ($configReplaced) {
      Restore-ArManagedFileAtomic -DestinationPath $configPath -BackupPath $oldConfig `
        -FailedPath $failedConfig -ExpectedOldSha256 $ExpectedOldConfigSha256 -ExpectedFailedSha256 $NewRunnerConfigSha256
    }
  } catch { $rollbackError = $_.Exception.Message }
  $result = if ($null -eq $rollbackError) { 'ROLLED_BACK' } else { 'FAIL' }
  $errorText = if ($null -eq $rollbackError) { $failure } else { "$failure; rollback failed: $rollbackError" }
  $resultPath = Write-ArRepairResult -Result $result -ErrorText $errorText -Details @{
    runner_restored = ((Get-ArSha256 $ManagedRunnerPath) -ceq $ExpectedOldRunnerSha256)
    config_restored = ((Get-ArSha256 $configPath) -ceq $ExpectedOldConfigSha256)
    task_triggered = $false
  }
  Get-Content $resultPath -Raw
  throw $errorText
}
