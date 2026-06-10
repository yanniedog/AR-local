#!/usr/bin/env node
/**
 * Push a staged mobile auto-release commit directly to main (no PR loop).
 */
import { spawnSync } from 'node:child_process';
import { AUTO_RELEASE_PUSH_BYPASS_HINT } from './lib/pr-mobile-auto-release-commit.mjs';

function parseArgs(argv) {
  const out = { dryRun: false, help: false };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--dry-run') out.dryRun = true;
  }
  return out;
}

function run(cmd, args, { allowFail = false, timeout = 60000 } = {}) {
  const r = spawnSync(cmd, args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'], timeout });
  if (r.error) throw new Error(r.error.message);
  if (r.status !== 0 && !allowFail) {
    const msg = (r.stderr || r.stdout || '').trim();
    throw new Error(msg || `${cmd} ${args.join(' ')} exit ${r.status}`);
  }
  return r;
}

export function isProtectedMainRejection(stderr) {
  const s = String(stderr || '');
  return (
    /protected branch hook declined/i.test(s)
    || /GH006: Protected branch update failed/i.test(s)
    || /refusing to allow a GitHub Actions workflow/i.test(s)
    || /Required status check/i.test(s)
  );
}

export function pushHeadToMain({
  branch = process.env.AUTO_RELEASE_COMMIT_BRANCH || 'main',
  maxAttempts = Number(process.env.AUTO_RELEASE_PUSH_RETRIES || 3),
  dryRun = false,
} = {}) {
  if (dryRun) {
    return { ok: true, dryRun: true };
  }

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    if (attempt > 1) {
      console.error(`mobile-auto-release-commit: retry ${attempt}/${maxAttempts} after rebase`);
    }
    run('git', ['pull', '--rebase', 'origin', branch]);

    const push = run('git', ['push', 'origin', `HEAD:${branch}`], { allowFail: true });
    if (push.status === 0) {
      console.log(`mobile-auto-release-commit: pushed auto-release to origin/${branch}`);
      return { ok: true };
    }

    const errText = (push.stderr || push.stdout || '').trim();
    if (isProtectedMainRejection(errText)) {
      console.error('::error::mobile-auto-release-commit: protected main rejected push');
      console.error(AUTO_RELEASE_PUSH_BYPASS_HINT);
      return { ok: false, protected: true, error: errText };
    }

    if (attempt === maxAttempts) {
      console.error(`mobile-auto-release-commit: push failed after ${maxAttempts} attempt(s)`);
      if (errText) console.error(errText);
      return { ok: false, protected: false, error: errText };
    }
  }

  return { ok: false, protected: false, error: 'push exhausted retries' };
}

function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log('Usage: node scripts/mobile-auto-release-commit.mjs [--dry-run]');
    process.exit(0);
  }

  const result = pushHeadToMain({ dryRun: args.dryRun });
  if (result.dryRun) {
    console.log('mobile-auto-release-commit: dry-run — would push HEAD to main');
    process.exit(0);
  }
  if (result.ok) process.exit(0);
  process.exit(result.protected ? 2 : 1);
}

const invoked = process.argv[1]?.replace(/\\/g, '/').endsWith('scripts/mobile-auto-release-commit.mjs');
if (invoked) {
  try {
    main();
  } catch (err) {
    console.error(`mobile-auto-release-commit: ${err.message}`);
    process.exit(1);
  }
}
