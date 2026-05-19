import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

/** @returns {string} */
export function gitRepoRoot() {
  const r = spawnSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' });
  return (r.stdout || '').trim() || process.cwd();
}

/**
 * Directory for per-PR bot-wait anchor JSON (portable across linked worktrees).
 * Override: AR_BOT_WAIT_STATE_DIR (absolute path).
 * Default: <repo>/.ar-bot-wait (not under .git).
 */
export function botWaitStateDir(repoRoot) {
  const env = process.env.AR_BOT_WAIT_STATE_DIR?.trim();
  if (env) return path.resolve(env);
  const root = repoRoot || gitRepoRoot();
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
  for (const p of [botWaitStatePath(prNumber, repoRoot), legacyBotWaitStatePath(prNumber, repoRoot)]) {
    if (!fs.existsSync(p)) continue;
    try {
      return JSON.parse(fs.readFileSync(p, 'utf8'));
    } catch {
      return null;
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
  const p = botWaitStatePath(prNumber, repoRoot);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
}
