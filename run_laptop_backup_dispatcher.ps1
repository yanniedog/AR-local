param(
  [Parameter(Mandatory = $true)][string]$PythonPath,
  [Parameter(Mandatory = $true)][string]$DispatcherPath,
  [Parameter(Mandatory = $true)][string]$ControlRoot
)

$ErrorActionPreference = 'Continue'
& $PythonPath $DispatcherPath run --control-root $ControlRoot
$code = $LASTEXITCODE
if ($code -ne 0) {
  $message = "AR-local laptop backup dispatcher failed (exit $code). Check dispatcher activation and scheduled-run evidence."
  & "$env:SystemRoot\System32\msg.exe" $env:USERNAME $message 2>$null
}
exit $code
