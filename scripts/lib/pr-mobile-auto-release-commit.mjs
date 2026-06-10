/**
 * Git paths and helpers for mobile auto-release version bumps (direct push + gate exempt).
 */
import { ghJson } from './gh-pr-review-threads.mjs';
import { fetchPrChangedPaths } from './pr-reports-only.mjs';

export const AUTO_RELEASE_BUMP_PREFIX = 'chore(mobile): auto-release bump to v';

/** Staged paths for auto-release commits (app.json + changelog tree). */
export const AUTO_RELEASE_COMMIT_REL_PATHS = ['mobile/app.json', 'mobile/changelog/'];

const VERSION_JSON_RE = /^mobile\/changelog\/versions\/\d+\.\d+\.\d+\.json$/;

/**
 * @param {string} filePath
 * @returns {boolean}
 */
export function isAutoReleaseCommitPath(filePath) {
  const p = String(filePath || '').replace(/\\/g, '/');
  if (p === 'mobile/app.json') return true;
  if (p === 'mobile/changelog/manifest.json') return true;
  return VERSION_JSON_RE.test(p);
}

/**
 * @param {string[]} paths
 * @returns {boolean}
 */
export function isAutoReleaseCommitOnly(paths) {
  if (!Array.isArray(paths) || paths.length === 0) return false;
  return paths.every((entry) => {
    const path = typeof entry === 'string' ? entry : entry?.path || '';
    return isAutoReleaseCommitPath(path);
  });
}

/**
 * @param {number|string} prNumber
 * @returns {boolean}
 */
export function isAutoReleaseOnlyPr(prNumber) {
  const paths = fetchPrChangedPaths(prNumber);
  if (!isAutoReleaseCommitOnly(paths)) return false;
  const view = ghJson(['pr', 'view', String(prNumber), '--json', 'title']);
  const title = String(view?.title || '').trim();
  return title.startsWith(AUTO_RELEASE_BUMP_PREFIX);
}

/** Shown when protected main rejects workflow push (no ruleset bypass). */
export const AUTO_RELEASE_PUSH_BYPASS_HINT = `Protected main rejected the mobile auto-release push. One-time repo setup (Settings → Rules → Rulesets):
1. Add or edit the main branch ruleset.
2. Under Bypass list, add "GitHub Actions" (bypass mode: always).
3. Optionally scope bypass to workflow file .github/workflows/mobile-auto-release-on-queue-drain.yml.
Legacy branch protection alone cannot grant path-scoped push bypass; a ruleset bypass is required.
See docs/HANDOFF.md → "Auto release when PR queue drains" → "Direct commit to main".`;
