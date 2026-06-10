#!/usr/bin/env node
/**
 * Stage, commit, and push PR bot matrix artifacts directly to main.
 * Used by .github/workflows/pr-bot-spreadsheet.yml (no PR loop).
 *
 * Usage: node scripts/pr-bot-matrix-commit.mjs [--dry-run]
 *
 * Env:
 *   MATRIX_COMMIT_BRANCH — target branch (default main)
 *   MATRIX_PUSH_RETRIES — rebase+push attempts on race (default 3)
 */
import { spawnSync } from 'node:child_process';
import {
  MATRIX_COMMIT_MESSAGE,
  MATRIX_COMMIT_REL_PATHS,
  MATRIX_PUSH_BYPASS_HINT,
} from './lib/pr-bot-matrix-commit.mjs';

const GH_ACTIONS_NAME = 'github-actions[bot]';
const GH_ACTIONS_EMAIL = '41898282+github-actions[bot]@users.noreply.github.com';

function parseArgs(argv) {
  const out = { dryRun: false, help: false };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--dry-run') out.dryRun = true;
  }
  return out;
}

function gitIdentityEnv() {
  return {
    GIT_AUTHOR_NAME: GH_ACTIONS_NAME,
    GIT_AUTHOR_EMAIL: GH_ACTIONS_EMAIL,
    GIT_COMMITTER_NAME: GH_ACTIONS_NAME,
    GIT_COMMITTER_EMAIL: GH_ACTIONS_EMAIL,
  };
}

function run(cmd, args, { allowFail = false, timeout = 60000, env } = {}) {
  const r = spawnSync(cmd, args, {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'pipe'],
    timeout,
    env: { ...process.env, ...env },
  });
  if (r.error) throw new Error(r.error.message);
  if (r.status !== 0 && !allowFail) {
    const msg = (r.stderr || r.stdout || '').trim();
    throw new Error(msg || `${cmd} ${args.join(' ')} exit ${r.status}`);
  }
  return r;
}

function runGit(args, opts = {}) {
  return run('git', args, { ...opts, env: { ...process.env, ...gitIdentityEnv(), ...opts.env } });
}

function hasStagedChanges() {
  const r = runGit(['diff', '--staged', '--quiet'], { allowFail: true });
  return r.status !== 0;
}

function stageMatrixFiles() {
  runGit(['add', '--', ...MATRIX_COMMIT_REL_PATHS]);
}

function commitMatrix() {
  runGit(['commit', '-m', MATRIX_COMMIT_MESSAGE]);
}

function pullRebase(branch) {
  runGit(['pull', '--rebase', 'origin', branch]);
}

function pushMain(branch) {
  return runGit(['push', 'origin', `HEAD:${branch}`], { allowFail: true });
}

function isProtectedMainRejection(stderr) {
  const s = String(stderr || '');
  return (
    /protected branch hook declined/i.test(s)
    || /GH006: Protected branch update failed/i.test(s)
    || /refusing to allow a GitHub Actions workflow/i.test(s)
    || /Required status check/i.test(s)
  );
}

function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log(`Usage: node scripts/pr-bot-matrix-commit.mjs [--dry-run]

Commits only:
  ${MATRIX_COMMIT_REL_PATHS.join('\n  ')}`);
    process.exit(0);
  }

  const branch = process.env.MATRIX_COMMIT_BRANCH || 'main';
  const maxAttempts = Number(process.env.MATRIX_PUSH_RETRIES || 3);

  stageMatrixFiles();

  if (!hasStagedChanges()) {
    console.log('pr-bot-matrix-commit: matrix unchanged — no commit');
    process.exit(0);
  }

  if (args.dryRun) {
    console.log('pr-bot-matrix-commit: dry-run — would commit and push to', branch);
    process.exit(0);
  }

  commitMatrix();

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    if (attempt > 1) {
      console.error(`pr-bot-matrix-commit: retry ${attempt}/${maxAttempts} after rebase`);
    }
    pullRebase(branch);

    const push = pushMain(branch);
    if (push.status === 0) {
      console.log(`pr-bot-matrix-commit: pushed matrix to origin/${branch}`);
      process.exit(0);
    }

    const errText = (push.stderr || push.stdout || '').trim();
    if (isProtectedMainRejection(errText)) {
      console.error('::error::pr-bot-matrix-commit: protected main rejected push');
      console.error(MATRIX_PUSH_BYPASS_HINT);
      process.exit(2);
    }

    if (attempt === maxAttempts) {
      console.error(`pr-bot-matrix-commit: push failed after ${maxAttempts} attempt(s)`);
      if (errText) console.error(errText);
      process.exit(1);
    }
  }
}

try {
  main();
} catch (err) {
  console.error(`pr-bot-matrix-commit: ${err.message}`);
  process.exit(1);
}
