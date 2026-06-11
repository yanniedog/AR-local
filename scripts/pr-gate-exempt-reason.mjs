#!/usr/bin/env node
/**
 * Resolve gate-exempt reason for a PR (stdout: reason or empty).
 * Used by bot gate workflows with event metadata + optional PR number fallback.
 *
 * Env: PR, PR_TITLE, PR_AUTHOR, PR_AUTHOR_TYPE, GH_TOKEN
 */
import { gateExemptReason, gateExemptReasonFromPrMeta } from './lib/pr-gate-exempt.mjs';

const pr = process.env.PR?.trim() || '';
const title = process.env.PR_TITLE || '';
const authorLogin = process.env.PR_AUTHOR || '';
const authorType = process.env.PR_AUTHOR_TYPE || '';

let reason = gateExemptReasonFromPrMeta({ title, authorLogin, authorType });
if (!reason && pr) {
  reason = gateExemptReason(pr);
}

process.stdout.write(reason || '');
