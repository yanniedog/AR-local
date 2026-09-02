param(
  [ValidateSet("menu", "daily", "force", "rebuild", "verify")]
  [string]$Action = "menu"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
& python (Join-Path $root "start_here.py") --action $Action
if ($LASTEXITCODE -ne 0) { throw "start_here.py failed: $LASTEXITCODE" }
