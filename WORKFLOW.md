# AR-local pull-request workflow

Use a fresh topic worktree from the repository default branch and preserve
unrelated changes. Open a draft PR against that exact default branch.

PR automation requires Node.js and Python 3.11 or newer. Wait-state writes use
native file locks and hardlinks on the state filesystem. Kernel ownership is
released on a writer crash; unknown legacy lock files require verified manual
migration.

Run checks appropriate to changed paths. For PR automation changes, run:

```sh
npm run pr:automation:verify
git diff --check
```

Read substantive review threads and relevant comments, post one feedback plan,
implement valid fixes, and reply with `Implemented`, `Deferred`, or `Declined`
before resolving each thread. Review vendors are advisory; substantive findings
still need disposition. Applicable product CI and `bot-feedback-gate` must pass.

The single required `bot-feedback-gate` combines substantive review-thread
resolution with applicable deterministic product CI. It stays pending when an
expected workflow is missing or running, and fails for failed, cancelled or
skipped expected jobs. Changed files (including rename sources) are paginated;
workflow identity, current run attempt, expected jobs and the exact PR head/base
are verified. Bot authors and chore titles never waive product CI.

The trusted reporter runs on PR lifecycle, review/comment and CI lifecycle
events. Automatic evaluations execute only default-branch code with the
GitHub Actions token; they never execute PR code or consume its artifacts.
Reports are serialized per PR. Closing a PR stops further gate publication.
Main-branch tests and the merged-PR report can legitimately run after merge.

If a thread was resolved without a new event, refresh the gate once:

```sh
gh workflow run pr-bot-feedback-check.yml -f pr_number=<number>
```

To recover a pending evaluation left on a previous head after a lost event,
add `-f retired_head=<previous-40-character-sha>`. This cancels only this PR's
owned pending reports from that old head and refuses to retire the current
open head. It does not cancel product CI or manufacture a passing check.

An explicit manual dispatch can use a reviewed workflow ref for bootstrapping
a reporter change before it is merged. Only manual dispatch checks out that
workflow's exact commit; automatic events always use the default branch.
The reporter never manufactures a pass: the same current-head CI and thread
requirements apply to bootstrap runs.

The tracked explicit closeout command is:

```sh
npm run pr:merge -- --pr <number>
```

Run it from the reviewed topic checkout. It checks the PR against the repository
default branch, promotes a draft only through this explicit CLI, and uses the
existing branch-sync and squash auto-merge path. GitHub branch protection remains
in force. `--dry-run` never promotes a draft. Do not substitute scripts from the
dirty developer checkout, use direct `gh pr merge`, or bypass protection.

The merge primitive independently rechecks applicable CI and required checks,
then passes `--match-head-commit`. A requested branch update parks immediately;
verify the new head in a later invocation. Missing CI, API errors and stale
evidence never authorize auto-merge. Keep product path rules and expected job
identities synchronized in `scripts/lib/pr-product-ci-policy.mjs`; the automation
tests detect drift. GitHub's own path-filter limits may leave a large PR without
an expected run; that PR stays blocked until the CI scope is corrected.

Fix actionable state immediately. When only GitHub checks or merge processing
remain, park ownership and check once in a later turn; do not use watch loops.
After merge, run `npm run pr:bot-feedback-audit` and handle actual late findings
through a follow-up PR.

Pi operations and deployment require the separate controlled runbook and latest
complete recovery handoff. A repository merge does not authorize runtime
activation or satisfy natural-backup or physical-recovery acceptance.

For product/Pi changes, complete the authorized deployment of the exact approved
commit, then perform both mandatory post-merge acceptance steps:

1. Inspect the live Pi dashboard at `http://100.78.28.10/`, including the changed
   behavior and relevant browser errors.
2. Run `npm run verify:local -- --base-url=http://100.78.28.10/` (equivalently,
   `npm run verify:pi`) against that same Pi deployment.

Record the deployed commit, URL, timestamp and actual results. Passing CI or the
merged-PR audit does not replace either check. A failed check requires a fix and
reverification; a blocked deployment or recovery gate leaves runtime acceptance
pending and ownership retained. Do not substitute localhost or the public
Australian Rates site for Pi acceptance. Repository-only documentation/workflow
changes do not deploy product behavior or authorize Pi mutation.

The GitHub Pi deployment watchdog must fail when SSH/Tailscale configuration is
missing or verification fails. A skipped verification is not Pi acceptance.
Its schedule remains observation-only; changing gate policy never activates a
Pi deployment, timer, repair or backup.
