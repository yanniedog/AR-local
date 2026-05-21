#!/usr/bin/env node
/**
 * One autopilot tick: gate scan, state.json, optional merge+Pi, optional Cursor invoke.
 *
 * Exit 0 — idle, or merge-ready with nothing to merge, or merged this tick
 * Exit 1 — gh/config error
 * Exit 2 — remediation needed (agent invoked or cooldown)
 * Exit 3 — another autopilot instance holds the lock
 */
import { spawnSync } from 'node:child_process';
import { setTimeout as sleepMs } from 'node:timers/promises';
import { runWatchCycle, cycleToState } from './lib/pr-watch-cycle.mjs';
import { REPO_ROOT } from './lib/pr-gates-lib.mjs';
import {
  acquireLock,
  touchLock,
  releaseLock,
  writeState,
  appendAutopilotLog,
  AUTO_LOCK_PATH,
  DEFAULT_PROMPT,
} from './lib/pr-watch-state.mjs';
import { invokeCursorForPrWatch } from './lib/cursor-invoke.mjs';

const COOLDOWN_MS = Number(process.env.AR_PR_WATCH_CURSOR_COOLDOWN_MS) || 10 * 60 * 1000;
const SKIP_CURSOR = process.env.AR_PR_WATCH_SKIP_CURSOR === '1';
const SKIP_MERGE = process.env.AR_PR_WATCH_SKIP_MERGE === '1';

function parseArgs(argv) {
  const out = { json: false, invoke: false, noLock: false, help: false };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--json') out.json = true;
    else if (a === '--invoke') out.invoke = true;
    else if (a === '--no-lock') out.noLock = true;
  }
  return out;
}

function run(cmd, args, opts = {}) {
  const r = spawnSync(cmd, args, {
    cwd: REPO_ROOT,
    encoding: 'utf8',
    env: process.env,
    timeout: opts.timeout || 600_000,
    shell: opts.shell ?? false,
    windowsHide: true,
  });
  return { status: r.status ?? 1, stdout: (r.stdout || '').trim(), stderr: (r.stderr || '').trim() };
}

function gitFetch() {
  return run('git', ['fetch', 'origin']);
}

function mergePr(prNumber) {
  appendAutopilotLog(`merge: squashing PR #${prNumber}`);
  const m = run('gh', ['pr', 'merge', String(prNumber), '--squash', '--delete-branch'], { timeout: 120_000 });
  if (m.status !== 0) {
    return { ok: false, detail: m.stderr || m.stdout || `gh pr merge exit ${m.status}` };
  }
  run('node', ['scripts/close-loop-check.mjs', '--pr', String(prNumber)]);
  run('npm', ['run', 'git:graph-hygiene']);
  return { ok: true };
}

function postMergePi() {
  const needs = run('npm', ['run', 'pi:needs-deploy', '--', '--ref', 'origin/main~1'], { shell: true });
  if (needs.status !== 0) {
    appendAutopilotLog('post-merge: pi:needs-deploy — no Pi paths touched; skip deploy');
    return { deployed: false, verifyExit: null };
  }
  appendAutopilotLog('post-merge: pi deploy + verify');
  const dep = run('npm', ['run', 'pi:deploy'], { shell: true, timeout: 600_000 });
  if (dep.status !== 0) {
    return { deployed: false, verifyExit: dep.status, detail: dep.stderr || dep.stdout };
  }
  run('npm', ['run', 'pi:deploy:verify'], { shell: true, timeout: 300_000 });
  const v = run('npm', ['run', 'verify:pi'], { shell: true, timeout: 120_000 });
  return { deployed: true, verifyExit: v.status };
}

function shouldInvokeCursor(state, prNumbers) {
  if (SKIP_CURSOR || !prNumbers.length) return false;
  const last = state?.lastCursorInvokeAt ? new Date(state.lastCursorInvokeAt).getTime() : 0;
  if (Number.isFinite(last) && Date.now() - last < COOLDOWN_MS) return false;
  const lastPrs = (state?.lastCursorInvokePrs || []).join(',');
  const nextPrs = prNumbers.join(',');
  if (lastPrs === nextPrs && Number.isFinite(last) && Date.now() - last < COOLDOWN_MS * 2) return false;
  return true;
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log(`Usage: npm run pr:watch:tick -- [--json] [--invoke] [--no-lock]

Writes .ar-pr-watch/state.json, optionally merges oldest merge-ready PR, invokes Cursor when gates fail.
`);
    process.exit(0);
  }

  let lockHeld = false;
  if (!args.noLock) {
    const lock = acquireLock(AUTO_LOCK_PATH, { role: 'tick' });
    if (!lock.ok) {
      const msg = `autopilot lock held by pid ${lock.lock?.pid}`;
      if (args.json) console.log(JSON.stringify({ locked: true, lock: lock.lock }, null, 2));
      else console.error(`pr-watch-tick: ${msg}`);
      process.exit(3);
    }
    lockHeld = true;
  }

  try {
    gitFetch();
    const cycle = await runWatchCycle({});
    if (cycle.error) {
      appendAutopilotLog(`error: ${cycle.error}`);
      console.error(`pr-watch-tick: ${cycle.error}`);
      process.exit(1);
    }

    const state = writeState({
      ...cycleToState(cycle, { prompt: DEFAULT_PROMPT }),
      lastTickAt: new Date().toISOString(),
    });

    if (cycle.idle) {
      appendAutopilotLog('idle: no open PRs');
      if (args.json) console.log(JSON.stringify({ idle: true, exitCode: 0 }, null, 2));
      process.exit(0);
    }

    let merged = null;
    let pi = null;
    if (!SKIP_MERGE && cycle.allPass) {
      const ready = cycle.results.filter((r) => r.gatesPass);
      const oldest = ready[0];
      if (oldest) {
        const mergeResult = mergePr(oldest.number);
        if (mergeResult.ok) {
          merged = oldest.number;
          pi = postMergePi();
          const after = await runWatchCycle({});
          writeState({
            ...cycleToState(after, { prompt: DEFAULT_PROMPT }),
            lastMergeAt: new Date().toISOString(),
            lastMergedPr: oldest.number,
            lastPiVerifyExit: pi?.verifyExit ?? null,
          });
        } else {
          appendAutopilotLog(`merge failed PR #${oldest.number}: ${mergeResult.detail}`);
        }
      }
    }

    const remediate = (state.remediateFirst || []).length
      ? state.remediateFirst
      : cycle.results.filter((r) => r.needsAgent).map((r) => r.number);

    if (!cycle.allPass && remediate.length) {
      const doInvoke = args.invoke || shouldInvokeCursor(state, remediate);
      let invokeResult = null;
      if (doInvoke) {
        appendAutopilotLog(`cursor invoke PR(s): ${remediate.join(', ')}`);
        invokeResult = await invokeCursorForPrWatch({
          prompt: DEFAULT_PROMPT,
          prNumbers: remediate,
          force: true,
        });
        writeState({
          ...cycleToState(cycle, { prompt: DEFAULT_PROMPT }),
          lastCursorInvokeAt: new Date().toISOString(),
          lastCursorInvokePrs: remediate,
          lastCursorBackend: invokeResult.backend,
          lastCursorInvokeOk: invokeResult.ok,
          lastCursorDetail: invokeResult.detail,
        });
        if (!invokeResult.ok) {
          appendAutopilotLog(`cursor invoke failed: ${invokeResult.detail}`);
        }
      } else {
        appendAutopilotLog(`remediation needed (cooldown) PR(s): ${remediate.join(', ')}`);
      }

      const payload = {
        idle: false,
        allPass: false,
        remediateFirst: remediate,
        merged,
        invoke: invokeResult,
        exitCode: 2,
      };
      if (args.json) console.log(JSON.stringify(payload, null, 2));
      process.exit(2);
    }

    const payload = { idle: false, allPass: cycle.allPass, merged, pi, exitCode: 0 };
    if (args.json) console.log(JSON.stringify(payload, null, 2));
    if (merged) appendAutopilotLog(`tick ok: merged #${merged}`);
    process.exit(0);
  } finally {
    if (lockHeld) {
      touchLock(AUTO_LOCK_PATH);
      releaseLock(AUTO_LOCK_PATH);
    }
  }
}

main().catch((e) => {
  appendAutopilotLog(`fatal: ${e.message}`);
  console.error(`pr-watch-tick: ${e.message}`);
  process.exit(1);
});
