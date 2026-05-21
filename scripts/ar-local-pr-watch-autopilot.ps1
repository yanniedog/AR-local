# AR-local PR watch autopilot host (Windows 24/7).
# Logs stdout/stderr to .ar-pr-watch/autopilot.log
param(
    [string]$RepoRoot = $PSScriptRoot + '\..'
)

$ErrorActionPreference = 'Stop'
$RepoRoot = (Resolve-Path $RepoRoot).Path
Set-Location $RepoRoot

$logDir = Join-Path $RepoRoot '.ar-pr-watch'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
$logFile = Join-Path $logDir 'autopilot.log'

$env:AR_PR_WATCH_AUTOPILOT = '1'
if (-not $env:AR_PI_BASE_URL) { $env:AR_PI_BASE_URL = 'http://100.78.28.10/' }

function Write-Log([string]$Message) {
    $line = "[{0}] {1}" -f (Get-Date -Format 'o'), $Message
    Add-Content -Path $logFile -Value $line -Encoding utf8
}

Write-Log "host start repo=$RepoRoot pid=$PID"

while ($true) {
    try {
        $p = Start-Process -FilePath 'npm.cmd' -ArgumentList @('run', 'pr:watch:autopilot') `
            -WorkingDirectory $RepoRoot -NoNewWindow -Wait -PassThru
        if ($p.ExitCode -ne 0) {
            Write-Log "npm exit $($p.ExitCode) (see node stdout in autopilot.log)"
        }
        Write-Log "autopilot exited $($p.ExitCode) — restart in 30s"
    } catch {
        Write-Log "autopilot error: $_"
    }
    Start-Sleep -Seconds 30
}
