if (-not ('ArTrustedMoveFile' -as [type])) {
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ArTrustedMoveFile {
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  public static extern bool MoveFileEx(string existingName, string newName, uint flags);
}
'@
}

function Move-ArTrustedFileWriteThrough {
  param([Parameter(Mandatory = $true)][string]$Source, [Parameter(Mandatory = $true)][string]$Destination)
  if (Test-Path -LiteralPath $Destination) { throw "Write-through destination already exists: $Destination" }
  if (-not [ArTrustedMoveFile]::MoveFileEx($Source,$Destination,0x00000008)) {
    throw [ComponentModel.Win32Exception]::new([Runtime.InteropServices.Marshal]::GetLastWin32Error())
  }
}

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

function Get-ArTrustedSddlBinarySha256 {
  param([Parameter(Mandatory = $true)][string]$Sddl)
  $descriptor = New-Object Security.AccessControl.RawSecurityDescriptor($Sddl)
  $bytes = New-Object byte[] $descriptor.BinaryLength
  $descriptor.GetBinaryForm($bytes,0)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try { ([BitConverter]::ToString($algorithm.ComputeHash($bytes)) -replace '-','').ToLowerInvariant() }
  finally { $algorithm.Dispose() }
}

function Read-ArTrustedPreExecutionManifest {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256
  )
  $stream = [IO.File]::Open($Path,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try {
    $actual = ([BitConverter]::ToString($algorithm.ComputeHash($stream)) -replace '-','').ToLowerInvariant()
    if ($actual -cne $ExpectedSha256) { throw 'Pre-execution manifest hash mismatch.' }
    $stream.Position = 0
    $reader = New-Object IO.StreamReader($stream,[Text.UTF8Encoding]::new($false),$true,4096,$true)
    try { $text = $reader.ReadToEnd() } finally { $reader.Dispose() }
  } finally { $algorithm.Dispose(); $stream.Dispose() }
  $value = $text | ConvertFrom-Json
  if ($null -eq $value -or $value -is [Array]) { throw 'Pre-execution manifest is not one object.' }
  $value
}

function Assert-ArTrustedPreExecutionManifest {
  param(
    [Parameter(Mandatory = $true)]$Manifest,
    [Parameter(Mandatory = $true)][Collections.Specialized.OrderedDictionary]$Expected,
    [switch]$RequireFresh
  )
  $required = @($Expected.Keys | ForEach-Object { [string]$_ }) + @('created_at','expires_at')
  $actual = @($Manifest.PSObject.Properties.Name)
  if ((Compare-Object ($required | Sort-Object) ($actual | Sort-Object))) { throw 'Pre-execution manifest fields are not exact.' }
  foreach ($key in $Expected.Keys) {
    $value = $Manifest.$key
    if ($Expected[$key] -is [int] -or $Expected[$key] -is [long]) {
      if ($null -eq $value -or ($value -isnot [int] -and $value -isnot [long]) -or [long]$value -ne [long]$Expected[$key]) {
        throw "Pre-execution manifest identity or type differs: $key"
      }
    } elseif ($value -isnot [string] -or $value -cne [string]$Expected[$key]) {
      throw "Pre-execution manifest identity or type differs: $key"
    }
  }
  try {
    $created = [DateTimeOffset]::ParseExact([string]$Manifest.created_at,'o',[Globalization.CultureInfo]::InvariantCulture)
    $expires = [DateTimeOffset]::ParseExact([string]$Manifest.expires_at,'o',[Globalization.CultureInfo]::InvariantCulture)
  } catch { throw 'Pre-execution manifest timestamps are invalid.' }
  $now = [DateTimeOffset]::UtcNow
  if ($created.Offset -ne [TimeSpan]::Zero -or $expires.Offset -ne [TimeSpan]::Zero -or $expires -le $created) {
    throw 'Pre-execution manifest timestamps are structurally invalid.'
  }
  if ($RequireFresh -and ($created -gt $now.AddMinutes(5) -or $now -ge $expires)) {
    throw 'Pre-execution manifest is expired or outside allowed clock skew.'
  }
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

function Get-ArTrustedSddlSemanticSha256 {
  param([Parameter(Mandatory = $true)][string]$Sddl)
  $descriptor = New-Object Security.AccessControl.RawSecurityDescriptor($Sddl)
  $aces = @()
  foreach ($ace in $descriptor.DiscretionaryAcl) {
    if ($ace -isnot [Security.AccessControl.QualifiedAce] -or $ace -isnot [Security.AccessControl.KnownAce]) {
      throw 'Task SDDL contains an unsupported ACE type.'
    }
    # Inheritance provenance is security-significant even when the current
    # effective access mask is identical.  Preserve every ACE flag so rollback
    # cannot silently replace inherited rights with explicit rights (or vice
    # versa) while retaining the same semantic digest.
    $flags = [int]$ace.AceFlags
    $objectType = if ($ace -is [Security.AccessControl.ObjectAce]) { [string]$ace.ObjectAceType } else { '' }
    $inheritedType = if ($ace -is [Security.AccessControl.ObjectAce]) { [string]$ace.InheritedObjectAceType } else { '' }
    $opaque = if ($ace.OpaqueLength -gt 0) { [BitConverter]::ToString($ace.GetOpaque()) -replace '-', '' } else { '' }
    $aces += '{0}|{1}|{2}|{3}|{4}|{5}|{6}' -f $ace.AceQualifier,$flags,$ace.AccessMask,
      $ace.SecurityIdentifier.Value,$objectType,$inheritedType,$opaque
  }
  $value = [ordered]@{
    owner = if ($null -ne $descriptor.Owner) { $descriptor.Owner.Value } else { $null }
    group = if ($null -ne $descriptor.Group) { $descriptor.Group.Value } else { $null }
    dacl_protected = (($descriptor.ControlFlags -band [Security.AccessControl.ControlFlags]::DiscretionaryAclProtected) -ne 0)
    aces = @($aces | Sort-Object)
  }
  Get-ArTrustedTextSha256 (($value | ConvertTo-Json -Depth 5 -Compress))
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
  if ($HostName.Length -gt 253 -or $HostName -notmatch '^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$' -or $HostName.Contains('..')) {
    throw 'SSH host must be one strict hostname or IPv4 token.'
  }
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
    [Parameter(Mandatory = $true)][string]$ControlRoot,
    [string[]]$AllowedRuntimeFiles = @()
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
  $allowedRuntime = @($AllowedRuntimeFiles | ForEach-Object {
    if ([IO.Path]::GetFileName($_) -cne $_) { throw 'Allowed runtime package file must be one fixed file name.' }
    $_.ToLowerInvariant()
  })
  $actual = @(Get-ChildItem -LiteralPath $Root -File -Recurse | Where-Object {
    $relative = $_.FullName.Substring(([IO.Path]::GetFullPath($Root).TrimEnd('\').Length + 1)).ToLowerInvariant()
    $_.FullName -ne $manifestPath -and $relative -notin $allowedRuntime
  })
  if ($actual.Count -ne $expected.Count) { throw 'Trusted package file population differs from its manifest.' }
  foreach ($file in $actual) {
    $relative = $file.FullName.Substring(([IO.Path]::GetFullPath($Root).TrimEnd('\').Length + 1)).ToLowerInvariant()
    if (-not $expected.ContainsKey($relative) -or (Get-ArTrustedSha256 $file.FullName) -cne $expected[$relative]) {
      throw "Trusted package file hash mismatch: $relative"
    }
  }
  $manifest
}

function Assert-ArTrustedChildConfiguration {
  param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$ControlRoot)
  $path = Join-Path $Root 'trusted-child.json'
  $config = Get-Content -LiteralPath $path -Raw -ErrorAction Stop | ConvertFrom-Json
  $fields = @(
    'atomic_path','atomic_sha256','authority_path','control_root','dispatcher_path','dispatcher_sha256',
    'git_path','git_sha256','python_path','python_sha256','schema_version',
    'receiver_path','scp_path','scp_sha256','ssh_path','ssh_sha256','whoami_path','whoami_sha256'
  )
  if ($config.schema_version -ne 3 -or @(Compare-Object $fields @($config.PSObject.Properties.Name | Sort-Object)).Count -ne 0 -or
      [IO.Path]::GetFullPath([string]$config.control_root) -cne [IO.Path]::GetFullPath($ControlRoot)) {
    throw 'Trusted child configuration identity is invalid.'
  }
  $internal = @(
    @('python_path','python_sha256','python\python.exe'),
    @('dispatcher_path','dispatcher_sha256','laptop_backup_dispatcher.py'),
    @('atomic_path','atomic_sha256','laptop_backup_atomic.py')
  )
  foreach ($item in $internal) {
    $actualPath = Assert-ArTrustedPlainPath ([string]$config.($item[0]))
    if ($actualPath -cne (Join-Path $Root $item[2]) -or (Get-ArTrustedSha256 $actualPath) -cne [string]$config.($item[1])) {
      throw "Trusted internal dependency is invalid: $($item[0])"
    }
  }
  foreach ($name in @('receiver_path','authority_path')) {
    $checkout = Assert-ArTrustedPlainPath ([string]$config.$name)
    $prefix = [IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    if (-not $checkout.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase) -or -not (Test-Path -LiteralPath $checkout -PathType Container)) {
      throw "Trusted checkout is invalid: $name"
    }
  }
  $system = [Environment]::GetFolderPath([Environment+SpecialFolder]::System)
  $programRoots = @([Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles),[Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)) | Where-Object { $_ }
  $tools = @(
    @('git_path','git_sha256','git.exe',$programRoots),
    @('ssh_path','ssh_sha256','ssh.exe',@($system)),
    @('scp_path','scp_sha256','scp.exe',@($system)),
    @('whoami_path','whoami_sha256','whoami.exe',@($system))
  )
  foreach ($item in $tools) {
    $actualPath = Assert-ArTrustedPlainPath ([string]$config.($item[0]))
    $allowed = $false
    foreach ($allowedRoot in $item[3]) {
      $prefix = [IO.Path]::GetFullPath([string]$allowedRoot).TrimEnd('\') + '\'
      if ($actualPath.StartsWith($prefix,[StringComparison]::OrdinalIgnoreCase)) { $allowed = $true }
    }
    if (-not $allowed -or [IO.Path]::GetFileName($actualPath) -ine $item[2] -or
        (Get-ArTrustedSha256 $actualPath) -cne [string]$config.($item[1])) {
      throw "Trusted external tool is invalid: $($item[2])"
    }
  }
  $config
}

function Set-ArTrustedRootAcl {
  param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$OperatorSid)
  $icacls = "$env:SystemRoot\System32\icacls.exe"
  & $icacls $Root '/setowner' '*S-1-5-32-544' '/T' '/C' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Failed to set trusted package owner.' }
  $item = Get-Item -LiteralPath $Root -Force -ErrorAction Stop
  if ($item.PSIsContainer) {
    $treeGrants = @('*S-1-5-18:(OI)(CI)(F)','*S-1-5-32-544:(OI)(CI)(F)',"*$OperatorSid`:(OI)(CI)(RX)")
    & $icacls $Root '/grant:r' $treeGrants '/T' '/C' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Failed to grant trusted package tree ACL.' }
    if (@(Get-ChildItem -LiteralPath $Root -Force -ErrorAction Stop).Count -gt 0) {
      $effectiveGrants = @('*S-1-5-18:(F)','*S-1-5-32-544:(F)',"*$OperatorSid`:(RX)")
      & $icacls (Join-Path $Root '*') '/grant:r' $effectiveGrants '/T' '/C' | Out-Null
      if ($LASTEXITCODE -ne 0) { throw 'Failed to grant effective trusted descendant ACL.' }
    }
  } else {
    $fileGrants = @('*S-1-5-18:(F)','*S-1-5-32-544:(F)',"*$OperatorSid`:(RX)")
    & $icacls $Root '/grant:r' $fileGrants '/C' | Out-Null
    if ($LASTEXITCODE -ne 0) { throw 'Failed to grant trusted file ACL.' }
  }
  & $icacls $Root '/inheritance:r' '/T' '/C' | Out-Null
  if ($LASTEXITCODE -ne 0) { throw 'Failed to protect trusted package ACL.' }
}

function Write-ArMutationIntent {
  param([Parameter(Mandatory = $true)][string]$Action, [Parameter(Mandatory = $true)][string]$TargetPath)
  $entry = [ordered]@{ at = [DateTimeOffset]::UtcNow.ToString('o'); action = $Action; target = $TargetPath }
  $path = Join-Path $script:executionRoot 'mutation-journal.jsonl'
  $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($entry | ConvertTo-Json -Compress) + "`n")
  $stream = [IO.File]::Open($path,[IO.FileMode]::Append,[IO.FileAccess]::Write,[IO.FileShare]::Read)
  try {
    $stream.Write($bytes,0,$bytes.Length)
    $stream.Flush($true)
  } finally {
    $stream.Dispose()
  }
  Set-ArTrustedRootAcl -Root $path -OperatorSid $OperatorSid
  Assert-ArTrustedSinglePathAcl -Path $path -OperatorSid $OperatorSid
}

function Assert-ArTrustedSinglePathAcl {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$OperatorSid
  )
  $dangerous = [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete -bor
    [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
    [Security.AccessControl.FileSystemRights]::TakeOwnership
  $fullControl = [Security.AccessControl.FileSystemRights]::FullControl
  $readExecute = [Security.AccessControl.FileSystemRights]::ReadAndExecute
  $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
  if (-not $acl.AreAccessRulesProtected) { throw "Trusted package ACL inherits: $Path" }
    $ownerSid = $acl.Owner
    try { $ownerSid = ([Security.Principal.NTAccount]$acl.Owner).Translate([Security.Principal.SecurityIdentifier]).Value } catch {}
  if ($ownerSid -cne 'S-1-5-32-544') { throw "Trusted package owner is not Administrators: $Path" }
    $effective = @{
      'S-1-5-18' = [Security.AccessControl.FileSystemRights]0
      'S-1-5-32-544' = [Security.AccessControl.FileSystemRights]0
      $OperatorSid = [Security.AccessControl.FileSystemRights]0
    }
    foreach ($rule in $acl.Access) {
      $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
      if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
          ($rule.FileSystemRights -band $dangerous) -and $sid -notin @('S-1-5-18','S-1-5-32-544')) {
        throw "Unprivileged write remains on trusted package: $sid at $Path"
      }
      if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Deny) {
        throw "Trusted package contains a deny ACE: $sid at $Path"
      }
      if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and $effective.ContainsKey($sid)) {
        $effective[$sid] = $effective[$sid] -bor $rule.FileSystemRights
      }
    }
    foreach ($sid in @('S-1-5-18','S-1-5-32-544')) {
      if (($effective[$sid] -band $fullControl) -ne $fullControl) { throw "Trusted administrator principal lacks full control: $sid at $Path" }
    }
    if (($effective[$OperatorSid] -band $readExecute) -ne $readExecute) { throw "Trusted operator lacks read and execute access at $Path" }
}

function Assert-ArTrustedRecoverablePathAcl {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$OperatorSid
  )
  Assert-ArTrustedPlainPath $Path | Out-Null
  $dangerous = [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete -bor
    [Security.AccessControl.FileSystemRights]::DeleteSubdirectoriesAndFiles -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor
    [Security.AccessControl.FileSystemRights]::TakeOwnership
  $fullControl = [Security.AccessControl.FileSystemRights]::FullControl
  $readExecute = [Security.AccessControl.FileSystemRights]::ReadAndExecute
  $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
  $ownerSid = $acl.Owner
  try { $ownerSid = ([Security.Principal.NTAccount]$acl.Owner).Translate([Security.Principal.SecurityIdentifier]).Value } catch {}
  if ($ownerSid -cne 'S-1-5-32-544') { throw "Recoverable package owner is not Administrators: $Path" }
  $effective = @{
    'S-1-5-18' = [Security.AccessControl.FileSystemRights]0
    'S-1-5-32-544' = [Security.AccessControl.FileSystemRights]0
    $OperatorSid = [Security.AccessControl.FileSystemRights]0
  }
  foreach ($rule in $acl.Access) {
    $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value
    if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and
        ($rule.FileSystemRights -band $dangerous) -and $sid -notin @('S-1-5-18','S-1-5-32-544')) {
      throw "Unprivileged write remains on recoverable package: $sid at $Path"
    }
    if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Deny) {
      throw "Recoverable package contains a deny ACE: $sid at $Path"
    }
    if ($rule.AccessControlType -eq [Security.AccessControl.AccessControlType]::Allow -and $effective.ContainsKey($sid)) {
      $effective[$sid] = $effective[$sid] -bor $rule.FileSystemRights
    }
  }
  foreach ($sid in @('S-1-5-18','S-1-5-32-544')) {
    if (($effective[$sid] -band $fullControl) -ne $fullControl) { throw "Recoverable administrator principal lacks full control: $sid at $Path" }
  }
  if (($effective[$OperatorSid] -band $readExecute) -ne $readExecute) { throw "Recoverable operator lacks read and execute access at $Path" }
}

function Assert-ArTrustedRecoverableRootAcl {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$OperatorSid
  )
  foreach ($path in @($Root) + @(Get-ChildItem -LiteralPath $Root -Force -Recurse | ForEach-Object FullName)) {
    Assert-ArTrustedRecoverablePathAcl -Path $path -OperatorSid $OperatorSid
  }
}

function Get-ArTrustedJournalPrefixIdentity {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][int]$LineCount
  )
  if ($LineCount -lt 1) { throw 'Journal prefix line count must be positive.' }
  $bytes = [IO.File]::ReadAllBytes($Path)
  $seen = 0
  $prefixLength = -1
  for ($index = 0; $index -lt $bytes.Length; $index++) {
    if ($bytes[$index] -eq 10) {
      $seen++
      if ($seen -eq $LineCount) { $prefixLength = $index + 1; break }
    }
  }
  if ($prefixLength -lt 0) { throw 'Journal prefix is incomplete or lacks a durable line terminator.' }
  $prefix = New-Object byte[] $prefixLength
  [Array]::Copy($bytes,0,$prefix,0,$prefixLength)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try {
    [pscustomobject]@{
      bytes = [long]$prefixLength
      lines = [int]$LineCount
      sha256 = ([BitConverter]::ToString($algorithm.ComputeHash($prefix)) -replace '-','').ToLowerInvariant()
    }
  } finally { $algorithm.Dispose() }
}

function Assert-ArTrustedRootAcl {
  param(
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$OperatorSid
  )
  foreach ($path in @($Root) + @(Get-ChildItem -LiteralPath $Root -Force -Recurse | ForEach-Object FullName)) {
    Assert-ArTrustedSinglePathAcl -Path $path -OperatorSid $OperatorSid
  }
}

function Get-ArTrustedQuarantineInventory {
  param([Parameter(Mandatory = $true)][string]$Root)
  $files = @()
  foreach ($file in @(Get-ChildItem -LiteralPath $Root -Recurse -Force -File | Sort-Object FullName)) {
    $files += [ordered]@{
      path = $file.FullName.Substring($Root.Length).TrimStart('\')
      size = [long]$file.Length
      sha256 = Get-ArTrustedSha256 $file.FullName
    }
  }
  $files
}

function Write-ArTrustedFailureObserved {
  param([Parameter(Mandatory = $true)][string]$Message)
  $path = Join-Path $script:executionRoot 'failure-observed.json'
  $record = [ordered]@{
    schema_version = 1
    observed_at = [DateTimeOffset]::UtcNow.ToString('o')
    error = $Message
  }
  $bytes = [Text.UTF8Encoding]::new($false).GetBytes(($record | ConvertTo-Json -Compress) + "`n")
  $stream = [IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {
    $stream.Write($bytes,0,$bytes.Length)
    $stream.Flush($true)
  } finally {
    $stream.Dispose()
  }
  $path
}

function Move-ArTrustedFailedRootToQuarantine {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$OperatorSid,
    [string]$ProgramFilesRoot = $env:ProgramFiles
  )
  # The content-addressed install/evidence names deliberately exceed one
  # hundred characters.  Nesting a failed package tree below the execution
  # evidence root can cross legacy MAX_PATH in icacls/Get-Acl and prevent both
  # rollback and the terminal result from being written.  Keep the tree intact
  # under one short, protected Program Files sibling and bind every byte from
  # the normal execution evidence instead.
  $quarantine = Join-Path $ProgramFilesRoot ('ARLBQ-' + [guid]::NewGuid().ToString('N'))
  Assert-ArTrustedPlainPath $quarantine | Out-Null
  if (Test-Path -LiteralPath $quarantine) { throw 'Short protected quarantine path already exists.' }
  Write-ArMutationIntent -Action 'PUBLISH_SHORT_PROTECTED_QUARANTINE' -TargetPath $quarantine
  Move-Item -LiteralPath $Path -Destination $quarantine -ErrorAction Stop
  Set-ArTrustedRootAcl -Root $quarantine -OperatorSid $OperatorSid
  Assert-ArTrustedRootAcl -Root $quarantine -OperatorSid $OperatorSid
  $files = @(Get-ArTrustedQuarantineInventory -Root $quarantine)
  $record = [ordered]@{
    schema_version = 1
    quarantined_at = [DateTimeOffset]::UtcNow.ToString('o')
    source_path = [IO.Path]::GetFullPath($Path)
    quarantine_path = [IO.Path]::GetFullPath($quarantine)
    quarantine_acl = (Get-Acl -LiteralPath $quarantine -ErrorAction Stop).Sddl
    files = $files
  }
  $recordPath = Join-Path $script:executionRoot ('quarantined-root-' + [guid]::NewGuid().ToString('N') + '.json')
  $bytes = [Text.UTF8Encoding]::new($false).GetBytes((ConvertTo-ArTrustedCanonicalJson $record) + "`n")
  $stream = [IO.File]::Open($recordPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {
    $stream.Write($bytes,0,$bytes.Length)
    $stream.Flush($true)
  } finally {
    $stream.Dispose()
  }
  [pscustomobject]@{ quarantine_path=$quarantine; record_path=$recordPath; file_count=$files.Count }
}

function Assert-ArTrustedShortQuarantineState {
  param(
    [Parameter(Mandatory = $true)][string]$OperatorSid,
    [string]$ProgramFilesRoot = $env:ProgramFiles
  )
  if ($null -eq $script:bootstrapGate) { throw 'Short quarantine reconciliation requires the global bootstrap gate.' }
  $programFiles = [IO.Path]::GetFullPath($ProgramFilesRoot).TrimEnd('\')
  $transactions = @()
  $destinations = @{}
  $sources = @{}
  $createdStaging = @{}
  $evidenceRoots = @(Get-ChildItem -LiteralPath $programFiles -Force -Directory -ErrorAction Stop | Where-Object {
    $_.Name -match '^AR-local-backup-evidence-[0-9a-f]{40}-[0-9a-f]{40}$'
  })
  foreach ($evidenceRoot in $evidenceRoots) {
    Assert-ArTrustedPlainPath $evidenceRoot.FullName | Out-Null
    Assert-ArTrustedSinglePathAcl -Path $evidenceRoot.FullName -OperatorSid $OperatorSid
    foreach ($execution in @(Get-ChildItem -LiteralPath $evidenceRoot.FullName -Force -Directory -ErrorAction Stop)) {
      $journalPath = Join-Path $execution.FullName 'mutation-journal.jsonl'
      if (-not (Test-Path -LiteralPath $journalPath -PathType Leaf)) { continue }
      Assert-ArTrustedPlainPath $execution.FullName | Out-Null
      Assert-ArTrustedSinglePathAcl -Path $execution.FullName -OperatorSid $OperatorSid
      $journalAcl = Get-Acl -LiteralPath $journalPath -ErrorAction Stop
      if (-not $journalAcl.AreAccessRulesProtected) {
        Assert-ArTrustedRecoverablePathAcl -Path $journalPath -OperatorSid $OperatorSid
        Write-ArMutationIntent -Action 'RECOVERY_SEAL_LEGACY_JOURNAL' -TargetPath $journalPath
        Set-ArTrustedRootAcl -Root $journalPath -OperatorSid $OperatorSid
      }
      Assert-ArTrustedSinglePathAcl -Path $journalPath -OperatorSid $OperatorSid
      $lines = @([IO.File]::ReadAllLines($journalPath,[Text.UTF8Encoding]::new($false)) | Where-Object { $_.Length -gt 0 })
      for ($index = 0; $index -lt $lines.Count; $index++) {
        $entry = $lines[$index] | ConvertFrom-Json
        if ([string]$entry.action -ceq 'CREATE_PACKAGE_STAGING') {
          $created = [IO.Path]::GetFullPath([string]$entry.target)
          if ([IO.Path]::GetDirectoryName($created) -cne $programFiles -or
              [IO.Path]::GetFileName($created) -notmatch '^ARLBS-[0-9a-f]{32}$' -or $createdStaging.ContainsKey($created)) {
            throw 'Created short staging root identity is invalid or duplicated.'
          }
          $prefix = Get-ArTrustedJournalPrefixIdentity -Path $journalPath -LineCount ([int]($index + 1))
          $createdStaging[$created] = [ordered]@{
            source_path=$created; source_journal=$journalPath
            source_journal_prefix_sha256=$prefix.sha256; source_journal_prefix_bytes=$prefix.bytes
            source_line=$prefix.lines
          }
          continue
        }
        if ([string]$entry.action -cne 'PUBLISH_SHORT_PROTECTED_QUARANTINE') { continue }
        if ($index -eq 0) { throw 'Short quarantine publication lacks a preceding source intent.' }
        $prior = $lines[$index - 1] | ConvertFrom-Json
        if ([string]$prior.action -notin @(
          'ROLLBACK_QUARANTINE_NEW_ROOT','RECOVERY_QUARANTINE_INTERRUPTED_ROOT','RECOVERY_QUARANTINE_ORPHANED_STAGING'
        )) {
          throw 'Short quarantine publication lacks its immediately preceding source intent.'
        }
        $source = [IO.Path]::GetFullPath([string]$prior.target)
        $destination = [IO.Path]::GetFullPath([string]$entry.target)
        if ([IO.Path]::GetDirectoryName($source) -cne $programFiles -or
            [IO.Path]::GetDirectoryName($destination) -cne $programFiles -or
            [IO.Path]::GetFileName($source) -notmatch '^(ARLBS-[0-9a-f]{32}|AR-local-backup-trusted-[0-9a-f]{40}-[0-9a-f]{40})$' -or
            [IO.Path]::GetFileName($destination) -notmatch '^ARLBQ-[0-9a-f]{32}$') {
          throw 'Short quarantine transaction paths are invalid.'
        }
        if ($sources.ContainsKey($source) -or $destinations.ContainsKey($destination)) {
          throw 'Short quarantine transaction path is not unique.'
        }
        $prefix = Get-ArTrustedJournalPrefixIdentity -Path $journalPath -LineCount ([int]($index + 1))
        $transaction = [ordered]@{
          source_path=$source; quarantine_path=$destination; source_journal=$journalPath
          source_journal_prefix_sha256=$prefix.sha256; source_journal_prefix_bytes=$prefix.bytes
          source_line=$prefix.lines
        }
        $transactions += $transaction
        $sources[$source] = $transaction
        $destinations[$destination] = $transaction
      }
    }
  }

  foreach ($created in @($createdStaging.Values)) {
    if ($sources.ContainsKey([string]$created.source_path) -or
        -not (Test-Path -LiteralPath ([string]$created.source_path) -PathType Container)) { continue }
    Assert-ArTrustedPlainPath ([string]$created.source_path) | Out-Null
    Assert-ArTrustedRecoverableRootAcl -Root ([string]$created.source_path) -OperatorSid $OperatorSid
    Write-ArMutationIntent -Action 'RECOVERY_SEAL_ORPHANED_STAGING' -TargetPath ([string]$created.source_path)
    Set-ArTrustedRootAcl -Root ([string]$created.source_path) -OperatorSid $OperatorSid
    Assert-ArTrustedRootAcl -Root ([string]$created.source_path) -OperatorSid $OperatorSid
    Write-ArMutationIntent -Action 'RECOVERY_QUARANTINE_ORPHANED_STAGING' -TargetPath ([string]$created.source_path)
    $recovered = Move-ArTrustedFailedRootToQuarantine -Path ([string]$created.source_path) -OperatorSid $OperatorSid `
      -ProgramFilesRoot $programFiles
    $currentJournal = Join-Path $script:executionRoot 'mutation-journal.jsonl'
    $currentLine = [int]@([IO.File]::ReadAllLines($currentJournal,[Text.UTF8Encoding]::new($false))).Count
    $prefix = Get-ArTrustedJournalPrefixIdentity -Path $currentJournal -LineCount $currentLine
    $transaction = [ordered]@{
      source_path=[string]$created.source_path; quarantine_path=[string]$recovered.quarantine_path
      source_journal=$currentJournal; source_journal_prefix_sha256=$prefix.sha256
      source_journal_prefix_bytes=$prefix.bytes; source_line=$prefix.lines
    }
    $transactions += $transaction
    $sources[$transaction.source_path] = $transaction
    $destinations[$transaction.quarantine_path] = $transaction
  }

  $shortRoots = @(Get-ChildItem -LiteralPath $programFiles -Force -Directory -ErrorAction Stop | Where-Object {
    $_.Name -match '^(ARLBS|ARLBQ)-[0-9a-f]{32}$'
  })
  foreach ($root in $shortRoots) {
    $full = [IO.Path]::GetFullPath($root.FullName)
    if (-not $sources.ContainsKey($full) -and -not $destinations.ContainsKey($full)) {
      throw "Unjournaled short bootstrap or quarantine root exists: $full"
    }
  }

  $verified = @()
  foreach ($transaction in $transactions) {
    $sourceExists = Test-Path -LiteralPath $transaction.source_path -PathType Container
    $destinationExists = Test-Path -LiteralPath $transaction.quarantine_path -PathType Container
    if ($sourceExists -and $destinationExists) { throw 'Short quarantine source and destination both exist.' }
    if (-not $sourceExists -and -not $destinationExists) { throw 'Journaled short quarantine source and destination are both absent.' }
    if ($sourceExists) {
      Assert-ArTrustedPlainPath $transaction.source_path | Out-Null
      Assert-ArTrustedRootAcl -Root $transaction.source_path -OperatorSid $OperatorSid
      Write-ArMutationIntent -Action 'RECOVERY_COMPLETE_SHORT_PROTECTED_QUARANTINE' -TargetPath $transaction.quarantine_path
      Move-Item -LiteralPath $transaction.source_path -Destination $transaction.quarantine_path -ErrorAction Stop
      Set-ArTrustedRootAcl -Root $transaction.quarantine_path -OperatorSid $OperatorSid
    }
    Assert-ArTrustedPlainPath $transaction.quarantine_path | Out-Null
    Assert-ArTrustedRootAcl -Root $transaction.quarantine_path -OperatorSid $OperatorSid
    $verified += [ordered]@{
      source_path=$transaction.source_path; quarantine_path=$transaction.quarantine_path
      source_journal=$transaction.source_journal; source_journal_prefix_sha256=$transaction.source_journal_prefix_sha256
      source_journal_prefix_bytes=$transaction.source_journal_prefix_bytes
      source_line=$transaction.source_line; quarantine_acl=(Get-Acl -LiteralPath $transaction.quarantine_path).Sddl
      files=@(Get-ArTrustedQuarantineInventory -Root $transaction.quarantine_path)
    }
  }
  $record = [ordered]@{ schema_version=1; verified_at=[DateTimeOffset]::UtcNow.ToString('o'); transactions=$verified }
  $path = Join-Path $script:executionRoot 'short-quarantine-reconciliation.json'
  $bytes = [Text.UTF8Encoding]::new($false).GetBytes((ConvertTo-ArTrustedCanonicalJson $record) + "`n")
  $stream = [IO.File]::Open($path,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
  try {
    $stream.Write($bytes,0,$bytes.Length)
    $stream.Flush($true)
  } finally {
    $stream.Dispose()
  }
  Set-ArTrustedRootAcl -Root $script:executionRoot -OperatorSid $OperatorSid
  Assert-ArTrustedRootAcl -Root $script:executionRoot -OperatorSid $OperatorSid
  [pscustomobject]@{ record_path=$path; transaction_count=$verified.Count }
}

function Get-ArTrustedInvocationContractSha256 {
  param([Parameter(Mandatory = $true)][Collections.Specialized.OrderedDictionary]$Parameters)
  $items = @()
  foreach ($key in $Parameters.Keys) {
    $value = $Parameters[$key]
    $type = if ($value -is [int] -or $value -is [long]) { 'integer' } else { 'string' }
    $items += [ordered]@{ name=[string]$key; type=$type; value=$value }
  }
  Get-ArTrustedTextSha256 (($items | ConvertTo-Json -Depth 5 -Compress))
}

function ConvertTo-ArTrustedCanonicalJson {
  param([Parameter(Mandatory = $false)]$Value)
  if ($null -eq $Value) { return 'null' }
  if ($Value -is [bool]) { if ($Value) { return 'true' } else { return 'false' } }
  if ($Value -is [string]) { return ($Value | ConvertTo-Json -Compress) }
  if ($Value -is [byte] -or $Value -is [sbyte] -or $Value -is [int16] -or $Value -is [uint16] -or
      $Value -is [int32] -or $Value -is [uint32] -or $Value -is [int64] -or $Value -is [uint64] -or
      $Value -is [single] -or $Value -is [double] -or $Value -is [decimal]) {
    return ([Convert]::ToString($Value,[Globalization.CultureInfo]::InvariantCulture))
  }
  if ($Value -is [Collections.IDictionary]) {
    $names = @($Value.Keys | ForEach-Object { [string]$_ } | Sort-Object)
    $parts = @($names | ForEach-Object { (ConvertTo-ArTrustedCanonicalJson $_) + ':' + (ConvertTo-ArTrustedCanonicalJson $Value[$_]) })
    return '{' + ($parts -join ',') + '}'
  }
  if ($Value -is [Management.Automation.PSCustomObject]) {
    $names = @($Value.PSObject.Properties.Name | Sort-Object)
    $parts = @($names | ForEach-Object { (ConvertTo-ArTrustedCanonicalJson $_) + ':' + (ConvertTo-ArTrustedCanonicalJson $Value.$_) })
    return '{' + ($parts -join ',') + '}'
  }
  if ($Value -is [Collections.IEnumerable]) {
    return '[' + (@($Value | ForEach-Object { ConvertTo-ArTrustedCanonicalJson $_ }) -join ',') + ']'
  }
  throw "Unsupported canonical JSON type: $($Value.GetType().FullName)"
}

function Assert-ArTrustedCatalogBaseline {
  param(
    [Parameter(Mandatory = $true)][string]$Target,
    [Parameter(Mandatory = $true)][string]$ExpectedCatalogSha256,
    [Parameter(Mandatory = $true)][long]$ExpectedCatalogSize,
    [Parameter(Mandatory = $true)][int]$ExpectedCatalogFinalSequence,
    [Parameter(Mandatory = $true)][string]$ExpectedCatalogFinalEntrySha256,
    [Parameter(Mandatory = $true)][string]$ExpectedLatestVerifiedSha256,
    [Parameter(Mandatory = $true)][long]$ExpectedLatestVerifiedSize,
    [Parameter(Mandatory = $true)][string]$ExpectedAcceptedCatalogEntrySha256,
    [Parameter(Mandatory = $true)][string]$ExpectedAcceptedReceiptRelativePath,
    [Parameter(Mandatory = $true)][string]$ExpectedAcceptedReceiptSha256,
    [Parameter(Mandatory = $true)][long]$ExpectedAcceptedReceiptSize,
    [Parameter(Mandatory = $true)][string]$ExpectedAcceptedObservationId,
    [Parameter(Mandatory = $true)][string]$ExpectedAcceptedArchiveSha256,
    [Parameter(Mandatory = $true)][long]$ExpectedAcceptedArchiveSize
  )
  if ([IO.Path]::IsPathRooted($ExpectedAcceptedReceiptRelativePath) -or
      $ExpectedAcceptedReceiptRelativePath -match '(^|[\\/])\.\.([\\/]|$)') {
    throw 'Accepted receipt path is not one safe relative path.'
  }
  $targetFull = [IO.Path]::GetFullPath($Target).TrimEnd('\')
  $catalogPath = Join-Path $Target 'catalog\generations.jsonl'
  $latestPath = Join-Path $Target 'catalog\latest-verified.json'
  $receiptPath = Join-Path $Target $ExpectedAcceptedReceiptRelativePath
  $archivePath = Join-Path ([IO.Path]::GetDirectoryName($receiptPath)) 'observation.tar.zst'
  if (-not [IO.Path]::GetFullPath($receiptPath).StartsWith($targetFull + '\',[StringComparison]::OrdinalIgnoreCase)) {
    throw 'Accepted receipt path escapes the backup target.'
  }
  foreach ($path in @($catalogPath,$latestPath,$receiptPath,$archivePath)) {
    Assert-ArTrustedPlainPath $path | Out-Null
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Catalog baseline file is absent: $path" }
  }
  $catalog = Get-Item -LiteralPath $catalogPath -ErrorAction Stop
  $latest = Get-Item -LiteralPath $latestPath -ErrorAction Stop
  $receipt = Get-Item -LiteralPath $receiptPath -ErrorAction Stop
  $archive = Get-Item -LiteralPath $archivePath -ErrorAction Stop
  if ($catalog.Length -ne $ExpectedCatalogSize -or (Get-ArTrustedSha256 $catalogPath) -cne $ExpectedCatalogSha256 -or
      $latest.Length -ne $ExpectedLatestVerifiedSize -or (Get-ArTrustedSha256 $latestPath) -cne $ExpectedLatestVerifiedSha256 -or
      $receipt.Length -ne $ExpectedAcceptedReceiptSize -or (Get-ArTrustedSha256 $receiptPath) -cne $ExpectedAcceptedReceiptSha256 -or
      $archive.Length -ne $ExpectedAcceptedArchiveSize -or (Get-ArTrustedSha256 $archivePath) -cne $ExpectedAcceptedArchiveSha256) {
    throw 'Catalog baseline bytes differ from the authenticated prestate.'
  }
  $catalogLines = @([IO.File]::ReadAllLines($catalogPath,[Text.UTF8Encoding]::new($false)) | Where-Object { $_.Length -gt 0 })
  if ($catalogLines.Count -lt 1) { throw 'Catalog baseline is empty.' }
  $entries = @()
  $prior = $null
  for ($index = 0; $index -lt $catalogLines.Count; $index++) {
    $entry = $catalogLines[$index] | ConvertFrom-Json
    if ($null -eq $entry -or $entry -is [Array] -or [int]$entry.sequence -ne ($index + 1) -or
        (($null -eq $prior -and $null -ne $entry.previous_entry_sha256) -or ($null -ne $prior -and [string]$entry.previous_entry_sha256 -cne $prior))) {
      throw 'Catalog baseline sequence or previous-entry link is invalid.'
    }
    $entryDigestPattern = [regex]'"entry_sha256":"(?<digest>[0-9a-f]{64})",'
    $digestMatches = $entryDigestPattern.Matches($catalogLines[$index])
    if ($digestMatches.Count -ne 1) { throw 'Catalog baseline entry digest field is not canonical.' }
    $canonicalMaterial = $entryDigestPattern.Replace($catalogLines[$index],'',1)
    $calculated = Get-ArTrustedTextSha256 ($canonicalMaterial + "`n")
    if ([string]$entry.entry_sha256 -cne $calculated -or $digestMatches[0].Groups['digest'].Value -cne $calculated) {
      throw 'Catalog baseline entry digest is invalid.'
    }
    $prior = $calculated
    $entries += $entry
  }
  $final = $entries[-1]
  $pointer = Get-Content -LiteralPath $latestPath -Raw -ErrorAction Stop | ConvertFrom-Json
  $accepted = Get-Content -LiteralPath $receiptPath -Raw -ErrorAction Stop | ConvertFrom-Json
  $pointerMatches = @($entries | Where-Object {
    [string]$_.entry_sha256 -ceq $ExpectedAcceptedCatalogEntrySha256 -and [string]$_.receipt_path -ceq $ExpectedAcceptedReceiptRelativePath.Replace('\','/') -and
    [string]$_.receipt_sha256 -ceq $ExpectedAcceptedReceiptSha256 -and [string]$_.kind -ceq 'observation'
  })
  if ([int]$final.sequence -ne $ExpectedCatalogFinalSequence -or [string]$final.entry_sha256 -cne $ExpectedCatalogFinalEntrySha256 -or
      [string]$pointer.catalog_entry_sha256 -cne $ExpectedAcceptedCatalogEntrySha256 -or $pointerMatches.Count -ne 1 -or
      [string]$pointer.receipt_path -cne $ExpectedAcceptedReceiptRelativePath.Replace('\','/') -or
      [string]$pointer.receipt_sha256 -cne $ExpectedAcceptedReceiptSha256 -or
      [string]$accepted.checks.observation.latest_pointer.generation_id -cne $ExpectedAcceptedObservationId -or
      [string]$accepted.archive_sha256 -cne $ExpectedAcceptedArchiveSha256 -or [long]$accepted.archive_bytes -ne $ExpectedAcceptedArchiveSize) {
    throw 'Catalog baseline identities differ from the authenticated prestate.'
  }
  [ordered]@{
    catalog_path=$catalogPath; catalog_size=$catalog.Length; catalog_sha256=$ExpectedCatalogSha256
    final_sequence=$ExpectedCatalogFinalSequence; final_entry_sha256=$ExpectedCatalogFinalEntrySha256
    latest_verified_path=$latestPath; latest_verified_size=$latest.Length; latest_verified_sha256=$ExpectedLatestVerifiedSha256
    accepted_catalog_entry_sha256=$ExpectedAcceptedCatalogEntrySha256
    accepted_receipt_path=$receiptPath; accepted_receipt_size=$receipt.Length; accepted_receipt_sha256=$ExpectedAcceptedReceiptSha256
    accepted_observation_id=$ExpectedAcceptedObservationId; accepted_archive_path=$archivePath
    accepted_archive_size=$archive.Length; accepted_archive_sha256=$ExpectedAcceptedArchiveSha256
  }
}

function Get-ArTrustedTreeDigest {
  param([Parameter(Mandatory = $true)][string]$Root)
  $rootFull = [IO.Path]::GetFullPath($Root).TrimEnd('\')
  $items = @()
  foreach ($file in @(Get-ChildItem -LiteralPath $Root -File -Recurse | Sort-Object FullName)) {
    $items += [ordered]@{ path = $file.FullName.Substring($rootFull.Length + 1).Replace('\','/'); sha256 = Get-ArTrustedSha256 $file.FullName }
  }
  Get-ArTrustedTextSha256 (($items | ConvertTo-Json -Depth 5 -Compress))
}

function Restore-ArTrustedControlRootAtomic {
  param(
    [Parameter(Mandatory = $true)][string]$ControlRoot,
    [Parameter(Mandatory = $true)][string]$Prestate,
    [Parameter(Mandatory = $true)][string]$EvidenceRoot,
    [Parameter(Mandatory = $true)][string]$OperatorSid,
    [Parameter(Mandatory = $true)][string]$ControlSddl,
    [Parameter(Mandatory = $true)][string]$ExpectedControlSddlSha256
  )
  $expected = Get-ArTrustedTreeDigest $Prestate
  $restore = $ControlRoot + '.restore-' + [guid]::NewGuid().ToString('N')
  $failed = $ControlRoot + '.failed-' + [guid]::NewGuid().ToString('N')
  Copy-Item -LiteralPath $Prestate -Destination $restore -Recurse -ErrorAction Stop
  if ((Get-ArTrustedTreeDigest $restore) -cne $expected) { throw 'Control restore staging digest mismatch.' }
  $movedCurrent = $false
  try {
    if (Test-Path -LiteralPath $ControlRoot) { Move-Item -LiteralPath $ControlRoot -Destination $failed -ErrorAction Stop; $movedCurrent = $true }
    Move-Item -LiteralPath $restore -Destination $ControlRoot -ErrorAction Stop
  } catch {
    if (-not (Test-Path -LiteralPath $ControlRoot) -and $movedCurrent -and (Test-Path -LiteralPath $failed)) {
      Move-Item -LiteralPath $failed -Destination $ControlRoot -ErrorAction SilentlyContinue
    }
    throw
  }
  $verificationError = $null
  $preservationError = $null
  try {
    if ((Get-ArTrustedTreeDigest $ControlRoot) -cne $expected) { throw 'Restored control digest mismatch.' }
    $restoredAcl = New-Object Security.AccessControl.DirectorySecurity
    $restoredAcl.SetSecurityDescriptorSddlForm($ControlSddl)
    Set-Acl -LiteralPath $ControlRoot -AclObject $restoredAcl -ErrorAction Stop
    $actualSddl = (Get-Acl -LiteralPath $ControlRoot -ErrorAction Stop).Sddl
    if ((Get-ArTrustedSddlBinarySha256 $actualSddl) -cne $ExpectedControlSddlSha256) { throw 'Restored control ACL differs from authenticated prestate.' }
  } catch { $verificationError = $_.Exception }
  finally {
    if ($movedCurrent -and (Test-Path -LiteralPath $failed)) {
      try {
        $destination = Join-Path $EvidenceRoot 'failed-dispatcher-control'
        Move-Item -LiteralPath $failed -Destination $destination -ErrorAction Stop
        Set-ArTrustedRootAcl -Root $destination -OperatorSid $OperatorSid
      } catch { $preservationError = $_.Exception }
    }
  }
  if ($null -ne $verificationError -and $null -ne $preservationError) {
    throw "Control restore verification failed: $($verificationError.Message); displaced-control preservation failed: $($preservationError.Message)"
  }
  if ($null -ne $preservationError) { throw $preservationError }
  if ($null -ne $verificationError) { throw $verificationError }
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
