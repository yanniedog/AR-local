#!/usr/bin/env node
/**
 * Apply branch protection on main requiring bot merge gates.
 * Requires admin/repo scope on GH_TOKEN or gh auth.
 *
 * Usage: npm run branch-protection:apply [-- --branch main] [-- --dry-run]
 */
import { spawnSync } from 'node:child_process';

const DEFAULT_CHECKS = ['bot-presence-gate', 'bot-feedback-gate'];

function parseArgs(argv) {
  const out = { branch: 'main', dryRun: false, help: false };
  for (let i = 2; i < argv.length; i += 1) {
    const a = argv[i];
    if (a === '--help' || a === '-h') out.help = true;
    else if (a === '--dry-run') out.dryRun = true;
    else if (a === '--branch' && argv[i + 1]) out.branch = argv[++i];
    else if (a.startsWith('--branch=')) out.branch = a.slice('--branch='.length);
  }
  return out;
}

function ghJson(args) {
  const r = spawnSync('gh', args, { encoding: 'utf8' });
  if (r.error) throw new Error(r.error.message);
  if (r.status !== 0) throw new Error((r.stderr || r.stdout || '').trim() || `gh exit ${r.status}`);
  return r.stdout.trim() ? JSON.parse(r.stdout) : null;
}

function printManualSteps(repo, branch, checks) {
  console.log(`
Branch protection could not be applied via API (token may lack admin:repo scope).

Manual GitHub UI steps for ${repo} → Settings → Branches → Branch protection rules → Add rule:

1. Branch name pattern: \`${branch}\`
2. Require a pull request before merging: ON (no approval count required unless you want human review)
3. Require status checks to pass before merging: ON
   - Require branches to be up to date before merging: ON
   - Required checks (exact job names):
${checks.map((c) => `     - \`${c}\``).join('\n')}
4. Require conversation resolution before merging: ON
5. Do not allow bypassing the above settings (recommended for admins too)

Note: GitHub cannot block "Close pull request" via branch protection. Agents must not close
PRs without merge unless the user waives in writing; \`npm run agent:auditor\` flags
closed-unmerged PRs with open bot threads.
`);
}

function main() {
  const args = parseArgs(process.argv);
  if (args.help) {
    console.log('Usage: npm run branch-protection:apply [-- --branch main] [-- --dry-run]');
    process.exit(0);
  }

  if (spawnSync('gh', ['--version'], { stdio: 'ignore' }).status !== 0) {
    console.error('apply-branch-protection: install gh CLI and authenticate (gh auth login)');
    process.exit(1);
  }

  let repo;
  try {
    repo = ghJson(['repo', 'view', '--json', 'nameWithOwner']).nameWithOwner;
  } catch (e) {
    console.error(`apply-branch-protection: ${e.message}`);
    process.exit(1);
  }

  const payload = {
    required_status_checks: { strict: true, contexts: DEFAULT_CHECKS },
    enforce_admins: true,
    required_pull_request_reviews: null,
    restrictions: null,
    required_conversation_resolution: true,
    allow_force_pushes: false,
    allow_deletions: false,
  };

  if (args.dryRun) {
    console.log(JSON.stringify({ repo, branch: args.branch, checks: DEFAULT_CHECKS, payload }, null, 2));
    process.exit(0);
  }

  const path = `repos/${repo}/branches/${args.branch}/protection`;
  const r = spawnSync(
    'gh',
    ['api', '--method', 'PUT', path, '--input', '-'],
    { encoding: 'utf8', input: JSON.stringify(payload) },
  );
  if (r.status === 0) {
    console.log(`Branch protection applied on ${repo}:${args.branch}`);
    console.log(`Required checks: ${DEFAULT_CHECKS.join(', ')}`);
    console.log('required_conversation_resolution: true');
    process.exit(0);
  }

  console.error(`apply-branch-protection: API failed (exit ${r.status})`);
  if (r.stderr) console.error(r.stderr.trim());
  printManualSteps(repo, args.branch, DEFAULT_CHECKS);
  process.exit(r.status === 403 || r.status === 404 ? 2 : 1);
}

main();
