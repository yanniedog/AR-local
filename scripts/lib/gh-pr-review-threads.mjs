/**
 * Fetch and classify PR review threads via GitHub GraphQL (gh api).
 */
import { spawnSync } from 'node:child_process';
import { isBotNoise } from './bot-noise.mjs';

const BOT_LOGIN_RE =
  /(?:gemini|codex|sourcery|coderabbit|copilot|greptile|chatgpt|github-actions\[bot\])/i;

// A disposition reply lets an UNRESOLVED thread pass (defer/decline without a
// resolve click). Intentionally forgiving of how agents/humans actually phrase
// it — "Fixed in <sha>", "Done", "Addressed", etc. — so a real reply is not
// rejected for missing a magic word (resolution alone also satisfies the gate).
const CLOSURE_BODY_RE =
  /\b(implemented|fixed|address(?:ed|ing)|resolv(?:ed|ing)|done|applied|handled|acknowledged|deferred|declin(?:ed|ing)|won'?t fix|wontfix|will not fix|by design|as designed|no change|not a bug|post-merge|follow[- ]?up|not applicable|n\/a)\b/i;

const REVIEW_THREADS_QUERY = `
query($owner: String!, $name: String!, $number: Int!, $after: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      number
      title
      state
      merged
      mergedAt
      reviewThreads(first: 100, after: $after) {
        pageInfo { hasNextPage endCursor }
        nodes {
          isResolved
          comments(first: 50) {
            nodes {
              author { login __typename }
              body
              createdAt
            }
          }
        }
      }
    }
  }
}
`;

export function hasGh() {
  return spawnSync('gh', ['--version'], { encoding: 'utf8', stdio: 'ignore' }).status === 0;
}

export function isGithubRateLimitError(message) {
  return /rate limit/i.test(message || '');
}

export class GhRateLimitError extends Error {
  constructor(message) {
    super(message);
    this.name = 'GhRateLimitError';
  }
}

export function repoSlugFromEnv() {
  const slug = (process.env.GITHUB_REPOSITORY || '').trim();
  if (!slug) return null;
  const [owner, name] = slug.split('/');
  if (!owner || !name) return null;
  return { owner, name };
}

export function ghJson(args, { timeout = 120_000, maxBuffer = 4 * 1024 * 1024 } = {}) {
  const r = spawnSync('gh', args, { encoding: 'utf8', timeout, maxBuffer });
  if (r.error?.code === 'ETIMEDOUT') {
    throw new Error(`gh timed out after ${timeout}ms`);
  }
  if (r.error || r.status !== 0) {
    const err = (r.stderr || r.stdout || r.error?.message || 'gh failed').trim();
    if (isGithubRateLimitError(err)) throw new GhRateLimitError(err);
    throw new Error(err);
  }
  return JSON.parse(r.stdout || '{}');
}

export function repoSlug() {
  const fromEnv = repoSlugFromEnv();
  if (fromEnv) return fromEnv;
  const json = ghJson(['repo', 'view', '--json', 'nameWithOwner']);
  const [owner, name] = (json.nameWithOwner || '').split('/');
  if (!owner || !name) throw new Error('Could not resolve repo owner/name from gh');
  return { owner, name };
}

export function isBotLogin(login) {
  return BOT_LOGIN_RE.test(login || '');
}

export function isClosureReply(body) {
  return CLOSURE_BODY_RE.test(body || '');
}

export function isLowSignalBotThread(comments) {
  if (!comments?.length) return true;
  const first = comments[0];
  const body = (first.body || '').trim();
  // Centralised in bot-noise.mjs so wait_for_bots and the feedback gate apply
  // the same definition. Covers quota / API-limit notices and trivial /
  // inconsequential replies (ack-only, emoji-only, "Useful? React with..."
  // tail-only summaries).
  return isBotNoise(body);
}

export function fetchPullRequestThreads(owner, name, prNumber) {
  const threads = [];
  let after = null;
  let prMeta = null;
  const queryOneLine = REVIEW_THREADS_QUERY.replace(/\s+/g, ' ').trim();

  for (;;) {
    const vars = [
      'api',
      'graphql',
      '-f',
      `owner=${owner}`,
      '-f',
      `name=${name}`,
      '-F',
      `number=${prNumber}`,
      '-f',
      `query=${queryOneLine}`,
    ];
    if (after) vars.push('-f', `after=${after}`);

    const data = ghJson(vars);
    const pr = data?.data?.repository?.pullRequest;
    if (!pr) throw new Error(`PR #${prNumber} not found or not accessible`);

    if (!prMeta) {
      prMeta = {
        number: pr.number,
        title: pr.title,
        state: pr.state,
        merged: pr.merged,
        mergedAt: pr.mergedAt,
      };
    }

    threads.push(...(pr.reviewThreads?.nodes || []));
    const page = pr.reviewThreads?.pageInfo;
    if (!page?.hasNextPage) break;
    after = page.endCursor;
  }

  return { ...prMeta, threads };
}

const BOT_SELF_ADDRESSED_RE = /\b(addressed|fixed|implemented|resolved|done|applied) in [0-9a-f]{7,40}\b/i;

function threadHasBotSelfAddressed(comments) {
  for (const c of comments) {
    if (!isBotLogin(c.author?.login || '')) continue;
    if (BOT_SELF_ADDRESSED_RE.test(c.body || '')) return true;
  }
  return false;
}

function threadHasOwnerClosure(comments, botAt) {
  for (const c of comments.slice(1)) {
    const login = c.author.login;
    if (isBotLogin(login) && c.author.__typename === 'Bot') continue;
    if (new Date(c.createdAt).getTime() < botAt) continue;
    if (isClosureReply(c.body)) return true;
  }
  return false;
}

/** @param {{ mergedAudit?: boolean }} opts */
export function classifyThreads(threads, opts = {}) {
  const { mergedAudit = false } = opts;
  const violations = [];

  for (let i = 0; i < threads.length; i++) {
    const t = threads[i];
    const comments = (t.comments?.nodes || []).filter((c) => c?.author?.login);
    if (!comments.length) continue;

    // Resolving a thread on GitHub is a deliberate acknowledgement and satisfies
    // the gate on its own — no separate "closure reply" keyword is also required.
    // (Previously a resolved thread still failed without a magic-word reply, which
    // forced agents to repost "Implemented in <sha>" and burn a whole CI cycle.)
    if (t.isResolved) continue;

    const first = comments[0];
    const starterLogin = first.author.login;
    const starterIsBot = isBotLogin(starterLogin) || first.author.__typename === 'Bot';
    const excerpt = (first.body || '').replace(/\s+/g, ' ').slice(0, 120);
    const botAt = new Date(first.createdAt).getTime();

    // Low-signal bot threads (quota notices, "Useful? React with..." tails,
    // emoji-only acks) carry no actionable feedback and never block merge.
    if (starterIsBot && isLowSignalBotThread(comments)) continue;
    // mergedAudit: only unresolved bot threads block (ignore human threads).
    if (mergedAudit && !starterIsBot) continue;

    // An unresolved thread still passes if it carries an explicit disposition
    // reply (fixed / implemented / deferred / declined / by design …) — so
    // declining or deferring does not force a resolve click. Resolution OR a
    // disposition reply == satisfied.
    if (starterIsBot && (threadHasOwnerClosure(comments, botAt) || threadHasBotSelfAddressed(comments))) {
      continue;
    }

    violations.push({
      threadIndex: i + 1,
      kind: 'unresolved',
      starter: starterLogin,
      isBot: starterIsBot,
      excerpt,
    });
  }

  return violations;
}
