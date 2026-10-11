/** Reviewers are advisory by default; required CI still determines readiness. */
export function requiredCiWaitResult(checks) {
  if (!checks.ok) return { status: 'error', message: checks.error };
  if (checks.failed) return { status: 'error', message: `Required CI failed: ${checks.failedNames.join(', ')}` };
  if (checks.pending) return { status: 'waiting', message: 'Required CI still pending; reviewers are advisory.' };
  return { status: 'ready', message: 'Required CI settled; reviewers are advisory.' };
}
