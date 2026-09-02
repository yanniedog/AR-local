if (-not ('ArTrustedJobObject' -as [type])) {
  Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class ArTrustedJobObject {
  [StructLayout(LayoutKind.Sequential)] struct BasicLimits {
    public long ProcessTime, JobTime; public uint Flags; public UIntPtr MinWorkingSet, MaxWorkingSet;
    public uint ActiveProcessLimit; public UIntPtr Affinity; public uint PriorityClass, SchedulingClass;
  }
  [StructLayout(LayoutKind.Sequential)] struct IoCounters {
    public ulong ReadOps, WriteOps, OtherOps, ReadBytes, WriteBytes, OtherBytes;
  }
  [StructLayout(LayoutKind.Sequential)] struct ExtendedLimits {
    public BasicLimits Basic; public IoCounters Io; public UIntPtr ProcessMemory, JobMemory, PeakProcessMemory, PeakJobMemory;
  }
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateJobObject(IntPtr attributes, string name);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job, int infoClass, IntPtr info, uint length);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateJobObject(IntPtr job, uint exitCode);
  [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
  public static IntPtr Create() {
    IntPtr job = CreateJobObject(IntPtr.Zero, null);
    if (job == IntPtr.Zero) throw new Win32Exception(Marshal.GetLastWin32Error());
    ExtendedLimits limits = new ExtendedLimits(); limits.Basic.Flags = 0x00002000;
    int size = Marshal.SizeOf(typeof(ExtendedLimits)); IntPtr buffer = Marshal.AllocHGlobal(size);
    try {
      Marshal.StructureToPtr(limits, buffer, false);
      if (!SetInformationJobObject(job, 9, buffer, (uint)size)) throw new Win32Exception(Marshal.GetLastWin32Error());
      return job;
    } catch { CloseHandle(job); throw; } finally { Marshal.FreeHGlobal(buffer); }
  }
  public static void Assign(IntPtr job, IntPtr process) {
    if (!AssignProcessToJobObject(job, process)) throw new Win32Exception(Marshal.GetLastWin32Error());
  }
  public static void Terminate(IntPtr job) {
    if (!TerminateJobObject(job, 1)) throw new Win32Exception(Marshal.GetLastWin32Error());
  }
  public static void Close(IntPtr job) { if (job != IntPtr.Zero) CloseHandle(job); }
}
'@
}

function New-ArTrustedProcessJob { [ArTrustedJobObject]::Create() }
function Add-ArTrustedProcessToJob {
  param([Parameter(Mandatory = $true)][IntPtr]$Job, [Parameter(Mandatory = $true)][Diagnostics.Process]$Process)
  [ArTrustedJobObject]::Assign($Job,$Process.Handle)
}
function Close-ArTrustedProcessJob { param([IntPtr]$Job) [ArTrustedJobObject]::Close($Job) }

function Stop-ArTrustedProcessTree {
  param(
    [Parameter(Mandatory = $true)][IntPtr]$Job,
    [Parameter(Mandatory = $true)][Diagnostics.Process]$Process,
    [Parameter(Mandatory = $true)][string]$Label
  )
  [ArTrustedJobObject]::Terminate($Job)
  if (-not $Process.WaitForExit(5000)) { throw "$Label timed out and could not be terminated." }
}

function Wait-ArTrustedProcess {
  param(
    [Parameter(Mandatory = $true)][IntPtr]$Job,
    [Parameter(Mandatory = $true)][Diagnostics.Process]$Process,
    [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
    [Parameter(Mandatory = $true)][string]$Label
  )
  if ($Process.WaitForExit([Math]::Max(0,$TimeoutMilliseconds))) { return }
  Stop-ArTrustedProcessTree -Job $Job -Process $Process -Label $Label
  throw "$Label timed out and was terminated."
}

function Wait-ArTrustedRedirectedTasks {
  param(
    [Parameter(Mandatory = $true)][IntPtr]$Job,
    [Parameter(Mandatory = $true)][Diagnostics.Process]$Process,
    [Parameter(Mandatory = $true)][Threading.Tasks.Task[]]$Tasks,
    [Parameter(Mandatory = $true)][int]$TimeoutMilliseconds,
    [Parameter(Mandatory = $true)][string]$Label
  )
  if ([Threading.Tasks.Task]::WaitAll($Tasks,[Math]::Max(0,$TimeoutMilliseconds))) { return }
  Stop-ArTrustedProcessTree -Job $Job -Process $Process -Label $Label
  [void]([Threading.Tasks.Task]::WaitAll($Tasks,5000))
  throw "$Label redirected streams did not close before the deadline."
}

function Test-ArTrustedLanEndpoint {
  param([Parameter(Mandatory = $true)][string]$Value)
  $address = $null
  if (-not [Net.IPAddress]::TryParse($Value,[ref]$address) -or
      $address.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork -or $address.ToString() -cne $Value) { return $false }
  $bytes = $address.GetAddressBytes()
  ($bytes[0] -eq 10) -or ($bytes[0] -eq 172 -and $bytes[1] -ge 16 -and $bytes[1] -le 31) -or
    ($bytes[0] -eq 192 -and $bytes[1] -eq 168)
}

function Resolve-ArTrustedSshEndpoint {
  param(
    [Parameter(Mandatory = $true)][string]$PythonPath,
    [Parameter(Mandatory = $true)][string]$ModulePath,
    [Parameter(Mandatory = $true)][string]$DiscoveryName,
    [ValidateRange(1,30)][int]$TimeoutSeconds
  )
  foreach ($path in @($PythonPath,$ModulePath)) {
    if ($path.Contains('"') -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'SSH discovery dependency path is invalid.' }
  }
  if ($DiscoveryName -cne 'ar.local') { throw 'SSH discovery name differs from the protected contract.' }
  $start = New-Object Diagnostics.ProcessStartInfo
  $start.FileName = $PythonPath
  $start.Arguments = '-I -B "' + $ModulePath + '" --name "' + $DiscoveryName + '"'
  $start.UseShellExecute = $false; $start.RedirectStandardOutput = $true; $start.RedirectStandardError = $true
  $start.CreateNoWindow = $true
  $process = New-Object Diagnostics.Process; $process.StartInfo = $start
  $job = New-ArTrustedProcessJob
  $clock = [Diagnostics.Stopwatch]::StartNew()
  try {
    if (-not $process.Start()) { throw 'SSH LAN endpoint discovery failed to start.' }
    Add-ArTrustedProcessToJob -Job $job -Process $process
    $stdoutTask = $process.StandardOutput.ReadToEndAsync(); $stderrTask = $process.StandardError.ReadToEndAsync()
    try {
      Wait-ArTrustedProcess -Job $job -Process $process -TimeoutMilliseconds ($TimeoutSeconds * 1000) -Label 'SSH LAN endpoint discovery'
    } catch {
      [void]([Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($stdoutTask,$stderrTask),5000)); throw
    }
    Wait-ArTrustedRedirectedTasks -Job $job -Process $process -Tasks @($stdoutTask,$stderrTask) `
      -TimeoutMilliseconds ([Math]::Max(0,($TimeoutSeconds * 1000) - [int]$clock.ElapsedMilliseconds)) -Label 'SSH LAN endpoint discovery'
    $stdout = $stdoutTask.GetAwaiter().GetResult(); $stderr = $stderrTask.GetAwaiter().GetResult()
    $match = [regex]::Match($stdout,'^(?<endpoint>[0-9.]+)\r?\n$')
    if ($process.ExitCode -ne 0 -or $stderr -or -not $match.Success -or -not (Test-ArTrustedLanEndpoint $match.Groups['endpoint'].Value)) {
      throw 'SSH LAN endpoint discovery did not return exactly one valid endpoint.'
    }
    $match.Groups['endpoint'].Value
  } finally {
    $clock.Stop(); Close-ArTrustedProcessJob -Job $job; $process.Dispose()
  }
}

function Invoke-ArTrustedSshScript {
  param(
    [Parameter(Mandatory = $true)][string]$SshPath,
    [Parameter(Mandatory = $true)][string]$HostName,
    [Parameter(Mandatory = $true)][string]$LogicalHost,
    [Parameter(Mandatory = $true)][string]$UserName,
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$IdentityPath,
    [Parameter(Mandatory = $true)][string]$KnownHostsPath,
    [Parameter(Mandatory = $true)][string]$Script,
    [ValidateRange(1,120000)][int]$TimeoutMilliseconds = 30000
  )
  if ($Script.Contains("`r")) { throw 'Remote script must contain LF only.' }
  if (-not (Test-ArTrustedLanEndpoint $HostName) -or $LogicalHost -cne 'ar-local-pi5') { throw 'SSH host must be one authenticated LAN endpoint.' }
  if ($UserName -notmatch '^[a-z_][a-z0-9_-]{0,31}$' -or $Port -lt 1 -or $Port -gt 65535) { throw 'SSH user or port is invalid.' }
  foreach ($path in @($SshPath,$IdentityPath,$KnownHostsPath)) {
    if ($path.Contains('"') -or -not (Test-Path -LiteralPath $path -PathType Leaf)) { throw 'SSH dependency path is invalid.' }
  }
  $start = New-Object Diagnostics.ProcessStartInfo
  $start.FileName = $SshPath
  $start.Arguments = '-F NUL -o BatchMode=yes -o ConnectTimeout=10 -o IdentitiesOnly=yes -o IdentityAgent=none ' +
    '-o PreferredAuthentications=publickey -o PubkeyAuthentication=yes -o GSSAPIAuthentication=no ' +
    '-o PasswordAuthentication=no -o KbdInteractiveAuthentication=no ' +
    '-o ChallengeResponseAuthentication=no -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=' + $KnownHostsPath + '" ' +
    '-o HostKeyAlias=' + $LogicalHost + ' -o HostKeyAlgorithms=ssh-ed25519 -o GlobalKnownHostsFile=NUL ' +
    '-o UpdateHostKeys=no -o VerifyHostKeyDNS=no -o ForwardAgent=no ' +
    '-o ClearAllForwardings=yes -o RequestTTY=no -i "' + $IdentityPath + '" -p ' + $Port +
    ' -l ' + $UserName + ' ' + $HostName + ' bash -s'
  $start.UseShellExecute = $false
  $start.RedirectStandardInput = $true; $start.RedirectStandardOutput = $true; $start.RedirectStandardError = $true
  $start.CreateNoWindow = $true
  $process = New-Object Diagnostics.Process; $process.StartInfo = $start
  $job = New-ArTrustedProcessJob
  $clock = [Diagnostics.Stopwatch]::StartNew()
  try {
    if (-not $process.Start()) { throw 'Failed to start SSH.' }
    Add-ArTrustedProcessToJob -Job $job -Process $process
    $stdoutTask = $process.StandardOutput.ReadToEndAsync(); $stderrTask = $process.StandardError.ReadToEndAsync()
    $process.StandardInput.AutoFlush = $true
    $inputTask = $process.StandardInput.WriteAsync($Script)
    if (-not $inputTask.Wait([Math]::Max(0,$TimeoutMilliseconds - [int]$clock.ElapsedMilliseconds))) {
      Stop-ArTrustedProcessTree -Job $job -Process $process -Label 'Trusted SSH preflight'
      [void]([Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($stdoutTask,$stderrTask),5000))
      throw 'Trusted SSH preflight input did not complete before the deadline.'
    }
    $process.StandardInput.Close()
    $remaining = $TimeoutMilliseconds - [int]$clock.ElapsedMilliseconds
    try {
      Wait-ArTrustedProcess -Job $job -Process $process -TimeoutMilliseconds $remaining -Label 'Trusted SSH preflight'
    } catch {
      [void]([Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($stdoutTask,$stderrTask),5000))
      throw
    }
    $remaining = $TimeoutMilliseconds - [int]$clock.ElapsedMilliseconds
    Wait-ArTrustedRedirectedTasks -Job $job -Process $process -Tasks @($stdoutTask,$stderrTask) `
      -TimeoutMilliseconds $remaining -Label 'Trusted SSH preflight'
    [pscustomobject]@{
      ExitCode=$process.ExitCode; Stdout=$stdoutTask.GetAwaiter().GetResult(); Stderr=$stderrTask.GetAwaiter().GetResult()
    }
  } finally {
    $clock.Stop(); Close-ArTrustedProcessJob -Job $job; $process.Dispose()
  }
}

function Assert-ArTrustedSystemSshExecutable {
  param([Parameter(Mandatory = $true)][string]$Path, [Parameter(Mandatory = $true)][string]$ExpectedSha256)
  Assert-ArTrustedPlainPath $Path | Out-Null
  if ((Get-ArTrustedSha256 $Path) -cne $ExpectedSha256) { throw 'Trusted SSH executable hash mismatch.' }
  $acl = Get-Acl -LiteralPath $Path -ErrorAction Stop
  $trustedInstallerSid = ([Security.Principal.NTAccount]::new('NT SERVICE\TrustedInstaller')).Translate([Security.Principal.SecurityIdentifier]).Value
  $privilegedSids = @('S-1-5-18','S-1-5-32-544',$trustedInstallerSid)
  $ownerSid = $acl.Owner
  try { $ownerSid = ([Security.Principal.NTAccount]$acl.Owner).Translate([Security.Principal.SecurityIdentifier]).Value } catch {}
  if (-not $acl.AreAccessRulesProtected -or $ownerSid -notin $privilegedSids) { throw 'Trusted SSH executable ACL owner or inheritance is invalid.' }
  $dangerous = [Security.AccessControl.FileSystemRights]::Write -bor [Security.AccessControl.FileSystemRights]::Delete -bor [Security.AccessControl.FileSystemRights]::ChangePermissions -bor [Security.AccessControl.FileSystemRights]::TakeOwnership
  foreach ($rule in $acl.Access) {
    if ($rule.AccessControlType -ne [Security.AccessControl.AccessControlType]::Allow -or -not ($rule.FileSystemRights -band $dangerous)) { continue }
    try { $sid = $rule.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value } catch { throw 'Trusted SSH executable has an unresolvable writer.' }
    if ($sid -notin $privilegedSids) { throw "Unprivileged write remains on trusted SSH executable: $sid" }
  }
}

function Install-ArTrustedSshIdentity {
  param(
    [Parameter(Mandatory = $true)][string]$SourcePath,
    [Parameter(Mandatory = $true)][string]$ExpectedSha256,
    [Parameter(Mandatory = $true)][string]$DestinationPath,
    [Parameter(Mandatory = $true)][string]$OperatorSid
  )
  Assert-ArTrustedPlainPath $SourcePath | Out-Null
  $inputRoot = Join-Path $env:ProgramFiles ('ARLBI-' + [guid]::NewGuid().ToString('N'))
  $inputPath = Join-Path $inputRoot 'id'
  try {
    Write-ArMutationIntent -Action 'CREATE_PROTECTED_SSH_INPUT' -TargetPath $inputRoot
    New-Item -ItemType Directory -Path $inputRoot -ErrorAction Stop | Out-Null
    Set-ArTrustedRootAcl -Root $inputRoot -OperatorSid $OperatorSid
    $source = [IO.File]::Open($SourcePath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    $input = [IO.File]::Open($inputPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try {
      $actual = ([BitConverter]::ToString($algorithm.ComputeHash($source)) -replace '-','').ToLowerInvariant()
      if ($actual -cne $ExpectedSha256) { throw 'SSH identity source hash mismatch.' }
      $source.Position = 0; $source.CopyTo($input); $input.Flush($true)
    } finally {
      $input.Dispose(); $algorithm.Dispose(); $source.Dispose()
    }
    Set-ArTrustedRootAcl -Root $inputRoot -OperatorSid $OperatorSid
    Assert-ArTrustedRootAcl -Root $inputRoot -OperatorSid $OperatorSid
    if ((Get-ArTrustedSha256 $inputPath) -cne $ExpectedSha256) { throw 'Protected SSH identity input hash mismatch.' }
    $identityText = [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($inputPath))
    if ($identityText.Contains("`r") -or -not $identityText.StartsWith("-----BEGIN OPENSSH PRIVATE KEY-----`n") -or
        -not $identityText.TrimEnd("`n").EndsWith('-----END OPENSSH PRIVATE KEY-----')) { throw 'Protected SSH identity format is invalid.' }
    Write-ArMutationIntent -Action 'INSTALL_PROTECTED_SSH_IDENTITY' -TargetPath $DestinationPath
    $locked = [IO.File]::Open($inputPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    $destination = [IO.File]::Open($DestinationPath,[IO.FileMode]::CreateNew,[IO.FileAccess]::Write,[IO.FileShare]::None)
    try { $locked.CopyTo($destination); $destination.Flush($true) } finally { $destination.Dispose(); $locked.Dispose() }
    if ((Get-ArTrustedSha256 $DestinationPath) -cne $ExpectedSha256) { throw 'Installed SSH identity hash mismatch.' }
  } finally {
    if (Test-Path -LiteralPath $inputRoot) {
      try { Write-ArMutationIntent -Action 'REMOVE_PROTECTED_SSH_INPUT' -TargetPath $inputRoot }
      finally { Remove-Item -LiteralPath $inputRoot -Recurse -Force -ErrorAction Stop }
    }
    if (Test-Path -LiteralPath $inputRoot) { throw 'Protected SSH identity input cleanup failed.' }
  }
}

function Remove-ArTrustedOrphanedSshInputs {
  param(
    [Parameter(Mandatory = $true)][string]$OperatorSid,
    [string]$ProgramFilesRoot = $env:ProgramFiles
  )
  $root = [IO.Path]::GetFullPath($ProgramFilesRoot)
  foreach ($item in @(Get-ChildItem -LiteralPath $root -Directory -Force -ErrorAction Stop | Where-Object { $_.Name -match '^ARLBI-[0-9a-f]{32}$' })) {
    if ([IO.Path]::GetDirectoryName([IO.Path]::GetFullPath($item.FullName)) -cne $root) { throw 'Protected SSH input escaped its reserved root.' }
    Assert-ArTrustedPlainPath $item.FullName | Out-Null
    if (@(Get-ChildItem -LiteralPath $item.FullName -Force -ErrorAction Stop).Count) {
      Assert-ArTrustedRootAcl -Root $item.FullName -OperatorSid $OperatorSid
    }
    Set-ArTrustedRootAcl -Root $item.FullName -OperatorSid $OperatorSid
    Write-ArMutationIntent -Action 'RECOVERY_REMOVE_PROTECTED_SSH_INPUT' -TargetPath $item.FullName
    Remove-Item -LiteralPath $item.FullName -Recurse -Force -ErrorAction Stop
    if (Test-Path -LiteralPath $item.FullName) { throw 'Orphaned protected SSH input cleanup failed.' }
  }
}

function Assert-ArTrustedSshConfiguration {
  param(
    [Parameter(Mandatory = $true)]$Config,
    [Parameter(Mandatory = $true)][string]$HostName,
    [Parameter(Mandatory = $true)][string]$UserName,
    [Parameter(Mandatory = $true)][int]$Port,
    [Parameter(Mandatory = $true)][string]$SshSha256,
    [Parameter(Mandatory = $true)][string]$IdentitySha256
  )
  $script:trustedSshConfig = $null
  $script:trustedSshEndpoint = $null
  $expectedSsh = Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::System)) 'OpenSSH\ssh.exe'
  if ([string]$Config.ssh_host -cne $HostName -or $HostName -cne 'ar.local' -or
      [string]$Config.ssh_logical_host -cne 'ar-local-pi5' -or [int]$Config.ssh_discovery_timeout_seconds -ne 10 -or
      [string]$Config.ssh_user -cne $UserName -or [int]$Config.ssh_port -ne $Port -or
      [string]$Config.ssh_sha256 -cne $SshSha256 -or [string]$Config.ssh_identity_sha256 -cne $IdentitySha256 -or
      [IO.Path]::GetFullPath([string]$Config.ssh_path) -cne [IO.Path]::GetFullPath($expectedSsh)) {
    throw 'Protected SSH configuration differs from the authenticated installer contract.'
  }
  if ((Get-ArTrustedSha256 ([string]$Config.python_path)) -cne [string]$Config.python_sha256 -or
      (Get-ArTrustedSha256 ([string]$Config.ssh_endpoint_path)) -cne [string]$Config.ssh_endpoint_sha256) {
    throw 'Protected SSH discovery dependency hash mismatch.'
  }
  $script:trustedSshEndpoint = Resolve-ArTrustedSshEndpoint -PythonPath ([string]$Config.python_path) `
    -ModulePath ([string]$Config.ssh_endpoint_path) -DiscoveryName ([string]$Config.ssh_host) `
    -TimeoutSeconds ([int]$Config.ssh_discovery_timeout_seconds)
  $script:trustedSshConfig = $Config
}
