import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';

/** @returns {string} */
export function gitRepoRoot() {
  const r = spawnSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' });
  return (r.stdout || '').trim() || process.cwd();
}

/**
 * Directory for per-PR bot-wait anchor JSON (valid in linked worktrees).
 * Override: AR_BOT_WAIT_STATE_DIR (absolute, or repo-relative).
 * Default: Git's resolved metadata path for the current worktree.
 */
export function botWaitStateDir(repoRoot) {
  const env = process.env.AR_BOT_WAIT_STATE_DIR?.trim();
  const root = repoRoot || gitRepoRoot();
  if (env) {
    return path.isAbsolute(env) ? path.resolve(env) : path.resolve(root, env);
  }
  const resolved = spawnSync(
    'git',
    ['-C', root, 'rev-parse', '--git-path', 'ar-bot-wait'],
    { encoding: 'utf8' },
  );
  const gitPath = (resolved.stdout || '').trim();
  if (resolved.status === 0 && gitPath) {
    return path.isAbsolute(gitPath) ? gitPath : path.resolve(root, gitPath);
  }
  return path.join(root, '.git', 'ar-bot-wait');
}

/** @param {number} prNumber @param {string} [repoRoot] */
export function botWaitStatePath(prNumber, repoRoot) {
  return path.join(botWaitStateDir(repoRoot), `${prNumber}.json`);
}

/** Legacy repo-root path used before linked-worktree state was shared. */
export function legacyBotWaitStatePath(prNumber, repoRoot) {
  const root = repoRoot || gitRepoRoot();
  return path.join(root, '.ar-bot-wait', `${prNumber}.json`);
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
      return JSON.parse(fs.readFileSync(p, 'utf8'));
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
  const p = botWaitStatePath(prNumber, repoRoot);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, `${JSON.stringify(state, null, 2)}\n`, 'utf8');
}
