#!/usr/bin/env node
/**
 * When the last open PR to main is squash-merged, bump expo.version and open a PR to main.
 * Branch protection requires bot gates on main; direct push is rejected (GH006).
 * mobile-android-apk.yml builds the APK after the bump PR squash-merges.
 *
 * Env:
 *   GH_TOKEN / GITHUB_TOKEN — required
 *   GITHUB_REPOSITORY — owner/repo
 *   MERGE_SHA — squash merge commit (optional idempotency hint)
 *
 * Usage: node scripts/mobile-auto-release-on-drain.mjs [--repo owner/name] [--dry-run]
 */
import { spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { bumpPatchVersion } from './bump-app-patch-version-pure.cjs';

const mobileDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = join(mobileDir, '..');
const dryRun = process.argv.includes('--dry-run');

const repoArgIdx = process.argv.indexOf('--repo');
const repo =
  (repoArgIdx >= 0 ? process.argv[repoArgIdx + 1] : process.env.GITHUB_REPOSITORY)?.trim() ||
  'yanniedog/AR-local';

const ghToken = process.env.GH_TOKEN?.trim() || process.env.GITHUB_TOKEN?.trim();
const mergeSha = process.env.MERGE_SHA?.trim() || '';

const AUTO_BUMP_PREFIX = 'chore(mobile): auto-release bump to v';
const POLL_ATTEMPTS = 6;
const POLL_SECONDS = 20;
const SPAWN_TIMEOUT_MS = 60_000;

function gh(args) {
  const env = ghToken ? { ...process.env, GH_TOKEN: ghToken } : process.env;
  const res = spawnSync('gh', args, {
    encoding: 'utf8',
    cwd: repoRoot,
    env,
    timeout: SPAWN_TIMEOUT_MS,
  });
  if (res.status !== 0) {
    throw new Error(`gh ${args.join(' ')} failed: ${(res.stderr || res.stdout || '').trim()}`);
  }
  return (res.stdout || '').trim();
}

function git(args) {
  const res = spawnSync('git', args, {
    encoding: 'utf8',
    cwd: repoRoot,
    timeout: SPAWN_TIMEOUT_MS,
  });
  if (res.status !== 0) {
    throw new Error(`git ${args.join(' ')} failed: ${(res.stderr || res.stdout || '').trim()}`);
  }
  return (res.stdout || '').trim();
}

function countOpenPrsToMain() {
  const raw = gh(['pr', 'list', '--state', 'open', '--base', 'main', '--json', 'number', '--repo', repo]);
  const rows = JSON.parse(raw || '[]');
  return Array.isArray(rows) ? rows.length : 0;
}

async function waitForQueueDrain() {
  for (let attempt = 1; attempt <= POLL_ATTEMPTS; attempt++) {
    const open = countOpenPrsToMain();
    if (open === 0) {
      return 0;
    }
    if (open > 1) {
      console.log(
        `mobile-auto-release-on-drain: ${open} open PR(s) to main — skip release (not queue drain)`,
      );
      return open;
    }
    console.log(
      `mobile-auto-release-on-drain: ${open} open PR(s) — poll ${attempt}/${POLL_ATTEMPTS} (possible simultaneous merge)`,
    );
    if (attempt === POLL_ATTEMPTS) {
      console.log('mobile-auto-release-on-drain: queue not drained after polling — skip release');
      return open;
    }
    await delay(POLL_SECONDS * 1000);
  }
  return countOpenPrsToMain();
}

function readHeadCommitMessage() {
  return git(['log', '-1', '--format=%s', 'origin/main']);
}

function readHeadCommitSha() {
  return git(['rev-parse', 'origin/main']);
}

function alreadyAutoBumpedOnHead() {
  const subject = readHeadCommitMessage();
  return subject.startsWith(AUTO_BUMP_PREFIX);
}

function listOpenAutoBumpPrs(nextVersion) {
  const raw = gh([
    'pr',
    'list',
    '--state',
    'open',
    '--base',
    'main',
    '--json',
    'number,title,url',
    '--repo',
    repo,
  ]);
  const rows = JSON.parse(raw || '[]');
  if (!Array.isArray(rows)) {
    return [];
  }
  const titlePrefix = `${AUTO_BUMP_PREFIX}${nextVersion}`;
  return rows.filter(
    (row) => row.title?.startsWith(AUTO_BUMP_PREFIX) || row.title?.startsWith(titlePrefix),
  );
}

function readCurrentVersion() {
  const appJson = JSON.parse(readFileSync(join(mobileDir, 'app.json'), 'utf8'));
  return String(appJson.expo?.version ?? '1.0.0').trim();
}

function bumpBranchName(nextVersion) {
  return `chore/mobile-auto-release-v${nextVersion}`;
}

function enableAutoMerge(prNumber) {
  gh(['pr', 'merge', String(prNumber), '--squash', '--auto', '--repo', repo]);
}

function publishViaPullRequest(next, message) {
  const branchName = bumpBranchName(next);
  const existing = listOpenAutoBumpPrs(next);
  if (existing.length > 0) {
    const pr = existing[0];
    console.log(
      `mobile-auto-release-on-drain: open bump PR #${pr.number} (${pr.url}) — ensure auto-merge`,
    );
    enableAutoMerge(pr.number);
    return pr.number;
  }

  git(['checkout', '-B', branchName]);
  git(['push', '-u', 'origin', branchName, '--force-with-lease']);

  const prHint = mergeSha ? `\n- Trigger merge: \`${mergeSha.slice(0, 7)}\`` : '';
  const body = [
    'Automated patch version bump after the PR queue to `main` drained.',
    '',
    `- Version: **${next}**${prHint}`,
    '',
    'Auto-merge enabled; **mobile-android-apk** builds when this lands on `main`.',
  ].join('\n');

  const prUrl = gh([
    'pr',
    'create',
    '--base',
    'main',
    '--head',
    branchName,
    '--title',
    message,
    '--body',
    body,
    '--repo',
    repo,
  ]);

  const prNumber = prUrl.match(/\/pull\/(\d+)/)?.[1];
  if (!prNumber) {
    throw new Error(`mobile-auto-release-on-drain: could not parse PR number from ${prUrl}`);
  }

  enableAutoMerge(prNumber);
  console.log(
    `mobile-auto-release-on-drain: opened PR #${prNumber} with auto-merge (${prUrl}); mobile-android-apk runs after merge`,
  );
  return Number(prNumber);
}

async function main() {
  if (!ghToken && !dryRun) {
    console.error('mobile-auto-release-on-drain: GH_TOKEN is not set');
    process.exit(1);
  }

  git(['fetch', 'origin', 'main', '--quiet']);
  git(['checkout', '-B', 'main', 'origin/main']);

  const remaining = dryRun ? 0 : await waitForQueueDrain();
  if (dryRun) {
    console.log('mobile-auto-release-on-drain: dry-run — skipping open PR count (assume drained)');
  }
  if (remaining !== 0) {
    process.exit(0);
  }

  if (alreadyAutoBumpedOnHead()) {
    console.log(
      `mobile-auto-release-on-drain: origin/main already at auto-release bump (${readHeadCommitSha()}) — skip`,
    );
    process.exit(0);
  }

  const current = readCurrentVersion();
  const next = bumpPatchVersion(current);
  console.log(`mobile-auto-release-on-drain: queue drained — bump ${current} → ${next}`);

  const pending = listOpenAutoBumpPrs(next);
  if (pending.length > 0) {
    console.log(
      `mobile-auto-release-on-drain: bump PR already open for v${next} (#${pending[0].number}) — skip`,
    );
    enableAutoMerge(pending[0].number);
    process.exit(0);
  }

  if (dryRun) {
    console.log(`mobile-auto-release-on-drain: dry-run — would open PR ${bumpBranchName(next)}`);
    process.exit(0);
  }

  const bump = spawnSync('node', ['scripts/bump-app-patch-version.mjs'], {
    encoding: 'utf8',
    cwd: mobileDir,
  });
  if (bump.status !== 0) {
    throw new Error((bump.stderr || bump.stdout || 'bump-app-patch-version failed').trim());
  }

  git(['config', 'user.name', 'github-actions[bot]']);
  git(['config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com']);
  git(['add', 'mobile/app.json']);

  const prHint = mergeSha ? ` (after ${mergeSha.slice(0, 7)})` : '';
  const message = `${AUTO_BUMP_PREFIX}${next}${prHint}`;
  git(['commit', '-m', message]);

  publishViaPullRequest(next, message);
}

const invoked = process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href;
if (invoked) {
  main().catch((err) => {
    console.error(err instanceof Error ? err.message : err);
    process.exit(1);
  });
}
