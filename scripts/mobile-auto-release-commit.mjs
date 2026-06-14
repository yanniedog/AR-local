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
  runCommand = run,
} = {}) {
  if (dryRun) {
    return { ok: true, dryRun: true };
  }

  // Record the exact stash commit created by this invocation. A clean tree
  // creates no stash, and must never pop an older unrelated entry.
  const stashBefore = runCommand('git', ['rev-parse', '--verify', 'refs/stash'], { allowFail: true });
  const beforeHash = stashBefore.status === 0 ? String(stashBefore.stdout || '').trim() : '';
  runCommand('git', ['stash', 'push', '--include-untracked', '-m', 'mobile-auto-release-commit'], { allowFail: true });
  const stashAfter = runCommand('git', ['rev-parse', '--verify', 'refs/stash'], { allowFail: true });
  const afterHash = stashAfter.status === 0 ? String(stashAfter.stdout || '').trim() : '';
  const invocationStash = afterHash && afterHash !== beforeHash ? afterHash : '';

  let result = { ok: false, protected: false, error: 'push exhausted retries' };
  try {
    for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
      if (attempt > 1) {
        console.error(`mobile-auto-release-commit: retry ${attempt}/${maxAttempts} after rebase`);
      }
      const pull = runCommand('git', ['pull', '--rebase', 'origin', branch], { allowFail: true });
      if (pull.status !== 0) {
        const errText = (pull.stderr || pull.stdout || '').trim();
        console.error(`mobile-auto-release-commit: pull failed: ${errText}`);
        runCommand('git', ['rebase', '--abort'], { allowFail: true });
        if (attempt === maxAttempts) {
          result = { ok: false, protected: false, error: errText };
          return result;
        }
        continue;
      }

      const push = runCommand('git', ['push', 'origin', `HEAD:${branch}`], { allowFail: true });
      if (push.status === 0) {
        console.log(`mobile-auto-release-commit: pushed auto-release to origin/${branch}`);
        result = { ok: true };
        return result;
      }

      const errText = (push.stderr || push.stdout || '').trim();
      if (isProtectedMainRejection(errText)) {
        console.error('::error::mobile-auto-release-commit: protected main rejected push');
        console.error(AUTO_RELEASE_PUSH_BYPASS_HINT);
        result = { ok: false, protected: true, error: errText };
        return result;
      }

      if (attempt === maxAttempts) {
        console.error(`mobile-auto-release-commit: push failed after ${maxAttempts} attempt(s)`);
        if (errText) console.error(errText);
        result = { ok: false, protected: false, error: errText };
        return result;
      }
    }
  } finally {
    if (invocationStash) {
      const applyResult = runCommand('git', ['stash', 'apply', invocationStash], { allowFail: true });
      if (applyResult.status !== 0) {
        const msg = (applyResult.stderr || applyResult.stdout || '').trim();
        if (msg) console.warn(`mobile-auto-release-commit: stash apply warning: ${msg}`);
      } else {
        const list = runCommand('git', ['stash', 'list', '--format=%H%x09%gd'], { allowFail: true });
        if (list.status !== 0) {
          const msg = (list.stderr || list.stdout || '').trim();
          console.warn(`mobile-auto-release-commit: stash list warning: ${msg || `exit ${list.status}`}`);
        } else {
          const match = String(list.stdout || '')
            .split(/\r?\n/)
            .map((line) => line.split('\t'))
            .find(([hash]) => hash === invocationStash);
          if (match?.[1]) {
            const dropResult = runCommand('git', ['stash', 'drop', match[1]], { allowFail: true });
            if (dropResult.status !== 0) {
              const msg = (dropResult.stderr || dropResult.stdout || '').trim();
              if (msg) console.warn(`mobile-auto-release-commit: stash drop warning: ${msg}`);
            }
          }
        }
      }
    }
  }

  return result;
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
