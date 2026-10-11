/** Reviewers are advisory by default; required CI still determines readiness. */
export function requiredCiWaitResult(checks) {
  if (!checks.ok) return { status: 'error', message: checks.error };
  if (checks.failed) return { status: 'error', message: `Required CI failed: ${checks.failedNames.join(', ')}` };
  if (checks.pending) return { status: 'waiting', message: 'Required CI still pending; reviewers are advisory.' };
  return { status: 'ready', message: 'Required CI settled; reviewers are advisory.' };
}

/** Apply current opt-in policy; saved session state never grants reviewer authority. */
export function applyReviewerPolicy(state, currentKeys) {
  const keys = [...currentKeys];
  if (JSON.stringify(state.requiredKeys) !== JSON.stringify(keys)) {
    state.requiredKeys = keys;
    state.readyAt = null;
  }
  return keys;
}

/** Self-gates are downstream of review synthesis and cannot gate bot wait itself. */
export function reviewWaitIgnoredChecks(raw = '') {
  return new Set([
    'bot-presence-gate', 'bot-feedback-gate', 'pr-bot-presence-gate',
    'pr-bot-feedback-check', 'pr-gates-advisory',
    ...String(raw).split(',').map((name) => name.trim().toLowerCase()).filter(Boolean),
  ]);
}
