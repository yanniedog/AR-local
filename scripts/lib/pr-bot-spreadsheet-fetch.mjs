/**
 * Fetch merged PR list and per-PR bot activity for the spreadsheet matrix.
 */
import { spawnSync } from 'node:child_process';
import { isBotNoise } from './bot-noise.mjs';
import { fetchPullRequestThreads, ghJson, hasGh, repoSlug } from './gh-pr-review-threads.mjs';
import { loginToBotKey } from './pr-bot-roster.mjs';

const ACTIVITY_QUERY = `
query($owner: String!, $name: String!, $num: Int!) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $num) {
      number
      title
      state
      merged
      mergedAt
      url
      reactions(last: 100) {
        nodes { user { login } content createdAt }
      }
      comments(last: 100) {
        nodes {
          author { login }
          createdAt
          body
          reactions(last: 100) {
            nodes { user { login } content createdAt }
          }
        }
      }
      reviews(last: 30) {
        nodes { author { login } submittedAt body state }
      }
    }
  }
}
`;

/**
 * @typedef {'comment' | 'review' | 'reaction' | 'thread_comment'} BotEventKind
 * @typedef {{ login: string, at: string, body: string, kind: BotEventKind, noise: boolean, botKey: string | null, reviewState?: string }} BotEvent
 */

/**
 * @param {string} owner
 * @param {string} name
 * @param {number} limit
 * @returns {Array<{ number: number, title: string, mergedAt: string, url: string }>}
 */
export function fetchMergedPrs(owner, name, limit) {
  const rows = ghJson([
    'pr',
    'list',
    '--repo',
    `${owner}/${name}`,
    '--state',
    'merged',
    '--limit',
    String(limit),
    '--json',
    'number,title,mergedAt,url',
  ]);
  return Array.isArray(rows) ? rows : [];
}

/**
 * @param {string} owner
 * @param {string} name
 * @param {number} prNumber
 * @returns {BotEvent[]}
 */
export function fetchPrBotEvents(owner, name, prNumber) {
  const queryOneLine = ACTIVITY_QUERY.replace(/\s+/g, ' ').trim();
  const data = ghJson([
    'api',
    'graphql',
    '-f',
    `owner=${owner}`,
    '-f',
    `name=${name}`,
    '-F',
    `num=${prNumber}`,
    '-f',
    `query=${queryOneLine}`,
  ]);
  const pr = data?.data?.repository?.pullRequest;
  if (!pr) throw new Error(`PR #${prNumber} not found`);

  /** @type {BotEvent[]} */
  const events = [];

  const push = (login, at, body, kind, reviewState) => {
    if (!login || !at) return;
    const botKey = loginToBotKey(login);
    if (!botKey) return;
    events.push({
      login,
      at,
      body: body || '',
      kind,
      noise: isBotNoise(body),
      botKey,
      reviewState,
    });
  };

  for (const c of pr.comments?.nodes || []) {
    push(c.author?.login, c.createdAt, c.body, 'comment');
    for (const reaction of c.reactions?.nodes || []) {
      if (reaction.content === 'THUMBS_UP' || reaction.content === 'THUMBS_DOWN') {
        push(reaction.user?.login, reaction.createdAt, `reaction:${reaction.content}`, 'reaction');
      }
    }
  }
  for (const rev of pr.reviews?.nodes || []) {
    push(rev.author?.login, rev.submittedAt, rev.body, 'review', rev.state);
  }
  for (const reaction of pr.reactions?.nodes || []) {
    if (reaction.content === 'THUMBS_UP' || reaction.content === 'THUMBS_DOWN') {
      push(reaction.user?.login, reaction.createdAt, `reaction:${reaction.content}`, 'reaction');
    }
  }

  events.sort((a, b) => new Date(a.at) - new Date(b.at));
  return events;
}

/**
 * @param {string} owner
 * @param {string} name
 * @param {number} prNumber
 * @returns {Promise<{ meta: object, events: BotEvent[], threads: object[] }>}
 */
export async function fetchPrBotMatrixRow(owner, name, prNumber) {
  const threadPayload = fetchPullRequestThreads(owner, name, prNumber);
  const events = fetchPrBotEvents(owner, name, prNumber);

  for (const t of threadPayload.threads || []) {
    for (const c of t.comments?.nodes || []) {
      const login = c.author?.login;
      const botKey = loginToBotKey(login);
      if (!botKey) continue;
      events.push({
        login,
        at: c.createdAt,
        body: c.body || '',
        kind: 'thread_comment',
        noise: isBotNoise(c.body),
        botKey,
      });
    }
  }
  events.sort((a, b) => new Date(a.at) - new Date(b.at));

  return {
    meta: {
      number: threadPayload.number,
      title: threadPayload.title,
      mergedAt: threadPayload.mergedAt,
      url: `https://github.com/${owner}/${name}/pull/${threadPayload.number}`,
      merged: threadPayload.merged,
    },
    events,
    threads: threadPayload.threads || [],
  };
}

export { hasGh, repoSlug };
