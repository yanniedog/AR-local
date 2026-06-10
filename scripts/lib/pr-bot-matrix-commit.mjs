/**
 * Git paths and helpers for committing generated PR bot matrix artifacts to main.
 */
import { DEFAULT_MATRIX_DIR, MATRIX_HTML_FILE, MATRIX_JSON_FILE, MATRIX_MD_FILE } from './pr-bot-matrix-writer.mjs';

/** Relative paths committed by pr-bot-spreadsheet (reports-only). */
export const MATRIX_COMMIT_REL_PATHS = [
  `${DEFAULT_MATRIX_DIR}/${MATRIX_MD_FILE}`,
  `${DEFAULT_MATRIX_DIR}/${MATRIX_HTML_FILE}`,
  `${DEFAULT_MATRIX_DIR}/${MATRIX_JSON_FILE}`,
];

export const MATRIX_COMMIT_MESSAGE = 'chore: update PR bot feedback matrix';

/**
 * @param {string} filePath
 * @returns {boolean}
 */
export function isMatrixCommitPath(filePath) {
  return MATRIX_COMMIT_REL_PATHS.includes(String(filePath || '').replace(/\\/g, '/'));
}

/**
 * @param {string[]} paths
 * @returns {boolean}
 */
export function isMatrixCommitOnly(paths) {
  if (!Array.isArray(paths) || paths.length === 0) return false;
  const normalized = paths.map((p) => String(p || '').replace(/\\/g, '/'));
  if (normalized.length !== MATRIX_COMMIT_REL_PATHS.length) return false;
  const sorted = [...normalized].sort();
  const expected = [...MATRIX_COMMIT_REL_PATHS].sort();
  return sorted.every((p, i) => p === expected[i]);
}

/** Shown when protected main rejects workflow push (no ruleset bypass). */
export const MATRIX_PUSH_BYPASS_HINT = `Protected main rejected the matrix push. One-time repo setup (Settings → Rules → Rulesets):
1. Add or edit the main branch ruleset.
2. Under Bypass list, add "GitHub Actions" (bypass mode: always).
3. Optionally scope bypass to workflow file .github/workflows/pr-bot-spreadsheet.yml.
Legacy branch protection alone cannot grant path-scoped push bypass; a ruleset bypass is required.
See docs/PR_BOT_MATRIX.md → "Direct commit to main".`;
