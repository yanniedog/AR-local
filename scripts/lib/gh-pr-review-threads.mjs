/**
 * Fetch and classify PR review threads via GitHub GraphQL (gh api).
 */
import { spawnSync } from 'node:child_process';

const BOT_LOGIN_RE =
  /(?:gemini|codex|sourcery|coderabbit|copilot|greptile|chatgpt|github-actions\[bot\])/i;

const CLOSURE_BODY_RE =
  /\b(implemented|deferred|declined|won't fix|wontfix|post-merge|not applicable|n\/a)\b/i;

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

export function ghJson(args) {
  const r = spawnSync('gh', args, { encoding: 'utf8' });
  if (r.error || r.status !== 0) {
    const err = (r.stderr || r.stdout || r.error?.message || 'gh failed').trim();
    throw new Error(err);
  }
  return JSON.parse(r.stdout || '{}');
}

export function repoSlug() {
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
  if (body.length < 40) return true;
  if (/^Useful\?\s*React with/m.test(body) && body.length < 200) return true;
  return false;
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

    const first = comments[0];
    const starterLogin = first.author.login;
    const starterIsBot = isBotLogin(starterLogin) || first.author.__typename === 'Bot';
    const excerpt = (first.body || '').replace(/\s+/g, ' ').slice(0, 120);
    const botAt = new Date(first.createdAt).getTime();
    const hasClosure =
      starterIsBot && !isLowSignalBotThread(comments)
        ? threadHasOwnerClosure(comments, botAt)
        : false;

    if (!t.isResolved) {
      // mergedAudit: ignore unresolved non-bot threads only; unresolved bot threads still fail.
      if (mergedAudit && !starterIsBot) continue;
      violations.push({
        threadIndex: i + 1,
        kind: 'unresolved',
        starter: starterLogin,
        isBot: starterIsBot,
        excerpt,
      });
      continue;
    }

    if (!starterIsBot) continue;
    if (isLowSignalBotThread(comments)) continue;

    if (!hasClosure) {
      violations.push({
        threadIndex: i + 1,
        kind: 'missing_closure_reply',
        starter: starterLogin,
        isBot: true,
        excerpt,
      });
    }
  }

  return violations;
}
