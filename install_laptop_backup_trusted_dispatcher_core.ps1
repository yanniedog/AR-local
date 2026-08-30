function Get-ArTrustedSha256 {
  param([Parameter(Mandatory = $true)][string]$Path)
  $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try { ([BitConverter]::ToString($algorithm.ComputeHash($stream)) -replace '-', '').ToLowerInvariant() }
  finally { $algorithm.Dispose(); $stream.Dispose() }
}

function Get-ArTrustedTextSha256 {
  param([Parameter(Mandatory = $true)][string]$Text)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try {
    $bytes = [Text.UTF8Encoding]::new($false).GetBytes($Text)
    ([BitConverter]::ToString($algorithm.ComputeHash($bytes)) -replace '-', '').ToLowerInvariant()
  } finally { $algorithm.Dispose() }
}

function Get-ArTrustedTaskXmlBytes {
  param([Parameter(Mandatory = $true)][string]$TaskName)
  [byte[]](0xff, 0xfe) + [Text.Encoding]::Unicode.GetBytes((Export-ScheduledTask -TaskName $TaskName -ErrorAction Stop))
}

function Get-ArTrustedTaskSddl {
  param([Parameter(Mandatory = $true)][string]$TaskName)
  $service = New-Object -ComObject 'Schedule.Service'
  $service.Connect()
  $service.GetFolder('\').GetTask("\$TaskName").GetSecurityDescriptor(7)
}

function Set-ArTrustedTaskSddl {
  param([Parameter(Mandatory = $true)][string]$TaskName, [Parameter(Mandatory = $true)][string]$OperatorSid)
  $sddl = "D:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;$OperatorSid)"
  $service = New-Object -ComObject 'Schedule.Service'
  $service.Connect()
  $service.GetFolder('\').GetTask("\$TaskName").SetSecurityDescriptor($sddl, 0)
  $actual = Get-ArTrustedTaskSddl $TaskName
  Assert-ArTrustedTaskSddl -Sddl $actual
  $actual
}

function Assert-ArTrustedTaskSddl {
  param([Parameter(Mandatory = $true)][string]$Sddl)
  $descriptor = New-Object Security.AccessControl.RawSecurityDescriptor($Sddl)
  if (($descriptor.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected) -eq 0) {
    throw 'Trusted task DACL is not protected.'
  }
  $dangerous = 0x40000000 -bor 0x00010000 -bor 0x00040000 -bor 0x00080000
  foreach ($ace in $descriptor.DiscretionaryAcl) {
    if ($ace -is [Security.AccessControl.CommonAce] -and
        $ace.AceQualifier -eq [Security.AccessControl.AceQualifier]::AccessAllowed -and
        ($ace.AccessMask -band $dangerous) -ne 0 -and
        $ace.SecurityIdentifier.Value -notin @('S-1-5-18','S-1-5-32-544')) {
      throw "Unprivileged task mutation right remains: $($ace.SecurityIdentifier.Value)"
    }
  }
}

function Assert-ArTrustedPlainPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  $full = [IO.Path]::GetFullPath($Path)
  $current = [IO.Path]::GetPathRoot($full)
  foreach ($part in $full.Substring($current.Length).Split(@([IO.Path]::DirectorySeparatorChar), [StringSplitOptions]::RemoveEmptyEntries)) {
    $current = Join-Path $current $part
    if (Test-Path -LiteralPath $current) {
      $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) { throw "Reparse point is forbidden: $current" }
    }
  }
  $full
}

function Invoke-ArTrustedSshScript {
  param(
    [Parameter(Mandatory = $true)][string]$SshPath,
    [Parameter(Mandatory = $true)][string]$HostName,
    [Parameter(Mandatory = $true)][string]$Script
  )
  if ($Script.Contains("`r")) { throw 'Remote script must contain LF only.' }
  $start = New-Object Diagnostics.ProcessStartInfo
  $start.FileName = $SshPath
  $start.Arguments = "-o BatchMode=yes -o ConnectTimeout=10 $HostName bash -s"
  $start.UseShellExecute = $false
  $start.RedirectStandardInput = $true
  $start.RedirectStandardOutput = $true
  $start.RedirectStandardError = $true
  $start.CreateNoWindow = $true
  $process = New-Object Diagnostics.Process
  $process.StartInfo = $start
  [void]$process.Start()
  $process.StandardInput.Write($Script)
  $process.StandardInput.Close()
  $stdout = $process.StandardOutput.ReadToEnd()
  $stderr = $process.StandardError.ReadToEnd()
  $process.WaitForExit()
  [pscustomobject]@{ ExitCode = $process.ExitCode; Stdout = $stdout; Stderr = $stderr }
}

function Expand-ArAuthenticatedPackage {
  param(
    [Parameter(Mandatory = $true)][string]$PackagePath,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][string]$Destination
  )
  Add-Type -AssemblyName System.IO.Compression
  $stream = [IO.File]::Open($PackagePath, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]::Read)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try {
    $actual = ([BitConverter]::ToString($algorithm.ComputeHash($stream)) -replace '-', '').ToLowerInvariant()
    if ($actual -cne $ExpectedSha256) { throw 'Trusted package hash mismatch.' }
    $stream.Position = 0
    $archive = New-Object IO.Compression.ZipArchive($stream, [IO.Compression.ZipArchiveMode]::Read, $true)
    try {
      $seen = @{}
      $root = [IO.Path]::GetFullPath($Destination).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
      foreach ($entry in $archive.Entries) {
        if ([String]::IsNullOrWhiteSpace($entry.Name)) { continue }
        $name = $entry.FullName.Replace('/', [IO.Path]::DirectorySeparatorChar)
        $target = [IO.Path]::GetFullPath((Join-Path $Destination $name))
        if (-not $target.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) { throw 'Trusted package entry escapes its root.' }
        $key = $target.ToLowerInvariant()
        if ($seen.ContainsKey($key)) { throw 'Trusted package contains a duplicate path.' }
        $seen[$key] = $true
        $parent = [IO.Path]::GetDirectoryName($target)
        New-Item -ItemType Directory -Path $parent -Force -ErrorAction Stop | Out-Null
        $input = $entry.Open()
        $output = [IO.File]::Open($target, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
        try { $input.CopyTo($output) } finally { $output.Dispose(); $input.Dispose() }
      }
    } finally { $archive.Dispose() }
  } finally { $algorithm.Dispose(); $stream.Dispose() }
}

function Assert-ArTrustedPackageManifest {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$InstallRoot,
    [Parameter(Mandatory = $true)][string]$CandidateCodeSha,
    [Parameter(Mandatory = $true)][string]$AuthorityCommit,
    [Parameter(Mandatory = $true)][string]$OperatorSid,
    [Parameter(Mandatory = $true)][string]$ControlRoot
  )
  $manifestPath = Join-Path $Root 'package-manifest.json'
  $manifest = Get-Content -LiteralPath $manifestPath -Raw -ErrorAction Stop | ConvertFrom-Json
  $fields = @('authority_commit','candidate_code_sha','control_root','files','install_root','operator_sid','schema_version')
  if ($manifest.schema_version -ne 1 -or @(Compare-Object $fields @($manifest.PSObject.Properties.Name | Sort-Object)).Count -ne 0 -or
      [string]$manifest.candidate_code_sha -cne $CandidateCodeSha -or [string]$manifest.authority_commit -cne $AuthorityCommit -or
      [string]$manifest.operator_sid -cne $OperatorSid -or
      [IO.Path]::GetFullPath([string]$manifest.install_root) -cne [IO.Path]::GetFullPath($InstallRoot) -or
      [IO.Path]::GetFullPath([string]$manifest.control_root) -cne [IO.Path]::GetFullPath($ControlRoot)) {
    throw 'Trusted package manifest identity is invalid.'
  }
  $expected = @{}
  foreach ($property in $manifest.files.PSObject.Properties) {
    if ($property.Name -eq 'package-manifest.json' -or [string]$property.Value -notmatch '^[0-9a-f]{64}$') {
      throw 'Trusted package file manifest is invalid.'
    }
    $expected[$property.Name.Replace('/', [IO.Path]::DirectorySeparatorChar).ToLowerInvariant()] = [string]$property.Value
  }
  $actual = @(Get-ChildItem -LiteralPath $Root -File -Recurse | Where-Object { $_.FullName -ne $manifestPath })
  if ($actual.Count -ne $expected.Count) { throw 'Trusted package file population differs from its manifest.' }
  foreach ($file in $actual) {
    $relative = $file.FullName.Substring(([IO.Path]::GetFullPath($Root).TrimEnd('\').Length + 1)).ToLowerInvariant()
    if (-not $expected.ContainsKey($relative) -or (Get-ArTrustedSha256 $file.FullName) -cne $expected[$relative]) {
      throw "Trusted package file hash mismatch: $relative"
    }
  }
  $manifest
}

function Set-ArTrustedRootAcl {
  param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$OperatorSid)
  $icacls = "$env:SystemRoot\System32\icacls.exe"
  & $icacls $Root '/setowner' '*S-1-5-32-544' '/T' '/C' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Failed to set trusted package owner.' }
  & $icacls $Root '/inheritance:r' '/grant:r' '*S-1-5-18:(OI)(CI)(F)' '*S-1-5-32-544:(OI)(CI)(F)' "*$OperatorSid`:(OI)(CI)(RX)" '/T' '/C' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Failed to protect trusted package ACL.' }
}

function Assert-ArTrustedRootAcl {
  param([Parameter(Mandatory = $true)][string]$Root)
  $dangerous = [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete -bor
    [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
    [Security.AccessControl.FileSystemRights]::TakeOwnership
  foreach ($path in @($Root) + @(Get-ChildItem -LiteralPath $Root -Force -Recurse | ForEach-Object FullName)) {
    $acl = Get-Acl -LiteralPath $path -ErrorAction Stop
    if (-not $acl.AreAccessRulesProtected) { throw "Trusted package ACL inherits: $path" }
    foreach ($rule in $acl.Access) {
      $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
      if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
          ($rule.FileSystemRights -band $dangerous) -and $sid -notin @('S-1-5-18','S-1-5-32-544')) {
        throw "Unprivileged write remains on trusted package: $sid"
      }
    }
  }
}

function New-ArTrustedTaskDefinition {
  param([string]$LauncherPath, [string]$InstallRoot, [string]$Principal, [bool]$Enabled = $false)
  $daily = New-ScheduledTaskTrigger -Daily -At '05:00'
  $startup = New-ScheduledTaskTrigger -AtStartup
  $startup.Delay = 'PT5M'
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 6) `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 30) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
  $settings.Enabled = $Enabled
  $taskPrincipal = New-ScheduledTaskPrincipal -UserId $Principal -LogonType S4U -RunLevel Limited
  $action = New-ScheduledTaskAction -Execute $LauncherPath -WorkingDirectory $InstallRoot
  New-ScheduledTask -Action $action -Trigger @($daily,$startup) -Settings $settings -Principal $taskPrincipal `
    -Description 'Runs the protected restricted-token AR-local laptop backup dispatcher.'
}

function Assert-ArTrustedTask {
  param(
    [string]$TaskName, [string]$LauncherPath, [string]$InstallRoot,
    [string]$OperatorSid, [bool]$Enabled,
    [scriptblock]$ResolvePrincipalSid = {
      param($UserId)
      ([Security.Principal.NTAccount]$UserId).Translate([Security.Principal.SecurityIdentifier]).Value
    }
  )
  $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $actions = @($task.Actions); $triggers = @($task.Triggers)
  $actualSid = & $ResolvePrincipalSid $task.Principal.UserId
  $daily = @($triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskDailyTrigger' })
  $boot = @($triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger' })
  $bad = @()
  if ($actions.Count -ne 1 -or $actions[0].Execute -cne $LauncherPath -or $actions[0].Arguments -or $actions[0].WorkingDirectory -cne $InstallRoot) { $bad += 'action' }
  if ($actualSid -cne $OperatorSid -or $task.Principal.LogonType.ToString() -ne 'S4U' -or $task.Principal.RunLevel.ToString() -ne 'Limited') { $bad += 'principal' }
  if ([bool]$task.Settings.Enabled -ne $Enabled -or $task.Settings.MultipleInstances.ToString() -ne 'IgnoreNew' -or
      $task.Settings.RestartCount -ne 3 -or $task.Settings.RestartInterval -ne 'PT30M' -or
      $task.Settings.ExecutionTimeLimit -ne 'PT6H' -or -not $task.Settings.StartWhenAvailable) { $bad += 'settings' }
  if ($triggers.Count -ne 2 -or $daily.Count -ne 1 -or ([datetimeoffset]$daily[0].StartBoundary).TimeOfDay -ne [timespan]::FromHours(5) -or
      $boot.Count -ne 1 -or $boot[0].Delay -ne 'PT5M') { $bad += 'triggers' }
  if ($bad.Count) { throw "Trusted task verification failed: $($bad -join ', ')." }
  $task
}

function Assert-ArTrustedProbeTask {
  param(
    [string]$TaskName, [string]$LauncherPath, [string]$InstallRoot, [string]$OperatorSid,
    [scriptblock]$ResolvePrincipalSid = {
      param($UserId)
      ([Security.Principal.NTAccount]$UserId).Translate([Security.Principal.SecurityIdentifier]).Value
    }
  )
  $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop
  $actions = @($task.Actions)
  $actualSid = & $ResolvePrincipalSid $task.Principal.UserId
  if ($actions.Count -ne 1 -or $actions[0].Execute -cne $LauncherPath -or $actions[0].Arguments -or
      $actions[0].WorkingDirectory -cne $InstallRoot -or $actualSid -cne $OperatorSid -or
      $task.Principal.LogonType.ToString() -ne 'S4U' -or $task.Principal.RunLevel.ToString() -ne 'Limited') {
    throw 'Disposable protected-token probe definition is invalid.'
  }
  $task
}

function Restore-ArTrustedPriorTask {
  param([string]$TaskName, [string]$TaskXml, [string]$TaskSddl)
  Register-ScheduledTask -TaskName $TaskName -Xml $TaskXml -Force -ErrorAction Stop | Out-Null
  $service = New-Object -ComObject 'Schedule.Service'; $service.Connect()
  $service.GetFolder('\').GetTask("\$TaskName").SetSecurityDescriptor($TaskSddl, 0)
}
