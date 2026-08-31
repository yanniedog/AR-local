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
  $contract = [ordered]@{ task_name='test'; expected_last_result=1; pre_execution_manifest_sha256='<SELF_SHA256>' }
  $contractHash = Get-ArTrustedInvocationContractSha256 $contract
  $contract.expected_last_result = 2
  if ((Get-ArTrustedInvocationContractSha256 $contract) -ceq $contractHash) { throw 'Invocation contract drift was accepted.' }
} finally { Remove-Item -LiteralPath $manifestPath -Force -ErrorAction SilentlyContinue }

$catalogRoot = Join-Path $env:TEMP ('ar-catalog-baseline-' + [guid]::NewGuid().ToString('N'))
try {
  $catalogDir = Join-Path $catalogRoot 'catalog'
  $receiptRelative = 'observations/2026-08-31/test/receipt.json'
  $receiptPath = Join-Path $catalogRoot $receiptRelative
  New-Item -ItemType Directory -Path $catalogDir,(Split-Path $receiptPath -Parent) -Force | Out-Null
  $archivePath = Join-Path (Split-Path $receiptPath -Parent) 'observation.tar.zst'
  [IO.File]::WriteAllBytes($archivePath,[Text.Encoding]::ASCII.GetBytes('archive'))
  $archiveHash = Get-ArTrustedSha256 $archivePath
  [IO.File]::WriteAllText($receiptPath,('{"archive_bytes":7,"archive_sha256":"' + $archiveHash + '","checks":{"observation":{"latest_pointer":{"generation_id":"obs-test"}}}}' + "`n"),[Text.UTF8Encoding]::new($false))
  $receiptHash = Get-ArTrustedSha256 $receiptPath
  $material = [ordered]@{ kind='observation'; previous_entry_sha256=$null; receipt_path=$receiptRelative; receipt_sha256=$receiptHash; sequence=1 }
  $entryHash = Get-ArTrustedTextSha256 ((ConvertTo-ArTrustedCanonicalJson $material) + "`n")
  $entry = [ordered]@{ entry_sha256=$entryHash; kind='observation'; previous_entry_sha256=$null; receipt_path=$receiptRelative; receipt_sha256=$receiptHash; sequence=1 }
  [IO.File]::WriteAllText((Join-Path $catalogDir 'generations.jsonl'),((ConvertTo-ArTrustedCanonicalJson $entry) + "`n"),[Text.UTF8Encoding]::new($false))
  $latest = [ordered]@{ catalog_entry_sha256=$entryHash; receipt_path=$receiptRelative; receipt_sha256=$receiptHash }
  [IO.File]::WriteAllText((Join-Path $catalogDir 'latest-verified.json'),((ConvertTo-ArTrustedCanonicalJson $latest) + "`n"),[Text.UTF8Encoding]::new($false))
  $catalogPath = Join-Path $catalogDir 'generations.jsonl'
  $latestPath = Join-Path $catalogDir 'latest-verified.json'
  $baseline = @{
    Target=$catalogRoot; ExpectedCatalogSha256=Get-ArTrustedSha256 $catalogPath; ExpectedCatalogSize=(Get-Item $catalogPath).Length
    ExpectedCatalogFinalSequence=1; ExpectedCatalogFinalEntrySha256=$entryHash
    ExpectedLatestVerifiedSha256=Get-ArTrustedSha256 $latestPath; ExpectedLatestVerifiedSize=(Get-Item $latestPath).Length
    ExpectedAcceptedCatalogEntrySha256=$entryHash
    ExpectedAcceptedReceiptRelativePath=$receiptRelative; ExpectedAcceptedReceiptSha256=$receiptHash
    ExpectedAcceptedReceiptSize=(Get-Item $receiptPath).Length; ExpectedAcceptedObservationId='obs-test'
    ExpectedAcceptedArchiveSha256=$archiveHash; ExpectedAcceptedArchiveSize=7
  }
  Assert-ArTrustedCatalogBaseline @baseline | Out-Null
  [IO.File]::AppendAllText($catalogPath,'drift',[Text.UTF8Encoding]::new($false))
  $rejected = $false
  try { Assert-ArTrustedCatalogBaseline @baseline | Out-Null } catch { $rejected = $true }
  if (-not $rejected) { throw 'Catalog drift was accepted.' }
} finally { Remove-Item -LiteralPath $catalogRoot -Recurse -Force -ErrorAction SilentlyContinue }

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if ($isAdmin) {
  $aclRoot = Join-Path $env:TEMP ('ar-trusted-acl-' + [guid]::NewGuid().ToString('N'))
  New-Item -ItemType Directory -Path $aclRoot -Force | Out-Null
  $operatorSidForAcl = [Security.Principal.WindowsIdentity]::GetCurrent().User.Value
  try {
    Set-ArTrustedRootAcl -Root $aclRoot -OperatorSid $operatorSidForAcl
    Assert-ArTrustedRootAcl -Root $aclRoot -OperatorSid $operatorSidForAcl
    & "$env:SystemRoot\System32\icacls.exe" $aclRoot '/deny' '*S-1-1-0:(RX)' | Out-Null
    $rejected = $false
    try { Assert-ArTrustedRootAcl -Root $aclRoot -OperatorSid $operatorSidForAcl } catch { $rejected = $true }
    if (-not $rejected) { throw 'Aggregate deny ACE was accepted.' }
    & "$env:SystemRoot\System32\icacls.exe" $aclRoot '/remove:d' '*S-1-1-0' | Out-Null
    & "$env:SystemRoot\System32\icacls.exe" $aclRoot '/remove:g' "*$operatorSidForAcl" | Out-Null
    $rejected = $false
    try { Assert-ArTrustedRootAcl -Root $aclRoot -OperatorSid $operatorSidForAcl } catch { $rejected = $true }
    if (-not $rejected) { throw 'Missing operator read/execute access was accepted.' }
  } finally { Remove-Item -LiteralPath $aclRoot -Recurse -Force -ErrorAction SilentlyContinue }
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

  $quarantineTestRoot = Join-Path $env:TEMP ('ar-short-quarantine-' + [guid]::NewGuid().ToString('N'))
  $evidenceName = 'AR-local-backup-evidence-' + ('a' * 40) + '-' + ('b' * 40)
  $evidenceRoot = Join-Path $quarantineTestRoot $evidenceName
  $priorExecution = Join-Path $evidenceRoot 'prior'
  $currentExecution = Join-Path $evidenceRoot 'current'
  $stagedExecution = Join-Path $evidenceRoot 'staged'
  $legacyExecution = Join-Path $evidenceRoot 'legacy'
  $source = Join-Path $quarantineTestRoot ('ARLBS-' + ('c' * 32))
  $destination = Join-Path $quarantineTestRoot ('ARLBQ-' + ('d' * 32))
  $orphanedStage = Join-Path $quarantineTestRoot ('ARLBS-' + ('f' * 32))
  try {
    New-Item -ItemType Directory -Path $priorExecution,$currentExecution,$stagedExecution,$legacyExecution,$source,$orphanedStage -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $source 'preserved.txt'),'preserved',[Text.UTF8Encoding]::new($false))
    [IO.File]::WriteAllText((Join-Path $orphanedStage 'orphaned.txt'),'orphaned',[Text.UTF8Encoding]::new($false))
    $journalLines = @(
      ([ordered]@{ at=[DateTimeOffset]::UtcNow.ToString('o'); action='ROLLBACK_QUARANTINE_NEW_ROOT'; target=$source } | ConvertTo-Json -Compress),
      ([ordered]@{ at=[DateTimeOffset]::UtcNow.ToString('o'); action='PUBLISH_SHORT_PROTECTED_QUARANTINE'; target=$destination } | ConvertTo-Json -Compress)
    )
    $priorJournal = Join-Path $priorExecution 'mutation-journal.jsonl'
    [IO.File]::WriteAllText($priorJournal,(($journalLines -join "`n") + "`n"),[Text.UTF8Encoding]::new($false))
    $stagedJournal = Join-Path $stagedExecution 'mutation-journal.jsonl'
    $stagedLine = [ordered]@{ at=[DateTimeOffset]::UtcNow.ToString('o'); action='CREATE_PACKAGE_STAGING'; target=$orphanedStage } | ConvertTo-Json -Compress
    [IO.File]::WriteAllText($stagedJournal,($stagedLine + "`n"),[Text.UTF8Encoding]::new($false))
    $legacyFailedRoot = Join-Path $legacyExecution ('failed-protected-root-' + ('9' * 32))
    New-Item -ItemType Directory -Path $legacyFailedRoot | Out-Null
    $legacySource = Join-Path $quarantineTestRoot ('AR-local-backup-trusted-' + ('1' * 40) + '-' + ('2' * 40) + '.staging-' + ('3' * 32))
    $legacyJournal = Join-Path $legacyExecution 'mutation-journal.jsonl'
    $legacyLines = @(
      ([ordered]@{ at=[DateTimeOffset]::UtcNow.ToString('o'); action='CREATE_PACKAGE_STAGING'; target=$legacySource } | ConvertTo-Json -Compress),
      ([ordered]@{ at=[DateTimeOffset]::UtcNow.ToString('o'); action='ROLLBACK_QUARANTINE_NEW_ROOT'; target=$legacySource } | ConvertTo-Json -Compress)
    )
    [IO.File]::WriteAllText($legacyJournal,(($legacyLines -join "`n") + "`n"),[Text.UTF8Encoding]::new($false))
    Set-ArTrustedRootAcl -Root $quarantineTestRoot -OperatorSid $operatorSidForAcl
    Set-ArTrustedRootAcl -Root $evidenceRoot -OperatorSid $operatorSidForAcl
    Set-ArTrustedRootAcl -Root $source -OperatorSid $operatorSidForAcl
    Set-ArTrustedRootAcl -Root $orphanedStage -OperatorSid $operatorSidForAcl
    & "$env:SystemRoot\System32\icacls.exe" $priorJournal '/inheritance:e' '/C' | Out-Null
    if ($LASTEXITCODE -ne 0 -or (Get-Acl -LiteralPath $priorJournal).AreAccessRulesProtected) {
      throw 'Failed to create inherited legacy-journal fixture.'
    }
    & "$env:SystemRoot\System32\icacls.exe" $orphanedStage '/inheritance:e' '/T' '/C' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Failed to create inherited staging fixture.' }
    $script:OperatorSid = $operatorSidForAcl
    $script:bootstrapGate = [object]::new()
    $script:executionRoot = $currentExecution
    Assert-ArTrustedShortQuarantineState -OperatorSid $operatorSidForAcl -ProgramFilesRoot $quarantineTestRoot | Out-Null
    $recoveryState = [ordered]@{
      source_exists=Test-Path -LiteralPath $source
      destination_file_exists=Test-Path -LiteralPath (Join-Path $destination 'preserved.txt')
      orphaned_stage_exists=Test-Path -LiteralPath $orphanedStage
      quarantine_roots=@(Get-ChildItem -LiteralPath $quarantineTestRoot -Directory | Where-Object { $_.Name -match '^ARLBQ-' } | ForEach-Object Name)
      reconciliation_exists=Test-Path -LiteralPath (Join-Path $currentExecution 'short-quarantine-reconciliation.json')
    }
    if ($recoveryState.source_exists -or -not $recoveryState.destination_file_exists -or
        $recoveryState.orphaned_stage_exists -or $recoveryState.quarantine_roots.Count -ne 2 -or
        -not $recoveryState.reconciliation_exists) {
      throw ('Journaled short quarantine was not recovered and sealed: ' + ($recoveryState | ConvertTo-Json -Compress))
    }
    Assert-ArTrustedSinglePathAcl -Path $priorJournal -OperatorSid $operatorSidForAcl
    $reconciliation = Get-Content -LiteralPath (Join-Path $currentExecution 'short-quarantine-reconciliation.json') -Raw | ConvertFrom-Json
    $legacyRecords = @($reconciliation.legacy_closed_staging)
    $legacyRecord = $legacyRecords | Select-Object -First 1
    $expectedLegacySource = [IO.Path]::GetFullPath($legacySource)
    $legacyChecks = [ordered]@{
      count=(@($legacyRecords).Count -eq 1)
      source=[string]::Equals([string]($legacyRecord.source_path),$expectedLegacySource,[StringComparison]::Ordinal)
      absent=([bool]($legacyRecord.source_absent) -eq $true); line=([int]($legacyRecord.source_line) -eq 2)
      trust=[string]::Equals([string]($legacyRecord.preserved_content_trust),'UNTRUSTED_OPAQUE_NOT_CONSUMED',[StringComparison]::Ordinal)
    }
    if (@($legacyChecks.Values | Where-Object { -not $_ }).Count -gt 0) {
      throw ('Closed legacy long staging journal was not preserved in reconciliation evidence: ' +
        ([ordered]@{ checks=$legacyChecks; record=$legacyRecord; expected_source=$expectedLegacySource } | ConvertTo-Json -Compress -Depth 5))
    }
    foreach ($item in @($reconciliation.transactions)) {
      if ([string]::IsNullOrWhiteSpace([string]$item.source_journal_prefix_sha256) -or [long]$item.source_journal_prefix_bytes -lt 1) {
        throw 'Reconciliation did not bind an immutable journal prefix.'
      }
      $identity = Get-ArTrustedJournalPrefixIdentity -Path ([string]$item.source_journal) -LineCount ([int]$item.source_line)
      if ($identity.sha256 -cne [string]$item.source_journal_prefix_sha256 -or
          $identity.bytes -ne [long]$item.source_journal_prefix_bytes) {
        throw 'Reconciliation journal prefix identity did not survive later appends.'
      }
    }
    $nextExecution = Join-Path $evidenceRoot 'next'
    New-Item -ItemType Directory -Path $nextExecution | Out-Null
    Set-ArTrustedRootAcl -Root $nextExecution -OperatorSid $operatorSidForAcl
    $script:executionRoot = $nextExecution
    Assert-ArTrustedShortQuarantineState -OperatorSid $operatorSidForAcl -ProgramFilesRoot $quarantineTestRoot | Out-Null
    $orphan = Join-Path $quarantineTestRoot ('ARLBS-' + ('e' * 32))
    New-Item -ItemType Directory -Path $orphan | Out-Null
    Set-ArTrustedRootAcl -Root $orphan -OperatorSid $operatorSidForAcl
    $blockedExecution = Join-Path $evidenceRoot 'blocked'
    New-Item -ItemType Directory -Path $blockedExecution | Out-Null
    Set-ArTrustedRootAcl -Root $blockedExecution -OperatorSid $operatorSidForAcl
    $script:executionRoot = $blockedExecution
    $rejected = $false
    try {
      Assert-ArTrustedShortQuarantineState -OperatorSid $operatorSidForAcl -ProgramFilesRoot $quarantineTestRoot | Out-Null
    } catch { if ($_.Exception.Message -notmatch 'Unjournaled short bootstrap') { throw }; $rejected = $true }
    if (-not $rejected) { throw 'Unjournaled short bootstrap root was accepted.' }
    Remove-Item -LiteralPath $orphan -Recurse -Force
    $legacyJournalOriginal = [IO.File]::ReadAllBytes($legacyJournal)
    $duplicateLine = ([ordered]@{ at=[DateTimeOffset]::UtcNow.ToString('o'); action='CREATE_PACKAGE_STAGING'; target=$legacySource } | ConvertTo-Json -Compress)
    [IO.File]::AppendAllText($legacyJournal,($duplicateLine + "`n"),[Text.UTF8Encoding]::new($false))
    $script:executionRoot = $blockedExecution
    $rejected = $false
    try { Assert-ArTrustedShortQuarantineState -OperatorSid $operatorSidForAcl -ProgramFilesRoot $quarantineTestRoot | Out-Null
    } catch { if ($_.Exception.Message -notmatch 'Legacy long staging source is duplicated') { throw }; $rejected = $true }
    if (-not $rejected) { throw 'Duplicated legacy staging source was accepted.' }
    [IO.File]::WriteAllBytes($legacyJournal,$legacyJournalOriginal)
    [IO.File]::AppendAllText($legacyJournal,"`n",[Text.UTF8Encoding]::new($false))
    $rejected = $false
    try { Assert-ArTrustedShortQuarantineState -OperatorSid $operatorSidForAcl -ProgramFilesRoot $quarantineTestRoot | Out-Null
    } catch { if ($_.Exception.Message -notmatch 'empty physical line') { throw }; $rejected = $true }
    if (-not $rejected) { throw 'Blank physical journal line was accepted.' }
  } finally {
    Remove-Item -LiteralPath $quarantineTestRoot -Recurse -Force -ErrorAction SilentlyContinue
  }

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
