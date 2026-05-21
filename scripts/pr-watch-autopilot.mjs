#!/usr/bin/env node
/**
 * 24/7 PR watch autopilot: continuous ticks, Cursor invoke on exit 2, merge+Pi when green.
 *
 *   npm run pr:watch:autopilot
 *   npm run pr:watch:autopilot -- --probe-cursor
 *
 * Env:
 *   AR_PR_WATCH_AUTOPILOT=1     (checked by install script)
 *   AR_PR_WATCH_TICK_SEC=120    idle poll between ticks when exit 0
 *   AR_PR_WATCH_BUSY_SEC=60     poll when exit 2
 *   AR_PR_WATCH_SKIP_CURSOR=1   gate scan only
 *   AR_PR_WATCH_SKIP_MERGE=1    never merge from autopilot
 *   AR_CURSOR_AGENT_CMD         full command override
 *   CURSOR_API_KEY              enables @cursor/sdk fallback
 */
import { setTimeout as sleepMs } from 'node:timers/promises';
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import {
  acquireLock,
  touchLock,
  releaseLock,
  appendAutopilotLog,
  AUTO_LOCK_PATH,
  ensureWatchDir,
} from './lib/pr-watch-state.mjs';
import { probeCursorInvoker } from './lib/cursor-invoke.mjs';
import { REPO_ROOT } from './lib/pr-gates-lib.mjs';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const TICK_SCRIPT = path.join(__dirname, 'pr-watch-tick.mjs');

const TICK_SEC = Number(process.env.AR_PR_WATCH_TICK_SEC) || 120;
const BUSY_SEC = Number(process.env.AR_PR_WATCH_BUSY_SEC) || 60;
const ERROR_SEC = Number(process.env.AR_PR_WATCH_ERROR_SEC) || 180;

function parseArgs(argv) {
  const out = { probeCursor: false, once: false, help: false };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--probe-cursor') out.probeCursor = true;
    else if (a === '--once') out.once = true;
  }
  return out;
}

function runTick() {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [TICK_SCRIPT, '--invoke', '--no-lock'], {
      cwd: REPO_ROOT,
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
      windowsHide: true,
    });
    let stderr = '';
    child.stderr.on('data', (d) => {
      stderr += d;
    });
    child.on('close', (code) => {
      resolve({ exitCode: code ?? 1, stderr: stderr.trim() });
    });
  });
}

function sleepForExit(exitCode) {
  if (exitCode === 2) return BUSY_SEC;
  if (exitCode === 1 || exitCode === 3) return ERROR_SEC;
  return TICK_SEC;
}

async function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log(`Usage: npm run pr:watch:autopilot -- [--probe-cursor] [--once]

Runs pr-watch-tick in a loop with single-instance lock (.ar-pr-watch/autopilot.lock).
Logs to .ar-pr-watch/autopilot.log`);
    process.exit(0);
  }

  if (args.probeCursor) {
    const { invoker, lines } = probeCursorInvoker();
    for (const line of lines) console.log(line);
    process.exit(invoker.backend === 'sentinel' ? 2 : 0);
  }

  ensureWatchDir();
  const lock = acquireLock(AUTO_LOCK_PATH, { role: 'autopilot' });
  if (!lock.ok) {
    console.error(`pr-watch-autopilot: lock held by pid ${lock.lock?.pid} — exiting`);
    process.exit(3);
  }

  appendAutopilotLog(`autopilot start pid=${process.pid}`);
  const { lines } = probeCursorInvoker();
  appendAutopilotLog(lines.join(' | '));

  const shutdown = () => {
    appendAutopilotLog('autopilot shutdown');
    releaseLock(AUTO_LOCK_PATH);
    process.exit(0);
  };
  process.on('SIGINT', shutdown);
  process.on('SIGTERM', shutdown);

  try {
    for (;;) {
      touchLock(AUTO_LOCK_PATH);
      const { exitCode, stderr } = await runTick();
      if (stderr) appendAutopilotLog(`tick stderr: ${stderr.slice(0, 400)}`);
      appendAutopilotLog(`tick exit ${exitCode}`);
      if (args.once) break;
      const sec = sleepForExit(exitCode);
      await sleepMs(sec * 1000);
    }
  } finally {
    releaseLock(AUTO_LOCK_PATH);
  }
}

main().catch((e) => {
  appendAutopilotLog(`autopilot fatal: ${e.message}`);
  console.error(e.message);
  releaseLock(AUTO_LOCK_PATH);
  process.exit(1);
});
