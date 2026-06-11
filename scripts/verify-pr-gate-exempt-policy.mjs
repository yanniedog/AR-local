#!/usr/bin/env node
/**
 * Self-test for PR bot gate exemption policy (author + chore + automated chores).
 * Run: node scripts/verify-pr-gate-exempt-policy.mjs
 */
import {
  gateExemptReasonFromPrMeta,
  isBotPrAuthor,
  isChorePrTitle,
} from './lib/pr-gate-exempt.mjs';

const failures = [];

function check(name, got, want) {
  if (got !== want) failures.push(`${name}: got ${JSON.stringify(got)}, want ${JSON.stringify(want)}`);
}

check('bot login suffix', isBotPrAuthor('github-actions[bot]'), true);
check('human user', isBotPrAuthor({ login: 'yanniedog', type: 'User' }), false);
check('chore colon', isChorePrTitle('chore: update matrix'), true);
check('chore scope', isChorePrTitle('chore(mobile): bump'), true);
check('feat not chore', isChorePrTitle('feat(mobile): screen'), false);
check('agent branch title', isChorePrTitle('agent/dashboard-fix'), false);

check(
  'human feat requires bots',
  gateExemptReasonFromPrMeta({ title: 'fix: ING code', authorLogin: 'yanniedog', authorType: 'User' }),
  null,
);
check(
  'human chore skips',
  gateExemptReasonFromPrMeta({ title: 'chore: docs', authorLogin: 'yanniedog', authorType: 'User' }),
  'chore',
);
check(
  'bot-authored skips any title',
  gateExemptReasonFromPrMeta({ title: 'feat: automated', authorLogin: 'github-actions[bot]', authorType: 'Bot' }),
  'bot-authored',
);

if (failures.length) {
  console.error('FAIL verify-pr-gate-exempt-policy:');
  for (const f of failures) console.error('  -', f);
  process.exit(1);
}
console.log('PASS verify-pr-gate-exempt-policy');
