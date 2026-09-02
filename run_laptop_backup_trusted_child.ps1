param([Parameter(Mandatory = $true)][string]$ConfigPath)

$ErrorActionPreference = 'Stop'
$code = 1
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
function New-ArTrustedChildProcessJob { [ArTrustedJobObject]::Create() }
function Add-ArTrustedChildProcessToJob {
  param([IntPtr]$Job,[Diagnostics.Process]$Process)
  [ArTrustedJobObject]::Assign($Job,$Process.Handle)
}
function Close-ArTrustedChildProcessJob { param([IntPtr]$Job) [ArTrustedJobObject]::Close($Job) }
function Get-ArTrustedSha256 {
  param([Parameter(Mandatory = $true)][string]$Path)
  $stream = [IO.File]::OpenRead($Path)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try {
    ([BitConverter]::ToString($algorithm.ComputeHash($stream)) -replace '-', '').ToLowerInvariant()
  } finally {
    $algorithm.Dispose()
    $stream.Dispose()
  }
}
function Get-ArTrustedBytesSha256 {
  param([Parameter(Mandatory = $true)][byte[]]$Bytes)
  $algorithm = [Security.Cryptography.SHA256]::Create()
  try { ([BitConverter]::ToString($algorithm.ComputeHash($Bytes)) -replace '-', '').ToLowerInvariant() }
  finally { $algorithm.Dispose() }
}
function Assert-ArTrustedPlainPath {
  param([Parameter(Mandatory = $true)][string]$Path)
  $full = [IO.Path]::GetFullPath($Path)
  $current = [IO.Path]::GetPathRoot($full)
  foreach ($part in $full.Substring($current.Length).Split(@([IO.Path]::DirectorySeparatorChar), [StringSplitOptions]::RemoveEmptyEntries)) {
    $current = Join-Path $current $part
    if (Test-Path -LiteralPath $current) {
      $item = Get-Item -LiteralPath $current -Force -ErrorAction Stop
      if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0) {
        throw "Trusted child path traverses a reparse point: $current"
      }
    }
  }
  $full
}
function Assert-ArTrustedWriteDenied {
  param([Parameter(Mandatory = $true)][string]$Path)
  $stream = $null
  try {
    $stream = [IO.File]::Open($Path, [IO.FileMode]::Open, [IO.FileAccess]::Write, [IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete)
  } catch [UnauthorizedAccessException] {
    return
  } finally {
    if ($null -ne $stream) { $stream.Dispose() }
  }
  throw "Restricted child can modify trusted executable bytes: $Path"
}
function Assert-ArTrustedWithinRoot {
  param(
    [Parameter(Mandatory = $true)][string]$Path,
    [Parameter(Mandatory = $true)][string]$Root,
    [Parameter(Mandatory = $true)][string]$Label
  )
  $prefix = $Root.TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
  if (-not $Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "$Label is outside the administrator-protected launcher root."
  }
}
function Stop-ArTrustedChildProcessTree {
  param([IntPtr]$Job,[Diagnostics.Process]$Process)
  [ArTrustedJobObject]::Terminate($Job)
  if (-not $Process.WaitForExit(5000)) { throw 'Trusted SSH semantic preflight timed out and could not be terminated.' }
}
function Wait-ArTrustedChildProcess {
  param([IntPtr]$Job,[Diagnostics.Process]$Process, [int]$TimeoutMilliseconds)
  if ($Process.WaitForExit([Math]::Max(0,$TimeoutMilliseconds))) { return }
  Stop-ArTrustedChildProcessTree -Job $Job -Process $Process
  throw 'Trusted SSH semantic preflight timed out and was terminated.'
}
function Wait-ArTrustedChildRedirectedTasks {
  param([IntPtr]$Job,[Diagnostics.Process]$Process, [Threading.Tasks.Task[]]$Tasks, [int]$TimeoutMilliseconds)
  if ([Threading.Tasks.Task]::WaitAll($Tasks,[Math]::Max(0,$TimeoutMilliseconds))) { return }
  Stop-ArTrustedChildProcessTree -Job $Job -Process $Process
  [void]([Threading.Tasks.Task]::WaitAll($Tasks,5000))
  throw 'Trusted SSH semantic preflight redirected streams did not close before the deadline.'
}
try {
  $configFull = Assert-ArTrustedPlainPath $ConfigPath
  $config = Get-Content -LiteralPath $configFull -Raw -ErrorAction Stop | ConvertFrom-Json
  $fields = @(
    'atomic_path', 'atomic_sha256', 'authority_path', 'control_root', 'dispatcher_path', 'dispatcher_sha256',
    'dispatcher_security_path', 'dispatcher_security_sha256',
    'git_path', 'git_sha256', 'python_path', 'python_sha256', 'schema_version',
    'receiver_path', 'scp_path', 'scp_sha256', 'ssh_host', 'ssh_identity_path', 'ssh_identity_sha256',
    'ssh_known_hosts_path', 'ssh_known_hosts_sha256', 'ssh_path', 'ssh_port', 'ssh_sha256', 'ssh_user',
    'whoami_path', 'whoami_sha256'
  )
  if ($config.schema_version -ne 5 -or
      @(Compare-Object $fields @($config.PSObject.Properties.Name | Sort-Object)).Count -ne 0) {
    throw 'Trusted child configuration schema is invalid.'
  }
  $trustedRoot = Assert-ArTrustedPlainPath $PSScriptRoot
  $python = Assert-ArTrustedPlainPath ([string]$config.python_path)
  $dispatcher = Assert-ArTrustedPlainPath ([string]$config.dispatcher_path)
  $dispatcherSecurity = Assert-ArTrustedPlainPath ([string]$config.dispatcher_security_path)
  $atomic = Assert-ArTrustedPlainPath ([string]$config.atomic_path)
  $control = Assert-ArTrustedPlainPath ([string]$config.control_root)
  $receiver = Assert-ArTrustedPlainPath ([string]$config.receiver_path)
  $authority = Assert-ArTrustedPlainPath ([string]$config.authority_path)
  $identity = Assert-ArTrustedPlainPath ([string]$config.ssh_identity_path)
  $knownHosts = Assert-ArTrustedPlainPath ([string]$config.ssh_known_hosts_path)
  Assert-ArTrustedWithinRoot $python $trustedRoot 'Python interpreter'
  Assert-ArTrustedWithinRoot $dispatcher $trustedRoot 'Dispatcher'
  Assert-ArTrustedWithinRoot $dispatcherSecurity $trustedRoot 'Dispatcher security module'
  Assert-ArTrustedWithinRoot $atomic $trustedRoot 'Dispatcher atomic module'
  Assert-ArTrustedWithinRoot $receiver $trustedRoot 'Receiver checkout'
  Assert-ArTrustedWithinRoot $authority $trustedRoot 'Authority checkout'
  Assert-ArTrustedWithinRoot $identity $trustedRoot 'SSH identity'
  Assert-ArTrustedWithinRoot $knownHosts $trustedRoot 'SSH known_hosts'
  if ($atomic -cne (Join-Path ([IO.Path]::GetDirectoryName($dispatcher)) 'laptop_backup_atomic.py')) {
    throw 'Dispatcher atomic module path is not exact.'
  }
  if ($dispatcherSecurity -cne (Join-Path ([IO.Path]::GetDirectoryName($dispatcher)) 'laptop_backup_dispatcher_security.py')) {
    throw 'Dispatcher security module path is not exact.'
  }
  if (-not (Test-Path -LiteralPath $python -PathType Leaf) -or
      -not (Test-Path -LiteralPath $dispatcher -PathType Leaf) -or
      -not (Test-Path -LiteralPath $dispatcherSecurity -PathType Leaf) -or
      -not (Test-Path -LiteralPath $atomic -PathType Leaf) -or
      -not (Test-Path -LiteralPath $identity -PathType Leaf) -or
      -not (Test-Path -LiteralPath $knownHosts -PathType Leaf) -or
      -not (Test-Path -LiteralPath $control -PathType Container)) {
    throw 'Trusted child dependency is absent.'
  }
  if ((Get-ArTrustedSha256 $python) -cne [string]$config.python_sha256 -or
      (Get-ArTrustedSha256 $dispatcher) -cne [string]$config.dispatcher_sha256 -or
      (Get-ArTrustedSha256 $dispatcherSecurity) -cne [string]$config.dispatcher_security_sha256 -or
      (Get-ArTrustedSha256 $atomic) -cne [string]$config.atomic_sha256 -or
      (Get-ArTrustedSha256 $identity) -cne [string]$config.ssh_identity_sha256 -or
      (Get-ArTrustedSha256 $knownHosts) -cne [string]$config.ssh_known_hosts_sha256) {
    throw 'Trusted child dependency hash mismatch.'
  }
  foreach ($path in @($python, $dispatcher, $dispatcherSecurity, $atomic, $identity, $knownHosts)) { Assert-ArTrustedWriteDenied $path }

  $sshHost = [string]$config.ssh_host; $sshUser = [string]$config.ssh_user; $sshPort = [int]$config.ssh_port
  if ($sshUser -cne 'pi' -or $sshPort -ne 22 -or $sshHost.Length -gt 253 -or $sshHost -notmatch '^[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?$' -or
      $sshHost.Contains('..') -or $sshUser -notmatch '^[a-z_][a-z0-9_-]{0,31}$' -or $sshPort -lt 1 -or $sshPort -gt 65535) {
    throw 'Trusted SSH endpoint identity is invalid.'
  }
  $knownHostToken = if ($sshPort -eq 22) { $sshHost } else { "[$sshHost]:$sshPort" }
  $knownHostMatch = [regex]::Match([IO.File]::ReadAllText($knownHosts,[Text.Encoding]::ASCII),('^' + [regex]::Escape($knownHostToken) + ' ssh-ed25519 (?<key>[A-Za-z0-9+/]+={0,2})(?: [^\r\n]+)?\n$'))
  if (-not $knownHostMatch.Success -or
      (Get-ArTrustedBytesSha256 ([Convert]::FromBase64String($knownHostMatch.Groups['key'].Value))) -cne '84569741c26189ddf0076b4c327e84b8c9df3d9c60cc6688f432190078a9ea7e') {
    throw 'Trusted SSH pinned host-key file is invalid.'
  }

  $system = [Environment]::GetFolderPath([Environment+SpecialFolder]::System)
  $programRoots = @(
    [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFiles),
    [Environment]::GetFolderPath([Environment+SpecialFolder]::ProgramFilesX86)
  ) | Where-Object { -not [String]::IsNullOrWhiteSpace($_) }
  $tools = @(
    @{ Name = 'git.exe'; Path = Assert-ArTrustedPlainPath ([string]$config.git_path); Hash = [string]$config.git_sha256; Root = $programRoots },
    @{ Name = 'ssh.exe'; Path = Assert-ArTrustedPlainPath ([string]$config.ssh_path); Hash = [string]$config.ssh_sha256; Root = @($system) },
    @{ Name = 'scp.exe'; Path = Assert-ArTrustedPlainPath ([string]$config.scp_path); Hash = [string]$config.scp_sha256; Root = @($system) },
    @{ Name = 'whoami.exe'; Path = Assert-ArTrustedPlainPath ([string]$config.whoami_path); Hash = [string]$config.whoami_sha256; Root = @($system) }
  )
  foreach ($tool in $tools) {
    if ([IO.Path]::GetFileName($tool.Path) -ine $tool.Name -or -not (Test-Path -LiteralPath $tool.Path -PathType Leaf)) {
      throw "Trusted system tool is absent or misnamed: $($tool.Name)"
    }
    $allowed = $false
    foreach ($root in $tool.Root) {
      $prefix = ([IO.Path]::GetFullPath($root)).TrimEnd([IO.Path]::DirectorySeparatorChar) + [IO.Path]::DirectorySeparatorChar
      if ($tool.Path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { $allowed = $true }
    }
    if (-not $allowed -or (Get-ArTrustedSha256 $tool.Path) -cne $tool.Hash) {
      throw "Trusted system tool path or hash is invalid: $($tool.Name)"
    }
    Assert-ArTrustedWriteDenied $tool.Path
  }
  $ssh = [string]$config.ssh_path
  $sshArguments = @(
    '-F','NUL','-o','BatchMode=yes','-o','ConnectTimeout=10','-o','IdentitiesOnly=yes','-o','IdentityAgent=none',
    '-o','PreferredAuthentications=publickey','-o','PasswordAuthentication=no','-o','KbdInteractiveAuthentication=no',
    '-o','ChallengeResponseAuthentication=no','-o','StrictHostKeyChecking=yes','-o',("UserKnownHostsFile=$knownHosts"),
    '-o','GlobalKnownHostsFile=NUL','-o','UpdateHostKeys=no','-o','VerifyHostKeyDNS=no','-o','ForwardAgent=no',
    '-o','ClearAllForwardings=yes','-o','RequestTTY=no','-i',$identity,'-p',[string]$sshPort,'-l',$sshUser,$sshHost,
    'printf','AR_SSH_PREFLIGHT_PASS'
  )
  $start = New-Object Diagnostics.ProcessStartInfo
  $start.FileName = $ssh
  $start.Arguments = (($sshArguments | ForEach-Object {
    $argument = [string]$_
    if ($argument -match '\s') { '"' + $argument + '"' } else { $argument }
  }) -join ' ')
  $start.UseShellExecute = $false; $start.RedirectStandardOutput = $true; $start.RedirectStandardError = $true
  $start.CreateNoWindow = $true
  $process = New-Object Diagnostics.Process; $process.StartInfo = $start
  $job = New-ArTrustedChildProcessJob
  $clock = [Diagnostics.Stopwatch]::StartNew()
  try {
    if (-not $process.Start()) { throw 'Trusted SSH semantic preflight failed to start.' }
    Add-ArTrustedChildProcessToJob -Job $job -Process $process
    $stdoutTask = $process.StandardOutput.ReadToEndAsync(); $stderrTask = $process.StandardError.ReadToEndAsync()
    try {
      Wait-ArTrustedChildProcess -Job $job -Process $process -TimeoutMilliseconds (30000 - [int]$clock.ElapsedMilliseconds)
    } catch {
      [void]([Threading.Tasks.Task]::WaitAll([Threading.Tasks.Task[]]@($stdoutTask,$stderrTask),5000))
      throw
    }
    Wait-ArTrustedChildRedirectedTasks -Job $job -Process $process -Tasks @($stdoutTask,$stderrTask) `
      -TimeoutMilliseconds (30000 - [int]$clock.ElapsedMilliseconds)
    $preflight = $stdoutTask.GetAwaiter().GetResult().TrimEnd(); $preflightError = $stderrTask.GetAwaiter().GetResult()
    if ($process.ExitCode -ne 0 -or $preflight -cne 'AR_SSH_PREFLIGHT_PASS' -or $preflightError) {
      throw 'Trusted SSH semantic preflight failed.'
    }
  } finally {
    $clock.Stop(); Close-ArTrustedChildProcessJob -Job $job; $process.Dispose()
  }
  if ($preflight -cne 'AR_SSH_PREFLIGHT_PASS') {
    throw 'Trusted SSH semantic preflight failed.'
  }
  $env:PATH = (($tools | ForEach-Object { [IO.Path]::GetDirectoryName($_.Path) } | Select-Object -Unique) -join ';')
  $env:AR_TRUSTED_ROOT = $trustedRoot
  $env:GIT_CONFIG_COUNT = '2'
  $env:GIT_CONFIG_KEY_0 = 'safe.directory'
  $env:GIT_CONFIG_VALUE_0 = $receiver
  $env:GIT_CONFIG_KEY_1 = 'safe.directory'
  $env:GIT_CONFIG_VALUE_1 = $authority
  $env:GIT_CONFIG_GLOBAL = 'NUL'
  $env:GIT_OPTIONAL_LOCKS = '0'
  $env:PYTHONNOUSERSITE = '1'
  $env:PYTHONDONTWRITEBYTECODE = '1'
  $env:AR_BACKUP_SSH_HOST = $sshHost
  $env:AR_BACKUP_SSH_USER = $sshUser
  $env:AR_BACKUP_SSH_PORT = [string]$sshPort
  $env:AR_BACKUP_SSH_PATH = [string]$config.ssh_path
  $env:AR_BACKUP_SSH_SHA256 = [string]$config.ssh_sha256
  $env:AR_BACKUP_SCP_PATH = [string]$config.scp_path
  $env:AR_BACKUP_SCP_SHA256 = [string]$config.scp_sha256
  $env:AR_BACKUP_SSH_IDENTITY = $identity
  $env:AR_BACKUP_SSH_KNOWN_HOSTS = $knownHosts
  $env:AR_BACKUP_SSH_PREFLIGHT = 'PASS'
  Remove-Item Env:\PYTEST_CURRENT_TEST -ErrorAction SilentlyContinue
  Get-ChildItem Env:\AR_DISPATCHER_TEST_* -ErrorAction SilentlyContinue | Remove-Item -ErrorAction SilentlyContinue
  $finalizeMarker = Join-Path $trustedRoot 'finalize.enabled'
  if (Test-Path -LiteralPath $finalizeMarker -PathType Leaf) {
    & $python -B -s -E $dispatcher finalize --control-root $control --output (Join-Path $control 'bootstrap-finalize.json')
  } else {
    & $python -B -s -E $dispatcher run --control-root $control
  }
  if ($null -eq $LASTEXITCODE) { throw 'Dispatcher returned no exit code.' }
  $code = [int]$LASTEXITCODE
} catch {
  [Console]::Error.WriteLine($_.Exception.Message)
  $code = 1
}
exit $code
