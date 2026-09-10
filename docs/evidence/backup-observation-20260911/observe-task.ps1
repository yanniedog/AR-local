$ErrorActionPreference = 'Stop'
$task = Get-ScheduledTask -TaskName 'AR-local user-session backup'
$info = $task | Get-ScheduledTaskInfo
$history = Get-WinEvent -ListLog 'Microsoft-Windows-TaskScheduler/Operational'
$result = [ordered]@{
    checked_at = (Get-Date).ToString('o')
    state = [string]$task.State
    last_run = $info.LastRunTime.ToString('o')
    last_result = $info.LastTaskResult
    next_run = $info.NextRunTime.ToString('o')
    run_level = [string]$task.Principal.RunLevel
    history_enabled = $history.IsEnabled
    trigger_origin = 'UNVERIFIED'
    reason = 'Observed run aligns with daily trigger; disabled task history cannot establish trigger attribution.'
    task_mutated = $false
    exact_command = 'pwsh -NoProfile -File docs/evidence/backup-observation-20260911/observe-task.ps1'
}
$output = Join-Path $PSScriptRoot 'task-observation.json'
if (Test-Path -LiteralPath $output) { throw 'Preserve existing observation' }
$result | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $output -Encoding utf8
Export-ScheduledTask -TaskName $task.TaskName | Set-Content -LiteralPath (Join-Path $PSScriptRoot 'observed-task.xml') -Encoding utf8
$result | ConvertTo-Json -Compress
