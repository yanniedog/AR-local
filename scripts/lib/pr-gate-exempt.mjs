/**
 * PRs that skip bot-presence-gate, bot-feedback-gate, and wait-for-bots.
 *
 * Policy: Gemini / Codex / Sourcery are required only on human-initiated work PRs
 * (e.g. yanniedog). Skip for:
 *   - PRs opened by GitHub bots (github-actions[bot], dependabot, …)
 *   - Conventional chore PRs (chore: / chore(scope):)
 *   - Known automated chores (reports matrix)
 */
import { ghJson } from './gh-pr-review-threads.mjs';
import {
  isMatrixCommitTitle,
  isReportsOnlyFileList,
} from './pr-reports-only.mjs';
export { isMatrixCommitTitle };

/**
 * @param {{ login?: string, __typename?: string, type?: string }|string} author
 * @returns {boolean}
 */
export function isBotPrAuthor(author) {
  if (typeof author === 'string') {
    const login = author.trim();
    return login.endsWith('[bot]');
  }
  const login = String(author?.login || '').trim();
  const type = String(author?.__typename || author?.type || '').trim();
  if (type === 'Bot') return true;
  return login.endsWith('[bot]');
}

/**
 * Conventional-commit chore titles (chore: … or chore(scope): …).
 * @param {string} title
 * @returns {boolean}
 */
export function isChorePrTitle(title) {
  return /^chore(\(|:)/i.test(String(title || '').trim());
}

/**
 * Fast check from PR metadata (no file list). Used in Actions on pull_request opened.
 * @param {{ title?: string, authorLogin?: string, authorType?: string, author?: object }} meta
 * @returns {'bot-authored'|'chore'|'reports'|null}
 */
export function gateExemptReasonFromPrMeta(meta = {}) {
  const title = String(meta.title || '').trim();
  const author = meta.author || {
    login: meta.authorLogin,
    __typename: meta.authorType,
    type: meta.authorType,
  };

  if (isBotPrAuthor(author)) return 'bot-authored';
  if (isChorePrTitle(title)) {
    if (isMatrixCommitTitle(title)) return 'reports';
    return 'chore';
  }
  if (isMatrixCommitTitle(title)) return 'reports';
  return null;
}

/** @deprecated Use gateExemptReasonFromPrMeta */
export function gateExemptReasonFromTitle(title) {
  return gateExemptReasonFromPrMeta({ title });
}

/**
 * @param {string[]|object[]} files
 * @returns {boolean}
 */
export function isGateExemptFileList(files) {
  return isReportsOnlyFileList(files);
}

/**
 * @param {number|string} prNumber
 * @returns {boolean}
 */
export function isGateExemptPr(prNumber) {
  return gateExemptReason(prNumber) !== null;
}

/**
 * @param {number|string} prNumber
 * @returns {'bot-authored'|'chore'|'reports'|null}
 */
export function gateExemptReason(prNumber) {
  const view = ghJson(['pr', 'view', String(prNumber), '--json', 'title,author,files']);
  const metaReason = gateExemptReasonFromPrMeta({ title: view?.title, author: view?.author });
  if (metaReason) return metaReason;

  const paths = (Array.isArray(view?.files) ? view.files : []).map((f) => f.path);
  if (paths.length === 0) return null;
  if (isReportsOnlyFileList(paths)) return 'reports';
  return null;
}
