/**
 * Fetch and classify PR review threads via GitHub GraphQL (gh api).
 */
import { spawnSync } from 'node:child_process';
import { isBotNoise } from './bot-noise.mjs';

const BOT_LOGIN_RE =
  /(?:gemini|codex|sourcery|coderabbit|copilot|greptile|chatgpt|github-actions\[bot\])/i;

// Disposition reply detection. Used by the merged-PR audit (a historical PR may
// have replied-but-not-resolved threads); the LIVE gate requires resolution, so
// a reply alone does not pass it (see classifyThreads). Forgiving of phrasing
// ("Fixed in <sha>", "Done", "Deferred", "by design") but NEGATION-AWARE so
// "not fixed" / "isn't resolved" do NOT count as closed (Gemini PR #148).
const DISPOSITION_BODY_RE =
  /\b(deferred|declin(?:ed|ing)|won'?t\s*fix|wontfix|will\s*not\s*fix|by\s*design|as\s*designed|no\s*change|not\s*a\s*bug|post[- ]?merge|follow[- ]?up|not\s*applicable|n\/a)\b/i;
const ADDRESSED_BODY_RE =
  /\b(implemented|fixed|address(?:ed|ing)|resolv(?:ed|ing)|done|applied|handled|acknowledged)\b/i;
// Negation within ~2 words before an "addressed" verb → reply is NOT a closure.
const NEGATED_ADDRESSED_RE =
  /\b(?:not|isn'?t|wasn'?t|aren'?t|haven'?t|hasn'?t|never|no\s+longer|still\s+not)\s+(?:\w+\s+){0,2}?(?:implemented|fixed|address(?:ed|ing)?|resolv(?:ed|ing)?|done|applied|handled|acknowledged)\b/i;

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
  const b = String(body || '');
  // Explicit dispositions (incl. "won't fix" / "not applicable") always count.
  if (DISPOSITION_BODY_RE.test(b)) return true;
  // A negated "addressed" verb ("not fixed", "isn't resolved") is NOT a closure.
  if (NEGATED_ADDRESSED_RE.test(b)) return false;
  return ADDRESSED_BODY_RE.test(b);
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

    // Merged-PR audit is lenient: a historical PR may legitimately have
    // replied-but-not-resolved threads, and only bot threads are audited.
    if (mergedAudit) {
      if (!starterIsBot) continue;
      if (threadHasOwnerClosure(comments, botAt) || threadHasBotSelfAddressed(comments)) continue;
    }

    // LIVE gate: an unresolved thread is always a violation. This repo enables
    // required_conversation_resolution, so a disposition reply alone does NOT
    // unblock merge — the thread must be RESOLVED on GitHub. Keeping unresolved
    // = fail keeps this gate consistent with branch protection so the PR is never
    // "all-green but permanently blocked" (Codex P1 PR #148). Resolution remains
    // sufficient on its own (handled by the early `continue` above).
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
