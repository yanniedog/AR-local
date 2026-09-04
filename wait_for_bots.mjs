#!/usr/bin/env node
/** Settle the required checks reported for the current PR head. */
import { spawnSync } from 'node:child_process';
import { setTimeout as sleepMs } from 'node:timers/promises';

const POLL_SEC = positiveNumber(process.env.BOT_WAIT_POLL_SEC, 45);

function positiveNumber(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function gh(args) {
  const result = spawnSync('gh', args, { encoding: 'utf8' });
  return {
    error: result.error?.message || null,
    status: result.status ?? 1,
    stderr: (result.stderr || '').trim(),
    stdout: (result.stdout || '').trim(),
  };
}

function parseArgs(argv) {
  const args = { help: false, pr: null, watch: false };
  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === '--help' || value === '-h') args.help = true;
    else if (value === '--watch' || value === '-w') args.watch = true;
    else if (value === '--pr' && argv[index + 1]) args.pr = Number(argv[++index]);
    else if (value.startsWith('--pr=')) args.pr = Number(value.slice(5));
    else throw new Error(`unknown option: ${value}`);
  }
  if (args.pr !== null && (!Number.isInteger(args.pr) || args.pr <= 0)) {
    throw new Error('--pr must be a positive integer');
  }
  return args;
}

function currentBranch() {
  const result = spawnSync('git', ['rev-parse', '--abbrev-ref', 'HEAD'], { encoding: 'utf8' });
  return result.status === 0 ? (result.stdout || '').trim() : '';
}

function resolvePr(requested, branch) {
  if (requested) return requested;
  if (!/^(agent|feat|fix)\//.test(branch)) return null;
  const result = gh([
    'pr', 'list', '--state', 'open', '--head', branch,
    '--json', 'number', '--jq', '.[0].number',
  ]);
  if (result.error || result.status !== 0) {
    throw new Error(result.error || result.stderr || `gh exit ${result.status}`);
  }
  const number = Number(result.stdout);
  return Number.isInteger(number) && number > 0 ? number : null;
}

function requiredChecks(prNumber) {
  const meta = gh(['pr', 'view', String(prNumber), '--json', 'headRefOid,state']);
  if (meta.error || meta.status !== 0) {
    return { status: 'error', message: meta.error || meta.stderr || `gh exit ${meta.status}` };
  }
  let pr;
  try {
    pr = JSON.parse(meta.stdout || '{}');
  } catch (error) {
    return { status: 'error', message: `invalid PR metadata: ${error.message}` };
  }
  if (pr.state !== 'OPEN') return { status: 'error', message: `PR #${prNumber} is ${pr.state}` };

  const result = gh([
    'pr', 'checks', String(prNumber), '--required',
    '--json', 'name,bucket,state',
  ]);
  const message = result.error || result.stderr;
  if (result.error) return { status: 'error', message: result.error };
  if (result.status === 1 && !result.stdout) {
    if (/no (required )?checks reported/i.test(message)) {
      return {
        status: 'pending',
        message: `PR #${prNumber} @ ${pr.headRefOid}: required checks not reported yet`,
      };
    }
    return { status: 'error', message: message || 'gh checks failed' };
  }
  if (![0, 1, 8].includes(result.status)) {
    return { status: 'error', message: message || `gh exit ${result.status}` };
  }

  let checks;
  try {
    checks = JSON.parse(result.stdout || '[]');
  } catch (error) {
    return { status: 'error', message: `invalid check data: ${error.message}` };
  }
  if (!Array.isArray(checks) || checks.length === 0) {
    return {
      status: 'pending',
      message: `PR #${prNumber} @ ${pr.headRefOid}: required checks not reported yet`,
    };
  }

  const failed = checks.filter((check) =>
    ['fail', 'cancel'].includes(check.bucket)
    || ['FAILURE', 'ERROR', 'CANCELLED', 'TIMED_OUT', 'ACTION_REQUIRED'].includes(check.state),
  );
  if (failed.length) {
    return {
      status: 'failed',
      message: `PR #${prNumber} @ ${pr.headRefOid}: failed required checks: ${failed.map((c) => c.name).join(', ')}`,
    };
  }

  const pending = checks.filter((check) =>
    check.bucket === 'pending' || ['PENDING', 'QUEUED', 'IN_PROGRESS', 'WAITING'].includes(check.state),
  );
  if (result.status === 8 || pending.length) {
    return {
      status: 'pending',
      message: `PR #${prNumber} @ ${pr.headRefOid}: required checks pending: ${pending.map((c) => c.name).join(', ') || 'unknown'}`,
    };
  }
  if (result.status === 1) {
    return { status: 'error', message: message || 'required checks failed without a named result' };
  }

  return {
    status: 'ready',
    message: `PR #${prNumber} @ ${pr.headRefOid}: ${checks.length} required check(s) passed`,
  };
}

function printHelp() {
  console.log(`Usage: npm run wait-for-bots -- [--pr N] [--watch]

Checks required GitHub contexts on the exact current PR head. Reviewer services
are advisory; unresolved substantive review threads are enforced separately by
npm run pr:bot-feedback-check.

Exit codes: 0 ready | 2 pending | 1 failed/error`);
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    printHelp();
    return 0;
  }
  if (spawnSync('gh', ['--version'], { stdio: 'ignore' }).status !== 0) {
    throw new Error('gh CLI is required');
  }
  const prNumber = resolvePr(args.pr, currentBranch());
  if (!prNumber) return 0;

  for (;;) {
    const result = requiredChecks(prNumber);
    const stream = result.status === 'failed' || result.status === 'error' ? console.error : console.log;
    stream(`wait-for-bots: ${result.message}`);
    if (result.status === 'ready') return 0;
    if (result.status !== 'pending') return 1;
    if (!args.watch) return 2;
    await sleepMs(POLL_SEC * 1000);
  }
}

main()
  .then((code) => process.exit(code))
  .catch((error) => {
    console.error(`wait-for-bots: ${error.message}`);
    process.exit(1);
  });
