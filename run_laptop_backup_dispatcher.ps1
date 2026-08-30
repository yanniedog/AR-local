param(
  [Parameter(Mandatory = $true)][string]$PythonPath,
  [Parameter(Mandatory = $true)][string]$DispatcherPath,
  [Parameter(Mandatory = $true)][string]$ControlRoot
)

$ErrorActionPreference = 'Stop'
$code = 1
try {
  & $PythonPath $DispatcherPath run --control-root $ControlRoot
  if ($null -eq $LASTEXITCODE) { throw 'Dispatcher process did not return an exit code.' }
  $code = [int]$LASTEXITCODE
} catch {
  $code = 1
}
if ($code -ne 0) {
  $message = "AR-local laptop backup dispatcher failed (exit $code). Check dispatcher activation and scheduled-run evidence."
  try { & "$env:SystemRoot\System32\msg.exe" $env:USERNAME $message 2>$null } catch { }
}
exit $code
