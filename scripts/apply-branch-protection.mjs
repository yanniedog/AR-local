#!/usr/bin/env node
/**
 * Apply branch protection on main requiring bot merge gates.
 * Requires admin/repo scope on GH_TOKEN or gh auth.
 *
 * Usage: npm run branch-protection:apply [-- --branch main] [-- --dry-run]
 */
import { spawnSync } from 'node:child_process';

/** Bot merge gates — must match workflow YAML job keys exactly. */
const BOT_GATE_CHECKS = ['bot-presence-gate', 'bot-feedback-gate'];

const GH_TIMEOUT_MS = 120_000;

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

function ghJson(args, { allow404 = false } = {}) {
  const r = spawnSync('gh', args, { encoding: 'utf8', timeout: GH_TIMEOUT_MS });
  if (r.error) throw new Error(r.error.message);
  if (r.status === 404 && allow404) return null;
  if (r.status !== 0) throw new Error((r.stderr || r.stdout || '').trim() || `gh exit ${r.status}`);
  return r.stdout.trim() ? JSON.parse(r.stdout) : null;
}

function mergeCheckContexts(existingContexts, botChecks) {
  const merged = [...(existingContexts || []), ...botChecks];
  return [...new Set(merged.filter(Boolean))];
}

/** Map GET branch protection to PUT input, merging required check contexts. */
function buildProtectionPayload(existing, mergedContexts) {
  const strict = existing?.required_status_checks?.strict ?? true;
  const enforceAdmins =
    typeof existing?.enforce_admins?.enabled === 'boolean' ? existing.enforce_admins.enabled : true;

  const payload = {
    required_status_checks: { strict, contexts: mergedContexts },
    enforce_admins: enforceAdmins,
    required_pull_request_reviews: null,
    restrictions: null,
    required_conversation_resolution: existing?.required_conversation_resolution?.enabled ?? true,
    allow_force_pushes: existing?.allow_force_pushes?.enabled ?? false,
    allow_deletions: existing?.allow_deletions?.enabled ?? false,
  };

  const reviews = existing?.required_pull_request_reviews;
  if (reviews) {
    payload.required_pull_request_reviews = {
      dismiss_stale_reviews: reviews.dismiss_stale_reviews ?? false,
      require_code_owner_reviews: reviews.require_code_owner_reviews ?? false,
      required_approving_review_count: reviews.required_approving_review_count ?? 0,
    };
  }

  return payload;
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

  const protectionPath = `repos/${repo}/branches/${args.branch}/protection`;
  let existing = null;
  try {
    existing = ghJson(['api', protectionPath], { allow404: true });
  } catch (e) {
    console.error(`apply-branch-protection: could not read existing protection: ${e.message}`);
    process.exit(1);
  }

  const existingContexts = existing?.required_status_checks?.contexts || [];
  const mergedContexts = mergeCheckContexts(existingContexts, BOT_GATE_CHECKS);
  const payload = buildProtectionPayload(existing, mergedContexts);

  if (args.dryRun) {
    console.log(
      JSON.stringify(
        {
          repo,
          branch: args.branch,
          existingContexts,
          mergedContexts,
          botGates: BOT_GATE_CHECKS,
          payload,
        },
        null,
        2,
      ),
    );
    process.exit(0);
  }

  const path = protectionPath;
  const r = spawnSync(
    'gh',
    ['api', '--method', 'PUT', path, '--input', '-'],
    { encoding: 'utf8', input: JSON.stringify(payload), timeout: GH_TIMEOUT_MS },
  );
  if (r.status === 0) {
    console.log(`Branch protection applied on ${repo}:${args.branch}`);
    console.log(`Required checks (${mergedContexts.length}): ${mergedContexts.join(', ')}`);
    if (existingContexts.length) {
      console.log(`Preserved ${existingContexts.length} existing check(s); added bot gates: ${BOT_GATE_CHECKS.join(', ')}`);
    }
    console.log(`required_conversation_resolution: ${payload.required_conversation_resolution}`);
    process.exit(0);
  }

  console.error(`apply-branch-protection: API failed (exit ${r.status})`);
  if (r.stderr) console.error(r.stderr.trim());
  printManualSteps(repo, args.branch, mergedContexts);
  process.exit(r.status === 403 || r.status === 404 ? 2 : 1);
}

main();
