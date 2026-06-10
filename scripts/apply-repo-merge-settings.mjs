#!/usr/bin/env node
/**
 * Apply squash-only + auto-merge + delete-branch-on-merge repo settings.
 * Requires admin:repo scope on GH_TOKEN or gh auth.
 *
 * Usage: npm run repo-merge-settings:apply [-- --dry-run]
 *
 * Note: squash is chosen at merge time (gh pr merge --squash), not at gh pr create.
 */
import { spawnSync } from 'node:child_process';

const GH_TIMEOUT_MS = 120_000;

/** @type {Record<string, boolean>} */
const DESIRED = {
  allow_squash_merge: true,
  allow_merge_commit: false,
  allow_rebase_merge: false,
  delete_branch_on_merge: true,
  allow_auto_merge: true,
};

function parseArgs(argv) {
  const out = { dryRun: false, help: false };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--dry-run') out.dryRun = true;
  }
  return out;
}

function ghJson(args) {
  const r = spawnSync('gh', args, { encoding: 'utf8', timeout: GH_TIMEOUT_MS });
  if (r.error) throw new Error(r.error.message);
  if (r.status !== 0) {
    throw new Error((r.stderr || r.stdout || '').trim() || `gh exit ${r.status}`);
  }
  return r.stdout.trim() ? JSON.parse(r.stdout) : null;
}

function printManualSteps(repo) {
  console.log(`
Could not PATCH repo settings via API (token may lack admin:repo scope).

Manual steps for ${repo} → Settings → General → Pull Requests:

1. Allow squash merging: ON
2. Allow merge commits: OFF
3. Allow rebase merging: OFF
4. Allow auto-merge: ON
5. Automatically delete head branches: ON

Agents merge with: gh pr merge <n> --auto --squash --delete-branch
(or: npm run pr:merge -- --pr <n> after pr:gates:check exit 0)

Squash is selected at merge time, not when opening a PR with gh pr create.
`);
}

function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log('Usage: npm run repo-merge-settings:apply [-- --dry-run]');
    process.exit(0);
  }

  if (spawnSync('gh', ['--version'], { stdio: 'ignore' }).status !== 0) {
    console.error('apply-repo-merge-settings: install gh CLI and authenticate');
    process.exit(1);
  }

  let repo;
  try {
    repo = ghJson(['repo', 'view', '--json', 'nameWithOwner']).nameWithOwner;
  } catch (e) {
    console.error(`apply-repo-merge-settings: ${e.message}`);
    process.exit(1);
  }

  let current;
  try {
    current = ghJson(['api', `repos/${repo}`]);
  } catch (e) {
    console.error(`apply-repo-merge-settings: could not read repo: ${e.message}`);
    process.exit(1);
  }

  const changes = {};
  for (const [key, want] of Object.entries(DESIRED)) {
    if (current[key] !== want) changes[key] = want;
  }

  if (!Object.keys(changes).length) {
    console.log(`Repo merge settings already match policy on ${repo}`);
    for (const [k, v] of Object.entries(DESIRED)) {
      console.log(`  ${k}: ${v}`);
    }
    process.exit(0);
  }

  if (args.dryRun) {
    console.log(JSON.stringify({ repo, changes }, null, 2));
    process.exit(0);
  }

  const input = JSON.stringify(changes);
  const r = spawnSync(
    'gh',
    ['api', '--method', 'PATCH', `repos/${repo}`, '--input', '-'],
    { encoding: 'utf8', input, timeout: GH_TIMEOUT_MS },
  );

  if (r.status === 0) {
    console.log(`Repo merge settings updated on ${repo}:`);
    for (const [k, v] of Object.entries(changes)) {
      console.log(`  ${k}: ${current[k]} → ${v}`);
    }
    process.exit(0);
  }

  console.error(`apply-repo-merge-settings: API failed (exit ${r.status})`);
  if (r.stderr) console.error(r.stderr.trim());
  printManualSteps(repo);
  process.exit(r.status === 403 || r.status === 404 ? 2 : 1);
}

main();
