import fs from 'node:fs';
import { createHash, randomUUID } from 'node:crypto';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

/** @returns {string} */
export function gitRepoRoot() {
  const r = spawnSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' });
  return (r.stdout || '').trim() || process.cwd();
}

/**
 * Directory for per-PR bot-wait anchor JSON (portable across linked worktrees).
 * Override: AR_BOT_WAIT_STATE_DIR (absolute, or repo-relative).
 * Default: <repo>/.ar-bot-wait (not under .git).
 */
export function botWaitStateDir(repoRoot) {
  const env = process.env.AR_BOT_WAIT_STATE_DIR?.trim();
  const root = repoRoot || gitRepoRoot();
  if (env) {
    return path.isAbsolute(env) ? path.resolve(env) : path.resolve(root, env);
  }
  return path.join(root, '.ar-bot-wait');
}

/** @param {number} prNumber @param {string} [repoRoot] */
export function botWaitStatePath(prNumber, repoRoot) {
  return path.join(botWaitStateDir(repoRoot), `${prNumber}.json`);
}

/** Legacy path under .git (read-only fallback). */
export function legacyBotWaitStatePath(prNumber, repoRoot) {
  const root = repoRoot || gitRepoRoot();
  return path.join(root, '.git', 'ar-bot-wait', `${prNumber}.json`);
}

/**
 * @param {number} prNumber
 * @param {string} [repoRoot]
 * @returns {object | null}
 */
export function readBotWaitStateFile(prNumber, repoRoot) {
  const candidates = [botWaitStatePath(prNumber, repoRoot)];
  // Explicit override: do not fall back to legacy .git anchors (stale/misleading).
  if (!process.env.AR_BOT_WAIT_STATE_DIR?.trim()) {
    candidates.push(legacyBotWaitStatePath(prNumber, repoRoot));
  }
  for (const p of candidates) {
    if (!fs.existsSync(p)) continue;
    try {
      return readJsonState(p);
    } catch {
      continue;
    }
  }
  return null;
}

/**
 * @param {number} prNumber
 * @param {object} state
 * @param {string} [repoRoot]
 */
export function writeBotWaitStateFile(prNumber, state, repoRoot) {
  writeJsonAtomically(botWaitStatePath(prNumber, repoRoot), state);
}

const SNAPSHOT = Symbol('wait-state-snapshot');
const fingerprint = (content) => createHash('sha256').update(content).digest('hex');

/** Keep the read version outside JSON so callers can safely mutate their snapshot. */
export function readJsonState(filename) {
  const content = fs.readFileSync(filename, 'utf8');
  const state = JSON.parse(content);
  if (!state || typeof state !== 'object' || Array.isArray(state)) throw new Error('Invalid wait state');
  Object.defineProperty(state, SNAPSHOT, { value: { filename: path.resolve(filename), fingerprint: fingerprint(content) }, writable: true, configurable: true });
  return state;
}

/** Exclusive compare-and-swap rejects stale snapshots instead of replacing newer anchors. */
export function writeJsonAtomically(destination, state) {
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  const lock = `${destination}.lock`;
  let lockDescriptor;
  try {
    lockDescriptor = fs.openSync(lock, 'wx');
  } catch (error) {
    if (error.code === 'EEXIST') throw new Error('Wait state update is locked; retry after the writer exits');
    throw error;
  }
  const temporary = `${destination}.${process.pid}.${randomUUID()}.tmp`;
  try {
    fs.writeFileSync(lockDescriptor, JSON.stringify({ pid: process.pid }));
    const actual = fs.existsSync(destination) ? fingerprint(fs.readFileSync(destination, 'utf8')) : null;
    const snapshot = state[SNAPSHOT];
    const expected = snapshot?.filename === path.resolve(destination) ? snapshot.fingerprint : null;
    if (actual !== expected) throw new Error('Wait state changed since read; reread before updating');
    const content = `${JSON.stringify(state, null, 2)}\n`;
    const descriptor = fs.openSync(temporary, 'wx');
    try {
      fs.writeFileSync(descriptor, content, 'utf8');
      fs.fsyncSync(descriptor);
    } finally {
      fs.closeSync(descriptor);
    }
    fs.renameSync(temporary, destination);
    Object.defineProperty(state, SNAPSHOT, { value: { filename: path.resolve(destination), fingerprint: fingerprint(content) }, writable: true, configurable: true });
    syncStateDirectory(path.dirname(destination));
  } finally {
    if (fs.existsSync(temporary)) fs.unlinkSync(temporary);
    fs.closeSync(lockDescriptor);
    fs.unlinkSync(lock);
  }
}

function syncStateDirectory(directoryPath) {
  // Node cannot open directory descriptors on Windows.
  if (process.platform === 'win32') return;
  try {
    const directory = fs.openSync(directoryPath, 'r');
    try { fs.fsyncSync(directory); } finally { fs.closeSync(directory); }
  } catch (error) {
    if (['EINVAL', 'ENOTSUP', 'EOPNOTSUPP'].includes(error.code)) {
      console.warn('Wait state replaced; this filesystem does not support directory fsync.');
      return;
    }
    throw new Error('Wait state was replaced, but its directory could not be synced', { cause: error });
  }
}
