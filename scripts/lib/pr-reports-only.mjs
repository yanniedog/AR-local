/**
 * Detect PRs that only change generated matrix artifacts under reports/.
 * Bot wait / thread gates skip these (paths-ignore left required checks stale).
 */
import { ghJson } from './gh-pr-review-threads.mjs';

export const REPORTS_ONLY_PREFIX = 'reports/';

/** Title for direct/matrix commits to main (gate-exempt when files match reports/). */
export const MATRIX_COMMIT_TITLE = 'chore: update PR bot feedback matrix';

export function isReportsOnlyPath(filePath) {
  return String(filePath || '').startsWith(REPORTS_ONLY_PREFIX);
}

export function isReportsOnlyFileList(files) {
  if (!Array.isArray(files) || files.length === 0) return false;
  return files.every((entry) => {
    const path = typeof entry === 'string' ? entry : entry?.path || '';
    return isReportsOnlyPath(path);
  });
}

export function fetchPrChangedPaths(prNumber) {
  const view = ghJson(['pr', 'view', String(prNumber), '--json', 'files']);
  return (view.files || []).map((f) => f.path);
}

/**
 * @param {string} title
 * @returns {boolean}
 */
export function isMatrixCommitTitle(title) {
  return String(title || '').trim() === MATRIX_COMMIT_TITLE;
}

export function isReportsOnlyPr(prNumber) {
  const view = ghJson(['pr', 'view', String(prNumber), '--json', 'title,files']);
  const title = String(view?.title || '').trim();
  const paths = (Array.isArray(view?.files) ? view.files : []).map((f) => f.path);
  if (isMatrixCommitTitle(title) && paths.length === 0) return true;
  return isReportsOnlyFileList(paths);
}
