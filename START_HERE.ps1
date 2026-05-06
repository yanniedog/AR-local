param(
  [ValidateSet("menu", "daily", "force", "rebuild", "dashboard", "schedule")]
  [string]$Action = "menu"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

function Get-PythonCommand {
  $python = Get-Command python -ErrorAction SilentlyContinue
  if ($python) { return @{ Exe = $python.Source; Prefix = @() } }
  $py = Get-Command py -ErrorAction SilentlyContinue
  if ($py) { return @{ Exe = $py.Source; Prefix = @("-3") } }
  throw "Python was not found. Install Python 3.10+ or add it to PATH."
}

function Invoke-LocalPython {
  param([Parameter(Mandatory = $true)][string[]]$Arguments)
  $cmd = Get-PythonCommand
  & $cmd.Exe @($cmd.Prefix + $Arguments)
  if ($LASTEXITCODE -ne 0) {
    throw "Python command failed with exit code $LASTEXITCODE."
  }
}

function Get-LatestRunDate {
  $runs = Join-Path $ScriptDir "runs"
  if (-not (Test-Path $runs)) { return $null }
  Get-ChildItem -Path $runs -Directory |
    Where-Object { $_.Name -match '^\d{4}-\d{2}-\d{2}$' } |
    Sort-Object Name -Descending |
    Select-Object -First 1 -ExpandProperty Name
}

function Get-RunDateOrThrow {
  $date = Get-LatestRunDate
  if (-not $date) {
    throw "No run folders found. Choose option 1 first to fetch CDR data."
  }
  return $date
}

function Invoke-DailyRun {
  param([switch]$Force)
  $args = @(".\cdr_daily.py", "--workers", "8")
  if ($Force) { $args += "--force" }
  Invoke-LocalPython -Arguments $args
}

function Invoke-RebuildExports {
  $date = Get-RunDateOrThrow
  Invoke-LocalPython -Arguments @(".\cdr_outputs.py", ".\runs\$date")
}

function Join-LocalUrl {
  param(
    [Parameter(Mandatory = $true)][string]$BaseUrl,
    [Parameter(Mandatory = $true)][string]$Path
  )
  return $BaseUrl.TrimEnd("/") + "/" + $Path.TrimStart("/")
}

function Open-Dashboard {
  $date = Get-RunDateOrThrow
  $exports = ".\runs\$date\_exports"
  if (-not (Test-Path $exports)) {
    Invoke-RebuildExports
  }
  $portFile = Join-Path ([System.IO.Path]::GetTempPath()) ("ar-cdr-dashboard-{0}.json" -f [System.Guid]::NewGuid())
  $python = Get-PythonCommand
  $arguments = @($python.Prefix + @(".\cdr_dashboard_server.py", "--exports", $exports, "--port", "auto", "--port-file", $portFile))
  $proc = Start-Process -FilePath $python.Exe -ArgumentList $arguments -WorkingDirectory $ScriptDir -WindowStyle Hidden -PassThru
  $url = $null
  $opened = $false
  $deadline = (Get-Date).AddSeconds(30)
  while ((Get-Date) -lt $deadline) {
    if ($proc.HasExited) {
      throw "Dashboard server exited with code $($proc.ExitCode)."
    }
    if (Test-Path $portFile) {
      try {
        $url = [string]((Get-Content -Path $portFile -Raw | ConvertFrom-Json).url)
      } catch {
        $url = $null
      }
      if ($url) {
        try {
          $health = Join-LocalUrl -BaseUrl $url -Path "api/latest"
          $response = Invoke-WebRequest -Uri $health -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
          if ($response.StatusCode -eq 200) {
            Start-Process $url
            $opened = $true
            break
          }
        } catch {
          Start-Sleep -Milliseconds 500
          continue
        }
      }
    }
    Start-Sleep -Milliseconds 500
  }
  Remove-Item -Path $portFile -ErrorAction SilentlyContinue
  if (-not $opened) {
    Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
    throw "Dashboard server did not become ready within 30 seconds."
  }
  Write-Host ""
  Write-Host "Dashboard opened: $url"
  Write-Host "Server process: $($proc.Id)"
}

function Install-DailyTask {
  & "$ScriptDir\install_daily_task.ps1" -At "03:15" -ExtraArgs "--workers 8"
}

function Show-Menu {
  while ($true) {
    $latest = Get-LatestRunDate
    if (-not $latest) { $latest = "none" }
    Write-Host ""
    Write-Host "Australian Rates local CDR"
    Write-Host "Latest run: $latest"
    Write-Host ""
    Write-Host "1. Run/update today's CDR data"
    Write-Host "2. Force rerun today's CDR data"
    Write-Host "3. Rebuild Excel/JSON/SQLite for latest run"
    Write-Host "4. Open dashboard"
    Write-Host "5. Install daily scheduled task"
    Write-Host "0. Exit"
    Write-Host ""
    $choice = Read-Host "Choose"
    switch ($choice) {
      "1" { Invoke-DailyRun; Read-Host "Done. Press Enter" }
      "2" { Invoke-DailyRun -Force; Read-Host "Done. Press Enter" }
      "3" { Invoke-RebuildExports; Read-Host "Done. Press Enter" }
      "4" { Open-Dashboard; Read-Host "Dashboard is open. Press Enter" }
      "5" { Install-DailyTask; Read-Host "Task installed. Press Enter" }
      "0" { return }
      default { Write-Host "Choose 0-5." }
    }
  }
}

switch ($Action) {
  "daily" { Invoke-DailyRun }
  "force" { Invoke-DailyRun -Force }
  "rebuild" { Invoke-RebuildExports }
  "dashboard" { Open-Dashboard }
  "schedule" { Install-DailyTask }
  default { Show-Menu }
}
