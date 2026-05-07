param(
  [ValidateSet("menu", "daily", "force", "rebuild", "dashboard", "schedule", "git-status", "db-summary")]
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

$cmd = Get-PythonCommand
$arguments = @($cmd.Prefix + @(".\start_here.py", "--action", $Action))
& $cmd.Exe @arguments
if ($LASTEXITCODE -ne 0) {
  throw "start_here.py failed with exit code $LASTEXITCODE."
}
