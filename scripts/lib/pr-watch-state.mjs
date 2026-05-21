/**
 * PR watch autopilot: state dir, single-instance lock, stale cleanup.
 */
import fs from 'node:fs';
import path from 'node:path';
import { REPO_ROOT } from './pr-gates-lib.mjs';

export const WATCH_DIR = path.join(REPO_ROOT, '.ar-pr-watch');
export const STATE_PATH = path.join(WATCH_DIR, 'state.json');
export const AUTO_LOCK_PATH = path.join(WATCH_DIR, 'autopilot.lock');
export const DAEMON_LOCK_PATH = path.join(WATCH_DIR, 'daemon.lock');
export const AUTO_LOG_PATH = path.join(WATCH_DIR, 'autopilot.log');
export const WAKE_PATH = path.join(WATCH_DIR, 'wake.json');

/** Lock older than this with no heartbeat is stale (ms). */
export const DEFAULT_STALE_LOCK_MS = Number(process.env.AR_PR_WATCH_STALE_LOCK_MS) || 6 * 60 * 60 * 1000;

export const DEFAULT_PROMPT =
  'Follow .cursor/skills/pr-watch-agent/SKILL.md — pr-fix remediation on failing gates, then gates/merge/Pi per WORKFLOW.md. One pr-watch worker; chief holds path locks. Pi verify: http://100.78.28.10/';

export function ensureWatchDir() {
  fs.mkdirSync(WATCH_DIR, { recursive: true });
}

function pidAlive(pid) {
  if (!pid || !Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === 'EPERM';
  }
}

export function readLock(lockPath) {
  try {
    return JSON.parse(fs.readFileSync(lockPath, 'utf8'));
  } catch {
    return null;
  }
}

export function lockIsStale(lock, maxAgeMs = DEFAULT_STALE_LOCK_MS) {
  if (!lock) return true;
  const heartbeat = lock.heartbeatAt || lock.startedAt;
  const t = new Date(heartbeat || 0).getTime();
  if (!Number.isFinite(t)) return true;
  if (Date.now() - t > maxAgeMs) return true;
  if (lock.pid && !pidAlive(lock.pid)) return true;
  return false;
}

export function acquireLock(lockPath, meta = {}) {
  ensureWatchDir();
  const existing = readLock(lockPath);
  if (existing && !lockIsStale(existing)) {
    return { ok: false, lock: existing };
  }
  if (existing && lockIsStale(existing)) {
    try {
      fs.unlinkSync(lockPath);
    } catch {
      /* ignore */
    }
  }
  const lock = {
    pid: process.pid,
    startedAt: new Date().toISOString(),
    heartbeatAt: new Date().toISOString(),
    ...meta,
  };
  fs.writeFileSync(lockPath, `${JSON.stringify(lock, null, 2)}\n`, 'utf8');
  return { ok: true, lock };
}

export function touchLock(lockPath) {
  const lock = readLock(lockPath);
  if (!lock || lock.pid !== process.pid) return;
  lock.heartbeatAt = new Date().toISOString();
  fs.writeFileSync(lockPath, `${JSON.stringify(lock, null, 2)}\n`, 'utf8');
}

export function releaseLock(lockPath) {
  const lock = readLock(lockPath);
  if (lock?.pid === process.pid) {
    try {
      fs.unlinkSync(lockPath);
    } catch {
      /* ignore */
    }
  }
}

export function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_PATH, 'utf8'));
  } catch {
    return null;
  }
}

export function writeState(payload) {
  ensureWatchDir();
  const state = {
    updatedAt: new Date().toISOString(),
    statePath: STATE_PATH,
    prompt: DEFAULT_PROMPT,
    ...payload,
  };
  fs.writeFileSync(STATE_PATH, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
  return state;
}

export function appendAutopilotLog(line) {
  ensureWatchDir();
  const ts = new Date().toISOString();
  fs.appendFileSync(AUTO_LOG_PATH, `[${ts}] ${line}\n`, 'utf8');
}
