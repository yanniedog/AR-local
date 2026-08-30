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

$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
  [Security.Principal.WindowsBuiltInRole]::Administrator
)
if ($isAdmin) {
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
    $replacement = New-ScheduledTask -Action (New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\whoami.exe") `
      -Settings $settings -Principal $principal
    Register-ScheduledTask -TaskName $name -InputObject $replacement -Force | Out-Null
    Restore-ArTrustedPriorTask -TaskName $name -TaskXml $xml -TaskSddl $sddl
    if ((Get-ArTrustedTextSha256 (Get-ArTrustedTaskSddl $name)) -cne (Get-ArTrustedTextSha256 $sddl) -or
        (Get-ArTrustedTextSha256 ([Text.Encoding]::Unicode.GetString((Get-ArTrustedTaskXmlBytes $name), 2, (Get-ArTrustedTaskXmlBytes $name).Length - 2))) -cne
        (Get-ArTrustedTextSha256 ([Text.Encoding]::Unicode.GetString($xmlBytes, 2, $xmlBytes.Length - 2)))) {
      throw 'Task Scheduler did not round-trip the authenticated task definition exactly.'
    }
  } finally {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction SilentlyContinue
  }
}
