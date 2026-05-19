import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import {
  allKnownBotLogins,
  formatRequiredKeys,
  missingRequiredKeys,
  resolveRequiredKeys,
} from './bot-wait-config.mjs';

function gitRepoRoot() {
  const r = spawnSync('git', ['rev-parse', '--show-toplevel'], { encoding: 'utf8' });
  return (r.stdout || '').trim() || process.cwd();
}

export function readBotWaitState(prNumber, cwd) {
  const root = cwd || gitRepoRoot();
  const p = path.join(root, '.git', 'ar-bot-wait', `${prNumber}.json`);
  if (!fs.existsSync(p)) return null;
  try {
    return JSON.parse(fs.readFileSync(p, 'utf8'));
  } catch {
    return null;
  }
}

/** Resolve anchor ISO; fall back to fallbackIso when anchor is missing/invalid. */
export function resolveAnchorIso(anchorIso, fallbackIso) {
  const ms = new Date(anchorIso).getTime();
  if (Number.isFinite(ms)) return new Date(ms).toISOString();
  const fbMs = new Date(fallbackIso).getTime();
  if (Number.isFinite(fbMs)) return new Date(fbMs).toISOString();
  throw new Error(`Invalid anchor time: ${anchorIso ?? '(none)'}`);
}

const COMMENTS_QUERY =
  'query($owner:String!,$name:String!,$num:Int!){repository(owner:$owner,name:$name){pullRequest(number:$num){createdAt comments(last:100){nodes{author{login}createdAt}}reviews(last:30){nodes{author{login}submittedAt}}reviewThreads(last:100){nodes{comments(last:10){nodes{author{login}createdAt}}}}}}}';

function ghGraphql(owner, name, prNumber) {
  const r = spawnSync(
    'gh',
    [
      'api',
      'graphql',
      '-f',
      `query=${COMMENTS_QUERY}`,
      '-F',
      `owner=${owner}`,
      '-F',
      `name=${name}`,
      '-F',
      `num=${prNumber}`,
    ],
    { encoding: 'utf8' },
  );
  if (r.status !== 0) {
    throw new Error((r.stderr || r.stdout || 'gh api graphql failed').trim());
  }
  try {
    return JSON.parse(r.stdout || '{}');
  } catch (e) {
    throw new Error(`Invalid JSON from gh api graphql: ${e.message}`);
  }
}

export function collectBotEvents(prPayload, knownBots, anchorIso, fallbackIso) {
  const anchorMs = new Date(resolveAnchorIso(anchorIso, fallbackIso)).getTime();
  const events = [];
  for (const c of prPayload.comments?.nodes || []) {
    if (c.author?.login && c.createdAt) events.push({ login: c.author.login, at: c.createdAt });
  }
  for (const rev of prPayload.reviews?.nodes || []) {
    if (rev.author?.login && rev.submittedAt) events.push({ login: rev.author.login, at: rev.submittedAt });
  }
  for (const t of prPayload.reviewThreads?.nodes || []) {
    for (const c of t.comments?.nodes || []) {
      if (c.author?.login && c.createdAt) events.push({ login: c.author.login, at: c.createdAt });
    }
  }
  events.sort((a, b) => new Date(a.at) - new Date(b.at));
  const filtered = events.filter(
    (e) => knownBots.has(e.login.toLowerCase()) && new Date(e.at).getTime() >= anchorMs,
  );
  filtered.sort((a, b) => new Date(a.at) - new Date(b.at));
  return filtered;
}

export function checkRequiredBotsOnPr(owner, name, prNumber, { requiredKeys, anchorIso, repoRoot } = {}) {
  const state = readBotWaitState(prNumber, repoRoot);
  const keys =
    requiredKeys?.length ? requiredKeys : state?.requiredKeys?.length ? state.requiredKeys : resolveRequiredKeys();
  const knownBots = allKnownBotLogins(keys);
  const data = ghGraphql(owner, name, prNumber);
  const pr = data?.data?.repository?.pullRequest;
  if (!pr) throw new Error('GraphQL: pull request not found');
  const anchor = resolveAnchorIso(anchorIso || state?.anchor, pr.createdAt);
  const events = collectBotEvents(pr, knownBots, anchor, pr.createdAt);
  const seenLogins = [...new Set(events.map((e) => e.login))];
  const missing = missingRequiredKeys(keys, seenLogins);
  return {
    requiredKeys: keys,
    anchor,
    missing,
    botsSeen: seenLogins,
    ok: missing.length === 0,
    detail: formatRequiredKeys(keys),
  };
}
