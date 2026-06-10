/**
 * PRs that skip bot-presence-gate, bot-feedback-gate, and wait-for-bots.
 * Reports matrix artifacts and mobile auto-release version bumps only.
 */
import { isReportsOnlyFileList, isReportsOnlyPr } from './pr-reports-only.mjs';
import {
  isAutoReleaseCommitOnly,
  isAutoReleaseOnlyPr,
} from './pr-mobile-auto-release-commit.mjs';

export { isReportsOnlyPr, isAutoReleaseOnlyPr };

/**
 * @param {string[]|object[]} files
 * @returns {boolean}
 */
export function isGateExemptFileList(files) {
  return isReportsOnlyFileList(files) || isAutoReleaseCommitOnly(files);
}

/**
 * @param {number|string} prNumber
 * @returns {boolean}
 */
export function isGateExemptPr(prNumber) {
  return isReportsOnlyPr(prNumber) || isAutoReleaseOnlyPr(prNumber);
}

/**
 * @param {number|string} prNumber
 * @returns {'reports'|'mobile-auto-release'|null}
 */
export function gateExemptReason(prNumber) {
  if (isReportsOnlyPr(prNumber)) return 'reports';
  if (isAutoReleaseOnlyPr(prNumber)) return 'mobile-auto-release';
  return null;
}
