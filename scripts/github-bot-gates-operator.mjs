#!/usr/bin/env node
/**
 * Operator helper: GitHub ruleset + bot-review policy for AR-local.
 *
 * Usage:
 *   node scripts/github-bot-gates-operator.mjs           # print setup + verify local artifacts
 *   node scripts/github-bot-gates-operator.mjs --verify-pr 123
 *   node scripts/github-bot-gates-operator.mjs --dry-run-protection
 *
 * GitHub side: import .github/rulesets/main-bot-gates.json via UI (API bypass 422 on personal repos).
 * Repo side: scripts/lib/pr-gate-exempt.mjs skips bot gates for chore + bot-authored PRs.
 */
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

const repoRoot = join(dirname(fileURLToPath(import.meta.url)), '..');
const RULESET_JSON = join(repoRoot, '.github', 'rulesets', 'main-bot-gates.json');
const REQUIRED_CHECKS = ['bot-presence-gate', 'bot-feedback-gate'];

function parseArgs(argv) {
  const out = { verifyPr: null, dryRunProtection: false, help: false };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--dry-run-protection') out.dryRunProtection = true;
    else if (a === '--verify-pr' && argv[i + 1]) out.verifyPr = argv[++i];
  }
  return out;
}

function printPolicy() {
  console.log(`
=== Bot review policy (repo code — NOT in GitHub ruleset) ===

Required on merge (human work PRs):
  - bot-presence-gate   (waits for gemini on human feat/fix/agent PRs)
  - bot-feedback-gate   (thread closure on human PRs)

Skipped automatically (scripts/lib/pr-gate-exempt.mjs):
  - PR author is a GitHub bot (login ends with [bot], e.g. github-actions[bot])
  - Title is conventional chore (chore: or chore(scope):)
  - Known automation titles (mobile auto-release bump, PR bot matrix)

Human PR example (bots required):  yanniedog + feat/fix/agent/*
Chore example (bots skipped):     chore(mobile): auto-release bump to v1.0.13 (after c1f0e31)
Bot PR example (bots skipped):      github-actions[bot] opens any title
`);
}

function printRulesetImport() {
  console.log(`
=== GitHub ruleset (one-time UI import) ===

File to import:
  ${RULESET_JSON}

Steps:
  1. GitHub → Settings → Rules → Rulesets → New ruleset → Import a ruleset
  2. Select the JSON file above
  3. Confirm:
       Target branches: refs/heads/main, ~DEFAULT_BRANCH
       Required checks:  bot-presence-gate, bot-feedback-gate (strict)
       PR rule:          squash only, conversation resolution ON, 0 approvals
       Bypass list:      GitHub Actions — mode Always (actor_id 15368)
  4. Save → Enforcement: Active
  5. DELETE legacy branch protection on main (Settings → Branches → main rule)
     Keeping both blocks workflow direct pushes even with ruleset bypass.

Why Actions bypass:
  - pr-bot-spreadsheet commits reports/* directly to main
  - mobile-auto-release-on-queue-drain pushes version bumps directly to main

API note: POST ruleset with bypass_actors often returns 422 on personal repos — use UI import.

Full doc: docs/GITHUB_RULESET_IMPORT.md
`);
}

function validateRulesetJson() {
  const raw = readFileSync(RULESET_JSON, 'utf8');
  const ruleset = JSON.parse(raw);
  const checks =
    ruleset.rules
      ?.find((r) => r.type === 'required_status_checks')
      ?.parameters?.required_status_checks?.map((c) => c.context) || [];
  const missing = REQUIRED_CHECKS.filter((c) => !checks.includes(c));
  if (missing.length) {
    throw new Error(`ruleset JSON missing checks: ${missing.join(', ')}`);
  }
  const hasActionsBypass = (ruleset.bypass_actors || []).some(
    (a) => a.actor_type === 'Integration' && a.actor_id === 15368,
  );
  if (!hasActionsBypass) {
    throw new Error('ruleset JSON missing GitHub Actions bypass (actor_id 15368)');
  }
  console.log('OK ruleset JSON:', RULESET_JSON);
  console.log('   required checks:', checks.join(', '));
  console.log('   Actions bypass:  actor_id 15368, mode always');
}

function runLocalVerifiers() {
  const scripts = [
    'scripts/verify-pr-gate-exempt-policy.mjs',
    'scripts/verify-pr-gate-logic.mjs',
    'scripts/verify-mobile-auto-release-commit.mjs',
    'scripts/verify-pr-bot-matrix-commit.mjs',
  ];
  for (const rel of scripts) {
    const r = spawnSync(process.execPath, [join(repoRoot, rel)], {
      encoding: 'utf8',
      cwd: repoRoot,
      timeout: 60_000,
    });
    if (r.status !== 0) {
      console.error((r.stderr || r.stdout || '').trim());
      throw new Error(`failed: ${rel}`);
    }
    console.log((r.stdout || '').trim());
  }
}

function verifyPrExemption(prNumber) {
  const r = spawnSync(
    process.execPath,
    ['scripts/pr-gate-exempt-reason.mjs'],
    {
      encoding: 'utf8',
      cwd: repoRoot,
      env: { ...process.env, PR: String(prNumber) },
      timeout: 60_000,
    },
  );
  if (r.status !== 0 || r.error) {
    throw new Error(
      `Failed to verify PR exemption: ${(r.stderr || r.error?.message || '').trim() || `exit ${r.status}`}`,
    );
  }
  const reason = (r.stdout || '').trim();
  if (reason) {
    console.log(`PR #${prNumber}: gate-exempt (${reason}) — bot review NOT required for merge`);
    return;
  }
  console.log(`PR #${prNumber}: NOT gate-exempt — gemini + thread closure required for merge`);
}

function dryRunBranchProtection() {
  const r = spawnSync(process.execPath, ['scripts/apply-branch-protection.mjs', '--dry-run'], {
    encoding: 'utf8',
    cwd: repoRoot,
    timeout: 120_000,
  });
  process.stdout.write(r.stdout || '');
  if (r.stderr) process.stderr.write(r.stderr);
  if (r.status !== 0) process.exit(r.status ?? 1);
}

function printPostSetupVerify() {
  console.log(`
=== After ruleset is active — verify ===

Local (no GitHub push):
  npm run pr:gate-logic:verify
  node scripts/github-bot-gates-operator.mjs

Exempt PR (expect gate-exempt reason):
  node scripts/github-bot-gates-operator.mjs --verify-pr <n>

Human PR gates:
  npm run pr:gates:check -- --pr <n>

Direct-to-main workflows (need Actions bypass + no legacy protection):
  gh workflow run pr-bot-spreadsheet.yml
  gh run list --workflow=pr-bot-spreadsheet.yml --limit 3

Repo merge settings (squash auto-merge):
  npm run repo-merge-settings:apply
`);
}

function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log(`Usage: node scripts/github-bot-gates-operator.mjs [--verify-pr N] [--dry-run-protection]`);
    process.exit(0);
  }

  printPolicy();
  printRulesetImport();

  try {
    validateRulesetJson();
  } catch (e) {
    console.error(`FAIL ruleset validation: ${e.message}`);
    process.exit(1);
  }

  console.log('\n=== Local policy self-tests ===');
  try {
    runLocalVerifiers();
  } catch (e) {
    console.error(`FAIL: ${e.message}`);
    process.exit(1);
  }

  if (args.verifyPr) {
    console.log('\n=== PR exemption check ===');
    try {
      verifyPrExemption(args.verifyPr);
    } catch (e) {
      console.error(`FAIL PR check: ${e.message}`);
      process.exit(1);
    }
  }

  if (args.dryRunProtection) {
    console.log('\n=== Legacy branch protection dry-run (no Actions bypass) ===');
    dryRunBranchProtection();
  }

  printPostSetupVerify();
}

main();
