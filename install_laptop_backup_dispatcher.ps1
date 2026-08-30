param(
  [string]$TaskName = 'AR-local laptop backup',
  [Parameter(Mandatory = $true)][string]$SourceRoot,
  [Parameter(Mandatory = $true)][string]$Receiver,
  [Parameter(Mandatory = $true)][string]$Target,
  [Parameter(Mandatory = $true)][string]$ControlRoot,
  [Parameter(Mandatory = $true)][string]$ManifestPath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ManifestSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$CandidateCodeSha,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{40}$')][string]$ProtectedCodeSha,
  [Parameter(Mandatory = $true)][string]$Operator,
  [Parameter(Mandatory = $true)][string]$Principal,
  [Parameter(Mandatory = $true)][string]$OperatorSid,
  [Parameter(Mandatory = $true)][string]$PythonPath,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedOldTaskXmlSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$ExpectedOldTaskSddlSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$DispatcherSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$AtomicModuleSha256,
  [Parameter(Mandatory = $true)][ValidatePattern('^[0-9a-f]{64}$')][string]$RunnerSha256,
  [Parameter(Mandatory = $true)][string]$EvidenceRoot,
  [string]$InstallRoot = "$env:ProgramFiles\AR-local Backup Dispatcher",
  [string]$PiHost = 'ar-local-pi5-lan'
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'install_laptop_backup_dispatcher_core.ps1')

function Write-ArBootstrapResult {
  param([string]$Result, [string]$ErrorText, [hashtable]$Evidence)
  $files = @()
  foreach ($file in @(Get-ChildItem -LiteralPath $script:executionRoot -File -Recurse | Sort-Object FullName)) {
    $files += [ordered]@{
      path = $file.FullName
      sha256 = Get-ArSha256 $file.FullName
      size = $file.Length
    }
  }
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
    operator = $Operator
    task_name = $TaskName
    manifest_sha256 = $ManifestSha256
    timestamps = [ordered]@{
      started_at = $script:startedAt
      completed_at = [DateTimeOffset]::UtcNow.ToString('o')
    }
    exact_commands = @($script:exactCommand)
    result = $Result
    error = $ErrorText
    evidence = $Evidence
    evidence_files = $files
    deviations = @()
    deviation_authorization = $null
  }
  $path = Join-Path $script:executionRoot 'bootstrap-result.json'
  $json = $payload | ConvertTo-Json -Depth 12 -Compress
  [IO.File]::WriteAllText($path, $json + "`n", [Text.UTF8Encoding]::new($false))
  $path
}

function Invoke-ArLimitedProbe {
  param([string]$DispatcherPath, [string]$ProbeOutput)
  $probeName = "AR-local dispatcher probe $([guid]::NewGuid().ToString('N'))"
  $probeArgs = @(
    ('"{0}"' -f $DispatcherPath), 'probe',
    '--control-root', ('"{0}"' -f $ControlRoot),
    '--output', ('"{0}"' -f $ProbeOutput)
  ) -join ' '
  $action = New-ScheduledTaskAction -Execute $PythonPath -Argument $probeArgs -WorkingDirectory $InstallRoot
  $settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  $principal = New-ScheduledTaskPrincipal -UserId $Principal -LogonType S4U -RunLevel Limited
  $task = New-ScheduledTask -Action $action -Settings $settings -Principal $principal `
    -Description 'One-time limited-token AR-local dispatcher semantic probe.'
  try {
    Register-ScheduledTask -TaskName $probeName -InputObject $task -Force -ErrorAction Stop | Out-Null
    Start-ScheduledTask -TaskName $probeName -ErrorAction Stop
    $deadline = [DateTimeOffset]::Now.AddMinutes(2)
    do {
      Start-Sleep -Seconds 1
      $info = Get-ScheduledTaskInfo -TaskName $probeName -ErrorAction Stop
      $state = (Get-ScheduledTask -TaskName $probeName -ErrorAction Stop).State.ToString()
    } while ($state -eq 'Running' -and [DateTimeOffset]::Now -lt $deadline)
    if ($state -eq 'Running' -or $info.LastTaskResult -ne 0) { throw 'Limited semantic probe did not complete successfully.' }
    $value = Get-Content -LiteralPath $ProbeOutput -Raw -ErrorAction Stop | ConvertFrom-Json -AsHashtable
    if ($value.ok -ne $true -or $value.result -ne 'PASS' -or $value.is_admin -ne $false -or
        ([string]$value.operator_sid).ToLowerInvariant() -ne $OperatorSid.ToLowerInvariant() -or
        $value.manifest_sha256 -ne $ManifestSha256) {
      throw 'Limited semantic probe identity is invalid.'
    }
    return $value
  } finally {
    Unregister-ScheduledTask -TaskName $probeName -Confirm:$false -ErrorAction SilentlyContinue
  }
}

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) { throw 'The one-time dispatcher bootstrap requires an elevated Windows process.' }
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if ($identity.Name.ToLowerInvariant() -ne $Principal.ToLowerInvariant() -or $identity.User.Value -ne $OperatorSid) {
  throw 'Elevated bootstrap identity does not match the authorised operator.'
}
$local = [DateTimeOffset]::Now
if ($local.TimeOfDay -lt [TimeSpan]::FromHours(3.5) -or $local.TimeOfDay -ge [TimeSpan]::FromHours(22)) {
  throw 'Dispatcher bootstrap is outside the D-006 daylight window.'
}

foreach ($path in @($SourceRoot, $Receiver, $Target, $ControlRoot, $EvidenceRoot)) {
  if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw "Required directory is missing: $path" }
}
foreach ($path in @($ManifestPath, $PythonPath)) {
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Required file is missing: $path" }
}
if ((Get-ArSha256 $ManifestPath) -cne $ManifestSha256) { throw 'Initial manifest hash mismatch.' }
$script:manifest = Get-Content -LiteralPath $ManifestPath -Raw -ErrorAction Stop | ConvertFrom-Json -AsHashtable
$script:startedAt = [DateTimeOffset]::UtcNow.ToString('o')
$script:exactCommand = (Get-CimInstance Win32_Process -Filter "ProcessId=$PID").CommandLine
if ((git -C $Receiver rev-parse HEAD).Trim() -ne $CandidateCodeSha -or (git -C $Receiver status --porcelain)) {
  throw 'Receiver is not clean at the exact candidate commit.'
}
$free = (Get-PSDrive -Name ([IO.Path]::GetPathRoot($Target).Substring(0, 1))).Free
if ($free -lt 50GB) { throw 'Laptop free space is below 50 GiB.' }
$activeProcesses = @(Get-CimInstance Win32_Process | Where-Object {
  $_.ProcessId -ne $PID -and $_.CommandLine -match 'laptop_backup_(scheduled|transition)|laptop_pull_backup'
})
if ($activeProcesses.Count -gt 0) { throw 'A laptop backup or transition process is already active.' }

$piCheck = @"
set -eu
cd /srv/ar-local/AR-local
test "`$(git rev-parse HEAD)" = '$ProtectedCodeSha'
test -z "`$(git status --porcelain)"
! systemctl is-active --quiet ar-local-daily.service
test ! -e /srv/ar-local/data/state/daily-ingest.lock
curl -fsS --max-time 10 http://127.0.0.1:8808/api/latest >/dev/null
"@
& ssh -o BatchMode=yes -o ConnectTimeout=10 $PiHost $piCheck
if ($LASTEXITCODE -ne 0) { throw 'Pi bootstrap preflight failed.' }

New-Item -ItemType Directory -Path $EvidenceRoot -Force | Out-Null
$executionId = [DateTimeOffset]::UtcNow.ToString('yyyyMMddTHHmmssZ') + '-' + [guid]::NewGuid().ToString('N')
$script:executionRoot = Join-Path (Join-Path $EvidenceRoot 'executions') $executionId
New-Item -ItemType Directory -Path $script:executionRoot -ErrorAction Stop | Out-Null
$fileHashes = @{
  'laptop_backup_dispatcher.py' = $DispatcherSha256
  'laptop_backup_atomic.py' = $AtomicModuleSha256
  'run_laptop_backup_dispatcher.ps1' = $RunnerSha256
}
$taskArguments = Get-ArDispatcherTaskArguments -InstallRoot $InstallRoot -PythonPath $PythonPath -ControlRoot $ControlRoot
$dispatcherPath = Join-Path $InstallRoot 'laptop_backup_dispatcher.py'
$probeOutput = Join-Path $script:executionRoot 'limited-probe.json'
$evidence = @{}
$mutated = $false
$installedFiles = $false
$activated = $false
$oldXml = $null
$oldSddl = $null

try {
  if (Test-Path -LiteralPath $InstallRoot) {
    foreach ($name in $fileHashes.Keys) {
      if ((Get-ArSha256 (Join-Path $InstallRoot $name)) -cne $fileHashes[$name]) { throw 'Installed dispatcher state is partial or drifted.' }
    }
    Assert-ArProtectedDispatcherAcl -InstallRoot $InstallRoot -OperatorSid $OperatorSid
    Assert-ArDispatcherTask -TaskName $TaskName -ExpectedArguments $taskArguments `
      -ExpectedWorkingDirectory $InstallRoot -ExpectedPrincipalSid $OperatorSid -ExpectedEnabled $true | Out-Null
    $probe = Invoke-ArLimitedProbe -DispatcherPath $dispatcherPath -ProbeOutput $probeOutput
    $resultPath = Write-ArBootstrapResult -Result 'PASS' -ErrorText $null -Evidence @{
      mode = 'ALREADY_INSTALLED'; probe = $probe; free_bytes = $free
    }
    Get-Content -LiteralPath $resultPath -Raw
    exit 0
  }

  foreach ($name in @('manifests', 'activation-receipts', 'lease-recoveries', 'active-runner.json', 'transition.lease')) {
    if (Test-Path -LiteralPath (Join-Path $ControlRoot $name)) {
      throw 'Unexplained dispatcher control state exists before initial bootstrap.'
    }
  }

  $oldTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $oldInfo = Get-ScheduledTaskInfo -TaskName $TaskName -ErrorAction Stop
  if ($oldTask.State.ToString() -ne 'Ready' -or -not $oldTask.Settings.Enabled -or $oldInfo.LastTaskResult -ne 0) {
    throw 'Existing laptop backup task is not Ready, enabled, and successful.'
  }
  $oldXml = Export-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $oldXmlBytes = Get-ArTaskXmlBytes -TaskName $TaskName
  $oldXmlPath = Join-Path $script:executionRoot 'pre-bootstrap-task.xml'
  [IO.File]::WriteAllBytes($oldXmlPath, $oldXmlBytes)
  if ((Get-ArSha256 $oldXmlPath) -cne $ExpectedOldTaskXmlSha256) { throw 'Existing task XML is not the accepted artifact.' }
  $oldSddl = Get-ArTaskSddl -TaskName $TaskName
  if ((Get-ArTextSha256 $oldSddl) -cne $ExpectedOldTaskSddlSha256) { throw 'Existing task SDDL is not the accepted artifact.' }
  [IO.File]::WriteAllText((Join-Path $script:executionRoot 'pre-bootstrap-task.sddl'), $oldSddl, [Text.UTF8Encoding]::new($false))

  Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
  $mutated = $true
  $disabledTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  if ($disabledTask.State.ToString() -ne 'Disabled' -or $disabledTask.Settings.Enabled) {
    throw 'Existing laptop backup task did not become quiescent and disabled.'
  }
  $activeAfterDisable = @(Get-CimInstance Win32_Process | Where-Object {
    $_.ProcessId -ne $PID -and $_.CommandLine -match 'laptop_backup_(scheduled|transition)|laptop_pull_backup'
  })
  if ($activeAfterDisable.Count -gt 0) { throw 'A laptop backup process appeared during task quiescence.' }
  Install-ArProtectedDispatcherFiles -SourceRoot $SourceRoot -InstallRoot $InstallRoot `
    -OperatorSid $OperatorSid -ExpectedHashes $fileHashes
  $installedFiles = $true

  & $PythonPath $dispatcherPath activate --control-root $ControlRoot --manifest $ManifestPath
  if ($LASTEXITCODE -ne 0) { throw 'Initial dispatcher manifest activation failed.' }
  $activated = $true

  $definition = New-ArDispatcherTaskDefinition -InstallRoot $InstallRoot -Arguments $taskArguments -Operator $Principal
  Register-ScheduledTask -TaskName $TaskName -InputObject $definition -Force -ErrorAction Stop | Out-Null
  Assert-ArDispatcherTask -TaskName $TaskName -ExpectedArguments $taskArguments `
    -ExpectedWorkingDirectory $InstallRoot -ExpectedPrincipalSid $OperatorSid -ExpectedEnabled $false | Out-Null
  $probe = Invoke-ArLimitedProbe -DispatcherPath $dispatcherPath -ProbeOutput $probeOutput
  Enable-ScheduledTask -TaskName $TaskName -ErrorAction Stop | Out-Null
  Assert-ArDispatcherTask -TaskName $TaskName -ExpectedArguments $taskArguments `
    -ExpectedWorkingDirectory $InstallRoot -ExpectedPrincipalSid $OperatorSid -ExpectedEnabled $true | Out-Null
  $postXml = Join-Path $script:executionRoot 'installed-task.xml'
  [IO.File]::WriteAllBytes($postXml, (Get-ArTaskXmlBytes -TaskName $TaskName))
  $postSddl = Get-ArTaskSddl -TaskName $TaskName
  [IO.File]::WriteAllText((Join-Path $script:executionRoot 'installed-task.sddl'), $postSddl, [Text.UTF8Encoding]::new($false))
  $evidence = @{
    mode = 'INSTALLED'; probe = $probe; free_bytes = $free
    old_task_xml_sha256 = $ExpectedOldTaskXmlSha256
    old_task_sddl_sha256 = $ExpectedOldTaskSddlSha256
    installed_task_xml_sha256 = Get-ArSha256 $postXml
    installed_task_sddl_sha256 = Get-ArTextSha256 $postSddl
    dispatcher_sha256 = Get-ArSha256 $dispatcherPath
  }
  $resultPath = Write-ArBootstrapResult -Result 'PASS' -ErrorText $null -Evidence $evidence
  Get-Content -LiteralPath $resultPath -Raw
} catch {
  $failure = $_.Exception.Message
  if ($mutated -and $null -ne $oldXml -and $null -ne $oldSddl) {
    try {
      Restore-ArPriorTask -TaskName $TaskName -TaskXml $oldXml -TaskSddl $oldSddl
      $rollback = Join-Path $script:executionRoot 'rollback'
      New-Item -ItemType Directory -Path $rollback -Force | Out-Null
      if ($installedFiles -and (Test-Path -LiteralPath $InstallRoot)) {
        Move-Item -LiteralPath $InstallRoot -Destination (Join-Path $rollback 'dispatcher-install') -ErrorAction Stop
      }
      if ($activated) {
        $controlRollback = Join-Path $rollback 'dispatcher-control'
        New-Item -ItemType Directory -Path $controlRollback -Force | Out-Null
        foreach ($name in @('manifests', 'activation-receipts', 'lease-recoveries', 'active-runner.json', 'transition.lease')) {
          $item = Join-Path $ControlRoot $name
          if (Test-Path -LiteralPath $item) { Move-Item -LiteralPath $item -Destination $controlRollback -ErrorAction Stop }
        }
      }
      $resultPath = Write-ArBootstrapResult -Result 'ROLLED_BACK' -ErrorText $failure -Evidence @{ rollback_path = $rollback }
      Get-Content -LiteralPath $resultPath -Raw
    } catch {
      $rollbackFailure = $_.Exception.Message
      Write-ArBootstrapResult -Result 'FAIL' -ErrorText "$failure; rollback failed: $rollbackFailure" -Evidence @{} | Out-Null
      throw
    }
  }
  throw
}
