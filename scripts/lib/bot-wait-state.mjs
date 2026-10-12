import fs from 'node:fs';
import { createHash } from 'node:crypto';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

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
const WRITE_HELPER = fileURLToPath(new URL('./bot-wait-state-write.py', import.meta.url));
const MAX_REQUEST_BYTES = 1024 * 1024;

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
  const filename = path.resolve(destination);
  const snapshot = state[SNAPSHOT];
  const expected = snapshot?.filename === filename ? snapshot.fingerprint : null;
  const content = `${JSON.stringify(state, null, 2)}\n`;
  const input = JSON.stringify({ destination: filename, content, expected });
  if (Buffer.byteLength(input, 'utf8') > MAX_REQUEST_BYTES) throw new Error('Wait state request exceeds the supported size');
  // Python owns the entire CAS while holding native file locks. A timeout kills
  // only this child; kernel locks release even if it dies before cleaning up.
  const result = spawnSync(process.platform === 'win32' ? 'python' : 'python3', ['-I', '-S', '-B', WRITE_HELPER], {
    input, encoding: 'utf8', windowsHide: true, timeout: 10_000, killSignal: 'SIGKILL', maxBuffer: 64 * 1024,
  });
  if (result.error) throw new Error('Wait state writer failed; Python 3 is required. Reread state before retrying', { cause: result.error });
  if (result.status !== 0) throw new Error(result.stderr.trim() || 'Wait state writer failed; reread before retrying');
  const written = JSON.parse(result.stdout);
  if (written?.fingerprint !== fingerprint(content)) throw new Error('Invalid wait state writer receipt; reread before retrying');
  if (result.stderr.trim()) console.warn(result.stderr.trim());
  Object.defineProperty(state, SNAPSHOT, { value: { filename, fingerprint: written.fingerprint }, writable: true, configurable: true });
}
