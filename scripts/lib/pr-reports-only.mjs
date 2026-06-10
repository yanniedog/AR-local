/**
 * Detect PRs that only change generated matrix artifacts under reports/.
 * Bot wait / thread gates skip these (paths-ignore left required checks stale).
 */
import { ghJson } from './gh-pr-review-threads.mjs';

export const REPORTS_ONLY_PREFIX = 'reports/';

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

export function isReportsOnlyPr(prNumber) {
  return isReportsOnlyFileList(fetchPrChangedPaths(prNumber));
}
