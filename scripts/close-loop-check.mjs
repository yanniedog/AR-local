#!/usr/bin/env node
/**
 * Close-loop verification — no deferred gaps; merged PR fixes must be on main.
 *
 * Usage:
 *   node scripts/close-loop-check.mjs --pr N
 *   node scripts/close-loop-check.mjs --post-merge-gap [--limit 20]
 *
 * Exit 0 pass, 1 gap (prints remediation commands).
 */
import { spawnSync } from 'node:child_process';
import {
  fetchPullRequestThreads,
  hasGh,
  isBotLogin,
  repoSlug,
} from './lib/gh-pr-review-threads.mjs';

const PATH_RE =
  /(?:^|[\s"'`])([/\\]?(?:[\w.-]+[/\\])*[\w.-]+\.(?:py|mjs|js|mdc|md|json|yml|yaml))\b/g;

function isPlausibleRepoPath(p) {
  if (/^Node\.js$/i.test(p)) return false;
  return !p.includes('node_modules');
}

function sh(cmd, { allowFail = false } = {}) {
  const r = spawnSync(cmd, { shell: true, encoding: 'utf8' });
  if (r.status !== 0 && !allowFail) {
    throw new Error((r.stderr || r.stdout || 'command failed').trim());
  }
  if (r.status !== 0) return null;
  return (r.stdout || '').trim();
}

function ghJson(args) {
  const r = spawnSync('gh', args, { encoding: 'utf8' });
  if (r.status !== 0) throw new Error((r.stderr || 'gh failed').trim());
  return JSON.parse(r.stdout || '{}');
}

function extractFilePaths(text) {
  const paths = new Set();
  for (const m of (text || '').matchAll(PATH_RE)) {
    const p = m[1].replace(/\\/g, '/');
    if (!p.includes('node_modules') && isPlausibleRepoPath(p)) paths.add(p);
  }
  return [...paths];
}

function mergeCommitOnMain(mergeOid) {
  return sh(`git merge-base --is-ancestor ${mergeOid} origin/main`, { allowFail: true }) !== null;
}

function fileExistsOnRef(ref, filePath) {
  return sh(`git cat-file -e "${ref}:${filePath}"`, { allowFail: true }) !== null;
}

function blobHash(ref, filePath) {
  return sh(`git rev-parse "${ref}:${filePath}"`, { allowFail: true });
}

function checkPrOnMain(prNumber) {
  const pr = ghJson([
    'pr',
    'view',
    String(prNumber),
    '--json',
    'number,title,state,mergedAt,mergeCommit,headRefOid,headRefName,baseRefOid,commits',
  ]);

  if (pr.state !== 'MERGED' || !pr.mergedAt) {
    return {
      gaps: [
        {
          kind: 'not_merged',
          pr: prNumber,
          remediation: `Complete ship bar for PR #${prNumber} before close-loop pass`,
        },
      ],
      pr,
    };
  }

  const gaps = [];
  const mergeOid = pr.mergeCommit?.oid;
  if (!mergeOid) {
    gaps.push({
      kind: 'no_merge_commit',
      pr: prNumber,
      remediation: `gh pr view ${prNumber} --json mergeCommit`,
    });
    return { gaps, pr };
  }

  sh('git fetch origin main');

  if (!mergeCommitOnMain(mergeOid)) {
    gaps.push({
      kind: 'merge_not_on_main',
      pr: prNumber,
      mergeOid,
      remediation: `git fetch origin && git branch -r --contains ${mergeOid}`,
    });
  }

  const headBranch = pr.headRefName;
  if (headBranch) {
    sh(`git fetch origin ${headBranch}`, { allowFail: true });
    const orphanCommits = sh(
      `git log origin/${headBranch} --after="${pr.mergedAt}" --format=%H --not origin/main`,
      { allowFail: true },
    );
    if (orphanCommits) {
      for (const oid of orphanCommits.split(/\n/).filter(Boolean)) {
        gaps.push({
          kind: 'post_merge_commit_not_on_main',
          pr: prNumber,
          commit: oid,
          remediation: `git cherry-pick ${oid} && git push origin main`,
        });
      }
    }
  }

  return { gaps, pr };
}

function checkPostMergeGaps(limit = 20) {
  const merged = ghJson([
    'pr',
    'list',
    '--state',
    'merged',
    '--limit',
    String(limit),
    '--json',
    'number,title,mergedAt,headRefOid,mergeCommit,headRefName',
  ]);

  const allGaps = [];
  let owner;
  let name;
  try {
    ({ owner, name } = repoSlug());
  } catch {
    return allGaps;
  }

  for (const pr of merged) {
    const { gaps } = checkPrOnMain(pr.number);
    allGaps.push(...gaps);

    let threadData;
    try {
      threadData = fetchPullRequestThreads(owner, name, pr.number);
    } catch {
      continue;
    }

    const botFiles = new Set();
    for (const t of threadData.threads) {
      for (const c of t.comments?.nodes || []) {
        if (isBotLogin(c.author?.login)) {
          for (const p of extractFilePaths(c.body)) botFiles.add(p);
        }
      }
    }

    for (const f of botFiles) {
      if (!fileExistsOnRef('origin/main', f)) {
        allGaps.push({
          kind: 'bot_thread_file_missing_on_main',
          pr: pr.number,
          file: f,
          remediation: `Verify ${f} from PR #${pr.number} bot thread; open agent/close-loop-pr-${pr.number} if missing`,
        });
      }
    }
  }

  return allGaps;
}

function printGaps(gaps) {
  if (!gaps.length) {
    console.log('close-loop-check: pass (no gaps)');
    return;
  }
  console.error(`close-loop-check: ${gaps.length} gap(s) detected`);
  for (const g of gaps) {
    const detail = [g.file, g.commit?.slice(0, 8), g.mergeOid?.slice(0, 8)].filter(Boolean).join(' ');
    console.error(`  [${g.kind}] PR #${g.pr ?? '?'}${detail ? ` ${detail}` : ''}`);
    if (g.remediation) console.error(`    → ${g.remediation}`);
  }
  console.error('');
  console.error('Remediation: npm run close-loop:check -- --post-merge-gap');
  console.error('Follow-up:   git checkout -b agent/close-loop-followup origin/main');
}

function parseArgs(argv) {
  const out = { pr: null, postMergeGap: false, limit: 20, help: false };
  for (let i = 2; i < argv.length; i++) {
    const a = argv[i];
    if (a === '--pr' && argv[i + 1]) out.pr = Number(argv[++i]);
    else if (a === '--post-merge-gap') out.postMergeGap = true;
    else if (a === '--limit' && argv[i + 1]) out.limit = Number(argv[++i]);
    else if (a === '--help' || a === '-h') out.help = true;
  }
  return out;
}

function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log('Usage: close-loop-check.mjs [--pr N | --post-merge-gap [--limit N]]');
    process.exit(0);
  }

  if (!hasGh()) {
    console.error('close-loop-check: gh CLI required');
    process.exit(1);
  }

  try {
    if (args.pr) {
      const { gaps } = checkPrOnMain(args.pr);
      printGaps(gaps);
      process.exit(gaps.length ? 1 : 0);
    }

    const branch = sh('git rev-parse --abbrev-ref HEAD', { allowFail: true });
    if (args.postMergeGap || branch === 'main') {
      const gaps = checkPostMergeGaps(args.limit);
      printGaps(gaps);
      process.exit(gaps.length ? 1 : 0);
    }

    console.log('close-loop-check: pass (use --pr N or --post-merge-gap on feature branch)');
    process.exit(0);
  } catch (e) {
    console.error(`close-loop-check: ${e.message}`);
    process.exit(1);
  }
}

main();
