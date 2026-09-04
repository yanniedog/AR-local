param(
  [ValidateSet("menu", "daily", "force", "rebuild", "verify")]
  [string]$Action = "menu"
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
if (Get-Command python -ErrorAction SilentlyContinue) {
  & python (Join-Path $root "start_here.py") --action $Action
} elseif (Get-Command py -ErrorAction SilentlyContinue) {
  & py -3 (Join-Path $root "start_here.py") --action $Action
} else {
  throw "Python 3 is required"
}
if ($LASTEXITCODE -ne 0) { throw "start_here.py failed: $LASTEXITCODE" }
