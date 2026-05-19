import { spawnSync } from 'node:child_process';
import {
  allKnownBotLogins,
  formatRequiredKeys,
  missingRequiredKeys,
  resolveRequiredKeys,
} from './bot-wait-config.mjs';

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
  return JSON.parse(r.stdout || '{}');
}

export function collectBotEvents(prPayload, knownBots, anchorIso) {
  const anchorMs = new Date(anchorIso).getTime();
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
  return events.filter(
    (e) => knownBots.has(e.login.toLowerCase()) && new Date(e.at).getTime() >= anchorMs,
  );
}

export function checkRequiredBotsOnPr(owner, name, prNumber, { requiredKeys, anchorIso } = {}) {
  const keys = requiredKeys || resolveRequiredKeys();
  const knownBots = allKnownBotLogins(keys);
  const data = ghGraphql(owner, name, prNumber);
  const pr = data?.data?.repository?.pullRequest;
  if (!pr) throw new Error('GraphQL: pull request not found');
  const anchor = anchorIso || pr.createdAt;
  const events = collectBotEvents(pr, knownBots, anchor);
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
