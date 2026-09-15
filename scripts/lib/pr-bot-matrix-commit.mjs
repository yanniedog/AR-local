/**
 * Git paths and helpers for committing generated PR bot matrix artifacts to main.
 */
import { DEFAULT_MATRIX_DIR, MATRIX_MD_FILE, MATRIX_HTML_FILE, MATRIX_JSON_FILE } from './pr-bot-matrix-writer.mjs';

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

/** Legacy export name retained; a rejected local push never justifies weakening protection. */
export const MATRIX_PUSH_BYPASS_HINT = `Protected main rejected the matrix push. Preserve existing branch protection.
Keep the generated reports locally, or submit the intended changes through a pull request.
The automated matrix report uses read-only Actions summaries and downloadable artifacts.
See docs/PR_BOT_MATRIX.md.`;
