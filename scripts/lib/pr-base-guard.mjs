import { ghJson } from './gh-pr-review-threads.mjs';

export const BASE_GUARD_GATE_ID = 'base-unprotected';

/**
 * Required checks attach to the target branch. A PR aimed at a feature branch
 * can therefore bypass the default branch's gates, even if that feature branch
 * happens to look protected today. Only the exact repository default is safe.
 */
export function evaluateDefaultBase(baseRefName, defaultBranch) {
  if (!baseRefName) {
    return { covered: false, detail: 'PR base is unknown; auto-merge is refused' };
  }
  if (!defaultBranch) {
    return {
      covered: false,
      detail: 'Default branch could not be verified; auto-merge fails closed',
    };
  }
  if (baseRefName !== defaultBranch) {
    return {
      covered: false,
      detail:
        `PR targets ${baseRefName}, not default branch ${defaultBranch}. `
        + 'Retarget it at the default branch; feature-branch bases bypass required checks.',
    };
  }
  return {
    covered: true,
    detail: `base ${baseRefName} is the verified default branch`,
  };
}

export function checkDefaultBase(baseRefName, read = ghJson) {
  try {
    const repo = read(['repo', 'view', '--json', 'defaultBranchRef']);
    return evaluateDefaultBase(baseRefName, repo?.defaultBranchRef?.name);
  } catch (error) {
    return {
      covered: false,
      detail: `Default branch verification failed: ${error.message}`,
    };
  }
}
