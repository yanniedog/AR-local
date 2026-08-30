param(
  [string]$TaskName = 'AR-local laptop backup',
  [Parameter(Mandatory = $true)][string]$PackagePath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$PackageSha256,
  [Parameter(Mandatory = $true)][string]$InstallRoot,
  [Parameter(Mandatory = $true)][string]$Target,
  [Parameter(Mandatory = $true)][string]$ControlRoot,
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
  [Parameter(Mandatory = $true)][int]$ExpectedOldTaskLastResult,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$InstallerSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$CoreSha256,
  [string]$PiHost = 'ar-local-pi5-lan'
)

$ErrorActionPreference = 'Stop'
$corePath = Join-Path $PSScriptRoot 'install_laptop_backup_trusted_dispatcher_core.ps1'
if ((Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $InstallerSha256 -or
    (Get-FileHash -LiteralPath $corePath -Algorithm SHA256).Hash.ToLowerInvariant() -cne $CoreSha256) {
  throw 'Trusted installer implementation hash mismatch.'
}
. $corePath

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

$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$isAdmin = ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -or $identity.User.Value -cne $OperatorSid) { throw 'Trusted bootstrap requires the authorised elevated operator.' }
$local = [DateTimeOffset]::Now
if ($local.TimeOfDay -lt [TimeSpan]::FromHours(3.5) -or $local.TimeOfDay -ge [TimeSpan]::FromHours(22)) { throw 'Trusted bootstrap is outside the D-006 daylight window.' }
if (-not (Test-Path -LiteralPath $PackagePath -PathType Leaf)) { throw 'Trusted package is absent.' }
foreach ($path in @($Target,$ControlRoot,$EvidenceRoot)) { if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw "Required directory is absent: $path" } }
foreach ($path in @($PackagePath,$Target,$ControlRoot,$EvidenceRoot,([IO.Path]::GetDirectoryName($InstallRoot)))) { Assert-ArTrustedPlainPath $path | Out-Null }
$expectedControl = Join-Path ([IO.Path]::GetFullPath($Target)) 'dispatcher-control'
if ([IO.Path]::GetFullPath($ControlRoot) -cne [IO.Path]::GetFullPath($expectedControl)) { throw 'ControlRoot must be exactly Target\dispatcher-control.' }
$targetPrefix = [IO.Path]::GetFullPath($Target).TrimEnd('\') + '\'
$controlPrefix = [IO.Path]::GetFullPath($ControlRoot).TrimEnd('\') + '\'
$evidenceFull = [IO.Path]::GetFullPath($EvidenceRoot)
if (-not $evidenceFull.StartsWith($targetPrefix,[StringComparison]::OrdinalIgnoreCase) -or
    $evidenceFull.StartsWith($controlPrefix,[StringComparison]::OrdinalIgnoreCase)) {
  throw 'EvidenceRoot must be within Target but outside dispatcher-control.'
}
$programFilesRoot = [IO.Path]::GetFullPath($env:ProgramFiles).TrimEnd('\') + '\'
$installFull = [IO.Path]::GetFullPath($InstallRoot)
if (-not $installFull.StartsWith($programFilesRoot, [StringComparison]::OrdinalIgnoreCase)) { throw 'InstallRoot must be below Program Files.' }
if (Test-Path -LiteralPath $InstallRoot) { throw 'Trusted content-addressed install root already exists.' }
if ((Get-PSDrive -Name ([IO.Path]::GetPathRoot($Target).Substring(0,1))).Free -lt 50GB) { throw 'Laptop free space is below 50 GiB.' }
$active = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine -match 'laptop_backup_(scheduled|dispatcher)|laptop_pull_backup' })
if ($active.Count) { throw 'A laptop backup or dispatcher process is already active.' }

$ssh = "$env:SystemRoot\System32\OpenSSH\ssh.exe"
$piLines = @('set -eu','cd /srv/ar-local/AR-local',('test "$(git rev-parse HEAD)" = ''{0}''' -f $ProtectedCodeSha),'test -z "$(git status --porcelain=v1)"','! systemctl is-active --quiet ar-local-daily.service','test ! -e /srv/ar-local/data/state/daily-ingest.lock','curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest >/dev/null','echo AR_PI_PREFLIGHT_PASS')
$piScript = ($piLines -join "`n") + "`n"
$piResult = Invoke-ArTrustedSshScript -SshPath $ssh -HostName $PiHost -Script $piScript
$piOutput = @($piResult.Stdout.TrimEnd() -split "`n")
if ($piResult.ExitCode -ne 0 -or $piOutput[-1] -cne 'AR_PI_PREFLIGHT_PASS') { throw 'Pi trusted-bootstrap preflight failed.' }

$script:startedAt = [DateTimeOffset]::UtcNow.ToString('o')
$script:exactCommand = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").CommandLine
$executionId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N')
$script:executionRoot = Join-Path $EvidenceRoot $executionId
New-Item -ItemType Directory -Path $script:executionRoot -ErrorAction Stop | Out-Null
[IO.File]::WriteAllText((Join-Path $script:executionRoot 'pi-preflight.txt'), (($piOutput -join "`n") + "`n"), [Text.UTF8Encoding]::new($false))

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
if ((Get-ArTrustedSha256 $oldXmlPath) -cne $ExpectedOldTaskXmlSha256 -or (Get-ArTrustedTextSha256 $oldSddl) -cne $ExpectedOldTaskSddlSha256) { throw 'Existing task is not the authorised prestate.' }

$staging = $InstallRoot + '.staging-' + [guid]::NewGuid().ToString('N')
$probeName = 'AR-local trusted dispatcher probe ' + [guid]::NewGuid().ToString('N')
$controlPrestate = Join-Path $script:executionRoot 'dispatcher-control-prestate'
$mutated = $false; $probeRegistered = $false; $installed = $false; $controlChanged = $false
try {
  Write-ArMutationIntent -Action 'DISABLE_PRODUCTION_TASK' -TargetPath $TaskName
  $mutated = $true
  Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
  $disabled = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $activeAfterDisable = @(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -ne $PID -and $_.CommandLine -and $_.CommandLine -match 'laptop_backup_(scheduled|dispatcher)|laptop_pull_backup' })
  if ($disabled.State.ToString() -ne 'Disabled' -or $disabled.Settings.Enabled -or $activeAfterDisable.Count) { throw 'Production task did not become safely quiescent.' }
  Copy-Item -LiteralPath $ControlRoot -Destination $controlPrestate -Recurse -ErrorAction Stop
  Write-ArMutationIntent -Action 'CREATE_PACKAGE_STAGING' -TargetPath $staging
  New-Item -ItemType Directory -Path $staging -ErrorAction Stop | Out-Null
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
      [IO.Path]::GetFullPath([string]$dispatcherManifest.allowed_receiver_root) -cne [IO.Path]::GetFullPath($InstallRoot)) {
    throw 'Protected dispatcher manifest does not match the authorised bootstrap identity.'
  }
  $trustedConfig = Assert-ArTrustedChildConfiguration -Root $InstallRoot -ControlRoot $ControlRoot
  $toolPaths = @($trustedConfig.git_path,$trustedConfig.ssh_path,$trustedConfig.scp_path,$trustedConfig.whoami_path)
  $env:PATH = (($toolPaths | ForEach-Object { [IO.Path]::GetDirectoryName([string]$_) } | Select-Object -Unique) -join ';')
  $env:AR_TRUSTED_ROOT = $InstallRoot; $env:GIT_OPTIONAL_LOCKS = '0'; $env:PYTHONNOUSERSITE = '1'; $env:PYTHONDONTWRITEBYTECODE = '1'
  $controlChanged = $true
  Write-ArMutationIntent -Action 'ACTIVATE_DISPATCHER_MANIFEST' -TargetPath $ControlRoot
  & $python -s -E $dispatcher activate --control-root $ControlRoot --manifest $manifest --defer-proof
  if ($LASTEXITCODE -ne 0) { throw 'Protected dispatcher activation failed.' }

  $definition = New-ArTrustedTaskDefinition -LauncherPath $launcher -InstallRoot $InstallRoot -Principal $Principal -Enabled $false
  Write-ArMutationIntent -Action 'REGISTER_DISABLED_PRODUCTION_TASK' -TargetPath $TaskName
  Register-ScheduledTask -TaskName $TaskName -InputObject $definition -Force -ErrorAction Stop | Out-Null
  $installedTaskSddl = Set-ArTrustedTaskSddl -TaskName $TaskName -OperatorSid $OperatorSid
  Assert-ArTrustedTask -TaskName $TaskName -LauncherPath $launcher -InstallRoot $InstallRoot -OperatorSid $OperatorSid -Enabled $false | Out-Null

  $probeMarker = Join-Path $InstallRoot 'probe.enabled'
  [IO.File]::WriteAllBytes($probeMarker, [Text.Encoding]::ASCII.GetBytes('PROBE'))
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
  Write-ArMutationIntent -Action 'REMOVE_DISPOSABLE_PROBE' -TargetPath $probeName
  Unregister-ScheduledTask -TaskName $probeName -Confirm:$false -ErrorAction Stop; $probeRegistered = $false
  Write-ArMutationIntent -Action 'REMOVE_PROBE_MARKER' -TargetPath $probeMarker
  Remove-Item -LiteralPath $probeMarker -Force -ErrorAction Stop
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
  $failure = $_.Exception.Message; $rollbackFailure = $null
  try {
    if ($probeRegistered) { Write-ArMutationIntent -Action 'ROLLBACK_REMOVE_PROBE' -TargetPath $probeName; Unregister-ScheduledTask -TaskName $probeName -Confirm:$false -ErrorAction Stop }
    if ($mutated) {
      Write-ArMutationIntent -Action 'ROLLBACK_RESTORE_PRODUCTION_TASK' -TargetPath $TaskName
      Restore-ArTrustedPriorTask -TaskName $TaskName -TaskXml $oldXml -TaskSddl $oldSddl
      $restoredXml = Join-Path $script:executionRoot 'rollback-task.xml'
      [IO.File]::WriteAllBytes($restoredXml, (Get-ArTrustedTaskXmlBytes $TaskName))
      if ((Get-ArTrustedSha256 $restoredXml) -cne $ExpectedOldTaskXmlSha256 -or (Get-ArTrustedTextSha256 (Get-ArTrustedTaskSddl $TaskName)) -cne $ExpectedOldTaskSddlSha256) { throw 'Rollback task differs from authenticated prestate.' }
      $restoredTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
      if ($restoredTask.State.ToString() -ne 'Ready' -or -not $restoredTask.Settings.Enabled) { throw 'Rollback did not restore a Ready enabled task.' }
    }
    if ($controlChanged) {
      Write-ArMutationIntent -Action 'ROLLBACK_RESTORE_CONTROL' -TargetPath $ControlRoot
      Remove-Item -LiteralPath $ControlRoot -Recurse -Force -ErrorAction Stop
      Copy-Item -LiteralPath $controlPrestate -Destination $ControlRoot -Recurse -ErrorAction Stop
    }
    foreach ($path in @($staging,$InstallRoot)) { if (Test-Path -LiteralPath $path) { Write-ArMutationIntent -Action 'ROLLBACK_REMOVE_NEW_ROOT' -TargetPath $path; Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop } }
  } catch { $rollbackFailure = $_.Exception.Message }
  $outcome = if ($null -eq $rollbackFailure) { 'ROLLED_BACK' } else { 'FAIL' }
  $message = if ($null -eq $rollbackFailure) { $failure } else { "$failure; rollback failed: $rollbackFailure" }
  Write-ArTrustedResult -Result $outcome -ErrorText $message -Detail @{} | Out-Null
  throw $message
}
