param(
  [Parameter(Mandatory = $true)][string]$PythonPath,
  [Parameter(Mandatory = $true)][string]$ScriptPath,
  [Parameter(Mandatory = $true)][string]$Target,
  [Parameter(Mandatory = $true)][string]$RecoveryImage,
  [Parameter(Mandatory = $true)][string]$CandidateCodeSha,
  [Parameter(Mandatory = $true)][string]$ProtectedCodeSha,
  [Parameter(Mandatory = $true)][string]$PlanGitCommit,
  [Parameter(Mandatory = $true)][string]$Operator
)

$ErrorActionPreference = 'Continue'
& $PythonPath -B $ScriptPath --target $Target --recovery-image $RecoveryImage `
  --candidate-code-sha $CandidateCodeSha --protected-code-sha $ProtectedCodeSha `
  --plan-git-commit $PlanGitCommit --operator $Operator
$code = $LASTEXITCODE
if ($code -ne 0) {
  $message = "AR-local laptop backup failed (exit $code). Check catalog/latest-scheduled.json."
  & "$env:SystemRoot\System32\msg.exe" $env:USERNAME $message 2>$null
}
exit $code
