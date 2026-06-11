#!/usr/bin/env node
/**
 * After APK publish: refresh README install section and land on main.
 * Direct push when ruleset allows; otherwise open a bot-authored docs PR with auto-merge.
 *
 * Usage:
 *   node scripts/publish-readme-app-install.mjs [--repo owner/name] [--manifest path] [--dry-run]
 */
import { spawnSync } from 'node:child_process';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { pushHeadToMain } from '../../scripts/mobile-auto-release-commit.mjs';
import { updateReadmeInstallSection } from './update-readme-app-install.mjs';

const mobileDir = join(dirname(fileURLToPath(import.meta.url)), '..');
const repoRoot = join(mobileDir, '..');

export const README_APK_QR_COMMIT_PREFIX = 'docs: refresh Android install QR';

const SPAWN_TIMEOUT_MS = 60_000;

const repoArgIdx = process.argv.indexOf('--repo');
const repo =
  (repoArgIdx >= 0 ? process.argv[repoArgIdx + 1] : process.env.GITHUB_REPOSITORY)?.trim() ||
  'yanniedog/AR-local';

const manifestArgIdx = process.argv.indexOf('--manifest');
const manifestPath =
  manifestArgIdx >= 0 && process.argv[manifestArgIdx + 1]
    ? resolve(process.argv[manifestArgIdx + 1])
    : undefined;

const dryRun = process.argv.includes('--dry-run');
const ghToken = process.env.GH_TOKEN?.trim() || process.env.GITHUB_TOKEN?.trim();

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

function git(args, { allowFail = false } = {}) {
  const res = spawnSync('git', args, {
    encoding: 'utf8',
    cwd: repoRoot,
    timeout: SPAWN_TIMEOUT_MS,
  });
  if (res.status !== 0 && !allowFail) {
    throw new Error(`git ${args.join(' ')} failed: ${(res.stderr || res.stdout || '').trim()}`);
  }
  return res;
}

export function readmeApkQrCommitMessage(version, buildNumber) {
  return `${README_APK_QR_COMMIT_PREFIX} (v${version} build ${buildNumber}) [skip ci]`;
}

export function readmeApkQrBranchName(version, buildNumber) {
  return `chore/readme-apk-qr-v${version}-b${buildNumber}`;
}

function listOpenReadmeQrPrs(version, buildNumber) {
  const raw = gh(['pr', 'list', '--state', 'open', '--base', 'main', '--json', 'number,title,url', '--repo', repo]);
  const rows = JSON.parse(raw || '[]');
  if (!Array.isArray(rows)) return [];
  const message = readmeApkQrCommitMessage(version, buildNumber);
  return rows.filter((row) => row.title === message);
}

function enableAutoMerge(prNumber) {
  gh(['pr', 'merge', String(prNumber), '--squash', '--auto', '--repo', repo]);
}

function publishViaPullRequest(version, buildNumber, message) {
  const branchName = readmeApkQrBranchName(version, buildNumber);
  const existing = listOpenReadmeQrPrs(version, buildNumber);
  if (existing.length > 0) {
    const pr = existing[0];
    console.log(`publish-readme-app-install: open README QR PR #${pr.number} (${pr.url}) — ensure auto-merge`);
    enableAutoMerge(pr.number);
    return { mode: 'pr-existing', prNumber: pr.number };
  }

  git(['checkout', '-B', branchName]);
  git(['push', '-u', 'origin', branchName, '--force-with-lease']);

  const body = [
    'Automated README refresh after **mobile-android-apk** published a new preview APK.',
    '',
    `- Version: **${version}** (build **${buildNumber}**)`,
    '- Updates the install table and QR embed cache-bust (`?v=<build>`).',
    '',
    'Bot-authored gate-exempt PR. Auto-merge enabled; does not re-trigger APK workflow (README-only).',
  ].join('\n');

  const prUrl = gh([
    'pr', 'create', '--base', 'main', '--head', branchName, '--title', message, '--body', body, '--repo', repo,
  ]);
  const prNumber = Number(prUrl.match(/\/pull\/(\d+)/)?.[1]);
  if (!Number.isFinite(prNumber)) {
    throw new Error(`publish-readme-app-install: could not parse PR number from ${prUrl}`);
  }

  enableAutoMerge(prNumber);
  console.log(`publish-readme-app-install: opened fallback PR #${prNumber} with auto-merge (${prUrl})`);
  return { mode: 'pr-created', prNumber };
}

/**
 * @param {{ repo?: string, manifestPath?: string, dryRun?: boolean }} [opts]
 */
export function publishReadmeAppInstall(opts = {}) {
  const ghRepo = opts.repo?.trim() || repo;
  const manifest = opts.manifestPath ? resolve(opts.manifestPath) : manifestPath;
  const readmePath = join(repoRoot, 'README.md');

  const result = updateReadmeInstallSection({
    readmePath,
    repo: ghRepo,
    manifestPath: manifest,
  });

  if (!result.changed) {
    console.log('publish-readme-app-install: README unchanged — nothing to publish');
    return { ok: true, changed: false, ...result };
  }

  const message = readmeApkQrCommitMessage(result.version, result.buildNumber);
  if (opts.dryRun || dryRun) {
    console.log(`publish-readme-app-install: dry-run — would commit "${message}" and push to main`);
    return { ok: true, changed: true, dryRun: true, ...result };
  }

  if (!ghToken) {
    throw new Error('publish-readme-app-install: GH_TOKEN is not set');
  }

  git(['config', 'user.name', 'github-actions[bot]']);
  git(['config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com']);
  git(['add', 'README.md']);
  git(['commit', '-m', message]);

  const push = pushHeadToMain();
  if (push.ok) {
    console.log('publish-readme-app-install: pushed README QR refresh to origin/main');
    return { ok: true, changed: true, mode: 'direct', ...result };
  }

  if (push.protected) {
    console.warn('publish-readme-app-install: direct push blocked — falling back to docs PR with auto-merge');
    const pr = publishViaPullRequest(result.version, result.buildNumber, message);
    return { ok: true, changed: true, ...pr, ...result };
  }

  throw new Error(push.error || 'publish-readme-app-install: push to main failed');
}

function main() {
  try {
    const outcome = publishReadmeAppInstall({ dryRun });
    if (!outcome.ok) process.exit(1);
  } catch (err) {
    console.error(err instanceof Error ? err.message : err);
    process.exit(1);
  }
}

const invoked = process.argv[1]?.replace(/\\/g, '/').endsWith('publish-readme-app-install.mjs');
if (invoked) {
  main();
}
