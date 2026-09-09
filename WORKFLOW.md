# AR-local pull-request workflow

Use a fresh topic worktree from the repository default branch and preserve
unrelated changes. Open a draft PR against that exact default branch.

Run checks appropriate to changed paths. For PR automation changes, run:

```sh
npm run pr:automation:verify
git diff --check
```

Read substantive review threads and relevant comments, post one feedback plan,
implement valid fixes, and reply with `Implemented`, `Deferred`, or `Declined`
before resolving each thread. Review vendors are advisory; substantive findings
still need disposition. Applicable product CI and `bot-feedback-gate` must pass.

The tracked explicit closeout command is:

```sh
npm run pr:merge -- --pr <number>
```

Run it from the reviewed topic checkout. It checks the PR against the repository
default branch, promotes a draft only through this explicit CLI, and uses the
existing branch-sync and squash auto-merge path. GitHub branch protection remains
in force. `--dry-run` never promotes a draft. Do not substitute scripts from the
dirty developer checkout, use direct `gh pr merge`, or bypass protection.

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
