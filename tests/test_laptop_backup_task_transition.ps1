$ErrorActionPreference = 'Stop'
. (Join-Path (Join-Path $PSScriptRoot '..') 'laptop_backup_task_transition_core.ps1')

$script:enabled = $true
$script:state = 'Ready'
$script:candidate = 'dddddddddddddddddddddddddddddddddddddddd'
$script:disableReadBackFails = $false
$script:registeredXml = $null
$script:registrationFails = $false

function Get-ScheduledTask {
  [CmdletBinding()]
  param([string]$TaskName)
  [pscustomobject]@{
    State = $script:state
    Actions = @([pscustomobject]@{
      Execute = 'powershell.exe'
      Arguments = "-CandidateCodeSha $($script:candidate)"
      WorkingDirectory = 'C:\receiver'
    })
    Triggers = @(
      [pscustomobject]@{
        CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskDailyTrigger' }
        StartBoundary = '2026-08-29T05:00:00+10:00'
        Delay = ''
      },
      [pscustomobject]@{
        CimClass = [pscustomobject]@{ CimClassName = 'MSFT_TaskBootTrigger' }
        StartBoundary = ''
        Delay = 'PT5M'
      }
    )
    Principal = [pscustomobject]@{ UserId = 'YANNIEDOG\jkoka'; LogonType = 'S4U'; RunLevel = 'Limited' }
    Settings = [pscustomobject]@{
      Enabled = $script:enabled
      MultipleInstances = 'IgnoreNew'
      RestartCount = 3
      RestartInterval = 'PT30M'
      ExecutionTimeLimit = 'PT6H'
      StartWhenAvailable = $true
    }
  }
}

function Get-ScheduledTaskInfo {
  [CmdletBinding()]
  param([string]$TaskName)
  [pscustomobject]@{ LastTaskResult = 0; NextRunTime = [datetime]'2026-08-30T05:00:00' }
}

function Export-ScheduledTask { [CmdletBinding()] param([string]$TaskName) '<Task>accepted</Task>' }

function Disable-ScheduledTask {
  [CmdletBinding()]
  param([string]$TaskName)
  if (-not $script:disableReadBackFails) {
    $script:enabled = $false
    $script:state = 'Disabled'
  }
}

function Register-ScheduledTask {
  [CmdletBinding()]
  param([string]$TaskName, [string]$Xml, [switch]$Force)
  if ($script:registrationFails) { throw 'injected registration failure' }
  $script:registeredXml = $Xml
  $script:state = 'Ready'
}

function Enable-ScheduledTask {
  [CmdletBinding()]
  param([string]$TaskName)
  $script:enabled = $true
  $script:state = 'Ready'
}

$snapshot = Invoke-ArTransitionTaskAction -Action Snapshot -TaskName 'test'
$xmlBytes = [Convert]::FromBase64String($snapshot.xml_base64)
if ($xmlBytes[0] -ne 0xff -or $xmlBytes[1] -ne 0xfe) { throw 'Snapshot XML is not UTF-16LE+BOM.' }
if ($snapshot.receiver_sha -ne $script:candidate) { throw 'Snapshot candidate extraction failed.' }

$disabled = Invoke-ArTransitionTaskAction -Action Disable -TaskName 'test'
if ($disabled.state -ne 'Disabled' -or $disabled.enabled) { throw 'Disable did not prove disabled read-back.' }

$oldXml = Join-Path $TestDrive 'old-task.xml'
Set-Content -LiteralPath $oldXml -Value '<Task>old exact</Task>' -NoNewline
$restored = Invoke-ArTransitionTaskAction -Action Restore -TaskName 'test' -OldTaskXmlPath $oldXml
if ($restored.state -ne 'Ready' -or -not $restored.enabled) { throw 'Restore did not prove Ready/enabled.' }
if ($script:registeredXml -ne '<Task>old exact</Task>') { throw 'Restore did not register exact XML.' }

$receiver = Join-Path $TestDrive 'receiver'
New-Item -ItemType Directory -Path $receiver | Out-Null
$installer = Join-Path $receiver 'install_laptop_backup_task.ps1'
@'
param($TaskName,$Target,$RecoveryImage,$CandidateCodeSha,$ProtectedCodeSha,$PlanGitCommit,$Operator,$PythonPath,$TransitionId)
'{"ok":true,"result":"PASS","action":"NO_BACKUP_DATA_WRITE","execution_record":"C:\\record.json"}'
'transition-id=' + $TransitionId
'{"task_name":"AR-local laptop backup"}'
exit 0
'@ | Set-Content -LiteralPath $installer
$script:candidate = 'cccccccccccccccccccccccccccccccccccccccc'
$installed = Invoke-ArTransitionTaskAction -Action Install -TaskName 'test' -Receiver $receiver `
  -Target 'C:\target' -RecoveryImage 'C:\image' -CandidateCodeSha $script:candidate `
  -ProtectedCodeSha '9999999999999999999999999999999999999999' `
  -PlanGitCommit 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' -Operator 'jkoka' `
  -PythonPath 'C:\python.exe' -TransitionId 'test-transition'
if ($installed.task.receiver_sha -ne $script:candidate) { throw 'Install read-back candidate failed.' }
if ($installed.installer_stdout -notmatch 'NO_BACKUP_DATA_WRITE') { throw 'Installer output was not preserved.' }
if ($installed.installer_stdout -notmatch 'transition-id=test-transition') { throw 'Transition identity was not delegated.' }

$script:disableReadBackFails = $true
$script:enabled = $true
$script:state = 'Ready'
$disableFailed = $false
try { Invoke-ArTransitionTaskAction -Action Disable -TaskName 'test' } catch {
  if ($_.Exception.Message -notmatch 'read-back failed') { throw }
  $disableFailed = $true
}
if (-not $disableFailed) { throw 'Partial disable did not fail closed.' }

$script:registrationFails = $true
$restoreFailed = $false
try { Invoke-ArTransitionTaskAction -Action Restore -TaskName 'test' -OldTaskXmlPath $oldXml } catch {
  if ($_.Exception.Message -notmatch 'injected registration failure') { throw }
  $restoreFailed = $true
}
if (-not $restoreFailed) { throw 'Restore registration failure did not fail closed.' }
